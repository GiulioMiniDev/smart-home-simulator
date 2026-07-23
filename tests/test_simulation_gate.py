from datetime import date
from pathlib import Path

from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import Scenario
from smart_home_sim.hybrid_planning.simulation_gate import (
    _dates_from_activity_ids,
    simulate_chunk,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_SCENARIO = PROJECT_ROOT / "examples/valid/minimal.json"
MINIMAL_PACKAGE = PROJECT_ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"


def test_dates_from_activity_ids_parses_embedded_dates() -> None:
    assert _dates_from_activity_ids({"hybrid_20260810_04"}) == {date(2026, 8, 10)}
    assert _dates_from_activity_ids(
        {"hybrid_20260810_01", "hybrid_20260812_07"}
    ) == {date(2026, 8, 10), date(2026, 8, 12)}
    # An id without a valid date contributes nothing rather than raising.
    assert _dates_from_activity_ids({"no_date_here", "hybrid_20261340_01"}) == set()


def test_simulate_chunk_accepts_an_executable_chunk() -> None:
    scenario = Scenario.model_validate_json(MINIMAL_SCENARIO.read_bytes())
    package = PersonalProcessPackage.model_validate_json(MINIMAL_PACKAGE.read_bytes())
    plan = compile_scenario(scenario).plan
    assert plan is not None

    result = simulate_chunk(scenario, plan, package)

    assert result.success is True
    assert result.stage == "ok"
    assert result.failing_activity_ids == frozenset()
    assert result.failing_dates == frozenset()
