"""Turn an execution trace into a resident profile.

The whole module rests on one function, `spread`: it projects a real interval onto the local wall
clock, yielding the minutes it contributes to each (date, slot) pair. Activity occupancy, region
presence and the observed window itself all go through it, which is what keeps shares inside
[0, 1] — the denominator is measured with exactly the same arithmetic as the numerator, so a
horizon that begins at noon, ends mid-morning or crosses a daylight-saving boundary cannot report
a slot as being busier than it was observed.

Local time comes from the timestamps themselves. The simulator writes every instant with the
home's own offset, so dropping the offset leaves the resident's wall clock and no timezone
database is consulted. The one place this shows is an interval that straddles a daylight-saving
change: it contributes the wall-clock minutes it spans, which is an hour fewer (or more) than the
real duration. That happens twice a year, to one interval, and the observed window absorbs it the
same way.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from smart_home_sim.domain.execution import ActivityExecution, ExecutionTrace, MovementExecution
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.domain.profile import (
    BehaviourSlice,
    DayType,
    IntentRhythm,
    RegionRhythm,
    ResidentBehaviour,
    ResidentProfile,
    SlotSummary,
)

GENERATOR_NAME = "smart-home-sim.profiling"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SLOT_MINUTES = 15
DAY_TYPES: tuple[DayType, ...] = ("all", "weekday", "weekend")

# A dropped activity never ran: it has no actual duration to place anywhere on the clock, and
# counting it would describe a person by what she failed to do. Failed and deviated activities did
# occupy the resident, so they enter the profile exactly as they occupied her.
OCCUPYING_STATUSES = frozenset({"completed", "deviated", "failed"})


def spread(start: datetime, end: datetime, slot_minutes: int) -> Iterator[tuple[date, int, float]]:
    """The minutes of [start, end) that fall in each local (date, slot)."""
    cursor = start.replace(tzinfo=None)
    finish = end.replace(tzinfo=None)
    while cursor < finish:
        slot = (cursor.hour * 60 + cursor.minute) // slot_minutes
        boundary = datetime.combine(cursor.date(), datetime.min.time()) + timedelta(
            minutes=(slot + 1) * slot_minutes
        )
        step = min(boundary, finish)
        yield cursor.date(), slot, (step - cursor).total_seconds() / 60.0
        cursor = step


def day_type_of(day: date) -> DayType:
    return "weekend" if day.weekday() >= 5 else "weekday"


def slot_labels(slot_minutes: int) -> list[str]:
    """`00:00-00:15`-style labels, the axis the habit-segmentation reference prints."""

    def clock(minutes: int) -> str:
        return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"

    return [
        f"{clock(index * slot_minutes)}-{clock((index + 1) * slot_minutes)}"
        for index in range(1440 // slot_minutes)
    ]


def _circular_start(minutes: list[float]) -> tuple[str | None, float | None]:
    """The typical start of a set of start times, and how tightly they cluster around it.

    Clock times are angles, so they are averaged as angles: the resultant vector's direction is the
    typical time and its length says how concentrated the sample is. An activity that starts at
    23:50 on some nights and 00:10 on others has a typical start of midnight, where averaging the
    minute counts would place it at noon. A resultant of zero — starts spread evenly around the
    day — has no typical time at all, and saying so beats inventing one.
    """
    if not minutes:
        return None, None
    angles = [value / 1440.0 * 2.0 * math.pi for value in minutes]
    mean_cos = sum(math.cos(angle) for angle in angles) / len(angles)
    mean_sin = sum(math.sin(angle) for angle in angles) / len(angles)
    resultant = math.hypot(mean_cos, mean_sin)
    if resultant < 1e-9:
        return None, None
    centre = math.atan2(mean_sin, mean_cos) % (2.0 * math.pi) / (2.0 * math.pi) * 1440.0
    spread_minutes = math.sqrt(-2.0 * math.log(min(resultant, 1.0))) / (2.0 * math.pi) * 1440.0
    # A single occurrence has a resultant of exactly one, and `sqrt(-0.0)` is negative zero, which
    # renders as "±-0 min". Zero is zero.
    return _hhmm(centre), abs(round(spread_minutes, 1))


def _hhmm(minutes: float) -> str:
    total = int(round(minutes)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


class _Accumulator:
    """Running totals for one resident, kept per day type so no second pass is needed."""

    def __init__(self, slot_count: int) -> None:
        self.slot_count = slot_count
        self.occupancy: dict[tuple[DayType, str], list[float]] = defaultdict(self._row)
        self.regions: dict[tuple[DayType, str], list[float]] = defaultdict(self._row)
        self.starts: dict[tuple[DayType, str], list[int]] = defaultdict(self._counts)
        self.durations: dict[tuple[DayType, str], list[float]] = defaultdict(list)
        self.start_minutes: dict[tuple[DayType, str], list[float]] = defaultdict(list)
        self.days: dict[tuple[DayType, str], set[date]] = defaultdict(set)
        self.occurrences: Counter[tuple[DayType, str]] = Counter()
        self.activities: Counter[DayType] = Counter()
        self.dropped = 0

    def _row(self) -> list[float]:
        return [0.0] * self.slot_count

    def _counts(self) -> list[int]:
        return [0] * self.slot_count

    def add_activity(self, activity: ActivityExecution, slot_minutes: int) -> None:
        if activity.status not in OCCUPYING_STATUSES:
            self.dropped += 1
            return
        for day, slot, minutes in spread(activity.actual_start, activity.actual_end, slot_minutes):
            for day_type in ("all", day_type_of(day)):
                self.occupancy[(day_type, activity.intent)][slot] += minutes
                self.days[(day_type, activity.intent)].add(day)
        local_start = activity.actual_start.replace(tzinfo=None)
        start_slot = (local_start.hour * 60 + local_start.minute) // slot_minutes
        duration = (activity.actual_end - activity.actual_start).total_seconds() / 60.0
        for day_type in ("all", day_type_of(local_start.date())):
            key = (day_type, activity.intent)
            self.starts[key][start_slot] += 1
            self.durations[key].append(duration)
            self.start_minutes[key].append(float(local_start.hour * 60 + local_start.minute))
            self.days[key].add(local_start.date())
            self.occurrences[key] += 1
            self.activities[day_type] += 1

    def add_presence(self, region_id: str, start: datetime, end: datetime, minutes: int) -> None:
        for day, slot, amount in spread(start, end, minutes):
            for day_type in ("all", day_type_of(day)):
                self.regions[(day_type, region_id)][slot] += amount

    def intents_of(self, day_type: DayType) -> list[str]:
        """Every intent this resident showed on that class of day.

        Taken from the occurrence counter as well as the occupancy rows: an activity the simulator
        opened and closed on the same instant occupies no slot but did happen, and a profile that
        omitted it would be missing a row the diary can show.
        """
        return sorted(
            {intent for slice_type, intent in self.occupancy if slice_type == day_type}
            | {intent for slice_type, intent in self.occurrences if slice_type == day_type}
        )


def _observed(
    started_at: datetime, ended_at: datetime, slot_minutes: int, slot_count: int
) -> tuple[dict[DayType, list[float]], dict[DayType, set[date]]]:
    minutes: dict[DayType, list[float]] = {name: [0.0] * slot_count for name in DAY_TYPES}
    days: dict[DayType, set[date]] = {name: set() for name in DAY_TYPES}
    for day, slot, amount in spread(started_at, ended_at, slot_minutes):
        for day_type in ("all", day_type_of(day)):
            minutes[day_type][slot] += amount
            days[day_type].add(day)
    return minutes, days


def _share(value: float, observed: float) -> float:
    return min(value / observed, 1.0) if observed > 0 else 0.0


def _slot_summaries(
    intents: list[IntentRhythm], observed: list[float], labels: list[str]
) -> list[SlotSummary]:
    summaries: list[SlotSummary] = []
    for slot, available in enumerate(observed):
        mix = {
            item.intent: item.occupancy_minutes[slot]
            for item in intents
            if item.occupancy_minutes[slot] > 0
        }
        total = sum(mix.values())
        dominant = max(mix.items(), key=lambda item: (item[1], item[0]))[0] if mix else None
        # Entropy over the labelled mix only. Unlabelled time is not one more activity: a slot in
        # which the resident does one thing for ten minutes and nothing measurable for five is
        # perfectly predictable, and charging it entropy for the gap would say otherwise.
        entropy = -sum(
            (amount / total) * math.log2(amount / total) for amount in mix.values() if amount > 0
        )
        summaries.append(
            SlotSummary(
                slot=slot,
                start=labels[slot].split("-")[0],
                observed_minutes=round(available, 3),
                labelled_share=round(_share(total, available), 6),
                dominant_intent=dominant,
                dominant_share=round(_share(mix[dominant], available), 6) if dominant else 0.0,
                entropy_bits=round(abs(entropy), 6),
            )
        )
    return summaries


def _clock(minutes: float) -> str:
    total = int(round(minutes))
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total} min"


def _clock_gap(first: str, second: str) -> int:
    """Signed minutes from `first` to `second`, taking the shorter way round the clock."""
    start = int(first[:2]) * 60 + int(first[3:])
    end = int(second[:2]) * 60 + int(second[3:])
    difference = (end - start) % 1440
    return difference - 1440 if difference > 720 else difference


def _narrate(slices: dict[DayType, BehaviourSlice]) -> list[str]:
    """Say the profile in sentences, from the same numbers the heatmap draws.

    A heatmap answers questions the reader already knew to ask. These sentences say the things a
    person asks first — when she sleeps, how reliably, what fills the day, where the weekend
    departs from the week — and they are generated deterministically from the slices, so two runs
    of the same trace describe the resident with the same words.
    """
    whole = slices["all"]
    if not whole.intents:
        return ["The trace records no activity for this resident."]
    lines = [
        f"{whole.activity_count} activities over {whole.day_count} observed day(s), "
        f"across {len(whole.intents)} distinct intents."
    ]
    for item in whole.intents[:6]:
        occasions = (
            f"{item.days_observed} of {whole.day_count} day(s)"
            if whole.day_count
            else f"{item.occurrences} time(s)"
        )
        # Plain ASCII: these sentences are echoed by the CLI too, and a Windows console renders a
        # "±" as a question mark.
        when = (
            f"around {item.typical_start} (spread {item.start_spread_minutes:.0f} min)"
            if item.typical_start is not None and item.start_spread_minutes is not None
            else "at no settled hour"
        )
        lines.append(
            f"{item.intent.replace('_', ' ')}: {occasions}, {when}, "
            f"for {_clock(item.mean_duration_minutes)} on average."
        )
    lines.extend(_weekend_shift(slices))
    rigid = [item for item in whole.slots if item.labelled_share > 0.5 and item.entropy_bits < 0.2]
    if rigid:
        lines.append(
            f"{len(rigid)} of {len(whole.slots)} slots are held by a single activity on most days; "
            "these are where the habit bands of the day sit."
        )
    return lines


def _weekend_shift(slices: dict[DayType, BehaviourSlice]) -> list[str]:
    weekday, weekend = slices["weekday"], slices["weekend"]
    if not weekday.day_count or not weekend.day_count:
        return []
    on_weekend = {item.intent: item for item in weekend.intents}
    shifts = []
    for item in weekday.intents[:8]:
        other = on_weekend.get(item.intent)
        if other is None or item.typical_start is None or other.typical_start is None:
            continue
        offset = _clock_gap(item.typical_start, other.typical_start)
        if abs(offset) >= 20:
            direction = "later" if offset > 0 else "earlier"
            shifts.append(f"{item.intent.replace('_', ' ')} {abs(offset)} min {direction}")
    return [f"The weekend moves the routine: {'; '.join(shifts[:4])}."] if shifts else []


def _presence(
    movements: Iterable[MovementExecution], started_at: datetime, ended_at: datetime
) -> dict[str, list[tuple[str, datetime, datetime]]]:
    """Where each actor was, as intervals, reconstructed from her movements.

    A movement says she arrived somewhere at a known instant, and she stays there until the next
    one departs. The run opens with her already somewhere: the origin of her first movement is the
    only evidence of where, and it holds until that movement departs.
    """
    by_actor: dict[str, list[MovementExecution]] = defaultdict(list)
    for movement in movements:
        by_actor[movement.actor_id].append(movement)
    presence: dict[str, list[tuple[str, datetime, datetime]]] = {}
    for actor_id, items in by_actor.items():
        items.sort(key=lambda item: (item.started_at, item.movement_id))
        intervals: list[tuple[str, datetime, datetime]] = []
        if items[0].started_at > started_at:
            intervals.append((items[0].origin_region_id, started_at, items[0].started_at))
        for index, movement in enumerate(items):
            following = items[index + 1].started_at if index + 1 < len(items) else ended_at
            if following > movement.ended_at:
                intervals.append((movement.destination_region_id, movement.ended_at, following))
        presence[actor_id] = intervals
    return presence


def _intent_rhythm(
    intent: str, day_type: DayType, totals: _Accumulator, observed: list[float]
) -> IntentRhythm:
    key = (day_type, intent)
    row = totals.occupancy.get(key, [0.0] * totals.slot_count)
    durations = totals.durations[key]
    typical_start, spread_minutes = _circular_start(totals.start_minutes[key])
    return IntentRhythm(
        intent=intent,
        occurrences=totals.occurrences[key],
        days_observed=len(totals.days[key]),
        total_minutes=round(sum(row), 3),
        mean_duration_minutes=round(sum(durations) / len(durations), 3) if durations else 0.0,
        median_duration_minutes=round(median(durations), 3) if durations else 0.0,
        typical_start=typical_start,
        start_spread_minutes=spread_minutes,
        occupancy_minutes=[round(value, 3) for value in row],
        occupancy_share=[round(_share(value, observed[slot]), 6) for slot, value in enumerate(row)],
        starts=list(totals.starts[key]),
    )


def _resident(
    actor_id: str,
    totals: _Accumulator,
    observed_minutes: dict[DayType, list[float]],
    observed_days: dict[DayType, set[date]],
    labels: list[str],
) -> ResidentBehaviour:
    slices: dict[DayType, BehaviourSlice] = {}
    for day_type in DAY_TYPES:
        available = observed_minutes[day_type]
        intents = sorted(
            (
                _intent_rhythm(intent, day_type, totals, available)
                for intent in totals.intents_of(day_type)
            ),
            key=lambda item: (-item.total_minutes, item.intent),
        )
        regions = sorted(
            (
                RegionRhythm(
                    region_id=region_id,
                    total_minutes=round(sum(row), 3),
                    occupancy_share=[
                        round(_share(value, available[slot]), 6) for slot, value in enumerate(row)
                    ],
                )
                for (slice_type, region_id), row in totals.regions.items()
                if slice_type == day_type
            ),
            key=lambda item: (-item.total_minutes, item.region_id),
        )
        slices[day_type] = BehaviourSlice(
            day_type=day_type,
            day_count=len(observed_days[day_type]),
            observed_minutes=round(sum(available), 3),
            activity_count=totals.activities[day_type],
            intents=intents,
            regions=regions,
            slots=_slot_summaries(intents, available, labels),
        )
    return ResidentBehaviour(
        resident_id=actor_id,
        activity_count=totals.activities["all"],
        dropped_activity_count=totals.dropped,
        narrative=_narrate(slices),
        slices=[slices[day_type] for day_type in DAY_TYPES],
    )


def build_profile(
    *,
    trace_id: str,
    semantic_digest: str,
    seed: int,
    started_at: datetime,
    ended_at: datetime,
    activities: Iterable[ActivityExecution],
    movements: Iterable[MovementExecution],
    run_id: str | None = None,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
    now: datetime | None = None,
) -> ResidentProfile:
    """Aggregate one run's realized behaviour into a readable profile.

    `now` is left unset by every caller in the application, so the document carries no generation
    timestamp. That is deliberate: an export promises that the same run and the same request
    rebuild the same bytes, and a clock reading inside the only computed role would quietly break
    it. Provenance still names the generator, its version and the slot width it used.
    """
    if slot_minutes < 1 or 1440 % slot_minutes != 0:
        raise ValueError("slot minutes must divide the day evenly")
    if ended_at < started_at:
        raise ValueError("the trace window ends before it starts")
    labels = slot_labels(slot_minutes)
    observed_minutes, observed_days = _observed(started_at, ended_at, slot_minutes, len(labels))
    accumulators: dict[str, _Accumulator] = defaultdict(lambda: _Accumulator(len(labels)))
    for activity in activities:
        accumulators[activity.actor_id].add_activity(activity, slot_minutes)
    for actor_id, intervals in _presence(movements, started_at, ended_at).items():
        for region_id, start, end in intervals:
            accumulators[actor_id].add_presence(region_id, start, end, slot_minutes)
    return ResidentProfile(
        profile_id=f"profile_{trace_id}",
        run_id=run_id,
        trace_id=trace_id,
        source_trace_semantic_digest=semantic_digest,
        seed=seed,
        start_date=started_at.replace(tzinfo=None).date(),
        end_date=ended_at.replace(tzinfo=None).date(),
        day_count=len(observed_days["all"]),
        slot_minutes=slot_minutes,
        slot_labels=labels,
        residents=[
            _resident(actor_id, accumulators[actor_id], observed_minutes, observed_days, labels)
            for actor_id in sorted(accumulators)
        ],
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=now,
            parameters={"slotMinutes": slot_minutes},
        ),
    )


def profile_from_trace(
    trace: ExecutionTrace,
    *,
    run_id: str | None = None,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> ResidentProfile:
    """Profile a parsed trace, optionally only the part of it inside [start, end].

    An event belongs to the window when it opens inside it, which is the rule the export applies
    to every other role: a window that keeps a sensor reading and drops the activity that caused
    it would leave the two halves of one dataset describing different months.
    """
    started_at = max(trace.started_at, start) if start else trace.started_at
    ended_at = min(trace.ended_at, end) if end else trace.ended_at
    return build_profile(
        trace_id=trace.trace_id,
        semantic_digest=trace.semantic_digest,
        seed=trace.seed,
        started_at=started_at,
        ended_at=max(ended_at, started_at),
        activities=[
            item
            for item in trace.activity_executions
            if started_at <= item.actual_start <= ended_at
        ],
        movements=[item for item in trace.movements if started_at <= item.started_at <= ended_at],
        run_id=run_id,
        slot_minutes=slot_minutes,
        now=now,
    )


def profile_from_trace_file(
    path: Path,
    *,
    run_id: str | None = None,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> ResidentProfile:
    trace = ExecutionTrace.model_validate_json(path.read_text(encoding="utf-8"))
    return profile_from_trace(
        trace, run_id=run_id, slot_minutes=slot_minutes, start=start, end=end, now=now
    )
