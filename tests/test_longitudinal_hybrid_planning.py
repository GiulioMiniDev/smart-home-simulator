from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import activity, proposal

from smart_home_sim.hybrid_planning.behavioral_models import (
    HabitCadence,
    HabitDrift,
    HabitLedger,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.habit_gates import (
    effective_habit_cadence,
    effective_habit_time_bands,
    update_habit_ledger,
)
from smart_home_sim.hybrid_planning.longitudinal import (
    generate_one_month_plan,
    one_month_end,
    slice_planning_case,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    LongitudinalCheckpoint,
    LongitudinalHabitMetric,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.longitudinal_quality import (
    evaluate_longitudinal_quality,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
    ProposedActivity,
    TimeBand,
)
from smart_home_sim.hybrid_planning.service import (
    HybridPlanningError,
    _read_models,
    _rebuild_memory,
)

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"

def guarded_month_fixture() -> list[DailyProposal]:
    start = date(2026, 8, 10)
    variable_intents = [
        "clean_kitchen",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    grocery_dates = {
        date(2026, 8, 10),
        date(2026, 8, 17),
        date(2026, 8, 24),
        date(2026, 8, 31),
        date(2026, 9, 7),
    }
    mother_dates = {
        date(2026, 8, 15),
        date(2026, 8, 23),
        date(2026, 9, 5),
    }
    result: list[DailyProposal] = []
    for offset in range(31):
        value = start + timedelta(days=offset)
        daily = proposal(
            value,
            variable_intents[offset % len(variable_intents)],
        )
        additions: list[ProposedActivity] = []
        if value in grocery_dates:
            additions.append(
                activity(
                    "buy_groceries",
                    "supermarket_barcelona",
                    "afternoon",
                )
            )
        if value.weekday() in {0, 2, 4}:
            additions.append(
                activity(
                    "read",
                    "living_room_01",
                    "evening",
                    mandatory=False,
                )
            )
        if value.weekday() in {1, 5}:
            additions.append(
                activity(
                    "evening_walk",
                    "neighborhood_park",
                    "evening",
                    mandatory=False,
                )
            )
        if value in mother_dates:
            additions.extend(
                [
                    activity(
                        "travel_to_mothers_home",
                        "mother_house_barcelona",
                        "afternoon",
                    ),
                    activity(
                        "visit_mother_and_have_dinner",
                        "mother_house_barcelona",
                        "evening",
                    ),
                    activity(
                        "travel_home",
                        "living_room_01",
                        "evening",
                    ),
                ]
            )
        daily = daily.model_copy(
            update={
                "activities": [
                    *daily.activities[:-2],
                    *additions,
                    *daily.activities[-2:],
                ]
            }
        )
        result.append(daily)
    return result


def replace_habit_band(
    proposal: DailyProposal,
    intent: str,
    band: TimeBand,
) -> DailyProposal:
    return proposal.model_copy(
        update={
            "activities": [
                item.model_copy(update={"time_band": band})
                if item.intent == intent
                else item
                for item in proposal.activities
            ]
        }
    )


class FakeChunkGenerator:
    def __init__(self) -> None:
        self.call_count = 0
        self.fail_on_call: int | None = None
        self.repeat_every_day = False
        self.chunk_starts: list[date] = []

    def __call__(
        self,
        case_path: Path,
        output_dir: Path,
        _config: HybridPlanningConfig,
        *,
        behavioral_profile_path: Path,
        ledger_path: Path | None,
        initial_memory: PlanningMemory,
        client: Any,
    ) -> SimpleNamespace:
        del client
        self.call_count += 1
        planning_case = PlanningCase.model_validate_json(
            case_path.read_text(encoding="utf-8")
        )
        self.chunk_starts.append(planning_case.dates()[0])
        if self.call_count == self.fail_on_call:
            raise HybridPlanningError("synthetic chunk failure")
        profile = valid_profile()
        assert behavioral_profile_digest(profile) == behavioral_profile_digest(
            type(profile).model_validate_json(
                behavioral_profile_path.read_text(encoding="utf-8")
            )
        )
        if ledger_path is None:
            raise AssertionError("longitudinal chunks require a habit ledger")
        ledger = HabitLedger.model_validate_json(
            ledger_path.read_text(encoding="utf-8")
        )
        guarded_by_date = {
            item.date: item for item in guarded_month_fixture()
        }
        proposals = (
            [proposal(value, "read") for value in planning_case.dates()]
            if self.repeat_every_day
            else [guarded_by_date[value] for value in planning_case.dates()]
        )
        output_dir.mkdir(parents=True)
        (output_dir / "canonical-plan.json").write_text(
            '{"documentType":"canonical_plan"}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            proposals=tuple(proposals),
            memory=_rebuild_memory(proposals, initial_memory),
            habit_ledger=update_habit_ledger(
                profile,
                behavioral_profile_digest(profile),
                ledger,
                proposals,
            ),
        )


@pytest.fixture
def fake_chunk_generator(tmp_path: Path) -> FakeChunkGenerator:
    (tmp_path / "profile.json").write_text(
        valid_profile().model_dump_json(indent=2, by_alias=True) + "\n",
        encoding="utf-8",
    )
    return FakeChunkGenerator()


def test_one_month_end_clamps_day_for_shorter_month() -> None:
    assert one_month_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert one_month_end(date(2028, 1, 31)) == date(2028, 2, 29)
    assert one_month_end(date(2026, 8, 10)) == date(2026, 9, 10)


def test_effective_habit_fields_follow_latest_drift() -> None:
    habit = valid_profile().habits[-1]
    drifted = habit.model_copy(
        update={
            "drifts": [
                HabitDrift(
                    effective_from=date(2026, 9, 1),
                    rationale="A sustained change in the synthetic routine.",
                    cadence_override=HabitCadence(
                        minimum_occurrences=0,
                        typical_occurrences=2,
                        maximum_occurrences=2,
                        period_days=30,
                    ),
                    preferred_time_bands_override=[TimeBand.evening],
                )
            ]
        }
    )

    assert (
        effective_habit_cadence(drifted, date(2026, 9, 2)).typical_occurrences
        == 2
    )
    assert effective_habit_time_bands(
        drifted, date(2026, 9, 2)
    ) == [TimeBand.evening]


def test_longitudinal_quality_contract_carries_mining_metrics() -> None:
    metric = LongitudinalHabitMetric(
        habit_id="weekly_groceries",
        intent="buy_groceries",
        expected_occurrences=4.4,
        lower_occurrences=4,
        upper_occurrences=5,
        observed_occurrences=5,
        target_deviation=0.6,
        temporal_adherence=0.8,
        location_adherence=1.0,
    )
    report = LongitudinalQualityReport(
        valid=True,
        day_count=31,
        maximum_consecutive_identical_days=1,
        mean_daily_activities=8.2,
        minimum_daily_activities=6,
        maximum_daily_activities=11,
        habit_metrics=[metric],
    )

    assert report.habit_metrics == [metric]
    assert report.mean_daily_activities == 8.2


def test_slice_planning_case_covers_month_without_gaps() -> None:
    planning_case, _ = _read_models(CASE)

    chunks = slice_planning_case(
        planning_case,
        end_exclusive=date(2026, 9, 10),
        chunk_days=7,
    )

    assert [len(item.dates()) for item in chunks] == [7, 7, 7, 7, 3]
    dates = [value for chunk in chunks for value in chunk.dates()]
    assert dates == [
        date.fromordinal(date(2026, 8, 10).toordinal() + offset)
        for offset in range(31)
    ]
    assert all(chunk.case_id == planning_case.case_id for chunk in chunks)
    assert all(chunk.initial_state.at == chunk.planning_window.start for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_days", "end_exclusive", "message"),
    [
        (0, date(2026, 9, 10), "chunk_days"),
        (8, date(2026, 9, 10), "chunk_days"),
        (7, date(2026, 8, 10), "end_exclusive"),
    ],
)
def test_slice_planning_case_rejects_invalid_bounds(
    chunk_days: int,
    end_exclusive: date,
    message: str,
) -> None:
    planning_case, _ = _read_models(CASE)

    with pytest.raises(ValueError, match=message):
        slice_planning_case(
            planning_case,
            end_exclusive=end_exclusive,
            chunk_days=chunk_days,
        )


def test_longitudinal_quality_rejects_four_identical_consecutive_days() -> None:
    days = [
        proposal(
            date.fromordinal(date(2026, 8, 10).toordinal() + offset),
            "read",
        )
        for offset in range(4)
    ]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert not report.valid
    assert report.maximum_consecutive_identical_days == 4
    assert "CONSECUTIVE_DUPLICATE_DAYS" in report.reasons


def test_longitudinal_quality_rejects_sparse_daily_life() -> None:
    sparse = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Sparse Sunday",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("read_and_rest", "living_room_01", "afternoon"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    report = evaluate_longitudinal_quality(valid_profile(), [sparse])

    assert "DAILY_LIFE_VIOLATIONS" in report.reasons
    assert report.minimum_daily_activities == 4


def test_longitudinal_quality_reports_habit_frequency_and_time_deviation() -> None:
    days = guarded_month_fixture()
    days[0] = replace_habit_band(
        days[0],
        "buy_groceries",
        TimeBand.morning,
    )

    report = evaluate_longitudinal_quality(valid_profile(), days)

    groceries = next(
        item for item in report.habit_metrics if item.intent == "buy_groceries"
    )
    mother_visits = next(
        item
        for item in report.habit_metrics
        if item.intent == "visit_mother_and_have_dinner"
    )
    assert groceries.temporal_adherence < 1
    assert (
        mother_visits.lower_occurrences
        <= mother_visits.observed_occurrences
        <= mother_visits.upper_occurrences
    )
    assert "HABIT_TEMPORAL_DEVIATION" in report.reasons


def test_longitudinal_quality_rejects_commute_without_work_shift() -> None:
    day = proposal(date(2026, 8, 16), "read")
    bad = day.model_copy(
        update={
            "activities": [
                *day.activities[:-2],
                activity(
                    "commute_to_work",
                    "garden_workplace",
                    "afternoon",
                    mandatory=False,
                ),
                *day.activities[-2:],
            ]
        }
    )

    report = evaluate_longitudinal_quality(valid_profile(), [bad])

    assert not report.valid
    assert {item.code for item in report.causal_violations} == {
        "WORK_TRAVEL_WITHOUT_SHIFT"
    }


def test_longitudinal_quality_accepts_habit_skeleton_with_variable_shell() -> None:
    days = guarded_month_fixture()[:7]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert report.valid
    assert report.optional_windows_without_variation == []


def test_longitudinal_quality_reports_incomplete_habit_chain() -> None:
    day = proposal(date(2026, 8, 16), "read")
    incomplete = day.model_copy(
        update={
            "activities": [
                *day.activities[:-2],
                activity(
                    "visit_mother_and_have_dinner",
                    "mother_house_barcelona",
                    "evening",
                ),
                *day.activities[-2:],
            ]
        }
    )

    report = evaluate_longitudinal_quality(valid_profile(), [incomplete])

    assert {item.code for item in report.causal_violations} == {
        "MISSING_HABIT_PREDECESSOR",
        "MISSING_HABIT_SUCCESSOR",
    }


def test_longitudinal_quality_reports_week_without_variable_shell() -> None:
    days = [
        proposal(
            date.fromordinal(date(2026, 8, 10).toordinal() + offset),
            "clean_kitchen",
        )
        for offset in range(7)
    ]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert report.optional_windows_without_variation == [date(2026, 8, 10)]
    assert "MISSING_WEEKLY_VARIABLE_SHELL" in report.reasons


def test_one_month_orchestrator_accepts_five_chunks_and_completes(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    result = generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        chunk_generator=fake_chunk_generator,
    )

    assert result.checkpoint.next_date == date(2026, 9, 10)
    assert len(result.checkpoint.chunks) == 5
    assert result.quality.valid
    manifest = json.loads((tmp_path / "month/run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["executionPerformed"] is False
    assert manifest["baselineExposedToModel"] is False


def test_resume_skips_accepted_chunks(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    fake_chunk_generator.fail_on_call = 3
    with pytest.raises(HybridPlanningError, match="synthetic chunk failure"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake"),
            chunk_generator=fake_chunk_generator,
        )
    assert (
        len(
            LongitudinalCheckpoint.model_validate_json(
                (tmp_path / "month/checkpoint.json").read_text(encoding="utf-8")
            ).chunks
        )
        == 2
    )

    fake_chunk_generator.fail_on_call = None
    generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        resume=True,
        chunk_generator=fake_chunk_generator,
    )

    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 10)) == 1
    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 17)) == 1
    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 24)) == 2


def test_failed_quality_does_not_advance_checkpoint(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    fake_chunk_generator.repeat_every_day = True

    with pytest.raises(HybridPlanningError, match="longitudinal quality"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake"),
            chunk_generator=fake_chunk_generator,
        )

    checkpoint = LongitudinalCheckpoint.model_validate_json(
        (tmp_path / "month/checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint.next_date < date(2026, 9, 10)
    assert len(checkpoint.chunks) < 5


def test_resume_rejects_modified_accepted_artifact(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    result = generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        chunk_generator=fake_chunk_generator,
    )
    first = result.checkpoint.chunks[0]
    proposals_path = (
        tmp_path / "month" / first.artifact_path / "accepted-proposals.json"
    )
    proposals_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(HybridPlanningError, match="digest mismatch"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake"),
            resume=True,
            chunk_generator=fake_chunk_generator,
        )
    manifest = json.loads((tmp_path / "month/run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_resume_rejects_configuration_change(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        chunk_generator=fake_chunk_generator,
    )

    with pytest.raises(HybridPlanningError, match="identity mismatch"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake", temperature=0.3),
            resume=True,
            chunk_generator=fake_chunk_generator,
        )


def test_resume_requires_existing_checkpoint(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    with pytest.raises(HybridPlanningError, match="checkpoint.json"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "missing-run",
            HybridPlanningConfig(model="fake"),
            resume=True,
            chunk_generator=fake_chunk_generator,
        )


def test_new_run_rejects_existing_output_directory(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(HybridPlanningError, match="already exists"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            output,
            HybridPlanningConfig(model="fake"),
            chunk_generator=fake_chunk_generator,
        )
