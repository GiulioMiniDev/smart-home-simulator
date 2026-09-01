"""Generate a frozen behavioural profile (the habit ground truth) from a persona via LM Studio.

The model proposes a small habit list over closed vocabularies (kind, frequency, time band).
Deterministic code expands each proposal into a schedulable habit, assembles the profile, and gates
it on a portfolio balance (enough anchor/contextual/optional/rare ones). An unbalanced portfolio
triggers a bounded, directive repair that states the exact current-versus-required counts, because a
small model otherwise under-produces the rarer kinds. The accepted profile is the frozen ground
truth the cadence calendar later expands into planned habit occurrences.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
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

PROMPT_TEMPLATE_VERSION = "recurring_activities-1.0.0"
GENERATOR_NAME = "smart-home-sim.hybrid_planning.recurring_activities"
GENERATOR_VERSION = "1.0.0"

# Reasoning models spend completion tokens on a private preamble, so the habit list needs a larger
# budget than a persona to avoid truncation.
HABITS_MAX_TOKENS = 16384

MIN_RECURRING_ACTIVITIES = 8
REQUIRED_KINDS: dict[str, int] = {"anchor": 3, "contextual": 2, "optional": 2, "rare": 1}

_TIME_ZONE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# The narrowest sub-band a daily cadence may divide its window into. Two occurrences drawn from
# twenty minutes apiece are still two moments a mining algorithm can tell apart; below that the
# "band" is a pin, and asking for four occurrences inside an hour describes a single stretch of
# time the author should have declared as one.
MINIMUM_SUB_BAND_MINUTES = 20


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


class RecurringActivityKind(StrEnum):
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


# The enum is declared in `date.weekday()` order, 0 = Monday. That is load-bearing wherever a
# calendar day has to be matched against a declared weekday, so it lives here beside the enum
# rather than being re-derived at each call site.
WEEKDAY_BY_INDEX: tuple[Weekday, ...] = tuple(Weekday)


def weekday_of(moment: date) -> Weekday:
    return WEEKDAY_BY_INDEX[moment.weekday()]


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


class ProfileGenerationError(ValueError):
    """The model output could not be turned into a balanced, valid behavioural profile."""


class ActivityCadence(ContractModel):
    """How often a recurring activity happens, and inside which hours.

    `times_per_period` means different things per period, and both readings are the natural one.
    Over a week or a month it counts *days*: three runs a week are three days on which a run
    happens. Over a day it counts *occurrences inside that day*, which is what a working day split
    into blocks, a course of medication taken twice, or a dog walked morning and evening actually
    is. The daily reading used to be discarded — `_due_times` scheduled exactly one occurrence per
    day whatever the field said — so an author writing `period: day, timesPerPeriod: 4` got one
    activity and no warning.
    """

    period: CadencePeriod
    times_per_period: int = Field(ge=1)
    every_n_periods: int = Field(default=1, ge=1)
    weekdays: list[Weekday] = Field(default_factory=list)
    window_start: str
    window_end: str
    # How far an occurrence ordinarily wanders from its usual moment — the spread of the common
    # case, not a bound on every day. `irregularity.stray_minutes` reads it as the width of the
    # mixture's body and adds the rare wide occurrence itself, so an author who wants a habit to be
    # occasionally very late does not have to widen the number until it is late every day.
    jitter_minutes: int = Field(default=30, ge=0)

    @model_validator(mode="after")
    def check_window(self) -> ActivityCadence:
        for value in (self.window_start, self.window_end):
            if not _TIME_ZONE_RE.match(value):
                raise ValueError(f"cadence window must be HH:MM, got {value!r}")
        if self.window_start >= self.window_end:
            raise ValueError("cadence window start must be before end")
        if self.period is CadencePeriod.day and self.times_per_period > 1:
            span = _to_minutes(self.window_end) - _to_minutes(self.window_start)
            needed = self.times_per_period * MINIMUM_SUB_BAND_MINUTES
            if span < needed:
                raise ValueError(
                    f"a daily cadence of {self.times_per_period} occurrences splits its window "
                    f"into {self.times_per_period} sub-bands, which needs at least {needed} "
                    f"minutes; {self.window_start}-{self.window_end} gives {span}"
                )
        return self


class RecurringActivity(ContractModel):
    recurring_activity_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: RecurringActivityKind
    cadence: ActivityCadence
    mining_difficulty: Literal["easy", "medium", "hard"] = "medium"
    # Which canonical intent this habit performs. Left unset the intent is inferred from the label
    # by keyword, which is safe here — the local pipeline writes those labels itself — but not for
    # an externally authored outline, where free prose silently misses: "Teach at Idioms High
    # School" matched nothing and fell back to `read_and_rest`, quietly disagreeing with the
    # process model the same document declared for it.
    intent: str | None = None
    # Which room this particular habit happens in, when it is not the one the activity catalog
    # gives the intent.
    #
    # It belongs here rather than on the intent because the intent is the *label* — what a
    # recogniser must output — and two habits can perform the same activity in different places:
    # television on the sofa in the afternoon and television at the kitchen table over dinner are
    # one activity and two habits. Moving the room onto the intent would have split the label
    # space instead, which changes what the dataset claims happened.
    #
    # Left unset, the catalog's room stands, so every outline written before this field means what
    # it meant. Set, the room must be one the world declares and must hold furniture answering what
    # the intent's process model needs — `_check_activity_locations` refuses the rest, because a
    # room that cannot answer binds to the per-region anchor and deletes the evidence silently.
    location: str | None = None
    note: str = ""


class BehavioralProfile(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["behavioral_profile"] = "behavioral_profile"
    profile_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    recurring_activities: list[RecurringActivity] = Field(min_length=MIN_RECURRING_ACTIVITIES)
    provenance: Provenance

    @model_validator(mode="after")
    def check_unique_ids(self) -> BehavioralProfile:
        identifiers = [activity.recurring_activity_id for activity in self.recurring_activities]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("activity identifiers must be unique")
        return self


@dataclass(frozen=True)
class ProfileGenerationResult:
    profile: BehavioralProfile
    completion: LMStudioJSONCompletion
    repair_attempts: int


def validate_portfolio(recurring_activities: list[RecurringActivity]) -> list[str]:
    """Return directive issue strings for an unbalanced or too-small activity portfolio."""
    counts = Counter(activity.kind.value for activity in recurring_activities)
    issues: list[str] = []
    if len(recurring_activities) < MIN_RECURRING_ACTIVITIES:
        issues.append(
            f"total activities: have {len(recurring_activities)}, "
            f"need >= {MIN_RECURRING_ACTIVITIES}"
        )
    for kind, required in REQUIRED_KINDS.items():
        have = counts.get(kind, 0)
        if have < required:
            issues.append(
                f"{kind} activities: have {have}, need >= {required} (add {required - have})"
            )
    return issues


def generate_recurring_activities(
    persona: Persona,
    client: LMStudioClient,
    *,
    max_repairs: int = 2,
    seed: int | None = None,
    now: datetime | None = None,
) -> ProfileGenerationResult:
    """Generate, balance, and freeze a behavioural profile for one persona."""
    stamped = now or datetime.now(UTC)
    completion = client.complete_json(
        _build_messages(persona), seed=seed, max_tokens=HABITS_MAX_TOKENS
    )
    recurring_activities = _normalise_recurring_activities(completion.data)
    issues = validate_portfolio(recurring_activities)

    attempts = 0
    while issues and attempts < max_repairs:
        attempts += 1
        completion = client.complete_json(
            _build_repair_messages(persona, recurring_activities, issues),
            seed=seed,
            max_tokens=HABITS_MAX_TOKENS,
        )
        recurring_activities = _normalise_recurring_activities(completion.data)
        issues = validate_portfolio(recurring_activities)

    if issues:
        raise ProfileGenerationError(
            f"Activity portfolio remained unbalanced after {attempts} repair(s): "
            f"{'; '.join(issues)}"
        )

    profile = _assemble_profile(
        persona, recurring_activities, client=client, seed=seed, now=stamped
    )
    return ProfileGenerationResult(profile=profile, completion=completion, repair_attempts=attempts)


def _assemble_profile(
    persona: Persona,
    recurring_activities: list[RecurringActivity],
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
            recurring_activities=recurring_activities,
            provenance=provenance,
        )
    except ValueError as error:
        raise ProfileGenerationError(f"Behavioural profile failed validation: {error}") from error


def _build_messages(persona: Persona) -> list[ChatMessage]:
    system = (
        "You design a realistic daily-activity portfolio for a fictional person in a smart-home "
        "behavioural dataset. Reply with a single JSON object and no prose."
    )
    user = (
        f"Person: {persona.name}, age {persona.age}, {persona.occupation}, {persona.household}, "
        f"in {persona.city}. Health: {', '.join(persona.health) or 'none noted'}. "
        f"Notes: {persona.notes or 'none'}.\n"
        f"Fixed daily anchors to include as anchor recurring_activities: "
        f"{', '.join(persona.routine_anchors)}.\n\n"
        'Return JSON {"recurring_activities": [ ... ]}. Each activity has:\n'
        '  "label" (short string), "kind" (one of anchor, contextual, optional, rare),\n'
        '  "frequency" (one of daily, few_times_week, weekly, biweekly, monthly, rarely),\n'
        '  "time_band" (one of early_morning, morning, midday, afternoon, evening, night),\n'
        '  optional "weekdays" (array like ["Tue","Fri"]) and "note" (short string).\n\n'
        "Provide AT LEAST 3 anchor, 2 contextual, 2 optional and 1 rare activity "
        "(8 or more in total). "
        "Anchors are near-daily fixed routines; contextual depend on day type; optional are "
        "occasional preferences; rare happen every few weeks or monthly. Keep them coherent with "
        "the person and mutually consistent."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _build_repair_messages(
    persona: Persona, recurring_activities: list[RecurringActivity], issues: list[str]
) -> list[ChatMessage]:
    counts = Counter(activity.kind.value for activity in recurring_activities)
    current = ", ".join(f"{kind}={counts.get(kind, 0)}" for kind in REQUIRED_KINDS)
    existing = ", ".join(
        f"{activity.label} ({activity.kind.value})" for activity in recurring_activities
    )
    system = (
        "You correct an unbalanced daily-activity portfolio. Reply with a single JSON object "
        '{"recurring_activities": [ ... ]} containing the FULL corrected list and no prose.'
    )
    user = (
        f"Person: {persona.name}, {persona.occupation}. Current kind counts: {current}.\n"
        f"Problems to fix:\n- " + "\n- ".join(issues) + "\n\n"
        f"Existing recurring_activities: {existing}.\n\n"
        "Return the complete corrected activity list (keep the good ones, add exactly what is "
        "missing) using the same fields: label, kind, frequency, time_band, optional weekdays "
        "and note. Required minimums: 3 anchor, 2 contextual, 2 optional, 1 rare, 8 or more total."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _normalise_recurring_activities(data: Any) -> list[RecurringActivity]:
    if isinstance(data, dict):
        raw = data.get("recurring_activities", data.get("activity", []))
    elif isinstance(data, list):
        raw = data
    else:
        raise ProfileGenerationError("RecurringActivity output must be a JSON object or array")
    if not isinstance(raw, list) or not raw:
        raise ProfileGenerationError(
            "RecurringActivity output must contain a non-empty 'recurring_activities' array"
        )

    recurring_activities: list[RecurringActivity] = []
    seen: set[str] = set()
    for entry in raw:
        activity = _normalise_recurring_activity(entry, seen)
        if activity is not None:
            recurring_activities.append(activity)
    if not recurring_activities:
        raise ProfileGenerationError("No activity entry could be normalised")
    return recurring_activities


def _normalise_recurring_activity(entry: Any, seen: set[str]) -> RecurringActivity | None:
    if not isinstance(entry, dict):
        return None
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    label = label.strip()

    recurring_activity_id = _unique_id(_slugify(label), seen)
    kind = _coerce_kind(entry.get("kind"))
    cadence = _build_cadence(entry.get("frequency"), entry.get("time_band"), entry.get("weekdays"))
    note = entry.get("note")
    try:
        return RecurringActivity(
            recurring_activity_id=recurring_activity_id,
            label=label,
            kind=kind,
            cadence=cadence,
            mining_difficulty=_difficulty_for(kind),
            note=note.strip() if isinstance(note, str) else "",
        )
    except ValueError:
        return None


def _build_cadence(frequency: Any, time_band: Any, weekdays: Any) -> ActivityCadence:
    freq_key = (
        frequency
        if isinstance(frequency, str) and frequency in _FREQUENCY_TO_CADENCE
        else (_DEFAULT_FREQUENCY)
    )
    period, times, every = _FREQUENCY_TO_CADENCE[freq_key]
    band_key = (
        time_band
        if isinstance(time_band, str) and time_band in _TIME_BAND_TO_WINDOW
        else (_DEFAULT_TIME_BAND)
    )
    start, end = _TIME_BAND_TO_WINDOW[band_key]
    resolved_weekdays = _coerce_weekdays(weekdays)
    if period is CadencePeriod.week and resolved_weekdays:
        times = len(resolved_weekdays)
    return ActivityCadence(
        period=period,
        times_per_period=times,
        every_n_periods=every,
        weekdays=resolved_weekdays,
        window_start=start,
        window_end=end,
    )


def _coerce_kind(value: Any) -> RecurringActivityKind:
    if isinstance(value, str):
        try:
            return RecurringActivityKind(value.strip().lower())
        except ValueError:
            return RecurringActivityKind.optional
    return RecurringActivityKind.optional


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


def _difficulty_for(kind: RecurringActivityKind) -> Literal["easy", "medium", "hard"]:
    if kind is RecurringActivityKind.anchor:
        return "easy"
    if kind is RecurringActivityKind.rare:
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
    return slug or "activity"
