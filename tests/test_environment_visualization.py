from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.build_environment_visualization import (
    OUTPUT_PATH,
    RESOURCE_PLACEMENTS,
    build_visualization_data,
    render_visualization,
)


def test_visualization_is_complete_faithful_and_reproducible() -> None:
    data = build_visualization_data()
    rendered = render_visualization(data)

    assert data["summary"] == {
        "domesticRegionCount": 7,
        "externalRegionCount": 7,
        "domesticEntityCount": 6,
        "externalEntityCount": 7,
        "resourceCount": 9,
        "obstacleCount": 4,
        "connectionCount": 13,
        "localConnectionCount": 6,
        "actionBindingCount": 766,
        "routeCheckCount": 441,
        "visualizedRouteCount": 49,
    }
    assert {item["id"] for item in data["resources"]} == set(RESOURCE_PLACEMENTS)
    assert {item["id"] for item in data["entities"]} == {
        "bedroom_storage",
        "bathroom_fixture",
        "entrance_access",
        "kitchen_workstation",
        "living_room_media",
        "balcony_utility",
    }
    assert {item["id"] for item in data["obstacles"]} == {
        "bedroom_bed",
        "bathroom_cabinet",
        "kitchen_island",
        "living_room_table",
    }
    assert "hallway_storage" not in rendered
    assert "entrance_hub" not in rendered
    assert "<iframe" not in rendered
    assert "https://unpkg.com" not in rendered
    assert rendered == render_visualization(build_visualization_data())
    assert OUTPUT_PATH.read_text(encoding="utf-8") == rendered


def test_visualization_contains_a_symbol_for_every_bound_resource_type() -> None:
    data = build_visualization_data()
    rendered = render_visualization(data)

    for resource_type in {item["type"] for item in data["resources"]}:
        assert f'id="sym-{resource_type}"' in rendered
    for resource in data["resources"]:
        assert resource["id"] in rendered
        assert resource["entityId"] in rendered


def test_visualization_rejects_a_stale_environment_report(tmp_path: Path) -> None:
    report = json.loads(
        Path("examples/bundles/mario_week.environment-report.json").read_text(encoding="utf-8")
    )
    report["homeSha256"] = "0" * 64
    report_path = tmp_path / "stale-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="different home digests"):
        build_visualization_data(report_path=report_path)


def test_visualization_rejects_missing_resource_placement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(RESOURCE_PLACEMENTS, "bed_01")

    with pytest.raises(ValueError, match="exactly cover"):
        build_visualization_data()
