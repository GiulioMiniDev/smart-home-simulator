from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import activity, proposal

from smart_home_sim.hybrid_planning.behavioral_models import HabitLedger
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.habit_gates import update_habit_ledger
from smart_home_sim.hybrid_planning.longitudinal import (
    generate_one_month_plan,
    one_month_end,
    slice_planning_case,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    LongitudinalCheckpoint,
)
from smart_home_sim.hybrid_planning.longitudinal_quality import (
    evaluate_longitudinal_quality,
)
from smart_home_sim.hybrid_planning.models import (
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
)
from smart_home_sim.hybrid_planning.service import (
    HybridPlanningError,
    _read_models,
    _rebuild_memory,
)

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"

VARIABLE_INTENTS = [
    "read",
    "evening_walk",
    "clean_kitchen",
    "buy_groceries",
    "watch_documentary",
    "start_laundry",
    "weekly_meal_preparation",
]


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
        proposals = [
            proposal(
                value,
                "read"
                if self.repeat_every_day
                else VARIABLE_INTENTS[
                    (value.toordinal() - date(2026, 8, 10).toordinal())
                    % len(VARIABLE_INTENTS)
                ],
            )
            for value in planning_case.dates()
        ]
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
    intents = [
        "read",
        "evening_walk",
        "clean_kitchen",
        "buy_groceries",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    days = [
        proposal(
            date.fromordinal(date(2026, 8, 10).toordinal() + offset),
            intent,
        )
        for offset, intent in enumerate(intents)
    ]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert report.valid
    assert report.optional_windows_without_variation == []


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
