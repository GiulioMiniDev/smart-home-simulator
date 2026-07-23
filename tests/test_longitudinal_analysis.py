from datetime import date, timedelta
from pathlib import Path

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import BASELINE, proposal
from test_longitudinal_hybrid_planning import CASE, FakeChunkGenerator

from smart_home_sim.hybrid_planning.longitudinal import generate_one_month_plan
from smart_home_sim.hybrid_planning.longitudinal_analysis import (
    compare_longitudinal_runs,
    compare_summaries,
    summarize_proposals,
)
from smart_home_sim.hybrid_planning.models import HybridPlanningConfig


def test_proposal_summary_measures_density_variety_and_daily_life() -> None:
    start = date(2026, 8, 10)
    intents = [
        "clean_kitchen",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
        "clean_kitchen",
    ]
    proposals = [
        proposal(start + timedelta(days=offset), intent)
        for offset, intent in enumerate(intents)
    ]

    summary = summarize_proposals(valid_profile(), proposals)

    assert summary["dayCount"] == 5
    assert summary["activityCount"] == sum(
        len(item.activities) for item in proposals
    )
    assert summary["dailyLife"]["nourishmentCoverage"] == 1.0
    assert summary["dailyLife"]["hygieneCoverage"] == 1.0
    assert summary["variety"]["distinctSignatures"] >= 4
    assert summary["habits"]["take_morning_medication"]["observed"] == 5


def test_summary_comparison_reports_core_deltas() -> None:
    start = date(2026, 8, 10)
    before = summarize_proposals(
        valid_profile(),
        [proposal(start + timedelta(days=index), "clean_kitchen") for index in range(3)],
    )
    after = summarize_proposals(
        valid_profile(),
        [
            proposal(start + timedelta(days=index), intent)
            for index, intent in enumerate(
                ["clean_kitchen", "watch_documentary", "start_laundry"]
            )
        ],
    )

    delta = compare_summaries(before, after)

    assert delta["meanDailyActivities"] == pytest.approx(
        after["density"]["mean"] - before["density"]["mean"]
    )
    assert delta["nourishmentCoverage"] == pytest.approx(
        after["dailyLife"]["nourishmentCoverage"]
        - before["dailyLife"]["nourishmentCoverage"]
    )


def test_longitudinal_run_comparison_verifies_and_summarizes_runs(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        valid_profile().model_dump_json(indent=2, by_alias=True) + "\n",
        encoding="utf-8",
    )
    before = tmp_path / "before"
    after = tmp_path / "after"
    generate_one_month_plan(
        CASE,
        profile_path,
        before,
        HybridPlanningConfig(model="fake"),
        chunk_generator=FakeChunkGenerator(),
    )
    generate_one_month_plan(
        CASE,
        profile_path,
        after,
        HybridPlanningConfig(model="fake"),
        chunk_generator=FakeChunkGenerator(),
    )

    report = compare_longitudinal_runs(
        before,
        after,
        baseline_path=BASELINE,
    )

    assert report["documentType"] == "hybrid_longitudinal_comparison"
    assert report["before"]["dayCount"] == 31
    assert report["after"]["dayCount"] == 31
    assert report["delta"]["meanDailyActivities"] == 0
    assert report["baseline"]["dayCount"] == 7
