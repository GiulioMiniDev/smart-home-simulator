from __future__ import annotations

from smart_home_sim.domain.models import Scenario


class ScenarioValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    return {value for value in values if value in seen or seen.add(value)}


def validate_scenario(scenario: Scenario) -> list[str]:
    errors: list[str] = []

    room_ids = [room.room_id for room in scenario.rooms]
    room_set = set(room_ids)
    for duplicate in sorted(_duplicates(room_ids)):
        errors.append(f"duplicate room id: {duplicate}")

    if scenario.resident.initial_room not in room_set:
        errors.append(f"unknown resident initial room: {scenario.resident.initial_room}")

    for room in scenario.rooms:
        for connection in room.connections:
            if connection not in room_set:
                errors.append(f"room {room.room_id} references unknown connection: {connection}")

    sensor_ids = [sensor.sensor_id for sensor in scenario.sensors]
    for duplicate in sorted(_duplicates(sensor_ids)):
        errors.append(f"duplicate sensor id: {duplicate}")
    for sensor in scenario.sensors:
        if sensor.room not in room_set:
            errors.append(f"sensor {sensor.sensor_id} references unknown room: {sensor.room}")

    activity_ids = [activity.activity_id for activity in scenario.activities]
    for duplicate in sorted(_duplicates(activity_ids)):
        errors.append(f"duplicate activity id: {duplicate}")

    ordered = sorted(scenario.activities, key=lambda activity: activity.start_minute)
    previous = None
    for activity in ordered:
        if activity.actor_id != scenario.resident.resident_id:
            errors.append(
                f"activity {activity.activity_id} references unknown actor: {activity.actor_id}"
            )
        if activity.destination not in room_set:
            errors.append(
                f"activity {activity.activity_id} references unknown destination: "
                f"{activity.destination}"
            )
        if previous is not None:
            previous_end = previous.start_minute + previous.duration_minutes
            if activity.start_minute < previous_end:
                errors.append(
                    f"activities overlap: {previous.activity_id} and {activity.activity_id}"
                )
        previous = activity

    return errors


def require_valid_scenario(scenario: Scenario) -> None:
    errors = validate_scenario(scenario)
    if errors:
        raise ScenarioValidationError(errors)
