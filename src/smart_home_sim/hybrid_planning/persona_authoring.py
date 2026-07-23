"""Invent a realistic resident persona with a local LLM (optional pre-Stage-0 step).

Stage 0 (``generate_behavioral_profile``) freezes ``immutableFacts`` verbatim from the
planning case's ``resident.profile`` and only expands traits and habits. To let the
researcher obtain a lifelike person *without hand-writing it*, this module generates the
persona itself — age, occupation, city, condition/illness, and the intent anchors that
follow from it — and emits a valid ``PlanningCase`` ready for Stage 0.

The home structure (locations, resources, initial state, window, timezone, seed) is taken
from a template planning case; only the person and their routine anchors are invented, so
the output is always structurally valid. This is an authoring-phase convenience; the
simulation runtime never invokes an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import Resident
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioError
from smart_home_sim.hybrid_planning.models import (
    HybridPlanningConfig,
    PlanningCase,
    RoutineRequirement,
    TimeBand,
)
from smart_home_sim.hybrid_planning.service import HybridPlanningError, _read_models

PERSONA_PROMPT_VERSION = "persona-0.1.0"


class RoutineProposal(ContractModel):
    intent: str = Field(min_length=1)
    day_types: list[str] = Field(default_factory=list)
    time_band: TimeBand | None = None
    minimum_occurrences: int = Field(default=1, ge=1, le=4)
    maximum_occurrences: int = Field(default=1, ge=1, le=4)


class PersonaProposal(ContractModel):
    display_name: str = Field(min_length=1)
    age: int = Field(ge=1, le=110)
    occupation: str = Field(min_length=1)
    city: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    routine_requirements: list[RoutineProposal] = Field(min_length=1, max_length=3)
    context_notes: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def _coerce_scalars(cls, data: Any) -> Any:
        """Tolerate small local models: coerce scalars to lists and cap over-production."""

        if not isinstance(data, dict):
            return data
        notes = data.get("contextNotes", data.get("context_notes"))
        if isinstance(notes, str):
            notes = [notes]
        if isinstance(notes, list):
            data = {**data, "contextNotes": notes[:6]}
        requirements = data.get("routineRequirements", data.get("routine_requirements"))
        if isinstance(requirements, list):
            fixed = []
            for item in requirements[:3]:
                if isinstance(item, dict):
                    day_types = item.get("dayTypes", item.get("day_types"))
                    if isinstance(day_types, str):
                        item = {**item, "dayTypes": [day_types] if day_types else []}
                fixed.append(item)
            data = {**data, "routineRequirements": fixed}
        return data


@dataclass(frozen=True, slots=True)
class PersonaResult:
    planning_case: PlanningCase
    proposal: PersonaProposal
    resident_id: str


_SYSTEM_PROMPT = (
    "You invent one realistic smart-home resident for a synthetic habit-mining dataset, as "
    "strict JSON. The person must be internally coherent: age, occupation, city and a health "
    "condition (use 'none' if healthy) that plausibly shape daily life.\n"
    "\n"
    "Then list the recurring intent ANCHORS that follow from that person. Anchors are ONLY "
    "the 2 to 3 non-negotiable routines the person keeps almost every applicable day. Do NOT "
    "list optional or occasional activities as anchors — those are added later. Keep "
    "occurrences small and realistic, and use ONLY intents from the ALLOWED list.\n"
    "\n"
    "Anchors MUST be coherent with the person's life stage and employment status:\n"
    "- Employment: an EMPLOYED person may have a work/commute routine, restricted to "
    "dayTypes ['workday']. A RETIRED, unemployed, homemaker, student or otherwise not-"
    "employed person MUST NOT have any work, commuting, or work-preparation routine, and "
    "MUST NOT restrict routines to workdays for employment reasons — retirees experience "
    "every day similarly. Match occupation to age (e.g. age >= ~67 usually retired).\n"
    "- Health: a chronic condition implies a matching self-care routine (e.g. a medication "
    "routine for a condition managed with medication).\n"
    "- Universal: sleep and basic daily self-care fit almost anyone.\n"
    "Before choosing anchors, silently reason about a typical day for THIS person, then pick "
    "only intents that genuinely recur for them. Return only the JSON object."
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "resident"


def _user_prompt(
    *,
    intents: list[str],
    brief: str | None,
    repair_errors: list[str] | None,
) -> str:
    parts = [
        f"ALLOWED intents for routine anchors: {intents}",
        "Return an object with: displayName, age, occupation, city, condition, "
        "routineRequirements (each: intent, dayTypes (subset of ['workday','weekend'] or "
        "empty for every day), timeBand (one of early_morning/morning/midday/afternoon/"
        "evening/night), minimumOccurrences, maximumOccurrences), contextNotes.",
    ]
    if brief:
        parts.append(f"Researcher brief to honour: {brief}")
    else:
        parts.append(
            "No brief supplied: invent a plausible, non-stereotyped ordinary adult."
        )
    if repair_errors:
        parts.append(
            "Fix ALL of these problems from your previous attempt:\n"
            + "\n".join(f"- {error}" for error in repair_errors)
        )
    return "\n\n".join(parts)


def _validate_proposal(proposal: PersonaProposal, catalog_intents: set[str]) -> list[str]:
    errors: list[str] = []
    for requirement in proposal.routine_requirements:
        if requirement.intent not in catalog_intents:
            errors.append(
                f"routine intent '{requirement.intent}' is not an allowed catalog intent"
            )
        if requirement.maximum_occurrences < requirement.minimum_occurrences:
            errors.append(
                f"routine '{requirement.intent}' has maximumOccurrences < minimumOccurrences"
            )
    return errors


def _build_planning_case(
    template: PlanningCase,
    proposal: PersonaProposal,
    resident_id: str,
) -> PlanningCase:
    start_date = template.dates()[0]
    resident = Resident(
        resident_id=resident_id,
        display_name=proposal.display_name,
        profile={
            "age": proposal.age,
            "occupation": proposal.occupation,
            "city": proposal.city,
            "condition": proposal.condition,
        },
    )
    initial_residents = [
        state.model_copy(update={"resident_id": resident_id})
        for state in template.initial_state.residents
    ]
    initial_state = template.initial_state.model_copy(
        update={"residents": initial_residents}
    )
    requirements = [
        RoutineRequirement(
            intent=item.intent,
            day_types=list(item.day_types),
            time_band=item.time_band,
            minimum_occurrences=item.minimum_occurrences,
            maximum_occurrences=item.maximum_occurrences,
        )
        for item in proposal.routine_requirements
    ]
    return template.model_copy(
        update={
            "case_id": f"{resident_id}_{start_date.isoformat().replace('-', '_')}",
            "resident": resident,
            "initial_state": initial_state,
            "routine_requirements": requirements,
            "context_notes": list(proposal.context_notes)
            or ["Synthetic persona invented for habit-mining dataset generation."],
        }
    )


def generate_persona(
    template_case_path: Path,
    *,
    config: HybridPlanningConfig,
    brief: str | None = None,
    resident_id: str | None = None,
    client: LMStudioClient | None = None,
) -> PersonaResult:
    """Invent a persona and return a valid planning case built on the template's home."""

    template, catalog = _read_models(template_case_path)
    catalog_intents = {activity.intent for activity in catalog.activities}
    intents = sorted(catalog_intents)
    active_client = client or LMStudioClient(config)

    repair_errors: list[str] | None = None
    last_reason = "unknown"
    proposal: PersonaProposal | None = None
    for attempt in range(config.max_structure_repairs + 1):
        try:
            candidate, _exchange = active_client.complete_json(
                schema_name="resident_persona",
                output_model=PersonaProposal,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_user_prompt(
                    intents=intents, brief=brief, repair_errors=repair_errors
                ),
                seed=template.seed + attempt,
                enforce_schema=False,
            )
        except LMStudioError as error:
            last_reason = f"llm error: {error}"
            repair_errors = [str(error)]
            continue
        errors = _validate_proposal(candidate, catalog_intents)
        if not errors:
            proposal = candidate
            break
        last_reason = "; ".join(errors[:3])
        repair_errors = errors
    if proposal is None:
        raise HybridPlanningError(
            f"persona generation failed to produce a valid proposal: {last_reason}"
        )

    chosen_id = resident_id or _slug(proposal.display_name)
    planning_case = _build_planning_case(template, proposal, chosen_id)
    return PersonaResult(
        planning_case=planning_case, proposal=proposal, resident_id=chosen_id
    )
