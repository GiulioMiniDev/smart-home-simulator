"""Invent a frozen resident persona from a short brief through a local LM Studio model.

The model proposes only a small identity object. Deterministic normalisation coerces the common
scalar-versus-list quirks a small model emits, caps the number of routine anchors so the later
habit portfolio can stay balanced, and stamps authoring provenance. The result is a validated,
digest-addressable persona that seeds the behavioural-profile stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioJSONCompletion,
)

# Each routine anchor canonicalises to an anchor habit, and the behavioural profile must still
# satisfy its minimum contextual/optional/rare counts; capping anchors keeps the portfolio
# balanceable on a small local model.
MAX_ROUTINE_ANCHORS = 3

PROMPT_TEMPLATE_VERSION = "persona-1.0.0"
GENERATOR_NAME = "smart-home-sim.hybrid_planning.persona"
GENERATOR_VERSION = "1.0.0"

_SEX_ALIASES = {
    "f": "F",
    "female": "F",
    "woman": "F",
    "m": "M",
    "male": "M",
    "man": "M",
}


class PersonaGenerationError(ValueError):
    """The model output could not be normalised into a valid persona."""


class Persona(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["persona"] = "persona"
    persona_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=120)
    sex: Literal["F", "M", "X"]
    occupation: str = Field(min_length=1)
    household: str = Field(min_length=1)
    health: list[str] = Field(default_factory=list)
    city: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    notes: str = ""
    routine_anchors: list[str] = Field(min_length=1, max_length=MAX_ROUTINE_ANCHORS)
    provenance: Provenance


@dataclass(frozen=True)
class PersonaGenerationResult:
    persona: Persona
    completion: LMStudioJSONCompletion


def generate_persona(
    brief: str,
    client: LMStudioClient,
    *,
    timezone: str = "Europe/Rome",
    seed: int | None = None,
    now: datetime | None = None,
) -> PersonaGenerationResult:
    """Invent one persona from a natural-language brief and freeze it with provenance."""
    if not brief.strip():
        raise PersonaGenerationError("Persona brief must not be empty")

    completion = client.complete_json(_build_messages(brief), seed=seed)
    persona = _normalise_persona(
        completion.data,
        client=client,
        timezone=timezone,
        seed=seed,
        now=now or datetime.now(UTC),
    )
    return PersonaGenerationResult(persona=persona, completion=completion)


def _build_messages(brief: str) -> list[ChatMessage]:
    system = (
        "You invent realistic but entirely fictional adults for a smart-home behavioural "
        "dataset. Reply with a single JSON object and no prose."
    )
    user = (
        "Invent one coherent person consistent with this brief:\n"
        f"{brief.strip()}\n\n"
        "Return JSON with these fields:\n"
        '  "name" (string), "age" (integer), "sex" ("F", "M" or "X"),\n'
        '  "occupation" (string), "household" (string, e.g. \"lives alone\"),\n'
        '  "health" (array of conditions, may be empty),\n'
        '  "city" (string), "notes" (short free text on lifestyle and temperament),\n'
        '  "routine_anchors" (array of 1 to 3 short labels for the person\'s most fixed '
        "daily habits, e.g. \"morning coffee\").\n"
        "Keep it plausible and internally consistent. Do not invent exact times or schedules."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _normalise_persona(
    data: Any,
    *,
    client: LMStudioClient,
    timezone: str,
    seed: int | None,
    now: datetime,
) -> Persona:
    if not isinstance(data, dict):
        raise PersonaGenerationError("Persona output must be a JSON object")

    name = _require_text(data, "name")
    anchors = _string_list(data.get("routine_anchors"))[:MAX_ROUTINE_ANCHORS]
    if not anchors:
        raise PersonaGenerationError("Persona output must include at least one routine anchor")

    provenance = Provenance(
        author_type=AuthorType.external_llm,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        model_name=client.config.model,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        generated_at=now,
        parameters={"temperature": client.config.temperature, "seed": seed},
    )

    try:
        return Persona(
            persona_id=_slugify(name),
            name=name,
            age=_coerce_age(data.get("age")),
            sex=_coerce_sex(data.get("sex")),
            occupation=_text_or_default(data.get("occupation"), "unspecified"),
            household=_text_or_default(data.get("household"), "unspecified"),
            health=_string_list(data.get("health")),
            city=_text_or_default(data.get("city"), "unspecified"),
            timezone=timezone,
            notes=_text_or_default(data.get("notes"), ""),
            routine_anchors=anchors,
            provenance=provenance,
        )
    except ValueError as error:
        raise PersonaGenerationError(f"Persona output failed validation: {error}") from error


def _require_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PersonaGenerationError(f"Persona output requires a non-empty '{key}'")
    return value.strip()


def _text_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _coerce_age(value: Any) -> int:
    if isinstance(value, bool):
        raise PersonaGenerationError("Persona age must be a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise PersonaGenerationError("Persona age must be an integer")


def _coerce_sex(value: Any) -> str:
    if isinstance(value, str):
        normalised = _SEX_ALIASES.get(value.strip().lower())
        if normalised is not None:
            return normalised
        if value.strip().upper() == "X":
            return "X"
    return "X"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "persona"
