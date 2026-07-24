"""Generate a frozen behavioural profile (the habit ground truth) from a persona via LM Studio.

The model proposes a small habit list over closed vocabularies (kind, frequency, time band).
Deterministic code expands each proposal into a schedulable habit, assembles the profile, and gates
it on a portfolio balance (enough anchor/contextual/optional/rare habits). An unbalanced portfolio
triggers a bounded, directive repair that states the exact current-versus-required counts, because a
small model otherwise under-produces the rarer kinds. The accepted profile is the frozen ground
truth the cadence calendar later expands into planned habit occurrences.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioJSONCompletion,
)
from smart_home_sim.hybrid_planning.persona import Persona

PROMPT_TEMPLATE_VERSION = "habits-1.0.0"
GENERATOR_NAME = "smart-home-sim.hybrid_planning.habits"
GENERATOR_VERSION = "1.0.0"

# Reasoning models spend completion tokens on a private preamble, so the habit list needs a larger
# budget than a persona to avoid truncation.
HABITS_MAX_TOKENS = 16384

MIN_HABITS = 8
REQUIRED_KINDS: dict[str, int] = {"anchor": 3, "contextual": 2, "optional": 2, "rare": 1}

_TIME_ZONE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class HabitKind(StrEnum):
    anchor = "anchor"
    contextual = "contextual"
    optional = "optional"
    rare = "rare"


class CadencePeriod(StrEnum):
    day = "day"
    week = "week"
    month = "month"


class Weekday(StrEnum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"


# Closed vocabularies the model picks from; deterministic maps turn them into a schedulable cadence.
_FREQUENCY_TO_CADENCE: dict[str, tuple[CadencePeriod, int, int]] = {
    "daily": (CadencePeriod.day, 1, 1),
    "few_times_week": (CadencePeriod.week, 3, 1),
    "weekly": (CadencePeriod.week, 1, 1),
    "biweekly": (CadencePeriod.week, 1, 2),
    "monthly": (CadencePeriod.month, 1, 1),
    "rarely": (CadencePeriod.month, 1, 3),
}
_DEFAULT_FREQUENCY = "weekly"

_TIME_BAND_TO_WINDOW: dict[str, tuple[str, str]] = {
    "early_morning": ("06:00", "08:00"),
    "morning": ("08:00", "11:00"),
    "midday": ("11:30", "13:30"),
    "afternoon": ("14:00", "17:00"),
    "evening": ("18:00", "20:30"),
    "night": ("21:00", "23:00"),
}
_DEFAULT_TIME_BAND = "morning"

_WEEKDAY_ALIASES: dict[str, Weekday] = {}
for _day in Weekday:
    _WEEKDAY_ALIASES[_day.value] = _day
    _WEEKDAY_ALIASES[_day.value[:3]] = _day


class HabitsGenerationError(ValueError):
    """The model output could not be turned into a balanced, valid behavioural profile."""


class HabitCadence(ContractModel):
    period: CadencePeriod
    times_per_period: int = Field(ge=1)
    every_n_periods: int = Field(default=1, ge=1)
    weekdays: list[Weekday] = Field(default_factory=list)
    window_start: str
    window_end: str
    jitter_minutes: int = Field(default=30, ge=0)

    @model_validator(mode="after")
    def check_window(self) -> HabitCadence:
        for value in (self.window_start, self.window_end):
            if not _TIME_ZONE_RE.match(value):
                raise ValueError(f"cadence window must be HH:MM, got {value!r}")
        if self.window_start >= self.window_end:
            raise ValueError("cadence window start must be before end")
        return self


class Habit(ContractModel):
    habit_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: HabitKind
    cadence: HabitCadence
    mining_difficulty: Literal["easy", "medium", "hard"] = "medium"
    note: str = ""


class BehavioralProfile(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["behavioral_profile"] = "behavioral_profile"
    profile_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    habits: list[Habit] = Field(min_length=MIN_HABITS)
    provenance: Provenance

    @model_validator(mode="after")
    def check_unique_ids(self) -> BehavioralProfile:
        identifiers = [habit.habit_id for habit in self.habits]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("habit identifiers must be unique")
        return self


@dataclass(frozen=True)
class HabitsGenerationResult:
    profile: BehavioralProfile
    completion: LMStudioJSONCompletion
    repair_attempts: int


def validate_portfolio(habits: list[Habit]) -> list[str]:
    """Return directive issue strings for an unbalanced or too-small habit portfolio."""
    counts = Counter(habit.kind.value for habit in habits)
    issues: list[str] = []
    if len(habits) < MIN_HABITS:
        issues.append(f"total habits: have {len(habits)}, need >= {MIN_HABITS}")
    for kind, required in REQUIRED_KINDS.items():
        have = counts.get(kind, 0)
        if have < required:
            issues.append(f"{kind} habits: have {have}, need >= {required} (add {required - have})")
    return issues


def generate_habits(
    persona: Persona,
    client: LMStudioClient,
    *,
    max_repairs: int = 2,
    seed: int | None = None,
    now: datetime | None = None,
) -> HabitsGenerationResult:
    """Generate, balance, and freeze a behavioural profile for one persona."""
    stamped = now or datetime.now(UTC)
    completion = client.complete_json(
        _build_messages(persona), seed=seed, max_tokens=HABITS_MAX_TOKENS
    )
    habits = _normalise_habits(completion.data)
    issues = validate_portfolio(habits)

    attempts = 0
    while issues and attempts < max_repairs:
        attempts += 1
        completion = client.complete_json(
            _build_repair_messages(persona, habits, issues),
            seed=seed,
            max_tokens=HABITS_MAX_TOKENS,
        )
        habits = _normalise_habits(completion.data)
        issues = validate_portfolio(habits)

    if issues:
        raise HabitsGenerationError(
            "Habit portfolio remained unbalanced after "
            f"{attempts} repair(s): {'; '.join(issues)}"
        )

    profile = _assemble_profile(persona, habits, client=client, seed=seed, now=stamped)
    return HabitsGenerationResult(profile=profile, completion=completion, repair_attempts=attempts)


def _assemble_profile(
    persona: Persona,
    habits: list[Habit],
    *,
    client: LMStudioClient,
    seed: int | None,
    now: datetime,
) -> BehavioralProfile:
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
        return BehavioralProfile(
            profile_id=f"{persona.persona_id}_profile",
            persona_id=persona.persona_id,
            habits=habits,
            provenance=provenance,
        )
    except ValueError as error:
        raise HabitsGenerationError(f"Behavioural profile failed validation: {error}") from error


def _build_messages(persona: Persona) -> list[ChatMessage]:
    system = (
        "You design a realistic daily-habit portfolio for a fictional person in a smart-home "
        "behavioural dataset. Reply with a single JSON object and no prose."
    )
    user = (
        f"Person: {persona.name}, age {persona.age}, {persona.occupation}, {persona.household}, "
        f"in {persona.city}. Health: {', '.join(persona.health) or 'none noted'}. "
        f"Notes: {persona.notes or 'none'}.\n"
        f"Fixed daily anchors to include as anchor habits: "
        f"{', '.join(persona.routine_anchors)}.\n\n"
        'Return JSON {"habits": [ ... ]}. Each habit has:\n'
        '  "label" (short string), "kind" (one of anchor, contextual, optional, rare),\n'
        '  "frequency" (one of daily, few_times_week, weekly, biweekly, monthly, rarely),\n'
        '  "time_band" (one of early_morning, morning, midday, afternoon, evening, night),\n'
        '  optional "weekdays" (array like ["Tue","Fri"]) and "note" (short string).\n\n'
        "Provide AT LEAST 3 anchor, 2 contextual, 2 optional, and 1 rare habit (8 or more total). "
        "Anchors are near-daily fixed routines; contextual depend on day type; optional are "
        "occasional preferences; rare happen every few weeks or monthly. Keep them coherent with "
        "the person and mutually consistent."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _build_repair_messages(
    persona: Persona, habits: list[Habit], issues: list[str]
) -> list[ChatMessage]:
    counts = Counter(habit.kind.value for habit in habits)
    current = ", ".join(f"{kind}={counts.get(kind, 0)}" for kind in REQUIRED_KINDS)
    existing = ", ".join(f"{habit.label} ({habit.kind.value})" for habit in habits)
    system = (
        "You correct an unbalanced daily-habit portfolio. Reply with a single JSON object "
        '{"habits": [ ... ]} containing the FULL corrected list and no prose.'
    )
    user = (
        f"Person: {persona.name}, {persona.occupation}. Current kind counts: {current}.\n"
        f"Problems to fix:\n- " + "\n- ".join(issues) + "\n\n"
        f"Existing habits: {existing}.\n\n"
        "Return the complete corrected habit list (keep the good ones, add exactly what is "
        "missing) using the same fields: label, kind, frequency, time_band, optional weekdays "
        "and note. Required minimums: 3 anchor, 2 contextual, 2 optional, 1 rare, 8 or more total."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _normalise_habits(data: Any) -> list[Habit]:
    if isinstance(data, dict):
        raw = data.get("habits", data.get("habit", []))
    elif isinstance(data, list):
        raw = data
    else:
        raise HabitsGenerationError("Habit output must be a JSON object or array")
    if not isinstance(raw, list) or not raw:
        raise HabitsGenerationError("Habit output must contain a non-empty 'habits' array")

    habits: list[Habit] = []
    seen: set[str] = set()
    for entry in raw:
        habit = _normalise_habit(entry, seen)
        if habit is not None:
            habits.append(habit)
    if not habits:
        raise HabitsGenerationError("No habit entry could be normalised")
    return habits


def _normalise_habit(entry: Any, seen: set[str]) -> Habit | None:
    if not isinstance(entry, dict):
        return None
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    label = label.strip()

    habit_id = _unique_id(_slugify(label), seen)
    kind = _coerce_kind(entry.get("kind"))
    cadence = _build_cadence(entry.get("frequency"), entry.get("time_band"), entry.get("weekdays"))
    note = entry.get("note")
    try:
        return Habit(
            habit_id=habit_id,
            label=label,
            kind=kind,
            cadence=cadence,
            mining_difficulty=_difficulty_for(kind),
            note=note.strip() if isinstance(note, str) else "",
        )
    except ValueError:
        return None


def _build_cadence(frequency: Any, time_band: Any, weekdays: Any) -> HabitCadence:
    freq_key = frequency if isinstance(frequency, str) and frequency in _FREQUENCY_TO_CADENCE else (
        _DEFAULT_FREQUENCY
    )
    period, times, every = _FREQUENCY_TO_CADENCE[freq_key]
    band_key = time_band if isinstance(time_band, str) and time_band in _TIME_BAND_TO_WINDOW else (
        _DEFAULT_TIME_BAND
    )
    start, end = _TIME_BAND_TO_WINDOW[band_key]
    resolved_weekdays = _coerce_weekdays(weekdays)
    if period is CadencePeriod.week and resolved_weekdays:
        times = len(resolved_weekdays)
    return HabitCadence(
        period=period,
        times_per_period=times,
        every_n_periods=every,
        weekdays=resolved_weekdays,
        window_start=start,
        window_end=end,
    )


def _coerce_kind(value: Any) -> HabitKind:
    if isinstance(value, str):
        try:
            return HabitKind(value.strip().lower())
        except ValueError:
            return HabitKind.optional
    return HabitKind.optional


def _coerce_weekdays(value: Any) -> list[Weekday]:
    if not isinstance(value, list):
        return []
    resolved: list[Weekday] = []
    for item in value:
        if isinstance(item, str):
            day = _WEEKDAY_ALIASES.get(item.strip().lower())
            if day is not None and day not in resolved:
                resolved.append(day)
    return resolved


def _difficulty_for(kind: HabitKind) -> Literal["easy", "medium", "hard"]:
    if kind is HabitKind.anchor:
        return "easy"
    if kind is HabitKind.rare:
        return "hard"
    return "medium"


def _unique_id(base: str, seen: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "habit"
