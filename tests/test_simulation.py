from pathlib import Path

from smart_home_sim.engine.simulator import run_simulation
from smart_home_sim.io import load_scenario

EXAMPLE = Path(__file__).parents[1] / "examples" / "minimal_scenario.json"


def test_minimal_scenario_runs_end_to_end() -> None:
    scenario = load_scenario(EXAMPLE)
    result = run_simulation(scenario)

    assert len(result.activity_executions) == len(scenario.activities)
    assert result.raw_sensor_events
    assert result.ground_truth
    assert {event.value for event in result.raw_sensor_events} == {"ON", "OFF"}
    assert all(not hasattr(event, "actor_id") for event in result.raw_sensor_events)
    assert {event.actor_id for event in result.ground_truth} == {scenario.resident.resident_id}


def test_simulation_is_deterministic_for_same_seed() -> None:
    scenario = load_scenario(EXAMPLE)

    first = run_simulation(scenario).model_dump()
    second = run_simulation(scenario).model_dump()

    assert first == second
