from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from smart_home_sim.behavior.service import default_activity_catalog_path
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.hybrid_planning.comparison import compare_scenarios
from smart_home_sim.hybrid_planning.lmstudio import (
    LMStudioClient,
    LMStudioError,
    LMStudioExchange,
)
from smart_home_sim.hybrid_planning.materialization import (
    materialize_day_activities,
    materialize_scenario,
)
from smart_home_sim.hybrid_planning.metrics import (
    day_signature,
    diversity_metrics,
    most_repetitive_day_index,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DiversityMetrics,
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
    WeeklyBrief,
)
from smart_home_sim.hybrid_planning.prompts import (
    SYSTEM_PROMPT,
    daily_prompt,
    diversity_repair_prompt,
    structural_repair_prompt,
    weekly_prompt,
)
from smart_home_sim.validation.service import validate_scenario

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


class HybridPlanningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HybridPlanningResult:
    output_dir: Path
    plan: CanonicalPlan
    diversity: DiversityMetrics
    comparison: dict[str, object] | None


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _persist_exchange(directory: Path, exchange: LMStudioExchange, parsed: BaseModel) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    _write_json(directory / "request.json", exchange.request)
    _write_json(directory / "response.api.json", exchange.api_response)
    _write_text(directory / "response.raw.txt", exchange.raw_content)
    _write_json(directory / "proposal.json", parsed)
    _write_json(
        directory / "digests.json",
        {
            "requestSha256": _sha256(
                json.dumps(
                    exchange.request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            "responseSha256": _sha256(exchange.raw_content),
        },
    )


def _validate_weekly_brief(planning_case: PlanningCase, brief: WeeklyBrief) -> None:
    if [item.date for item in brief.days] != planning_case.dates():
        raise HybridPlanningError("weekly brief does not cover the requested dates in order")


def _validate_daily_proposal(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    expected_date: object,
    proposal: DailyProposal,
) -> None:
    if proposal.date != expected_date:
        raise HybridPlanningError(f"daily proposal returned unexpected date {proposal.date}")
    intents = {item.intent for item in catalog.activities}
    locations = {item.location_id for item in planning_case.locations}
    unknown_intents = sorted({item.intent for item in proposal.activities} - intents)
    unknown_locations = sorted({item.location_id for item in proposal.activities} - locations)
    if unknown_intents:
        raise HybridPlanningError(f"daily proposal contains unknown intents: {unknown_intents}")
    if unknown_locations:
        raise HybridPlanningError(f"daily proposal contains unknown locations: {unknown_locations}")
    invalid_extended = sorted(
        {
            item.intent
            for item in proposal.activities
            if item.duration_class.value == "extended"
            and item.intent not in {"sleep", "work_shift"}
        }
    )
    if invalid_extended:
        raise HybridPlanningError(
            "extended duration is allowed only for sleep or work_shift, not: "
            f"{invalid_extended}"
        )
    day_type = planning_case.calendar_day(proposal.date).day_type
    for requirement in planning_case.routine_requirements:
        if requirement.day_types and day_type not in requirement.day_types:
            continue
        matches = [item for item in proposal.activities if item.intent == requirement.intent]
        if not requirement.minimum_occurrences <= len(matches) <= requirement.maximum_occurrences:
            raise HybridPlanningError(
                f"routine '{requirement.intent}' requires between "
                f"{requirement.minimum_occurrences} and {requirement.maximum_occurrences} "
                f"occurrences on {day_type}; found {len(matches)}"
            )
        if requirement.time_band is not None and any(
            item.time_band is not requirement.time_band for item in matches
        ):
            raise HybridPlanningError(
                f"routine '{requirement.intent}' must use timeBand "
                f"'{requirement.time_band.value}' on {day_type}"
            )
    try:
        materialize_day_activities(
            planning_case,
            proposal,
            final_date=planning_case.dates()[-1],
        )
    except ValueError as error:
        raise HybridPlanningError(str(error)) from error


def _daily_schema(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    expected_date: object,
) -> dict[str, object]:
    schema = deepcopy(DailyProposal.model_json_schema(by_alias=True))
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["date"] = {"type": "string", "const": str(expected_date)}
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    activity_definition = definitions["ProposedActivity"]
    assert isinstance(activity_definition, dict)
    activity_properties = activity_definition["properties"]
    assert isinstance(activity_properties, dict)
    activity_properties["intent"] = {
        "type": "string",
        "enum": [item.intent for item in catalog.activities],
    }
    activity_properties["locationId"] = {
        "type": "string",
        "enum": [item.location_id for item in planning_case.locations],
    }
    duration_property = activity_properties["durationClass"]
    assert isinstance(duration_property, dict)
    duration_property.pop("$ref", None)
    duration_property.update(
        {
            "type": "string",
            "enum": ["brief", "short", "medium", "long"],
        }
    )
    return schema


def _updated_memory(memory: PlanningMemory, proposal: DailyProposal) -> PlanningMemory:
    frequencies = dict(memory.intent_frequency)
    last_seen = dict(memory.intent_last_seen)
    for activity in proposal.activities:
        frequencies[activity.intent] = frequencies.get(activity.intent, 0) + 1
        last_seen[activity.intent] = proposal.date
    recent = [*memory.recent_days, {
        "date": proposal.date.isoformat(),
        "narrativeIntent": proposal.narrative_intent,
        "intents": [item.intent for item in proposal.activities],
    }][-14:]
    return PlanningMemory(
        through_date=proposal.date,
        recent_days=recent,
        intent_frequency=frequencies,
        intent_last_seen=last_seen,
        day_signatures=[*memory.day_signatures, day_signature(proposal)],
    )


def _rebuild_memory(proposals: list[DailyProposal]) -> PlanningMemory:
    memory = PlanningMemory()
    for proposal in proposals:
        memory = _updated_memory(memory, proposal)
    return memory


def _read_models(case_path: Path) -> tuple[PlanningCase, ActivityCatalog]:
    try:
        planning_case = PlanningCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        catalog = ActivityCatalog.model_validate_json(
            default_activity_catalog_path().read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise HybridPlanningError(f"cannot load hybrid planning inputs: {error}") from error
    if len(planning_case.dates()) > 7:
        raise HybridPlanningError(
            "the first vertical slice accepts at most seven days; "
            "annual runs will reuse this chunk boundary"
        )
    known_intents = {item.intent for item in catalog.activities}
    unknown_requirements = sorted(
        {item.intent for item in planning_case.routine_requirements} - known_intents
    )
    if unknown_requirements:
        raise HybridPlanningError(
            f"planning case contains unknown routine intents: {unknown_requirements}"
        )
    return planning_case, catalog


def generate_hybrid_plan(
    case_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    baseline_path: Path | None = None,
    client: CompletionClient | None = None,
) -> HybridPlanningResult:
    if output_dir.exists():
        raise HybridPlanningError(f"output directory already exists: {output_dir}")
    planning_case, catalog = _read_models(case_path)
    output_dir.mkdir(parents=True)
    run_manifest: dict[str, object] = {
        "documentType": "hybrid_planning_run",
        "runVersion": "0.1.0",
        "status": "running",
        "caseId": planning_case.case_id,
        "model": config.model,
        "executionPerformed": False,
        "baselineExposedToModel": False,
    }
    _write_json(output_dir / "run.json", run_manifest)
    _write_json(output_dir / "profile-snapshot.json", planning_case)
    active_client = client or LMStudioClient(config)
    try:
        brief, brief_exchange = active_client.complete_json(
            schema_name="weekly_brief",
            output_model=WeeklyBrief,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=weekly_prompt(planning_case, catalog),
            seed=planning_case.seed,
        )
        _persist_exchange(output_dir / "weekly-brief" / "attempt-1", brief_exchange, brief)
        _validate_weekly_brief(planning_case, brief)

        proposals: list[DailyProposal] = []
        memory = PlanningMemory()
        for index, day_brief in enumerate(brief.days):
            attempt = 1
            prompt = daily_prompt(planning_case, catalog, brief, day_brief, memory)
            response_schema = _daily_schema(planning_case, catalog, day_brief.date)
            while True:
                proposal, exchange = active_client.complete_json(
                    schema_name="daily_proposal",
                    output_model=DailyProposal,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    seed=planning_case.seed + index + attempt,
                    schema_override=response_schema,
                )
                _persist_exchange(
                    output_dir / "days" / day_brief.date.isoformat() / f"attempt-{attempt}",
                    exchange,
                    proposal,
                )
                try:
                    _validate_daily_proposal(
                        planning_case,
                        catalog,
                        day_brief.date,
                        proposal,
                    )
                    break
                except HybridPlanningError as validation_error:
                    if attempt > config.max_structure_repairs:
                        raise
                    prompt = structural_repair_prompt(
                        planning_case,
                        catalog,
                        brief,
                        proposal,
                        str(validation_error),
                    )
                    attempt += 1
            proposals.append(proposal)
            memory = _updated_memory(memory, proposal)
            _write_json(
                output_dir / "days" / day_brief.date.isoformat() / "memory-after.json",
                memory,
            )

        diversity = diversity_metrics(proposals)
        repair_number = 0
        while not diversity.passes_gate and repair_number < config.max_diversity_repairs:
            repair_number += 1
            target_index = most_repetitive_day_index(proposals)
            target = proposals[target_index]
            replacement, exchange = active_client.complete_json(
                schema_name="daily_proposal_repair",
                output_model=DailyProposal,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=diversity_repair_prompt(
                    planning_case,
                    catalog,
                    brief,
                    target,
                    proposals,
                    diversity.reasons,
                ),
                seed=planning_case.seed + 100 + repair_number,
                schema_override=_daily_schema(planning_case, catalog, target.date),
            )
            _persist_exchange(
                output_dir
                / "days"
                / target.date.isoformat()
                / f"diversity-repair-{repair_number}",
                exchange,
                replacement,
            )
            _validate_daily_proposal(planning_case, catalog, target.date, replacement)
            proposals[target_index] = replacement
            diversity = diversity_metrics(proposals)
        _write_json(output_dir / "diversity-report.json", diversity)
        if not diversity.passes_gate:
            raise HybridPlanningError(
                "generated week failed the diversity gate after explicit repairs: "
                + "; ".join(diversity.reasons)
            )

        final_memory = _rebuild_memory(proposals)
        _write_json(output_dir / "memory-checkpoint.json", final_memory)
        generated_at = datetime.now(ZoneInfo(planning_case.time_zone))
        scenario = materialize_scenario(planning_case, proposals, config, generated_at)
        validation = validate_scenario(scenario)
        _write_json(output_dir / "validation-report.json", validation)
        if not validation.valid:
            raise HybridPlanningError(
                "materialized scenario failed validation: "
                + ", ".join(item.code for item in validation.issues)
            )
        compilation = compile_scenario(scenario)
        _write_json(output_dir / "compilation-report.json", compilation.report)
        if compilation.plan is None:
            raise HybridPlanningError(
                "materialized scenario failed compilation: "
                + ", ".join(item.code for item in compilation.report.issues)
            )
        _write_json(output_dir / "scenario.json", scenario)
        _write_json(output_dir / "canonical-plan.json", compilation.plan)

        comparison: dict[str, object] | None = None
        if baseline_path is not None:
            try:
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HybridPlanningError(f"cannot read comparison baseline: {error}") from error
            comparison = compare_scenarios(
                scenario.model_dump(mode="json", by_alias=True), baseline
            )
            _write_json(output_dir / "comparison" / "report.json", comparison)

        run_manifest.update(
            {
                "status": "completed",
                "completedAt": generated_at.isoformat(),
                "diversityGatePassed": True,
                "comparisonPerformed": comparison is not None,
            }
        )
        _write_json(output_dir / "run.json", run_manifest)
        return HybridPlanningResult(output_dir, compilation.plan, diversity, comparison)
    except (HybridPlanningError, LMStudioError, ValueError) as error:
        run_manifest.update({"status": "failed", "error": str(error)})
        _write_json(output_dir / "run.json", run_manifest)
        if isinstance(error, HybridPlanningError):
            raise
        raise HybridPlanningError(str(error)) from error
