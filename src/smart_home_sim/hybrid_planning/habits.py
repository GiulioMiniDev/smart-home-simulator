"""What happened inside each declared habit band: one measurement, fed from one of two sources.

The habit ground truth is two kinds of statement. The **bands** are the outline's declaration and
true by definition. **Everything measured inside them** has to be what happened, and what happened
is the execution trace: actual start and end times, the activities the run really executed, and the
rooms the bodies were really in, from their movements. That is the only source a published ground
truth is measured on (`measured_on="execution_trace"`), and it is measured when a run is exported,
because a run is what a sensor log belongs to.

The same arithmetic also runs on the expanded plan (`measured_on="expanded_plan"`), for exactly one
purpose: to tell an author, straight after import and hours before a run exists, that a band she
drew holds nothing. That result is never published. It is honest about what it is — a statement
about the plan — and the field is what keeps it from being read as a statement about behaviour,
which is how the plan-side measurement was published for three contract versions.

Keeping one implementation for both is deliberate. Two implementations of "what fills a band"
drift, and they did: the experiments reconstructing the effective window from `activities.csv` got
379 minutes for a night band the export published as 417.
"""

from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from smart_home_sim.domain.execution import ExecutionTrace, MovementExecution
from smart_home_sim.domain.models import (
    BRANCH_EXTENSION,
    SEPARATE_BRANCH,
    Activity,
    AuthorType,
    DayPlan,
    LocationKind,
    Provenance,
    Scenario,
)
from smart_home_sim.hybrid_planning.outline import (
    CoPresenceSpan,
    DeclaredHabits,
    HabitComposition,
    HabitDayTypeObservation,
    HabitGroundTruth,
    HabitObservation,
    HabitSegment,
    HouseholdDay,
    HouseholdGroundTruth,
    SharedEpisode,
    SharingRealisation,
)
from smart_home_sim.profiling.builder import OCCUPYING_STATUSES

GENERATOR_NAME = "smart-home-sim.hybrid_planning.habits"
GENERATOR_VERSION = "1.0.0"

# A band's dominant activity has to hold a minute on at least this share of the applicable days
# before that minute counts as part of the band's effective window. Half is the weakest claim
# worth publishing — "on most days, this is what is happening here" — and it keeps a rare late
# night from stretching the window.
EFFECTIVE_DAY_SHARE = 0.5

MeasuredOn = Literal["execution_trace", "expanded_plan"]
_DayClass = Literal["weekday", "weekend"]


@dataclass(frozen=True)
class Stretch:
    """One resident over one half-open interval: where she was, and what she was doing."""

    resident_id: str
    start: datetime
    end: datetime
    location: str
    intent: str | None = None


@dataclass(frozen=True)
class Episode:
    """One activity more than one resident took part in."""

    activity_id: str
    intent: str
    location: str
    start: datetime
    end: datetime
    participant_ids: tuple[str, ...]


@dataclass(frozen=True)
class Occurrence:
    """One occurrence of a declared recurring activity, and who took part in it."""

    recurring_activity_id: str
    start: datetime
    resident_ids: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    """Everything the measurement reads, whichever source it came from.

    `activities` are what each resident was doing, split by room. `locations` are where each
    resident was; from a trace they cover the whole window, idle time included, because a body in
    the kitchen doing nothing is still a body in the kitchen as far as a sensor and a second
    resident are concerned. From a plan they are only the planned activities, since that is all
    a plan knows.
    """

    measured_on: MeasuredOn
    started_at: datetime
    ended_at: datetime
    resident_ids: tuple[str, ...]
    activities: Mapping[str, Sequence[Stretch]]
    locations: Mapping[str, Sequence[Stretch]]
    episodes: Sequence[Episode]
    # Declared recurring activities as they happened, together or apart. What a realised sharing
    # share is counted over; empty where the source could not say which habit an activity was.
    occurrences: Sequence[Occurrence] = ()
    run_id: str | None = None
    trace_id: str | None = None
    source_trace_semantic_digest: str | None = None


# --- sources -------------------------------------------------------------------------------------


def _clip(stretch: Stretch, start: datetime, end: datetime) -> Stretch | None:
    low = max(stretch.start, start)
    high = min(stretch.end, end)
    if high <= low:
        return None
    return Stretch(stretch.resident_id, low, high, stretch.location, stretch.intent)


def _location_timelines(
    movements: Iterable[MovementExecution],
    initial_regions: Mapping[str, str],
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, list[Stretch]]:
    """Where each resident was, as a partition of the trace window, reconstructed from her walks.

    She is in the room a walk takes her to from the moment the walk starts — the minutes spent
    crossing the hall belong to where she is going — until the next walk starts. Before her first
    walk she is where that walk sets out from, or, if she never walks, where the scenario put her.
    """
    by_resident: dict[str, list[MovementExecution]] = defaultdict(list)
    for movement in movements:
        by_resident[movement.actor_id].append(movement)
    timelines: dict[str, list[Stretch]] = {}
    for resident_id in sorted({*initial_regions, *by_resident}):
        items = sorted(
            by_resident.get(resident_id, []), key=lambda m: (m.started_at, m.movement_id)
        )
        region = items[0].origin_region_id if items else initial_regions.get(resident_id)
        if region is None:
            continue
        cursor = started_at
        timeline: list[Stretch] = []
        for movement in items:
            if movement.started_at > cursor:
                timeline.append(Stretch(resident_id, cursor, movement.started_at, region))
                cursor = movement.started_at
            region = movement.destination_region_id
        if ended_at > cursor:
            timeline.append(Stretch(resident_id, cursor, ended_at, region))
        timelines[resident_id] = timeline
    return timelines


def _split_by_location(
    timeline: Sequence[Stretch], start: datetime, end: datetime
) -> list[Stretch]:
    """The pieces of [start, end) spent in each room, read off a partition of where she was."""
    starts = [item.start for item in timeline]
    index = max(0, bisect.bisect_right(starts, start) - 1)
    pieces: list[Stretch] = []
    while index < len(timeline) and timeline[index].start < end:
        piece = _clip(timeline[index], start, end)
        if piece is not None:
            pieces.append(piece)
        index += 1
    return pieces


def evidence_from_trace(
    trace: ExecutionTrace,
    *,
    initial_regions: Mapping[str, str],
    run_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    recurring_by_activity: Mapping[str, str] | None = None,
) -> Evidence:
    """What the run did, inside [start, end] of it: the source of every published measurement.

    Activities count by the statuses the resident profile counts — a dropped activity never ran and
    occupies nobody, a failed one did occupy her while it failed — and for every resident who took
    part, not only its actor: the other person at a shared dinner was at the table.
    """
    started_at = max(trace.started_at, start) if start else trace.started_at
    ended_at = min(trace.ended_at, end) if end else trace.ended_at
    ended_at = max(ended_at, started_at)
    timelines = _location_timelines(
        trace.movements, initial_regions, trace.started_at, trace.ended_at
    )
    activities: dict[str, list[Stretch]] = defaultdict(list)
    episodes: list[Episode] = []
    occurrences: list[Occurrence] = []
    recurring = recurring_by_activity or {}
    # Each person's activities by start, so the errands nested inside one can be found and cut out.
    spans: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for execution in trace.activity_executions:
        if execution.status in OCCUPYING_STATUSES:
            for resident_id in (execution.actor_id, *execution.participant_ids):
                spans[resident_id].append(
                    (execution.actual_start, execution.actual_end, execution.activity_execution_id)
                )
    for series in spans.values():
        series.sort()
    for execution in trace.activity_executions:
        if execution.status not in OCCUPYING_STATUSES:
            continue
        begin = max(execution.actual_start, started_at)
        finish = min(execution.actual_end, ended_at)
        if finish <= begin:
            continue
        people = (execution.actor_id, *execution.participant_ids)
        if execution.source_activity_id in recurring:
            occurrences.append(
                Occurrence(
                    recurring[execution.source_activity_id],
                    execution.actual_start,
                    tuple(sorted(people)),
                )
            )
        for resident_id in people:
            for left, right in _without_nested(
                spans[resident_id], execution.activity_execution_id, begin, finish
            ):
                for piece in _split_by_location(timelines.get(resident_id, []), left, right):
                    activities[resident_id].append(
                        Stretch(
                            resident_id, piece.start, piece.end, piece.location, execution.intent
                        )
                    )
        if execution.participant_ids:
            where = _split_by_location(timelines.get(execution.actor_id, []), begin, finish)
            episodes.append(
                Episode(
                    activity_id=execution.activity_execution_id,
                    intent=execution.intent,
                    location=where[0].location if where else "unknown",
                    start=begin,
                    end=finish,
                    participant_ids=tuple(sorted(people)),
                )
            )
    locations = {
        resident_id: [
            piece for item in timeline if (piece := _clip(item, started_at, ended_at)) is not None
        ]
        for resident_id, timeline in timelines.items()
    }
    return Evidence(
        measured_on="execution_trace",
        started_at=started_at,
        ended_at=ended_at,
        resident_ids=tuple(sorted({*initial_regions, *timelines, *activities})),
        activities={key: sorted(value, key=lambda s: s.start) for key, value in activities.items()},
        locations=locations,
        episodes=sorted(episodes, key=lambda item: (item.start, item.activity_id)),
        occurrences=occurrences,
        run_id=run_id,
        trace_id=trace.trace_id,
        source_trace_semantic_digest=trace.semantic_digest,
    )


def _without_nested(
    series: Sequence[tuple[datetime, datetime, str]],
    execution_id: str,
    begin: datetime,
    finish: datetime,
) -> list[tuple[datetime, datetime]]:
    """[begin, finish] with every other activity of the same person that lies inside it removed.

    The engine puts a night's sleep down for the toilet and picks it up again, so the sleep's
    record spans the visit. Counted whole, the band's composition had both the minutes at the
    toilet and the same minutes asleep — in the bathroom, since that is where the body was.
    """
    pieces: list[tuple[datetime, datetime]] = []
    cursor = begin
    index = bisect.bisect_left(series, (begin,))
    while index < len(series) and series[index][0] < finish:
        start, end, other = series[index]
        index += 1
        if other == execution_id or end > finish or end <= start:
            continue
        if start > cursor:
            pieces.append((cursor, start))
        cursor = max(cursor, end)
    if finish > cursor:
        pieces.append((cursor, finish))
    return pieces


def _recurring_activity_id_of(activity: Activity) -> str | None:
    """Which declared habit an activity is an occurrence of, from the label the expander writes."""
    return next(
        (
            item.removeprefix("activity:")
            for item in activity.labels
            if item.startswith("activity:")
        ),
        None,
    )


def _is_understudy(activity: Activity) -> bool:
    """The arm of a degradable shared activity that only runs if the shared one does not fit."""
    declared = activity.extensions.get(BRANCH_EXTENSION)
    return isinstance(declared, dict) and declared.get("branch") == SEPARATE_BRANCH


def evidence_from_plan(
    days: Sequence[DayPlan],
    resident_ids: Sequence[str],
    *,
    started_at: datetime,
    ended_at: datetime,
) -> Evidence:
    """What the expanded plan proposes, read the same way — for authoring checks, never published.

    Preferred times and durations, every candidate as if it will happen, and the shared arm of a
    degradable activity rather than both arms. It is a statement about the plan and nothing else.
    """
    roster = set(resident_ids)
    activities: dict[str, list[Stretch]] = defaultdict(list)
    episodes: list[Episode] = []
    occurrences: list[Occurrence] = []
    for day in days:
        for activity in day.activities:
            if activity.start_window is None or activity.duration is None:
                continue
            if _is_understudy(activity):
                continue
            begin = activity.start_window.preferred
            finish = begin + timedelta(minutes=activity.duration.preferred_minutes)
            people = tuple(sorted({activity.actor_id, *activity.participant_ids} & roster))
            recurring = _recurring_activity_id_of(activity)
            if recurring is not None:
                occurrences.append(Occurrence(recurring, begin, people))
            for resident_id in people:
                activities[resident_id].append(
                    Stretch(resident_id, begin, finish, activity.location_ids[0], activity.intent)
                )
            if len(people) > 1:
                episodes.append(
                    Episode(
                        activity_id=activity.activity_id,
                        intent=activity.intent,
                        location=activity.location_ids[0],
                        start=begin,
                        end=finish,
                        participant_ids=people,
                    )
                )
    ordered = {key: sorted(value, key=lambda s: s.start) for key, value in activities.items()}
    return Evidence(
        measured_on="expanded_plan",
        started_at=started_at,
        ended_at=ended_at,
        resident_ids=tuple(sorted(roster)),
        activities=ordered,
        locations=ordered,
        episodes=sorted(episodes, key=lambda item: (item.start, item.activity_id)),
        occurrences=occurrences,
    )


# --- co-presence ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Together:
    start: datetime
    end: datetime
    location: str
    resident_ids: tuple[str, ...]


def _co_presence(evidence: Evidence) -> list[_Together]:
    """Every stretch in which two or more residents were in the same room, merged where it runs on.

    A sweep over every resident's whereabouts rather than a pairwise comparison, so it handles three
    people as easily as two and a plan's overlapping stretches as easily as a trace's partition.
    """
    events: list[tuple[datetime, int, str, str]] = []
    for resident_id, stretches in evidence.locations.items():
        for item in stretches:
            events.append((item.start, 1, resident_id, item.location))
            events.append((item.end, -1, resident_id, item.location))
    # Ends before starts at the same instant, so a resident leaving as another arrives is not
    # counted as having met her.
    events.sort(key=lambda item: (item[0], item[1]))
    active: dict[str, Counter[str]] = defaultdict(Counter)
    pieces: list[_Together] = []
    previous: datetime | None = None
    index = 0
    while index < len(events):
        moment = events[index][0]
        if previous is not None and moment > previous:
            for location, present in active.items():
                people = tuple(sorted(item for item, count in present.items() if count > 0))
                if len(people) > 1:
                    pieces.append(_Together(previous, moment, location, people))
        while index < len(events) and events[index][0] == moment:
            _, delta, resident_id, location = events[index]
            active[location][resident_id] += delta
            index += 1
        previous = moment
    pieces.sort(key=lambda item: (item.location, item.resident_ids, item.start))
    merged: list[_Together] = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.location == piece.location
            and last.resident_ids == piece.resident_ids
            and piece.start <= last.end
        ):
            merged[-1] = _Together(
                last.start, max(last.end, piece.end), last.location, last.resident_ids
            )
        else:
            merged.append(piece)
    return sorted(merged, key=lambda item: (item.start, item.location))


# --- the per-resident measurement ----------------------------------------------------------------


def _clock(minute: int) -> str:
    return f"{minute // 60 % 24:02d}:{minute % 60:02d}"


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60.0)


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def _instance(segment: HabitSegment, day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """One occurrence of a band: the evening of `day` and, for a night band, the morning after."""
    opens = _to_minutes(segment.window_start)
    closes = _to_minutes(segment.window_end)
    begin = datetime.combine(day, time(opens // 60, opens % 60), zone)
    finish_day = day + timedelta(days=1) if segment.crosses_midnight else day
    return begin, datetime.combine(finish_day, time(closes // 60, closes % 60), zone)


def _overlapping(stretches: Sequence[Stretch], begin: datetime, end: datetime) -> list[Stretch]:
    """Stretches intersecting [begin, end), clipped to it. `stretches` is sorted by start."""
    # Plans overlap, so a stretch starting well before `begin` may still reach into it; the longest
    # single stretch bounds how far back to look.
    starts = [item.start for item in stretches]
    longest = max((item.end - item.start for item in stretches), default=timedelta(0))
    index = bisect.bisect_left(starts, begin - longest)
    found: list[Stretch] = []
    while index < len(stretches) and stretches[index].start < end:
        piece = _clip(stretches[index], begin, end)
        if piece is not None:
            found.append(piece)
        index += 1
    return found


def _union_minutes(stretches: Sequence[Stretch]) -> float:
    total = 0.0
    frontier: datetime | None = None
    for item in sorted(stretches, key=lambda s: s.start):
        if frontier is None or item.start >= frontier:
            total += _minutes(item.start, item.end)
            frontier = item.end
        elif item.end > frontier:
            total += _minutes(frontier, item.end)
            frontier = item.end
    return total


def _compose(measured: Mapping[tuple[str, str], float], total: float) -> list[HabitComposition]:
    """One row per activity *and room*, largest first, ties broken by name so it is reproducible."""
    return [
        HabitComposition(
            intent=intent,
            location=location,
            minutes=round(minutes, 1),
            share=round(min(1.0, minutes / total), 4) if total else 0.0,
        )
        for (intent, location), minutes in sorted(
            measured.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def _longest_run(occupied: Sequence[bool]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for index, held in enumerate([*occupied, False]):
        if held and run_start is None:
            run_start = index
        elif not held and run_start is not None:
            if best is None or index - run_start > best[1] - best[0]:
                best = (run_start, index)
            run_start = None
    return best


@dataclass
class _Tally:
    days: int = 0
    total: float = 0.0
    covered: float = 0.0
    ambiguous: float = 0.0

    def __post_init__(self) -> None:
        self.composition: dict[tuple[str, str], float] = defaultdict(float)


def _observe(
    segment: HabitSegment,
    resident_id: str,
    evidence: Evidence,
    together: Sequence[Stretch],
    declared: DeclaredHabits,
    zone: ZoneInfo,
) -> HabitObservation:
    activities = evidence.activities.get(resident_id, [])
    overall = _Tally()
    by_class: dict[_DayClass, _Tally] = {"weekday": _Tally(), "weekend": _Tally()}
    instances: list[tuple[datetime, datetime, list[Stretch]]] = []
    # A night band's first morning belongs to the night before the horizon opened. That night is
    # outside it, but the hours after midnight are not, and they are measured like any other.
    first_day = declared.start_date - timedelta(days=1 if segment.crosses_midnight else 0)
    for day in _days(first_day, declared.end_date):
        if not segment.applies_on(day):
            continue
        begin, end = _instance(segment, day, zone)
        begin = max(begin, evidence.started_at)
        end = min(end, evidence.ended_at)
        if end <= begin:
            continue
        inside = _overlapping(activities, begin, end)
        instances.append((begin, end, inside))
        day_class: _DayClass = "weekend" if day.weekday() >= 5 else "weekday"
        band_minutes = _minutes(begin, end)
        covered = _union_minutes(inside)
        ambiguous = _union_minutes(_overlapping(together, begin, end))
        for tally in (overall, by_class[day_class]):
            tally.days += 1
            tally.total += band_minutes
            tally.covered += covered
            tally.ambiguous += ambiguous
            for piece in inside:
                assert piece.intent is not None
                tally.composition[(piece.intent, piece.location)] += _minutes(
                    piece.start, piece.end
                )

    # Ties broken by name, so a band split evenly between two rooms names the same one twice.
    dominant = (
        max(sorted(overall.composition), key=lambda key: overall.composition[key])
        if overall.composition
        else None
    )
    opens = _to_minutes(segment.window_start)
    closes = _to_minutes(segment.window_end)
    length = closes - opens if not segment.crosses_midnight else 1440 - opens + closes
    effective: tuple[int, int] | None = None
    if dominant is not None and instances:
        held = [0] * length
        for begin, _, inside in instances:
            # Minutes counted from the band's declared opening, not from where observation began, so
            # every instance lines up on the same axis.
            opening = datetime.combine(begin.date(), time(opens // 60, opens % 60), zone)
            if opening > begin:
                opening -= timedelta(days=1)
            marked: set[int] = set()
            for piece in inside:
                if (piece.intent, piece.location) != dominant:
                    continue
                first = int((piece.start - opening).total_seconds() // 60)
                last = int((piece.end - opening).total_seconds() // 60)
                marked.update(range(max(0, first), min(length, last)))
            for minute in marked:
                held[minute] += 1
        floor = EFFECTIVE_DAY_SHARE * len(instances)
        effective = _longest_run([count >= floor for count in held])

    def unaccounted(tally: _Tally) -> tuple[float, float]:
        remainder = max(0.0, tally.total - tally.covered)
        return round(remainder, 1), round(remainder / tally.total, 4) if tally.total else 0.0

    day_types = [
        HabitDayTypeObservation(
            day_type=name,
            day_count=tally.days,
            total_minutes=round(tally.total, 1),
            composition=_compose(tally.composition, tally.total),
            unaccounted_minutes=unaccounted(tally)[0],
            unaccounted_share=unaccounted(tally)[1],
            ambiguous_minutes=round(tally.ambiguous, 1),
            ambiguous_share=round(min(1.0, tally.ambiguous / tally.total), 4)
            if tally.total
            else 0.0,
        )
        for name, tally in by_class.items()
        if tally.days
    ]
    # Restating `composition` under another name helps nobody: the split is published only when the
    # band actually spans both kinds of day.
    if len(day_types) < 2:
        day_types = []

    return HabitObservation(
        habit_id=segment.habit_id,
        resident_id=resident_id,
        label=segment.label,
        window_start=segment.window_start,
        window_end=segment.window_end,
        crosses_midnight=segment.crosses_midnight,
        weekdays=list(segment.weekdays),
        day_count=overall.days,
        total_minutes=round(overall.total, 1),
        composition=_compose(overall.composition, overall.total),
        unaccounted_minutes=unaccounted(overall)[0],
        unaccounted_share=unaccounted(overall)[1],
        dominant_intent=dominant[0] if dominant else None,
        dominant_location=dominant[1] if dominant else None,
        effective_start=_clock(opens + effective[0]) if effective else None,
        effective_end=_clock(opens + effective[1]) if effective else None,
        effective_minutes=float(effective[1] - effective[0]) if effective else 0.0,
        effective_share=round((effective[1] - effective[0]) / length, 4) if effective else 0.0,
        day_types=day_types,
        ambiguous_minutes=round(overall.ambiguous, 1),
        ambiguous_share=round(min(1.0, overall.ambiguous / overall.total), 4)
        if overall.total
        else 0.0,
    )


def _provenance(declared: DeclaredHabits, evidence: Evidence) -> Provenance:
    return Provenance(
        author_type=AuthorType.rule_generator,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        parameters={
            "outlineId": declared.outline_id,
            "seed": declared.seed,
            "measuredOn": evidence.measured_on,
        },
    )


def measure_habits(declared: DeclaredHabits, evidence: Evidence) -> list[HabitGroundTruth]:
    """One document per declared resident: her bands, and what filled them in the evidence."""
    zone = ZoneInfo(declared.time_zone)
    shared = _co_presence(evidence)
    documents: list[HabitGroundTruth] = []
    for resident in declared.residents:
        who = resident.resident_id
        together = sorted(
            (
                Stretch(who, item.start, item.end, item.location)
                for item in shared
                if who in item.resident_ids
            ),
            key=lambda s: s.start,
        )
        documents.append(
            HabitGroundTruth(
                outline_id=declared.outline_id,
                resident_id=who,
                time_zone=declared.time_zone,
                start_date=declared.start_date,
                end_date=declared.end_date,
                seed=declared.seed,
                measured_on=evidence.measured_on,
                run_id=evidence.run_id,
                trace_id=evidence.trace_id,
                source_trace_semantic_digest=evidence.source_trace_semantic_digest,
                habits=[
                    _observe(segment, who, evidence, together, declared, zone)
                    for segment in resident.habits
                ],
                provenance=_provenance(declared, evidence),
            )
        )
    return documents


# --- the household -------------------------------------------------------------------------------


def _split_at_midnight(
    start: datetime, end: datetime, zone: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    pieces: list[tuple[datetime, datetime]] = []
    cursor = start.astimezone(zone)
    finish = end.astimezone(zone)
    while cursor < finish:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, zone)
        step = min(midnight, finish)
        pieces.append((cursor, step))
        cursor = step
    return pieces


def _wall_clock(moment: datetime, day: date) -> str:
    """HH:MM on `day`, with the midnight that closes the day written 24:00 rather than 00:00.

    Only ever called on a piece already split at midnight, so a later date can only be that
    midnight.
    """
    if moment.date() > day:
        return "24:00"
    return f"{moment.hour:02d}:{moment.minute:02d}"


def measure_household(
    declared: DeclaredHabits,
    evidence: Evidence,
    *,
    external_locations: Iterable[str],
) -> HouseholdGroundTruth:
    """What the house did, which no per-resident document can say.

    A habit ground truth answers "what was *she* doing between these hours". N of those still do
    not say the two of them were in the kitchen together at the time, and an experiment running on
    one shared sensor log needs that to tell a confounder apart from an error: without it, a minute
    two bodies produced and a minute one body produced look identical, and every failure on the
    first kind is charged to the algorithm.
    """
    zone = ZoneInfo(declared.time_zone)
    away = set(external_locations)
    roster = [item.resident_id for item in declared.residents] or list(evidence.resident_ids)
    together = _co_presence(evidence)

    at_home: dict[date, dict[str, float]] = defaultdict(lambda: dict.fromkeys(roster, 0.0))
    shared_minutes: dict[date, dict[str, float]] = defaultdict(lambda: dict.fromkeys(roster, 0.0))
    for resident_id, stretches in evidence.locations.items():
        if resident_id not in roster:
            continue
        # Unioned, so a plan's overlapping stretches do not count one hour at home twice.
        for piece in _merge_by_location(stretches):
            if piece.location in away:
                continue
            for begin, end in _split_at_midnight(piece.start, piece.end, zone):
                at_home[begin.date()][resident_id] += _minutes(begin, end)

    spans: list[CoPresenceSpan] = []
    for item in together:
        for begin, end in _split_at_midnight(item.start, item.end, zone):
            day = begin.date()
            spans.append(
                CoPresenceSpan(
                    day=day,
                    location=item.location,
                    start=_wall_clock(begin, day),
                    end=_wall_clock(end, day),
                    minutes=round(_minutes(begin, end), 1),
                    resident_ids=list(item.resident_ids),
                )
            )
            for resident_id in item.resident_ids:
                if resident_id in roster:
                    shared_minutes[day][resident_id] += _minutes(begin, end)

    episodes = [
        SharedEpisode(
            day=item.start.astimezone(zone).date(),
            activity_id=item.activity_id,
            intent=item.intent,
            location=item.location,
            start=f"{item.start.astimezone(zone):%H:%M}",
            # The clock it ended at, even past midnight: an episode is one sitting and is not split.
            end=f"{item.end.astimezone(zone):%H:%M}",
            minutes=round(_minutes(item.start, item.end), 1),
            participant_ids=list(item.participant_ids),
        )
        for item in evidence.episodes
    ]
    episodes_per_day = Counter(item.day for item in episodes)

    first = evidence.started_at.astimezone(zone).date()
    last = evidence.ended_at.astimezone(zone).date()
    days = [
        HouseholdDay(
            day=day,
            at_home_minutes={key: round(value, 1) for key, value in at_home[day].items()},
            shared_minutes={key: round(value, 1) for key, value in shared_minutes[day].items()},
            shared_activity_count=episodes_per_day[day],
        )
        for day in _days(
            max(first, declared.start_date), min(last + timedelta(days=1), declared.end_date)
        )
    ]
    return HouseholdGroundTruth(
        outline_id=declared.outline_id,
        resident_ids=roster,
        time_zone=declared.time_zone,
        start_date=declared.start_date,
        end_date=declared.end_date,
        seed=declared.seed,
        measured_on=evidence.measured_on,
        run_id=evidence.run_id,
        trace_id=evidence.trace_id,
        source_trace_semantic_digest=evidence.source_trace_semantic_digest,
        days=days,
        co_presence=spans,
        shared_episodes=episodes,
        sharing=_sharing_realised(declared, evidence, zone),
        provenance=_provenance(declared, evidence),
    )


def _sharing_realised(
    declared: DeclaredHabits, evidence: Evidence, zone: ZoneInfo
) -> list[SharingRealisation]:
    """Each declared shared activity, weekdays and weekends apart: declared against realised.

    A day counts once whatever happened on it — two separate dinners are one day on which dinner
    happened and was not shared — because a propensity is drawn once per day, and the share has to
    be counted in the unit the number was declared in. Only days inside the declared horizon are
    counted, so the day a window spills into does not dilute the share.
    """
    realised: list[SharingRealisation] = []
    for joint in declared.joint_activities:
        members = set(joint.participant_ids)
        held: dict[_DayClass, set[date]] = {"weekday": set(), "weekend": set()}
        shared: dict[_DayClass, set[date]] = {"weekday": set(), "weekend": set()}
        for item in evidence.occurrences:
            if item.recurring_activity_id != joint.recurring_activity_id:
                continue
            present = members & set(item.resident_ids)
            if not present:
                continue
            day = item.start.astimezone(zone).date()
            if not declared.start_date <= day < declared.end_date:
                continue
            day_class: _DayClass = "weekend" if day.weekday() >= 5 else "weekday"
            held[day_class].add(day)
            if len(present) > 1:
                shared[day_class].add(day)
        classes: tuple[_DayClass, ...] = ("weekday", "weekend")
        for day_class in classes:
            count = len(held[day_class])
            if not count:
                continue
            propensity = None
            if joint.propensity is not None:
                by_class = (
                    joint.propensity.weekend if day_class == "weekend" else joint.propensity.weekday
                )
                propensity = joint.propensity.default if by_class is None else by_class
            realised.append(
                SharingRealisation(
                    recurring_activity_id=joint.recurring_activity_id,
                    intent=joint.intent,
                    participant_ids=list(joint.participant_ids),
                    sharing=joint.sharing,
                    day_class=day_class,
                    declared_propensity=propensity,
                    days_with_occurrence=count,
                    days_shared=len(shared[day_class]),
                    realised_share=round(len(shared[day_class]) / count, 3),
                )
            )
    return realised


def _merge_by_location(stretches: Sequence[Stretch]) -> list[Stretch]:
    """The same whereabouts with overlapping stretches in one room fused into one."""
    by_location: dict[str, list[Stretch]] = defaultdict(list)
    for item in stretches:
        by_location[item.location].append(item)
    merged: list[Stretch] = []
    for location, items in by_location.items():
        items.sort(key=lambda s: s.start)
        current: Stretch | None = None
        for item in items:
            if current is not None and item.start <= current.end:
                current = Stretch(
                    current.resident_id, current.start, max(current.end, item.end), location
                )
            else:
                if current is not None:
                    merged.append(current)
                current = Stretch(item.resident_id, item.start, item.end, location)
        if current is not None:
            merged.append(current)
    return merged


DECLARED_HABITS_EXTENSION = "declaredHabits"


def declared_habits_of(scenario: Scenario) -> DeclaredHabits | None:
    """The bands a scenario carries, or nothing if it was not expanded from an outline."""
    payload = scenario.extensions.get(DECLARED_HABITS_EXTENSION)
    if payload is None:
        return None
    return DeclaredHabits.model_validate_json(json.dumps(payload))


def ground_truth_of_run(
    scenario: Scenario,
    trace: ExecutionTrace,
    *,
    run_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[list[HabitGroundTruth], HouseholdGroundTruth] | None:
    """The published habit ground truth of one run: its declared bands, measured on its trace.

    One entry point for everything that publishes it — the export and the command line — so there
    is exactly one reading of what a run did inside a band. Nothing, for a scenario that declares no
    bands: a horizon authored day by day never had an answer sheet, and inventing one here would be
    the same mistake in another place.
    """
    declared = declared_habits_of(scenario)
    if declared is None:
        return None
    evidence = evidence_from_trace(
        trace,
        initial_regions={
            item.resident_id: item.location_id for item in scenario.initial_state.residents
        },
        run_id=run_id,
        start=start,
        end=end,
        recurring_by_activity={
            activity.activity_id: recurring
            for day in scenario.days
            for activity in day.activities
            if (recurring := _recurring_activity_id_of(activity)) is not None
        },
    )
    external = [
        item.location_id for item in scenario.locations if item.kind is LocationKind.external
    ]
    return (
        measure_habits(declared, evidence),
        measure_household(declared, evidence, external_locations=external),
    )


__all__ = [
    "DECLARED_HABITS_EXTENSION",
    "declared_habits_of",
    "ground_truth_of_run",
    "EFFECTIVE_DAY_SHARE",
    "Episode",
    "Evidence",
    "MeasuredOn",
    "Occurrence",
    "Stretch",
    "evidence_from_plan",
    "evidence_from_trace",
    "measure_habits",
    "measure_household",
]
