"""The horizon outline: what an external LLM authors instead of concrete days (ADR-018).

Single-response authoring of a whole horizon collapses. Measured over the repository's generated
scenarios, the ratio of distinct daily signatures to days falls from 1.00 at a week to 0.74 at a
month to 0.03 at eight months: past roughly one month a model stops composing days and starts
copying a weekly template. The days are also where the size goes — 98.2% of the eight-month
bundle, of which 95% is literal repetition — while the process package, being per-intent, does not
grow with the horizon at all.

So the model stops writing days. It writes this instead: the recurring activities, the fixed
commitments, and
the arc of the period — phases that suspend or reshape recurring activities, and one-off events
with the window
they may land in. A deterministic expander rolls the outline into concrete days, computing sleep
debt, hunger, social need and fatigue, and placing occurrences.

The first constraint of ADR-018 — no timestamps outside fixed commitments — is enforced here by
construction rather than by a rule: no field of this contract can hold an absolute instant. Dates
select a day, `HH:MM` strings bound a band inside it, and durations are ranges. That is deliberate.
Requirement 11 of the authoring prompt asked for day-to-day variation for two versions and was
never enforceable, because the document it governed could express a pinned schedule. This one
cannot.

Two sources shape when an occurrence actually lands, and they are not interchangeable:

- the **drives** (`drives.py`) supply the slow, autocorrelated shift. A short night moves the whole
  following morning and makes a nap likely; yesterday still matters. This is state, and it is the
  reason the variation reads as a person rather than as noise.
- **`ActivityCadence.jitter_minutes`** bounds the fast, day-to-day wobble around that shift, per
  habit. It is what lets an anchor be punctual and an optional habit wander, which is the property
  `mining_difficulty` already presumes and which a single global spread cannot express.

The expander owns both. Neither is a field an author fills with a time.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, JsonValue, model_validator
from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
    JsonSchemaMode,
    JsonSchemaValue,
)

from smart_home_sim.domain.authoring import _remove_nested_resource_ids
from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    ExternalPerson,
    Location,
    LocationKind,
    Provenance,
    Resource,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.cadence import add_months
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    Weekday,
)

OUTLINE_SCHEMA_VERSION = "1.0.0"

_TIME_OF_DAY_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


class OutlineError(ValueError):
    """The outline is structurally valid JSON but cannot describe a coherent horizon."""


def _check_band(start: str, end: str, label: str) -> None:
    for value in (start, end):
        if not _TIME_OF_DAY_RE.match(value):
            raise ValueError(f"{label} must be HH:MM, got {value!r}")
    if start >= end:
        raise ValueError(f"{label} start must be before end")


class ActivityOverride(ContractModel):
    """What a phase does to one habit while it is active.

    Either the habit stops occurring, or it occurs on a different cadence. Both at once is
    contradictory and rejected: a suspended habit has no cadence to replace.
    """

    recurring_activity_id: str = Field(min_length=1)
    suspended: bool = False
    cadence: ActivityCadence | None = None

    @model_validator(mode="after")
    def check_exclusive(self) -> ActivityOverride:
        if self.suspended and self.cadence is not None:
            raise ValueError("a suspended activity cannot also declare a replacement cadence")
        if not self.suspended and self.cadence is None:
            raise ValueError("an override must either suspend the activity or replace its cadence")
        return self


class OutlinePhase(ContractModel):
    """A stretch of the horizon over which the routine is not the baseline routine.

    A phase is what makes eight months more than one month repeated eight times: a course that
    occupies Tuesday evenings from October, a fortnight away, a winter in which the walk stops.
    It carries dates, never instants, and reshapes recurring_activities only through explicit
    overrides.
    """

    phase_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    start_date: date
    end_date: date
    activity_overrides: list[ActivityOverride] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def check_phase(self) -> OutlinePhase:
        if self.start_date > self.end_date:
            raise ValueError(f"phase {self.phase_id!r} ends before it starts")
        seen = [item.recurring_activity_id for item in self.activity_overrides]
        if len(set(seen)) != len(seen):
            raise ValueError(f"phase {self.phase_id!r} overrides the same activity twice")
        return self


class Displacement(StrEnum):
    """What becomes of a activity occurrence the event pushed off its day."""

    skip = "skip"
    reschedule = "reschedule"


class ActivityDisplacement(ContractModel):
    """One habit the event pushes off its day, and what happens to that occurrence.

    The policy is carried per habit rather than per event because a single event routinely wants
    both. A week of flu postpones the shopping and simply cancels the runs; forcing one answer for
    the whole event would misdescribe half of it, and expressing the mixture as two overlapping
    events would be a workaround rather than a model.
    """

    recurring_activity_id: str = Field(min_length=1)
    policy: Displacement = Displacement.skip


class OutlineEvent(ContractModel):
    """Something that happens a bounded number of times inside a date window.

    The window is the point. `earliest_date == latest_date` pins the day when the day genuinely is
    fixed; anything wider hands the placement to the expander, which owns the calendar and the
    drive state and can put the event where the resident could plausibly absorb it.
    """

    event_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    earliest_date: date
    latest_date: date
    occurrences: int = Field(default=1, ge=1)
    # Time-of-day band, as for a recurring activity: a band is not a timestamp.
    window_start: str = "08:00"
    window_end: str = "22:00"
    minimum_minutes: int = Field(default=30, ge=1)
    maximum_minutes: int = Field(default=120, ge=1)
    weekdays: list[Weekday] = Field(default_factory=list)
    # Left unset, the expander maps the label to a canonical intent exactly as it does for a
    # recurring activity.
    intent: str | None = None
    displaces: list[ActivityDisplacement] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def check_event(self) -> OutlineEvent:
        if self.earliest_date > self.latest_date:
            raise ValueError(f"event {self.event_id!r} has an empty date window")
        _check_band(self.window_start, self.window_end, f"event {self.event_id!r} window")
        if self.minimum_minutes > self.maximum_minutes:
            raise ValueError(f"event {self.event_id!r} has an inverted duration range")
        span = (self.latest_date - self.earliest_date).days + 1
        if self.occurrences > span:
            raise ValueError(
                f"event {self.event_id!r} wants {self.occurrences} occurrences "
                f"in a {span}-day window"
            )
        displaced = [item.recurring_activity_id for item in self.displaces]
        if len(set(displaced)) != len(displaced):
            raise ValueError(f"event {self.event_id!r} repeats a displaced activity")
        return self


class FixedCommitment(ContractModel):
    """The one place absolute clock times are legitimate.

    Working hours and appointments are fixed by someone other than the resident, so pinning them
    is a fact about the world rather than a schedule the model invented. Everything else in this
    contract is a window.
    """

    commitment_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    weekdays: list[Weekday] = Field(min_length=1)
    start_time: str
    end_time: str
    # What the resident is doing while away. Declared, never guessed, exactly as for a habit.
    intent: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    note: str = ""

    @model_validator(mode="after")
    def check_commitment(self) -> FixedCommitment:
        _check_band(self.start_time, self.end_time, f"commitment {self.commitment_id!r}")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError(f"commitment {self.commitment_id!r} repeats a weekday")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError(f"commitment {self.commitment_id!r} ends before it starts")
        return self


class OutlineWorld(ContractModel):
    """Where the routine happens, declared once for the whole horizon.

    ADR-015 materializes the executable home from the scenario's declared locations, so those
    declarations have to come from the author rather than from a generator that never read the
    brief. Like everything else here, this is O(1) in the horizon.
    """

    home_model: VersionedReference
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    external_people: list[ExternalPerson] = Field(default_factory=list)
    start_location_id: str = Field(min_length=1)
    resident_facts: dict[str, JsonValue] = Field(default_factory=dict)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_facts: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_world(self) -> OutlineWorld:
        location_ids = [item.location_id for item in self.locations]
        if len(set(location_ids)) != len(location_ids):
            raise ValueError("location identifiers must be unique")
        known = set(location_ids)
        primitive = {
            item.location_id for item in self.locations if item.kind is not LocationKind.composite
        }
        for location in self.locations:
            for member in location.member_location_ids:
                if member not in primitive:
                    raise ValueError(
                        f"composite location {location.location_id!r} references "
                        f"unknown member {member!r}"
                    )
        resource_ids = [item.resource_id for item in self.resources]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("resource identifiers must be unique")
        for resource in self.resources:
            if resource.location_id not in known:
                raise ValueError(
                    f"resource {resource.resource_id!r} sits in unknown location "
                    f"{resource.location_id!r}"
                )
        if self.start_location_id not in primitive:
            raise ValueError(
                f"start location {self.start_location_id!r} is not a declared primitive location"
            )
        for resource_id in self.resource_facts:
            if resource_id not in set(resource_ids):
                raise ValueError(f"resourceFacts names unknown resource {resource_id!r}")
        return self


class HabitSegment(ContractModel):
    """A habit in the sense the smart-home literature uses the word.

    Leotta, Mecella and Sora define a habit as "a sequence or interleaving of activities that
    happen in specific contextual conditions", the focus being the routine rather than the goal —
    what the resident does each morning between 08:00 and 10:00. The habit-segmentation work makes
    the same point operationally: it discretises the timestamp axis, and each bin is a time range
    in which a clearly identifiable process runs. In their Aruba results the bin `05:15-07:00` is
    about 80% the *sleeping activity*, with `bed_to_toilet` and `meal_preparation` making up most
    of the rest.

    So a habit is a band of the day, and activities live inside it. That is why this contract
    separates the two: `RecurringActivity` says what recurs and how often, and this says how the
    day is carved up. A researcher's segmentation algorithm is trying to recover exactly these
    bands from a sensor log, which is why the expander publishes them as ground truth.

    The night band is the one that legitimately wraps: `window_start` after `window_end` means the
    segment crosses midnight.
    """

    habit_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    window_start: str
    window_end: str
    # The activities expected to populate the band. Declaring them is optional — the expander
    # measures what actually lands there — but it records the author's intent for the reader.
    recurring_activity_ids: list[str] = Field(default_factory=list)
    note: str = ""

    @property
    def crosses_midnight(self) -> bool:
        return self.window_start > self.window_end

    @model_validator(mode="after")
    def check_segment(self) -> HabitSegment:
        for value in (self.window_start, self.window_end):
            if not _TIME_OF_DAY_RE.match(value):
                raise ValueError(f"habit {self.habit_id!r} band must be HH:MM, got {value!r}")
        if self.window_start == self.window_end:
            raise ValueError(f"habit {self.habit_id!r} has an empty band")
        if len(set(self.recurring_activity_ids)) != len(self.recurring_activity_ids):
            raise ValueError(f"habit {self.habit_id!r} repeats an activity")
        return self

    def minute_spans(self) -> list[tuple[int, int]]:
        """The band as minute ranges inside one day, split in two when it crosses midnight."""
        start = _to_minutes(self.window_start)
        end = _to_minutes(self.window_end)
        if start < end:
            return [(start, end)]
        return [(start, 24 * 60), (0, end)]


class OutlineRhythm(ContractModel):
    """The persona-level constants the drive dynamics need, and nothing more.

    Age sets the nightly sleep need and the nocturia baseline; declared conditions move the same
    two dials. Everything downstream of these — the actual bedtimes, the debt, the naps — is
    computed, which is why an author declares who the resident is rather than when she sleeps.
    """

    age: int = Field(default=45, ge=1, le=120)
    health: list[str] = Field(default_factory=list)
    chronotype_bedtime: str = "22:30"

    @model_validator(mode="after")
    def check_rhythm(self) -> OutlineRhythm:
        if not _TIME_OF_DAY_RE.match(self.chronotype_bedtime):
            raise ValueError(f"chronotypeBedtime must be HH:MM, got {self.chronotype_bedtime!r}")
        return self


class HorizonOutline(ContractModel):
    """One brief, one confirmed outline, any horizon length.

    Nothing here grows with the number of days: a year and eight months differ in the event list,
    not in the structure. The confirmed outline is also the habit ground truth the external
    authoring path has never produced, `mining_difficulty` included.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:horizon-outline:1.0.0",
            "title": "Smart Home Horizon Outline 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["horizon_outline"] = "horizon_outline"
    outline_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    months: int = Field(ge=1)
    world: OutlineWorld
    profile: BehavioralProfile
    rhythm: OutlineRhythm = Field(default_factory=OutlineRhythm)
    habits: list[HabitSegment] = Field(default_factory=list)
    fixed_commitments: list[FixedCommitment] = Field(default_factory=list)
    phases: list[OutlinePhase] = Field(default_factory=list)
    events: list[OutlineEvent] = Field(default_factory=list)
    provenance: Provenance
    note: str = ""

    @property
    def end_date(self) -> date:
        """First day past the horizon, matching the cadence calendar's half-open span."""
        return add_months(self.start_date, self.months)

    def _within(self, day: date) -> bool:
        return self.start_date <= day < self.end_date

    @model_validator(mode="after")
    def check_outline(self) -> HorizonOutline:
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone {self.time_zone!r}") from error

        for items, what in (
            ([item.phase_id for item in self.phases], "phase"),
            ([item.event_id for item in self.events], "event"),
            ([item.commitment_id for item in self.fixed_commitments], "commitment"),
            ([item.habit_id for item in self.habits], "habit"),
        ):
            if len(set(items)) != len(items):
                raise ValueError(f"{what} identifiers must be unique")

        known = {activity.recurring_activity_id for activity in self.profile.recurring_activities}
        for segment in self.habits:
            for activity_id in segment.recurring_activity_ids:
                if activity_id not in known:
                    raise ValueError(
                        f"habit {segment.habit_id!r} lists unknown activity {activity_id!r}"
                    )
        # Habits partition the day, so two of them may not claim the same minute: a segmentation
        # ground truth that assigned one timestamp to two bins would not be a segmentation.
        spans = [
            (span, segment.habit_id) for segment in self.habits for span in segment.minute_spans()
        ]
        spans.sort()
        for (first, first_id), (second, second_id) in zip(spans, spans[1:], strict=False):
            if second[0] < first[1]:
                raise ValueError(f"habits {first_id!r} and {second_id!r} overlap in the day")

        for phase in self.phases:
            for override in phase.activity_overrides:
                if override.recurring_activity_id not in known:
                    raise ValueError(
                        f"phase {phase.phase_id!r} overrides unknown activity "
                        f"{override.recurring_activity_id!r}"
                    )
            for day, edge in ((phase.start_date, "start"), (phase.end_date, "end")):
                if not self._within(day):
                    raise ValueError(f"phase {phase.phase_id!r} {edge} falls outside the horizon")

        for event in self.events:
            for displaced in event.displaces:
                if displaced.recurring_activity_id not in known:
                    raise ValueError(
                        f"event {event.event_id!r} displaces unknown activity "
                        f"{displaced.recurring_activity_id!r}"
                    )
            for day, edge in ((event.earliest_date, "earliest"), (event.latest_date, "latest")):
                if not self._within(day):
                    raise ValueError(f"event {event.event_id!r} {edge} falls outside the horizon")

        for commitment in self.fixed_commitments:
            for day, edge in (
                (commitment.start_date, "start"),
                (commitment.end_date, "end"),
            ):
                if day is not None and not self._within(day):
                    raise ValueError(
                        f"commitment {commitment.commitment_id!r} {edge} falls outside the horizon"
                    )

        # Two phases overriding one habit at the same time leave the expander without a rule to
        # pick between them, and a silent winner is exactly the class of defect this contract
        # exists to remove.
        for index, first in enumerate(self.phases):
            for second in self.phases[index + 1 :]:
                if first.start_date > second.end_date or second.start_date > first.end_date:
                    continue
                shared = {item.recurring_activity_id for item in first.activity_overrides} & {
                    item.recurring_activity_id for item in second.activity_overrides
                }
                if shared:
                    raise ValueError(
                        f"phases {first.phase_id!r} and {second.phase_id!r} overlap and both "
                        f"override {sorted(shared)[0]!r}"
                    )
        return self


class HorizonAuthoringBundle(ContractModel):
    """Transport envelope for outline-first authoring: the arc, and how its actions are performed.

    Kept apart for the same reason `SimulationAuthoringBundle` keeps scenario and package apart:
    the two halves answer to different reviewers. A human confirms the outline, because whether
    eight months are plausible is not a machine question. The process package is already gated by
    behavior validation and the deterministic replay, so nobody needs to read its twenty-four
    graphs by hand.

    Neither half grows with the horizon. The package is per-intent, which is why moving the days
    out of the model's output removes the entire horizon-proportional part of the response.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:horizon-authoring-bundle:1.0.0",
            "title": "Smart Home Horizon Authoring Bundle 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["horizon_authoring_bundle"] = "horizon_authoring_bundle"
    outline: HorizonOutline
    personal_process_package: PersonalProcessPackage

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
    ) -> JsonSchemaValue:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
        )
        # Both halves publish their own `$id`; composed into one document they must not, or the
        # local `$ref`s stop resolving against the root. Same treatment as the simulation bundle.
        _remove_nested_resource_ids(schema, root=True)
        return schema


class HabitComposition(ContractModel):
    """How much of one habit band a single activity accounts for, measured over the horizon."""

    intent: str = Field(min_length=1)
    minutes: float = Field(ge=0)
    share: float = Field(ge=0, le=1)


class HabitObservation(ContractModel):
    """One habit band with the activity mix that actually landed inside it.

    This is the shape of Table IV in the habit-segmentation paper: for the Aruba bin `05:15-07:00`
    the sleeping activity accounts for about 80% of the band, the rest being other activities or
    unlabelled time. `unaccounted_share` is that remainder — minutes inside the band during which
    the plan has the resident doing nothing the outline named.
    """

    habit_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    window_start: str
    window_end: str
    crosses_midnight: bool
    day_count: int = Field(ge=0)
    total_minutes: float = Field(ge=0)
    composition: list[HabitComposition] = Field(default_factory=list)
    unaccounted_minutes: float = Field(ge=0)
    unaccounted_share: float = Field(ge=0, le=1)


class HabitGroundTruth(ContractModel):
    """What a habit-segmentation algorithm is supposed to recover, published as evidence.

    The researcher's algorithm sees only a sensor log and must discover both where the day divides
    and what runs in each division. This document states the answer: the bands the outline
    declared, and the activity mix the generated horizon actually produced in each. It is derived
    from the plan, not from an execution, so it is the *planned* truth — deviations introduced by
    the simulator belong to the execution trace.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:habit-ground-truth:1.0.0",
            "title": "Smart Home Habit Ground Truth 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["habit_ground_truth"] = "habit_ground_truth"
    outline_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    end_date: date
    seed: int
    habits: list[HabitObservation] = Field(default_factory=list)
    provenance: Provenance
