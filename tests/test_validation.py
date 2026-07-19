from smart_home_sim.domain.models import Scenario
from smart_home_sim.validation.scenario import validate_scenario


def test_validation_reports_unknown_sensor_room() -> None:
    scenario = Scenario.model_validate(
        {
            "schemaVersion": "0.1",
            "scenarioId": "invalid",
            "simulationDate": "2026-10-12",
            "seed": 1,
            "resident": {"residentId": "r1", "initialRoom": "bedroom"},
            "rooms": [{"roomId": "bedroom", "connections": []}],
            "sensors": [{"sensorId": "pir_1", "type": "pir", "room": "missing"}],
            "activities": [],
        }
    )

    assert validate_scenario(scenario) == ["sensor pir_1 references unknown room: missing"]
