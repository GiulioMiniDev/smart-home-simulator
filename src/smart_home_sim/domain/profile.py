"""The realized behaviour of a resident, aggregated into a shape a person can read.

Every other view of a run is per-event: the diary lists activities one by one, the observable log
lists readings one by one. Neither answers the question a researcher actually asks of a synthetic
resident — *what is this person like?* — because that answer lives in the aggregate: at what hour
does she reliably sleep, how wide is the spread on her wake-up, which rooms hold her day, where the
routine is rigid and where it dissolves.

This document is that aggregate, computed from the execution trace alone. It is the *realized*
truth: what the simulator actually produced, deviations, failures and all. It deliberately does not
consult the declared habit bands of `HabitGroundTruth`, so a band comparison stays an evaluation
someone performs, not a claim this document makes.

The unit is the slot: the day cut into equal pieces of `slot_minutes` (15 by default, the
discretisation the habit-segmentation reference uses on CASAS Aruba), and every measurement is
stated per slot so the whole thing renders as a heatmap without further arithmetic.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import ConfigDict, Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import Provenance

DayType = Literal["all", "weekday", "weekend"]


class IntentRhythm(ContractModel):
    """One activity across the clock: how much of each slot it holds, and when it typically starts.

    `occupancy_share` is the readable one — the fraction of the *observed* time in that slot during
    which the resident was doing this. It divides by observed minutes rather than by day count, so
    a horizon that starts at noon does not report the morning as empty behaviour when it is in fact
    unobserved time.

    `typical_start` is a circular mean, not an arithmetic one: an activity that starts at 23:50 on
    some nights and 00:10 on others has a typical start of midnight, whereas averaging the minute
    counts would place it at noon. `start_spread_minutes` is the matching circular deviation, and
    it is the number that says whether this is a habit or a whim.
    """

    intent: str = Field(min_length=1)
    occurrences: int = Field(ge=0)
    days_observed: int = Field(ge=0)
    total_minutes: float = Field(ge=0)
    mean_duration_minutes: float = Field(ge=0)
    median_duration_minutes: float = Field(ge=0)
    typical_start: str | None = None
    start_spread_minutes: float | None = Field(default=None, ge=0)
    occupancy_minutes: list[float] = Field(default_factory=list)
    occupancy_share: list[float] = Field(default_factory=list)
    starts: list[int] = Field(default_factory=list)


class RegionRhythm(ContractModel):
    """Where the resident is across the clock, reconstructed from her movements.

    A movement says she arrived somewhere at a known instant; she stays there until the next
    movement departs. Before the first movement of the run her position is taken from that
    movement's origin. This is presence, not activity: it holds while she sleeps, and it is the
    half of a profile that explains why a PIR in the hallway fires when it does.
    """

    region_id: str = Field(min_length=1)
    total_minutes: float = Field(ge=0)
    occupancy_share: list[float] = Field(default_factory=list)


class SlotSummary(ContractModel):
    """One slot of the clock, judged on how predictable it is.

    `dominant_share` is the fraction of the slot's observed time held by its most frequent
    activity, and `entropy_bits` the Shannon entropy of the whole mix in it. Together they are the
    quantity a segmentation algorithm is trying to find without being told: a slot at 0 bits is a
    slot the resident always spends the same way, and a run of such slots is a habit band. Slots
    are reported even when nothing is labelled in them, because an empty stretch of the day is a
    boundary and deleting it would hide where the day divides.
    """

    slot: int = Field(ge=0)
    start: str = Field(min_length=1)
    observed_minutes: float = Field(ge=0)
    labelled_share: float = Field(ge=0, le=1)
    dominant_intent: str | None = None
    dominant_share: float = Field(default=0.0, ge=0, le=1)
    entropy_bits: float = Field(default=0.0, ge=0)


class BehaviourSlice(ContractModel):
    """The same resident measured over one class of day.

    Weekday and weekend are reported separately because for most residents they are two different
    people wearing one name, and a single averaged heatmap smears the difference into a blur that
    reads as noise. The `all` slice is not the mean of the other two — it is the same computation
    over every day — so shares in it stay directly comparable.
    """

    day_type: DayType
    day_count: int = Field(ge=0)
    observed_minutes: float = Field(ge=0)
    activity_count: int = Field(ge=0)
    intents: list[IntentRhythm] = Field(default_factory=list)
    regions: list[RegionRhythm] = Field(default_factory=list)
    slots: list[SlotSummary] = Field(default_factory=list)


class ResidentBehaviour(ContractModel):
    """One resident's profile, with the sentences that describe it in words.

    `narrative` exists because a heatmap answers questions you already knew to ask. The sentences
    are generated from the same numbers, deterministically, and say the things a person would say
    first: when she sleeps, how reliably, what fills her day, where the weekend departs from the
    week.
    """

    resident_id: str = Field(min_length=1)
    activity_count: int = Field(ge=0)
    dropped_activity_count: int = Field(default=0, ge=0)
    narrative: list[str] = Field(default_factory=list)
    slices: list[BehaviourSlice] = Field(default_factory=list)


class ResidentProfile(ContractModel):
    """What a run's residents are like, derived from the execution trace and nothing else."""

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:resident-profile:1.0.0",
            "title": "Smart Home Resident Profile 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["resident_profile"] = "resident_profile"
    profile_id: str = Field(min_length=1)
    run_id: str | None = None
    trace_id: str = Field(min_length=1)
    source_trace_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    start_date: date
    end_date: date
    day_count: int = Field(ge=0)
    slot_minutes: int = Field(ge=1, le=1440)
    slot_labels: list[str] = Field(default_factory=list)
    residents: list[ResidentBehaviour] = Field(default_factory=list)
    provenance: Provenance
