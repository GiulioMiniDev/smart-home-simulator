from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitCadence,
    HabitKind,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    ProfileValidationReport,
    behavioral_profile_digest,
    validate_behavioral_profile,
)
from smart_home_sim.hybrid_planning.lmstudio import (
    LMStudioClient,
    LMStudioError,
    LMStudioExchange,
)
from smart_home_sim.hybrid_planning.models import HybridPlanningConfig, PlanningCase
from smart_home_sim.hybrid_planning.prompts import (
    PROFILE_SYSTEM_PROMPT,
    behavioral_profile_prompt,
    behavioral_profile_repair_prompt,
    behavioral_profile_structure_repair_prompt,
)
from smart_home_sim.hybrid_planning.service import (
    HybridPlanningError,
    _persist_exchange,
    _read_models,
    _write_json,
    _write_text,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class CompletionClient(Protocol):
    def complete_json(
        self,
        *,
        schema_name: str,
        output_model: type[ModelT],
        system_prompt: str,
        user_prompt: str,
        seed: int,
        schema_override: dict[str, object] | None = None,
    ) -> tuple[ModelT, LMStudioExchange]: ...


@dataclass(frozen=True, slots=True)
class BehavioralProfileResult:
    output_dir: Path
    profile: BehavioralProfile
    profile_digest: str
    validation: ProfileValidationReport


def _profile_schema(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
) -> dict[str, object]:
    schema = deepcopy(BehavioralProfile.model_json_schema(by_alias=True))
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["sourceCaseId"] = {"type": "string", "const": planning_case.case_id}
    properties["residentId"] = {
        "type": "string",
        "const": planning_case.resident.resident_id,
    }
    properties["effectiveFrom"] = {
        "type": "string",
        "format": "date",
        "const": planning_case.dates()[0].isoformat(),
    }
    properties["immutableFacts"] = {
        "type": "object",
        "const": planning_case.resident.profile,
    }
    trait_names = [
        "chronotype",
        "routineRigidity",
        "socialOrientation",
        "mealRegularity",
        "activityLevel",
        "noveltySeeking",
    ]
    properties["syntheticTraits"] = {
        "type": "object",
        "properties": {
            name: {"type": "string", "minLength": 8} for name in trait_names
        },
        "required": trait_names,
        "additionalProperties": False,
    }
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    habit = definitions["BehavioralHabit"]
    assert isinstance(habit, dict)
    habit_properties = habit["properties"]
    assert isinstance(habit_properties, dict)
    intents = [item.intent for item in catalog.activities]
    locations = [item.location_id for item in planning_case.locations]
    habit_properties["intent"] = {"type": "string", "enum": intents}
    for field in ("predecessorIntents", "successorIntents"):
        habit_properties[field] = {
            "type": "array",
            "items": {"type": "string", "enum": intents},
        }
    habit_properties["locationIds"] = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "enum": locations},
    }
    return schema


def _canonicalize_routine_anchors(
    planning_case: PlanningCase,
    profile: BehavioralProfile,
) -> tuple[BehavioralProfile, list[dict[str, object]]]:
    requirements = {item.intent: item for item in planning_case.routine_requirements}
    habits = []
    changes: list[dict[str, object]] = []
    for habit in profile.habits:
        requirement = requirements.get(habit.intent)
        if requirement is None:
            habits.append(habit)
            continue
        before = {
            "kind": habit.kind.value,
            "cadence": habit.cadence.model_dump(mode="json", by_alias=True),
            "applicableDayTypes": habit.applicable_day_types,
            "preferredTimeBands": [item.value for item in habit.preferred_time_bands],
        }
        typical = min(
            requirement.maximum_occurrences,
            max(requirement.minimum_occurrences, habit.cadence.typical_occurrences),
        )
        bands = (
            [requirement.time_band]
            if requirement.time_band is not None
            else habit.preferred_time_bands
        )
        normalized = habit.model_copy(
            update={
                "kind": HabitKind.anchor,
                "cadence": HabitCadence(
                    minimum_occurrences=requirement.minimum_occurrences,
                    typical_occurrences=typical,
                    maximum_occurrences=requirement.maximum_occurrences,
                    period_days=1,
                ),
                "applicable_day_types": list(requirement.day_types),
                "preferred_time_bands": bands,
            }
        )
        after = {
            "kind": normalized.kind.value,
            "cadence": normalized.cadence.model_dump(mode="json", by_alias=True),
            "applicableDayTypes": normalized.applicable_day_types,
            "preferredTimeBands": [item.value for item in normalized.preferred_time_bands],
        }
        if before != after:
            changes.append({"intent": habit.intent, "before": before, "after": after})
        habits.append(normalized)
    return profile.model_copy(update={"habits": habits}), changes


def generate_behavioral_profile(
    case_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    client: CompletionClient | None = None,
) -> BehavioralProfileResult:
    if output_dir.exists():
        raise HybridPlanningError(f"output directory already exists: {output_dir}")
    planning_case, catalog = _read_models(case_path)
    output_dir.mkdir(parents=True)
    manifest: dict[str, object] = {
        "documentType": "behavioral_profile_generation_run",
        "runVersion": "0.1.0",
        "status": "running",
        "caseId": planning_case.case_id,
        "model": config.model,
        "executionPerformed": False,
    }
    _write_json(output_dir / "run.json", manifest)
    active_client = client or LMStudioClient(config)
    prompt = behavioral_profile_prompt(planning_case, catalog)
    schema = _profile_schema(planning_case, catalog)
    try:
        attempt = 0
        structure_repairs = 0
        semantic_repairs = 0
        while True:
            attempt += 1
            try:
                profile, exchange = active_client.complete_json(
                    schema_name="behavioral_profile",
                    output_model=BehavioralProfile,
                    system_prompt=PROFILE_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    seed=planning_case.seed + attempt - 1,
                    schema_override=schema,
                )
            except LMStudioError as error:
                _write_text(
                    output_dir / "attempts" / f"attempt-{attempt}" / "structure-error.txt",
                    str(error) + "\n",
                )
                if structure_repairs >= config.max_structure_repairs:
                    raise
                structure_repairs += 1
                prompt = behavioral_profile_structure_repair_prompt(
                    planning_case,
                    catalog,
                    str(error),
                )
                continue
            _persist_exchange(output_dir / "attempts" / f"attempt-{attempt}", exchange, profile)
            profile, normalizations = _canonicalize_routine_anchors(planning_case, profile)
            _write_json(
                output_dir / "attempts" / f"attempt-{attempt}" / "normalizations.json",
                {"changes": normalizations},
            )
            validation = validate_behavioral_profile(planning_case, catalog, profile)
            _write_json(output_dir / f"validation-attempt-{attempt}.json", validation)
            if validation.valid:
                digest = behavioral_profile_digest(profile)
                _write_json(output_dir / "behavioral-profile.json", profile)
                _write_json(
                    output_dir / "intended-habits.json",
                    {
                        "documentType": "intended_habits",
                        "profileDigest": digest,
                        "habits": [
                            item.model_dump(mode="json", by_alias=True)
                            for item in profile.habits
                        ],
                    },
                )
                _write_json(output_dir / "validation-report.json", validation)
                _write_text(output_dir / "profile.sha256", digest + "\n")
                completed = datetime.now(ZoneInfo(planning_case.time_zone))
                manifest.update(
                    {
                        "status": "completed",
                        "completedAt": completed.isoformat(),
                        "profileDigest": digest,
                        "validationPassed": True,
                    }
                )
                _write_json(output_dir / "run.json", manifest)
                return BehavioralProfileResult(output_dir, profile, digest, validation)
            if semantic_repairs >= config.max_structure_repairs:
                codes = ", ".join(item.code for item in validation.issues)
                raise HybridPlanningError(
                    f"behavioral profile failed validation after explicit repairs: {codes}"
                )
            semantic_repairs += 1
            prompt = behavioral_profile_repair_prompt(
                planning_case,
                catalog,
                profile,
                validation.issues,
            )
    except (HybridPlanningError, LMStudioError, ValueError, json.JSONDecodeError) as error:
        manifest.update({"status": "failed", "error": str(error)})
        _write_json(output_dir / "run.json", manifest)
        if isinstance(error, HybridPlanningError):
            raise
        raise HybridPlanningError(str(error)) from error
    raise HybridPlanningError("behavioral profile generation ended without a result")
