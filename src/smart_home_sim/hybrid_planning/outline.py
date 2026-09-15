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
- **`ActivityCadence.jitter_minutes`** sizes the fast, day-to-day wobble around that shift, per
  habit. It is what lets an anchor be punctual and an optional habit wander, which is the property
  `mining_difficulty` already presumes and which a single global spread cannot express. It is the
  spread of an *ordinary* occurrence, not a bound on every one: `irregularity.stray_minutes` draws
  the wobble from a narrow body of that width plus a rare wide tail, because a bounded draw made
  the generated resident keep 96% of her nights within an hour of her usual bedtime where the
  Aruba resident keeps 60%.

The expander owns both. Neither is a field an author fills with a time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
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
from smart_home_sim.hybrid_planning.intents import IntentCategory
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    RecurringActivity,
    Weekday,
    weekday_of,
)

OUTLINE_SCHEMA_VERSION = "2.0.0"

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

    A band may also be scoped to particular days. Working hours are already weekday-scoped —
    `FixedCommitment.weekdays` is mandatory — so a single band covering 08:30-17:30 every day of
    the week has to hold both the working day and the domestic Saturday, and a segmentation
    algorithm asked to recover it is being asked to find one boundary for two behaviours. Measured
    on a generated year: the same band was `work_shift` at 96% across 260 weekdays and, across 105
    weekend days, a mixture whose largest component was `buy_groceries` at 23%. The band that
    produced those numbers had been named "Fascia diurna e weekend domestico" by its author, who
    could see the problem and had no field in which to say it.
    """

    habit_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    window_start: str
    window_end: str
    # The activities expected to populate the band. Declaring them is optional — the expander
    # measures what actually lands there — but it records the author's intent for the reader.
    recurring_activity_ids: list[str] = Field(default_factory=list)
    # Which days the band applies to. Empty means every day, which is what every outline written
    # before this field existed meant, so leaving it out stays valid and keeps its meaning.
    weekdays: list[Weekday] = Field(default_factory=list)
    note: str = ""

    def applies_on(self, moment: date) -> bool:
        return not self.weekdays or weekday_of(moment) in self.weekdays

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
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError(f"habit {self.habit_id!r} repeats a weekday")
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


_WEEKEND: frozenset[Weekday] = frozenset({Weekday.saturday, Weekday.sunday})


class SharingMode(StrEnum):
    """How two residents stand towards one activity.

    Four values and not two, because "together or not" hides two different questions. Whether a
    dinner is one event with two participants or two events at the same table is a question about
    the *occurrence*. Whether the other may be in the room at all while this one washes is a
    question about the *room*. Collapsing them loses the bathroom, which is the case that made the
    distinction necessary in the first place.
    """

    joint = "joint"
    optional_joint = "optional_joint"
    independent = "independent"
    exclusive = "exclusive"


class RelationKind(StrEnum):
    """Why two residents share a roof. Sharing follows from this, never from the activity.

    Two friends splitting the rent do not shower together and do not share a bed; a couple may, or
    may not. None of it is derivable from an intent, which is why the relation is declared and the
    policy resolves on the pair rather than on the house.
    """

    couple = "couple"
    housemates = "housemates"
    parent_child = "parent_child"
    siblings = "siblings"
    other = "other"


class HouseholdRelation(ContractModel):
    """What two named residents are to each other.

    Pairwise and not household-wide: in a couple with a teenager the sharing policy between the two
    parents is not the policy between a parent and the child, and a single household-level
    declaration would have to pick one of them and be wrong about the other.

    For `parent_child` the order of `between` is read: the first is the parent. Every other kind is
    symmetric and the order carries nothing.
    """

    between: list[str] = Field(min_length=2, max_length=2)
    kind: RelationKind
    note: str = ""

    @property
    def pair(self) -> frozenset[str]:
        return frozenset(self.between)

    @model_validator(mode="after")
    def check_relation(self) -> HouseholdRelation:
        if self.between[0] == self.between[1]:
            raise ValueError("a relation needs two distinct residents")
        return self


class SharingPropensity(ContractModel):
    """How often an `optional_joint` activity is actually shared, indexed by class of day.

    One number averages two regimes a household genuinely has. A couple who watch television
    together at the weekend and almost never during the week are described by `0.4` only in the
    sense that a person with one foot in ice and one in fire is on average comfortable: the
    expander would then scatter shared evenings at random through the working week and *fabricate*
    a weekly pattern in the ground truth, in precisely the distinction `day_types` exists to
    preserve.

    Indexed on the axis the outline already owns rather than on a predicate language. `weekdays`
    exists on `ActivityCadence`, `day_types` exists on the ground truth, phase overrides already
    pass through `ActivityOverride`, and a small model emits a number where it would invent a
    syntax — the same failure the authoring prompt shouts about for intents.

    A number never stands alone: co-presence is a precondition the expander checks before drawing,
    so a propensity cannot conjure a shared dinner on a day whose bands never meet.
    """

    default: float = Field(ge=0, le=1)
    weekday: float | None = Field(default=None, ge=0, le=1)
    weekend: float | None = Field(default=None, ge=0, le=1)

    def on(self, moment: date) -> float:
        """The declared propensity for the class of day `moment` belongs to."""
        if weekday_of(moment) in _WEEKEND:
            return self.default if self.weekend is None else self.weekend
        return self.default if self.weekday is None else self.weekday


class JointActivity(ContractModel):
    """A recurring activity declared once for the household, with its participants named.

    The rule this type exists to enforce: a shared activity is declared **once**, never once per
    resident. Asked for a family's routine in one response, a language model writes "dinner" twice
    with two similar bands; the solver has no reason to align them, they drift by forty minutes,
    and the dataset holds two dinners where the house had one.

    There is no "both" field anywhere here. In a household of four the dinner has four participants
    and the school run has two, and a contract that can only say *together* cannot say the second.

    The occurrence is anchored to the last participant who becomes free, which is not a field but a
    consequence: the expander has to place one interval that fits everybody, so if one of them is
    still commuting the interval moves past the arrival. The wait in front of it — the one who got
    home early tidying the kitchen for twenty-five minutes — is a residue of that anchoring and not
    a mechanism anybody wrote.
    """

    activity: RecurringActivity
    participant_ids: list[str] = Field(min_length=2)
    sharing: SharingMode = SharingMode.joint
    # Required for `optional_joint` and refused otherwise: a `joint` activity that also carried a
    # propensity would be declaring two different things about the same occurrence.
    propensity: SharingPropensity | None = None
    # Below this much overlap between the participants' bands the occurrence is not shared. A
    # breakfast squeezed into the twelve minutes two people have in common before one of them
    # leaves is an artefact of the arithmetic, not a shared breakfast.
    minimum_shared_minutes: int = Field(default=0, ge=0)
    # What happens on a day where the joint version does not fit, because the one who got home
    # early has something at 13:30 and cannot wait. Separately, and not compressed: eating a
    # forty-minute lunch in fifteen would be a worse lie than eating it alone. The decision belongs
    # to the compiler, the only layer that knows the slack; this flag says whether it may take it,
    # and `minimum_shared_minutes` is where "does not fit" begins.
    #
    # On by default. It was off while the habit ground truth was measured on the expanded plan,
    # because a day the compiler degraded then published a shared meal the plan did not contain.
    # The ground truth is measured on the run now, so whatever the compiler chose is what it
    # describes, and the realistic day costs nothing in truth. Turned off, a shared activity that
    # does not fit is squeezed or makes the day infeasible, which an author may still want to see.
    degrade_to_independent: bool = True
    note: str = ""

    @model_validator(mode="after")
    def check_joint_activity(self) -> JointActivity:
        what = self.activity.recurring_activity_id
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError(f"joint activity {what!r} repeats a participant")
        if self.sharing is SharingMode.optional_joint:
            if self.propensity is None:
                raise ValueError(
                    f"joint activity {what!r} is optional_joint and must declare a propensity"
                )
        elif self.sharing is SharingMode.joint:
            if self.propensity is not None:
                raise ValueError(
                    f"joint activity {what!r} is joint and cannot also declare a propensity"
                )
        else:
            raise ValueError(
                f"joint activity {what!r} declares {self.sharing.value!r}; a shared activity is "
                "joint or optional_joint, and an unshared one belongs to a resident"
            )
        return self


class SharingPolicy(ContractModel):
    """What happens when two residents each declared the same intent for themselves.

    `joint` and `optional_joint` cannot be written here, on purpose. An activity that is shared is
    declared once in `jointActivities`; a policy claiming these two share dinner while two dinners
    sit in two individual profiles is the divergence the household level exists to prevent, and the
    error message says where the declaration belongs.

    What is left is the pair of modes that govern two separately declared occurrences: whether they
    merely contend for the one kitchen, which the compiler already resolves through resources, or
    whether one of them empties the room.
    """

    between: list[str] = Field(min_length=2, max_length=2)
    intent: str = Field(min_length=1)
    sharing: SharingMode
    note: str = ""

    @property
    def pair(self) -> frozenset[str]:
        return frozenset(self.between)

    @model_validator(mode="after")
    def check_policy(self) -> SharingPolicy:
        if self.between[0] == self.between[1]:
            raise ValueError("a sharing policy needs two distinct residents")
        if self.sharing in (SharingMode.joint, SharingMode.optional_joint):
            raise ValueError(
                f"sharing policy for {self.intent!r} declares {self.sharing.value!r}: a shared "
                "activity is declared once in household.jointActivities, not twice in two profiles"
            )
        return self


class LocationPrivacy(ContractModel):
    """Who may not be in a room while its occupant is using it.

    Not capacity, and the difference is the whole point. Capacity counts bodies, and no room has a
    true one: two people fit in a shower cabin, and at the table one can sit in the other's lap.
    What decides co-presence is a norm between two named people, directional and specific to what
    the subject is doing, and an integer can express neither. `capacity 1 exceeded` is also not an
    error a researcher can read, where "Marco does not share the bathroom while he washes, and
    Luca's morning has no other window" is.

    What survives from capacity is on `Resource`, where it always belonged: `Resource.capacity`
    never counted bodies, it counts simultaneous *uses*. A shower taken by two is one use with two
    participants and passes; two independent showers at the same instant are two uses of one jet
    and are refused, without the model ever pronouncing on how many people are in the cabin.

    Directional, with a symmetric shorthand. Between two adults the norm is almost always
    reciprocal and is written once; between a parent and a small child it is not, and a
    symmetric-only contract could not say so.
    """

    location_id: str = Field(min_length=1)
    # The resident whose privacy this declares.
    subject_id: str = Field(min_length=1)
    # Left empty, everybody else in the household is excluded. Naming them matters once there are
    # three: a teenager may be kept out of a room a partner may enter.
    excluded_resident_ids: list[str] = Field(default_factory=list)
    # Left empty, the room is private whatever the subject is doing in it. Named, only for those.
    intents: list[str] = Field(default_factory=list)
    # Whether the same rule holds with the parties reversed. True is the shorthand for the ordinary
    # reciprocal case; a parent-and-child rule sets it false.
    symmetric: bool = True
    note: str = ""

    @model_validator(mode="after")
    def check_privacy(self) -> LocationPrivacy:
        where = self.location_id
        if self.subject_id in self.excluded_resident_ids:
            raise ValueError(
                f"location privacy for {where!r} excludes its own subject {self.subject_id!r}"
            )
        if len(set(self.excluded_resident_ids)) != len(self.excluded_resident_ids):
            raise ValueError(f"location privacy for {where!r} repeats an excluded resident")
        if len(set(self.intents)) != len(self.intents):
            raise ValueError(f"location privacy for {where!r} repeats an intent")
        return self


class Household(ContractModel):
    """What is true of the house rather than of any one person living in it.

    Empty is the honest description of a household of one: the same contract, with nothing to say
    about pairs because there are none. There is no separate single-resident path anywhere below
    this line — N=1 is the case where every loop runs once.

    The permissive settings are chosen, never inherited. Declared nothing, two residents are
    `independent` and rooms with a single sanitary fixture are private, because the two mistakes do
    not cost the same: a wrong permissive default is two people in one shower cabin, physically
    impossible and silently false all the way downstream, while a wrong restrictive default is a
    slightly formal cohabitation that a reader can see and correct.
    """

    relations: list[HouseholdRelation] = Field(default_factory=list)
    joint_activities: list[JointActivity] = Field(default_factory=list)
    sharing_policies: list[SharingPolicy] = Field(default_factory=list)
    location_privacy: list[LocationPrivacy] = Field(default_factory=list)
    # The one line that opts a room out of the restrictive default. A room holding a single
    # sanitary fixture is private unless it is named here, because that is the default whose
    # mistake is visible: a household that genuinely shares its bathroom says so, and a household
    # that never thought about it does not silently get two people in one shower cabin.
    shared_location_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_household(self) -> Household:
        seen: set[frozenset[str]] = set()
        for relation in self.relations:
            if relation.pair in seen:
                raise ValueError(
                    f"residents {sorted(relation.pair)} are declared related more than once"
                )
            seen.add(relation.pair)
        if len(set(self.shared_location_ids)) != len(self.shared_location_ids):
            raise ValueError("sharedLocationIds repeats a location")
        activity_ids = [item.activity.recurring_activity_id for item in self.joint_activities]
        if len(set(activity_ids)) != len(activity_ids):
            raise ValueError("joint activity identifiers must be unique")
        policies: set[tuple[frozenset[str], str]] = set()
        for policy in self.sharing_policies:
            key = (policy.pair, policy.intent)
            if key in policies:
                raise ValueError(
                    f"residents {sorted(policy.pair)} declare {policy.intent!r} more than once"
                )
            policies.add(key)
        return self


_VOCABULARY_IDENTIFIER = r"^[a-z][a-z0-9_]*$"


class FurnitureProposal(ContractModel):
    """A kind of object the case needs and the vocabulary in the prompt does not have.

    A proposal, not a declaration. It changes nothing about how the outline is simulated: an object
    whose type the vocabulary does not know still offers every capability until a researcher adds
    the type with what it is for. What the proposal buys is that the researcher does not have to
    reconstruct the author's intent from a resource type alone — the application shows it at import
    with the name and capabilities filled in, and one confirmation turns it into vocabulary.

    `capabilities` names what actions need from the object, chosen from the list the prompt gives.
    A capability no action asks for binds nothing, so inventing one would describe an object that
    could never be used; the review is where that is caught, because the list is the workspace's
    and not this contract's.
    """

    entity_type: str = Field(min_length=1, pattern=_VOCABULARY_IDENTIFIER)
    display_name: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    # Whether a deployment would fit it with a contact sensor: it has a door or a lid that opens.
    contact_instrumented: bool = False
    # Why the case needs it, in one sentence the researcher reads before accepting it.
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_furniture(self) -> FurnitureProposal:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError(f"furniture proposal {self.entity_type!r} repeats a capability")
        return self


class ActivityProposal(ContractModel):
    """An activity the case describes and no intent in the prompt's vocabulary names.

    Where the vocabulary has no word for what happens — a guest for dinner, written as a phone call
    because nothing closer existed — the outline may use the proposed intent instead of a proxy,
    and the process package implements it with the actions that already exist. The import refuses
    the outline until a researcher adds the activity to the vocabulary, because a new intent is a
    new label in the published ground truth and that is not a choice a generator makes alone.
    """

    intent_id: str = Field(min_length=1, pattern=_VOCABULARY_IDENTIFIER)
    label: str = Field(min_length=1)
    category: IntentCategory
    default_location: str = Field(min_length=1)
    description: str = ""
    rationale: str = Field(min_length=1)


class VocabularyProposals(ContractModel):
    """What the author asks to add to the vocabulary, for a researcher to accept or refuse."""

    furniture: list[FurnitureProposal] = Field(default_factory=list)
    activities: list[ActivityProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_proposals(self) -> VocabularyProposals:
        types = [item.entity_type for item in self.furniture]
        if len(set(types)) != len(types):
            raise ValueError("two furniture proposals share an entityType")
        intents = [item.intent_id for item in self.activities]
        if len(set(intents)) != len(intents):
            raise ValueError("two activity proposals share an intentId")
        return self


class OutlineResident(ContractModel):
    """One person: who she is, what recurs for her, how her day divides, what she cannot move.

    Identity and routine are one object rather than a roster keyed by id beside a list of profiles,
    because a person split across two lists is a person who can desynchronise, and nothing
    downstream would notice which half was stale.

    The portfolio gate applies here, per resident, and not to the household. A resident with two
    habits of her own and everything else held in common is not a second person, she is a shadow of
    the first; and a shadow contributes no second behaviour for a segmentation algorithm to confuse
    with the first, which is the entire reason for generating a shared log.
    """

    resident_id: str = Field(min_length=1)
    display_name: str = ""
    profile: BehavioralProfile
    rhythm: OutlineRhythm = Field(default_factory=OutlineRhythm)
    habits: list[HabitSegment] = Field(default_factory=list)
    fixed_commitments: list[FixedCommitment] = Field(default_factory=list)
    phases: list[OutlinePhase] = Field(default_factory=list)
    events: list[OutlineEvent] = Field(default_factory=list)
    # Where this resident is at midnight of the first day, when that is not the household's start
    # location. Two housemates have two bedrooms and are asleep in different rooms; a couple that
    # shares one does not need the field.
    start_location_id: str | None = None
    note: str = ""

    @model_validator(mode="after")
    def check_resident(self) -> OutlineResident:
        who = self.resident_id
        for items, what in (
            ([item.phase_id for item in self.phases], "phase"),
            ([item.event_id for item in self.events], "event"),
            ([item.commitment_id for item in self.fixed_commitments], "commitment"),
            ([item.habit_id for item in self.habits], "habit"),
        ):
            if len(set(items)) != len(items):
                raise ValueError(f"{what} identifiers must be unique within resident {who!r}")

        # Habits partition the day, so two of them may not claim the same minute: a segmentation
        # ground truth that assigned one timestamp to two bins would not be a segmentation. The
        # partition is per weekday, not per week — a band scoped to Saturday and Sunday and one
        # scoped to the working days may cover the same hours, because no single day is ever
        # claimed twice. It is also per resident: two people in one house divide their own days,
        # and a household-wide partition would forbid one of them sleeping while the other eats.
        for weekday in Weekday:
            spans = [
                (span, segment.habit_id)
                for segment in self.habits
                if not segment.weekdays or weekday in segment.weekdays
                for span in segment.minute_spans()
            ]
            spans.sort()
            for (first, first_id), (second, second_id) in zip(spans, spans[1:], strict=False):
                if second[0] < first[1]:
                    raise ValueError(
                        f"habits {first_id!r} and {second_id!r} of resident {who!r} overlap "
                        f"on {weekday.value}"
                    )

        # Two phases overriding one habit at the same time leave the expander without a rule to
        # pick between them, and a silent winner is exactly the class of defect this contract
        # exists to remove.
        for index, earlier in enumerate(self.phases):
            for later in self.phases[index + 1 :]:
                if earlier.start_date > later.end_date or later.start_date > earlier.end_date:
                    continue
                shared = {item.recurring_activity_id for item in earlier.activity_overrides} & {
                    item.recurring_activity_id for item in later.activity_overrides
                }
                if shared:
                    raise ValueError(
                        f"phases {earlier.phase_id!r} and {later.phase_id!r} of resident {who!r} "
                        f"overlap and both override {sorted(shared)[0]!r}"
                    )
        return self


class HorizonOutline(ContractModel):
    """One brief, one confirmed outline, any horizon length, any number of residents.

    Nothing here grows with the number of days: a year and eight months differ in the event list,
    not in the structure. The confirmed outline is also the habit ground truth the external
    authoring path has never produced, `mining_difficulty` included.

    2.0.0 makes the household the subject instead of the person. `residents` replaces
    `residentId` + `profile` + `rhythm`, and a `household` level holds what is true of a pair
    rather than of anyone: the relations, the activities that are shared, and the rooms that are
    private. A one-person outline is the case `len(residents) == 1`, not a separate path, which is
    why every consumer below reads the list and none of them asks how long it is.

    The three levels are all O(1) in the horizon, and the second one is what keeps the *authoring*
    O(1) too. Everything the household does together is written once, so two residents do not cost
    two outlines: the individual profiles hold only what is genuinely individual, and the portfolio
    gate stays affordable at four people.

    Two structural rules that a language model asked for "the family's routine" will otherwise
    break, and that are enforced here rather than hoped for:

    - a shared activity is declared once, in `household.joint_activities`, with explicit
      `participant_ids` and **one** band. Written twice in two profiles, the two copies drift by
      forty minutes under a solver that has no reason to align them, and the dataset ends up with
      two dinners where the house had one;
    - a recurring activity identifier is unique across the whole document, individual and joint
      alike. The expander merges every resident's day into one scenario, and two people who each
      named an activity `morning_coffee` would arrive there as one activity performed twice.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:horizon-outline:2.0.0",
            "title": "Smart Home Horizon Outline 2.0.0",
        },
    )

    schema_version: Literal["2.0.0"] = "2.0.0"
    document_type: Literal["horizon_outline"] = "horizon_outline"
    outline_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    months: int = Field(ge=1)
    # One house, one geometry, one set of resources, however many people live in it.
    world: OutlineWorld
    residents: list[OutlineResident] = Field(min_length=1)
    household: Household = Field(default_factory=Household)
    # Empty is the ordinary case: the prompt's vocabulary was enough.
    vocabulary_proposals: VocabularyProposals = Field(default_factory=VocabularyProposals)
    provenance: Provenance
    note: str = ""

    @property
    def end_date(self) -> date:
        """First day past the horizon, matching the cadence calendar's half-open span."""
        return add_months(self.start_date, self.months)

    @property
    def resident_ids(self) -> list[str]:
        return [item.resident_id for item in self.residents]

    def resident(self, resident_id: str) -> OutlineResident:
        for item in self.residents:
            if item.resident_id == resident_id:
                return item
        raise KeyError(resident_id)

    def joint_activities_for(self, resident_id: str) -> list[JointActivity]:
        """The shared activities this resident takes part in, in declaration order."""
        return [
            item for item in self.household.joint_activities if resident_id in item.participant_ids
        ]

    def start_location_of(self, resident: OutlineResident) -> str:
        """Where the resident stands at midnight of the first day."""
        return resident.start_location_id or self.world.start_location_id

    def _within(self, day: date) -> bool:
        return self.start_date <= day < self.end_date

    @model_validator(mode="after")
    def check_outline(self) -> HorizonOutline:
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone {self.time_zone!r}") from error

        known_residents = self.resident_ids
        if len(set(known_residents)) != len(known_residents):
            raise ValueError("resident identifiers must be unique")
        roster = set(known_residents)

        primitive_locations = {
            item.location_id
            for item in self.world.locations
            if item.kind is not LocationKind.composite
        }
        for resident in self.residents:
            start = resident.start_location_id
            if start is not None and start not in primitive_locations:
                raise ValueError(
                    f"resident {resident.resident_id!r} starts in unknown location {start!r}"
                )
        for proposal in self.vocabulary_proposals.activities:
            if proposal.default_location not in primitive_locations:
                raise ValueError(
                    f"activity proposal {proposal.intent_id!r} happens in unknown location "
                    f"{proposal.default_location!r}"
                )

        # Identifiers are unique across the document, not within a resident. Two residents who each
        # called an activity `morning_coffee` would be indistinguishable once the expander merged
        # their days into one scenario, and a phase override naming that id could not say whose
        # coffee it suspended.
        owner_of: dict[str, str] = {}
        for resident in self.residents:
            for activity in resident.profile.recurring_activities:
                key = activity.recurring_activity_id
                if key in owner_of:
                    raise ValueError(
                        f"recurring activity {key!r} is declared by both {owner_of[key]!r} "
                        f"and {resident.resident_id!r}"
                    )
                owner_of[key] = resident.resident_id
        for joint in self.household.joint_activities:
            key = joint.activity.recurring_activity_id
            if key in owner_of:
                raise ValueError(
                    f"joint activity {key!r} is also declared individually by {owner_of[key]!r}"
                )
            owner_of[key] = ""

        for joint in self.household.joint_activities:
            unknown = [item for item in joint.participant_ids if item not in roster]
            if unknown:
                raise ValueError(
                    f"joint activity {joint.activity.recurring_activity_id!r} names unknown "
                    f"participant {unknown[0]!r}"
                )

        for relation in self.household.relations:
            for who in relation.between:
                if who not in roster:
                    raise ValueError(f"relation names unknown resident {who!r}")

        for policy in self.household.sharing_policies:
            for who in policy.between:
                if who not in roster:
                    raise ValueError(f"sharing policy names unknown resident {who!r}")

        known_locations = {item.location_id for item in self.world.locations}
        for privacy in self.household.location_privacy:
            if privacy.location_id not in known_locations:
                raise ValueError(f"location privacy names unknown location {privacy.location_id!r}")
            for who in (privacy.subject_id, *privacy.excluded_resident_ids):
                if who not in roster:
                    raise ValueError(f"location privacy names unknown resident {who!r}")

        for resident in self.residents:
            self._check_resident_against_horizon(resident)
        return self

    def _check_resident_against_horizon(self, resident: OutlineResident) -> None:
        """The part of a resident's validity that only the household can judge.

        Everything structural about one person is checked on `OutlineResident`. What is left here
        needs the horizon's dates, and the set of activities the resident may legitimately name —
        which includes the shared ones she takes part in, so that a phase can suspend the joint
        dinner during the fortnight she is away.
        """
        who = resident.resident_id
        known = {item.recurring_activity_id for item in resident.profile.recurring_activities}
        known |= {item.activity.recurring_activity_id for item in self.joint_activities_for(who)}

        for segment in resident.habits:
            for activity_id in segment.recurring_activity_ids:
                if activity_id not in known:
                    raise ValueError(
                        f"habit {segment.habit_id!r} of resident {who!r} lists unknown "
                        f"activity {activity_id!r}"
                    )

        for phase in resident.phases:
            for override in phase.activity_overrides:
                if override.recurring_activity_id not in known:
                    raise ValueError(
                        f"phase {phase.phase_id!r} of resident {who!r} overrides unknown "
                        f"activity {override.recurring_activity_id!r}"
                    )
            for day, edge in ((phase.start_date, "start"), (phase.end_date, "end")):
                if not self._within(day):
                    raise ValueError(
                        f"phase {phase.phase_id!r} of resident {who!r} {edge} falls outside "
                        "the horizon"
                    )

        for event in resident.events:
            for displaced in event.displaces:
                if displaced.recurring_activity_id not in known:
                    raise ValueError(
                        f"event {event.event_id!r} of resident {who!r} displaces unknown "
                        f"activity {displaced.recurring_activity_id!r}"
                    )
            for day, edge in ((event.earliest_date, "earliest"), (event.latest_date, "latest")):
                if not self._within(day):
                    raise ValueError(
                        f"event {event.event_id!r} of resident {who!r} {edge} falls outside "
                        "the horizon"
                    )

        for commitment in resident.fixed_commitments:
            for day, edge in ((commitment.start_date, "start"), (commitment.end_date, "end")):
                if day is not None and not self._within(day):
                    raise ValueError(
                        f"commitment {commitment.commitment_id!r} of resident {who!r} {edge} "
                        "falls outside the horizon"
                    )


class HorizonAuthoringBundle(ContractModel):
    """Transport envelope for outline-first authoring: the arc, and how its actions are performed.

    Kept apart for the same reason `SimulationAuthoringBundle` keeps scenario and package apart:
    the two halves answer to different reviewers. A human confirms the outline, because whether
    eight months are plausible is not a machine question. The process package is already gated by
    behavior validation and the deterministic replay, so nobody needs to read its twenty-four
    graphs by hand.

    Neither half grows with the horizon. The package is per-intent, which is why moving the days
    out of the model's output removes the entire horizon-proportional part of the response.

    2.0.0 carries an outline 2.0.0, whose subject is a household rather than a person. The envelope
    itself is unchanged, and it is versioned with the document it transports because a consumer
    validating a bundle is validating the outline inside it.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:horizon-authoring-bundle:2.0.0",
            "title": "Smart Home Horizon Authoring Bundle 2.0.0",
        },
    )

    schema_version: Literal["2.0.0"] = "2.0.0"
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


# The fields 1.0.0 kept at the top level and 2.0.0 keeps per resident. Listed rather than derived
# from the model, because the point of a migration is to know exactly which document it reads.
_SINGLE_RESIDENT_FIELDS: tuple[str, ...] = (
    "residentId",
    "displayName",
    "profile",
    "rhythm",
    "habits",
    "fixedCommitments",
    "phases",
    "events",
)


def upgrade_outline_payload(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Lift a 1.0.0 outline into the 2.0.0 shape: one resident, and a household with nothing in it.

    The break is genuine — `residentId`, `profile` and `rhythm` are no longer top-level fields —
    but it is entirely mechanical, and refusing to read the outlines this project has already had
    authored would throw away the horizons it has actually generated. A document about one person
    is a household of one, and this says so without anyone retyping it.

    Only the shape moves. Every value is carried across untouched, which is what makes the
    migration's acceptance criterion checkable at all: re-expanding a lifted outline has to yield
    the same compiled plan, and it cannot if the lift invented anything.

    A document that already declares 2.0.0 is returned unchanged, so this is safe to put in front
    of every door rather than behind a flag the caller has to remember.
    """
    if payload.get("schemaVersion") != "1.0.0" or "residents" in payload:
        return dict(payload)
    resident: dict[str, JsonValue] = {
        key: payload[key] for key in _SINGLE_RESIDENT_FIELDS if key in payload
    }
    lifted = {
        key: value
        for key, value in payload.items()
        if key not in _SINGLE_RESIDENT_FIELDS and key != "schemaVersion"
    }
    lifted["schemaVersion"] = OUTLINE_SCHEMA_VERSION
    lifted["residents"] = [resident]
    return lifted


def upgrade_authoring_bundle_payload(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The same lift for the envelope the outline travels in."""
    outline = payload.get("outline")
    if not isinstance(outline, dict):
        return dict(payload)
    lifted = dict(payload)
    lifted["outline"] = upgrade_outline_payload(outline)
    if lifted.get("schemaVersion") == "1.0.0":
        lifted["schemaVersion"] = HorizonAuthoringBundle.model_fields["schema_version"].default
    return lifted


class DeclaredResidentHabits(ContractModel):
    """One resident's declared bands, exactly as the outline wrote them."""

    resident_id: str = Field(min_length=1)
    habits: list[HabitSegment] = Field(default_factory=list)


class DeclaredJointActivity(ContractModel):
    """How the household said a shared activity is shared, carried so the run can be held to it.

    The declared half of `SharingRealisation`. A propensity is a number precisely so that it can be
    compared with what happened (§15.2 of the design): "0.85 declared at the weekend, 0.79 realised
    over 34 weekends" is a statement a reader can check, where a predicate could only have been
    reported as realised.
    """

    recurring_activity_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    participant_ids: list[str] = Field(min_length=2)
    sharing: SharingMode
    propensity: SharingPropensity | None = None


class DeclaredHabits(ContractModel):
    """The declared half of the habit ground truth, carried in the scenario to be measured later.

    Nothing downstream of ingestion ever sees the outline, and the measured half cannot exist until
    a run does. So the scenario carries the declaration — bands, per resident, and the horizon they
    were declared over — and the export measures them on the trace of whichever run it is exporting.
    Only a declaration travels this way, which is why nothing here can be wrong about behaviour.
    """

    outline_id: str = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    end_date: date
    seed: int
    residents: list[DeclaredResidentHabits] = Field(default_factory=list)
    joint_activities: list[DeclaredJointActivity] = Field(default_factory=list)


class CoPresenceSpan(ContractModel):
    """A stretch during which more than one resident was in the same room.

    The measurement a per-resident document structurally cannot make. A habit ground truth answers
    "what was *she* doing between these hours"; nothing in N of those says the two of them were in
    the kitchen together at the time, and an experiment running on a shared sensor log needs that
    to tell a confounder apart from an error.
    """

    day: date
    location: str = Field(min_length=1)
    start: str
    end: str
    minutes: float = Field(ge=0)
    resident_ids: list[str] = Field(min_length=2)


class HouseholdDay(ContractModel):
    """One day of the household, as the plan has it.

    `at_home_minutes` counts planned minutes in a room of the dwelling, so time at work or out
    walking is absent by construction rather than by subtraction. `shared_minutes` is the part of
    that spent in a room another resident was also in — the daily total of the spans above, and the
    denominator anybody comparing two residents' recoverability will want first.
    """

    day: date
    at_home_minutes: dict[str, float] = Field(default_factory=dict)
    shared_minutes: dict[str, float] = Field(default_factory=dict)
    shared_activity_count: int = Field(default=0, ge=0)


class SharedEpisode(ContractModel):
    """One planned activity that more than one resident took part in.

    Emitted once with every participant named, exactly as the plan holds it. A reader counting
    dinners in this household counts these rows and gets the number of dinners, not the number of
    people who ate one.
    """

    day: date
    activity_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    location: str = Field(min_length=1)
    start: str
    end: str
    minutes: float = Field(ge=0)
    participant_ids: list[str] = Field(min_length=2)


class SharingRealisation(ContractModel):
    """One shared activity and one class of day: the share declared, and the share realised.

    `days_with_occurrence` counts the days the activity ran at all for any of its participants,
    together or apart; `days_shared` the days it ran as one sitting with more than one of them.
    Their ratio is `realised_share`, measured on the run, beside `declared_propensity` from the
    outline. A `joint` activity declares no propensity — it is shared whenever it fits — so its
    realised share is what the days allowed: co-presence, and the compiler's choice to degrade.
    """

    recurring_activity_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    participant_ids: list[str] = Field(min_length=2)
    sharing: SharingMode
    day_class: Literal["weekday", "weekend"]
    declared_propensity: float | None = Field(default=None, ge=0, le=1)
    days_with_occurrence: int = Field(ge=0)
    days_shared: int = Field(ge=0)
    realised_share: float | None = Field(default=None, ge=0, le=1)


class HouseholdGroundTruth(ContractModel):
    """What the house did, as opposed to what any one person in it did.

    One dataset per dwelling, with one shared sensor log, N per-resident habit ground truths and
    this. A dataset per resident would duplicate the same observable log N times and lose the only
    thing that makes the case interesting, which is that there is one log and more than one body
    producing it.

    Measured on the execution trace, like the per-resident documents beside it: co-presence is
    where the bodies actually were, from their movements, and a shared episode is an activity the
    run executed with more than one resident in it.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:household-ground-truth:1.0.0",
            "title": "Smart Home Household Ground Truth 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["household_ground_truth"] = "household_ground_truth"
    outline_id: str = Field(min_length=1)
    resident_ids: list[str] = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    end_date: date
    seed: int
    # What the numbers were measured on. `execution_trace` is the ground truth: what the residents
    # did in the run the sensor log was projected from. `expanded_plan` is the same arithmetic run
    # on the days the expander wrote, before anything was compiled, and exists only to warn an
    # author about a band nothing fills; it is never published. The field is there so the two can
    # never be mistaken for each other — a mistake this project made once, by publishing the
    # second as the first for three contract versions.
    measured_on: Literal["execution_trace", "expanded_plan"]
    # The run and the trace a published measurement answers to. Two runs of one outline are two
    # answer sheets, each exact for its own log.
    run_id: str | None = None
    trace_id: str | None = None
    source_trace_semantic_digest: str | None = None
    days: list[HouseholdDay] = Field(default_factory=list)
    co_presence: list[CoPresenceSpan] = Field(default_factory=list)
    shared_episodes: list[SharedEpisode] = Field(default_factory=list)
    # Declared propensity against realised share, per shared activity and class of day.
    sharing: list[SharingRealisation] = Field(default_factory=list)
    provenance: Provenance


class HabitComposition(ContractModel):
    """How much of one habit band a single activity in one room accounts for, over the horizon.

    Measured per room as well as per intent since a habit may name the room it happens in. Two
    habits performing the same activity in different places are one label and two behaviours —
    reading in the study and reading on the sofa — and keyed by intent alone they arrived here as a
    single row, so the distinction an author had just taken the trouble to declare was averaged
    away before any evaluation could see it. Rows stay one per (intent, room): a consumer that
    only wants the intent sums them.
    """

    intent: str = Field(min_length=1)
    location: str = Field(min_length=1)
    minutes: float = Field(ge=0)
    share: float = Field(ge=0, le=1)


class HabitDayTypeObservation(ContractModel):
    """The same band measured over one class of days.

    A band that is not weekday-scoped covers both the working week and the weekend, and those can
    be different behaviours wearing the same hours. This splits the measurement so the difference
    is visible without anyone having to re-derive it from the activity log.
    """

    day_type: Literal["weekday", "weekend"]
    day_count: int = Field(ge=0)
    total_minutes: float = Field(ge=0)
    composition: list[HabitComposition] = Field(default_factory=list)
    unaccounted_minutes: float = Field(ge=0)
    unaccounted_share: float = Field(ge=0, le=1)
    # Split for the same reason everything else here is: co-presence is exactly the quantity that
    # differs most between a working Tuesday and a Saturday, and a single figure would average the
    # two households a couple actually is.
    ambiguous_minutes: float = Field(default=0.0, ge=0)
    ambiguous_share: float = Field(default=0.0, ge=0, le=1)


class HabitObservation(ContractModel):
    """One habit band with the activity mix that actually landed inside it.

    This is the shape of Table IV in the habit-segmentation paper: for the Aruba bin `05:15-07:00`
    the sleeping activity accounts for about 80% of the band, the rest being other activities or
    unlabelled time. `unaccounted_share` is that remainder — minutes inside the band during which
    the plan has the resident doing nothing the outline named.

    Two fields exist because a declared window is not a claim about behaviour. The window is where
    the planner is *allowed* to put the band's activities, and it is routinely wider than where
    they land: a night band declared from 21:30 on a horizon whose resident reliably goes to bed at
    23:30 spends two of its nine hours being the evening. `effective_start`/`effective_end` say
    where the band's dominant activity actually runs, so an evaluation has a target that the
    behaviour supports. They are null when no single activity holds the band on most days — which
    is itself the finding, and the reason not to silently invent a boundary.
    """

    habit_id: str = Field(min_length=1)
    # Whose band this is. Redundant inside the document, which names one resident, and not
    # redundant at all once an export flattens every resident's bands into one table of rows.
    resident_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    window_start: str
    window_end: str
    crosses_midnight: bool
    # Empty means the band applies every day, matching `HabitSegment.weekdays`.
    weekdays: list[Weekday] = Field(default_factory=list)
    day_count: int = Field(ge=0)
    total_minutes: float = Field(ge=0)
    composition: list[HabitComposition] = Field(default_factory=list)
    unaccounted_minutes: float = Field(ge=0)
    unaccounted_share: float = Field(ge=0, le=1)
    # The activity holding the largest share of the band, and the stretch of the band it occupies
    # on at least `EFFECTIVE_DAY_SHARE` of the applicable days.
    dominant_intent: str | None = None
    # And the room it holds the band in. Named separately from the intent because it is the answer
    # to a different question — "where is the resident when this band is what she is doing" — which
    # a segmentation experiment can use as a feature or ignore, and which is not recoverable from
    # `dominant_intent` once a habit is allowed to declare its own room.
    dominant_location: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None
    effective_minutes: float = Field(default=0.0, ge=0)
    effective_share: float = Field(default=0.0, ge=0, le=1)
    # Populated only when the band spans both classes of day, since otherwise it would restate
    # `composition`.
    day_types: list[HabitDayTypeObservation] = Field(default_factory=list)
    # The share of the band's minutes during which another resident was in the same room.
    #
    # This is the second axis of difficulty, and in a shared house it is the one that decides
    # whether a band is recoverable at all. A sensor log that does not distinguish bodies cannot
    # attribute a minute two people were both present for, so an algorithm failing on a crowded
    # band and one failing on a noisy band produce the same number and mean different things.
    # It sits beside `unaccounted_share` because it answers the same question — how much of this
    # band can be got back — and putting it in a document of its own would force a join on
    # `habit_id` to read one figure.
    #
    # Zero for a household of one, by construction rather than by convention: there is nobody to
    # be ambiguous with.
    ambiguous_minutes: float = Field(default=0.0, ge=0)
    ambiguous_share: float = Field(default=0.0, ge=0, le=1)


class HabitGroundTruth(ContractModel):
    """What a habit-segmentation algorithm is supposed to recover, published as evidence.

    The researcher's algorithm sees only a sensor log and must discover both where the day divides
    and what runs in each division. This document states the answer, and it is two different kinds
    of statement that must not be confused:

    - **the bands** — windows, days, the activities expected in them — are the outline's
      declaration. They are true by definition: they are what the author said the day is divided
      into;
    - **everything measured inside them** — composition, the unaccounted remainder, where the
      dominant activity really runs, the ambiguity share — is measured on the execution trace of
      the run, with actual start and end times and the rooms the bodies were in. It is exactly what
      happened in the run the sensor log was projected from.

    Until 1.3.0 the measured half was taken from the expanded plan, before compilation: preferred
    times instead of scheduled ones, candidates the engine could still turn down counted as if they
    had happened, and nothing the compiler or the run changed. The contract said so, and it was
    still the wrong thing to publish as the answer to a sensor log.

    1.1.0 adds three things a segmentation experiment could not otherwise get without re-deriving
    them from the activity log: the days each band applies to, where the band's dominant activity
    actually runs as opposed to where the window allows it, and the same measurement split by
    class of day.

    1.2.0 adds the room. A recurring activity may now declare the room it happens in, so the same
    intent can be two behaviours in two places, and a composition keyed by intent alone reported
    them as one row — averaging away exactly the distinction the author had declared. Composition
    is per (intent, room) and the band names the room its dominant activity holds it in.

    1.3.0 measures on the execution trace and says so in `measuredOn`, names the run it answers
    to, adds the share of each band another resident spent in the same room, and says on every band
    whose it is. A household publishes one of these per person — segmentation is defined over a
    person, and a dwelling-wide document would not be comparable with the literature it answers to
    — beside one `HouseholdGroundTruth` for what none of them can say alone.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:habit-ground-truth:1.3.0",
            "title": "Smart Home Habit Ground Truth 1.3.0",
        },
    )

    schema_version: Literal["1.3.0"] = "1.3.0"
    document_type: Literal["habit_ground_truth"] = "habit_ground_truth"
    outline_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    time_zone: str = Field(min_length=1)
    start_date: date
    end_date: date
    seed: int
    # What the numbers were measured on. `execution_trace` is the ground truth: what the residents
    # did in the run the sensor log was projected from. `expanded_plan` is the same arithmetic run
    # on the days the expander wrote, before anything was compiled, and exists only to warn an
    # author about a band nothing fills; it is never published. The field is there so the two can
    # never be mistaken for each other — a mistake this project made once, by publishing the
    # second as the first for three contract versions.
    measured_on: Literal["execution_trace", "expanded_plan"]
    # The run and the trace a published measurement answers to. Two runs of one outline are two
    # answer sheets, each exact for its own log.
    run_id: str | None = None
    trace_id: str | None = None
    source_trace_semantic_digest: str | None = None
    habits: list[HabitObservation] = Field(default_factory=list)
    provenance: Provenance
