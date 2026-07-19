from __future__ import annotations

from typing import Any

from smart_home_sim.validation.service import validate_payload


def move_to_dst_fallback_day(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("2026-10-12", "2026-10-25").replace("+02:00", "+01:00")
    if isinstance(value, list):
        return [move_to_dst_fallback_day(item) for item in value]
    if isinstance(value, dict):
        return {key: move_to_dst_fallback_day(item) for key, item in value.items()}
    return value


def test_valid_offsets_across_daylight_saving_transition(
    valid_payload: dict[str, Any],
) -> None:
    payload = move_to_dst_fallback_day(valid_payload)
    payload["simulationWindow"] = {
        "start": "2026-10-25T00:00:00+02:00",
        "end": "2026-10-26T00:00:00+01:00",
    }
    payload["initialState"]["at"] = "2026-10-25T00:00:00+02:00"

    report = validate_payload(payload)

    assert report.valid, report.model_dump_json(indent=2)


def test_old_summer_offset_is_rejected_after_dst_change(
    valid_payload: dict[str, Any],
) -> None:
    payload = move_to_dst_fallback_day(valid_payload)
    payload["simulationWindow"] = {
        "start": "2026-10-25T00:00:00+02:00",
        "end": "2026-10-26T00:00:00+01:00",
    }
    payload["initialState"]["at"] = "2026-10-25T00:00:00+02:00"
    payload["runtimeEventCandidates"][0]["eligibleWindow"] = {
        "earliest": "2026-10-25T08:30:00+02:00",
        "preferred": "2026-10-25T08:35:00+02:00",
        "latest": "2026-10-25T08:45:00+02:00",
    }

    report = validate_payload(payload)

    assert "TIMEZONE_OFFSET_MISMATCH" in {item.code for item in report.issues}
