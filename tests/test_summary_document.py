"""The dataset summary: the drawing of the flat, and the page built around it."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.profiling import profile_from_trace_file
from smart_home_sim.summary import (
    ScenarioFacts,
    SummaryInputs,
    render_plan_svg,
    render_summary_html,
)
from smart_home_sim.summary.plan import (
    Wall,
    cut_doorways,
    dwelling_region_ids,
    front_door,
    plan_doors,
    plan_walls,
    polygon_area,
)

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE = PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30"


@pytest.fixture(scope="module")
def home() -> HomeModel:
    return HomeModel.model_validate_json((SOURCE / "home-model.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sensors() -> SensorModel:
    return SensorModel.model_validate_json(
        (SOURCE / "sensor-model.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def inputs(home: HomeModel, sensors: SensorModel) -> SummaryInputs:
    profile = profile_from_trace_file(SOURCE / "execution-trace.json", run_id="run_1")
    return SummaryInputs(
        run_id="run_1",
        seed=42,
        trace_digest=profile.source_trace_semantic_digest,
        profile=profile,
        files=(),
        home=home,
        sensors=sensors,
        scenario=ScenarioFacts(
            title="Three domestic days",
            language="it",
            time_zone="Europe/Rome",
            residents=[
                {
                    "residentId": "resident_mario_rossi",
                    "displayName": "Mario Rossi",
                    "profile": {"age": 72, "mobility": {"walkingSpeedMetersPerSecond": 0.9}},
                }
            ],
        ),
    )


def _band(**overrides: Any) -> dict[str, Any]:
    band = {
        "habitId": "habit_night",
        "label": "Notte",
        "windowStart": "20:30",
        "windowEnd": "06:45",
        "crossesMidnight": True,
        "weekdays": [],
        "dayCount": 153,
        "totalMinutes": 94095.0,
        "composition": [
            {"intent": "sleep", "minutes": 70591.0, "share": 0.75},
            {"intent": "watch_television", "minutes": 2509.0, "share": 0.0267},
        ],
        "unaccountedMinutes": 17105.0,
        "unaccountedShare": 0.1818,
        "dominantIntent": "sleep",
        "effectiveStart": "22:39",
        "effectiveEnd": "06:35",
        "effectiveMinutes": 476.0,
        "effectiveShare": 0.774,
        "dayTypes": [],
    }
    band.update(overrides)
    return band


def _json_model[T: HomeModel | SensorModel](model: type[T], payload: dict[str, Any]) -> T:
    """Build a contract model the way a file does.

    These models validate strictly in memory: a region kind has to be the enum member, not
    the string that spells it, while the same payload read from JSON coerces. Going through
    JSON keeps these fixtures written the way the artifacts on disk are.
    """
    return model.model_validate_json(json.dumps(payload))


def _rectangle(x: float, y: float, width: float, height: float) -> dict[str, Any]:
    return {
        "vertices": [
            {"x": x, "y": y},
            {"x": x + width, "y": y},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y + height},
        ]
    }


def _awkward_home(entrance: str | None = None, anchor: str = "point_living_room") -> HomeModel:
    """A home carrying every shape the drawing has to survive.

    A room with a chamfered corner and a repeated vertex, a cupboard too small to caption, a
    balcony that is part of the flat without being a room, an unreachable attic, a supermarket
    twelve metres away with furniture in it, and a sensor watching a thing that is not there.
    Generated flats produce all of these, and a page that failed on any of them would be a page
    that works only for the examples.
    """
    return _json_model(
        HomeModel,
        {
            "homeId": "awkward",
            "homeVersion": "1.0.0",
            "regions": [
                {
                    "regionId": "living_room",
                    "kind": "room",
                    "boundary": {
                        "vertices": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 5.0, "y": 0.0},
                            # The same corner twice: a zero-length edge, which is not a wall.
                            {"x": 5.0, "y": 0.0},
                            {"x": 5.0, "y": 4.0},
                            {"x": 0.4, "y": 4.0},
                            {"x": 0.0, "y": 3.6},
                        ]
                    },
                },
                {"regionId": "closet", "kind": "room", "boundary": _rectangle(5.0, 0.0, 0.6, 0.6)},
                # Reached through a door and therefore part of the dwelling, room or not.
                {
                    "regionId": "balcony",
                    "kind": "outdoor",
                    "boundary": _rectangle(0.0, 4.0, 5.0, 1.2),
                },
                {
                    "regionId": "attic",
                    "kind": "outdoor",
                    "boundary": _rectangle(0.0, 9.0, 2.0, 2.0),
                },
                {
                    "regionId": "supermarket",
                    "kind": "external",
                    "boundary": _rectangle(20.0, 20.0, 4.0, 4.0),
                },
            ],
            "connections": [
                {
                    "connectionId": "door_balcony",
                    "kind": "doorway",
                    "regionAId": "living_room",
                    "regionBId": "balcony",
                    "portalA": {"x": 2.5, "y": 3.9},
                    "portalB": {"x": 2.5, "y": 4.1},
                    "widthMeters": 0.9,
                },
                {
                    "connectionId": "passage_closet",
                    "kind": "passage",
                    "regionAId": "living_room",
                    "regionBId": "closet",
                    "portalA": {"x": 4.9, "y": 0.3},
                    "portalB": {"x": 5.1, "y": 0.3},
                    "widthMeters": 0.6,
                },
                {
                    "connectionId": "transit_supermarket",
                    "kind": "transit",
                    "regionAId": "living_room",
                    "regionBId": "supermarket",
                    "portalA": {"x": 0.2, "y": 0.2},
                    "portalB": {"x": 21.0, "y": 21.0},
                    "widthMeters": 1.0,
                    "traversalMode": "transport",
                    "distanceMeters": 900.0,
                },
                {
                    "connectionId": "passage_attic",
                    "kind": "passage",
                    "regionAId": "attic",
                    "regionBId": "supermarket",
                    "portalA": {"x": 1.0, "y": 9.9},
                    "portalB": {"x": 21.0, "y": 20.1},
                    "widthMeters": 0.8,
                },
            ],
            "obstacles": [
                {
                    "obstacleId": "obstacle_sofa",
                    "regionId": "living_room",
                    "boundary": _rectangle(0.2, 0.2, 1.8, 0.8),
                },
                {
                    "obstacleId": "obstacle_shelf",
                    "regionId": "supermarket",
                    "boundary": _rectangle(21.0, 21.0, 1.0, 0.4),
                },
            ],
            "interactionPoints": [
                {
                    "interactionPointId": "point_living_room",
                    "regionId": "living_room",
                    "position": {"x": 2.0, "y": 1.5},
                },
                {
                    "interactionPointId": "point_closet",
                    "regionId": "closet",
                    "position": {"x": 5.3, "y": 0.3},
                },
            ],
            "entities": [
                {
                    "entityId": "sofa",
                    "entityType": "sofa",
                    "regionId": "living_room",
                    "interactionPointId": "point_living_room",
                    "capabilities": [{"capability": "seating", "supportedOperations": ["sit"]}],
                },
            ]
            + (
                [
                    {
                        "entityId": "front_door",
                        "entityType": "entrance_door",
                        "regionId": entrance,
                        "interactionPointId": anchor,
                        "capabilities": [
                            {"capability": "access", "supportedOperations": ["leave_home"]}
                        ],
                    }
                ]
                if entrance is not None
                else []
            ),
            "locationBindings": [
                {
                    "scenarioLocationId": "living_room",
                    "regionIds": ["living_room"],
                    "anchorInteractionPointId": "point_living_room",
                }
            ],
        },
    )


def _awkward_sensors() -> SensorModel:
    return _json_model(
        SensorModel,
        {
            "sensorModelId": "awkward_sensors",
            "sensorModelVersion": "1.0.0",
            "sourceBundleId": "bundle",
            "sourceBundleSha256": "0" * 64,
            "seed": 1,
            "regionIds": ["living_room"],
            "entityIds": ["sofa", "not_here"],
            "sensors": [
                {
                    "sensorId": "thermo_living_room",
                    "sensorType": "temperature",
                    "position": {"x": 2.5, "y": 2.0},
                    "regionId": "living_room",
                    "baselineCelsius": 20.0,
                    "sources": [{"entityId": "sofa", "fact": "occupied", "deltaCelsius": 0.5}],
                },
                {
                    # Watching a thing this home does not contain: it belongs to no room, so it is
                    # named in the inventory and left off the drawing.
                    "sensorId": "contact_ghost",
                    "sensorType": "contact",
                    "position": {"x": 9.0, "y": 9.0},
                    "entityId": "not_here",
                },
            ],
        },
    )


def test_the_plan_survives_every_shape_a_generated_flat_produces() -> None:
    home = _awkward_home()
    sensors = _awkward_sensors()

    inside = dwelling_region_ids(home)
    assert inside == {"living_room", "closet", "balcony"}

    svg = render_plan_svg(home, sensors)

    # A passage is an opening with no leaf, so nothing swings across it.
    assert svg.count("door-swing") == 1
    # The supermarket's shelf is not drawn, because the supermarket is not.
    assert svg.count('class="obstacle"') == 1
    # The cupboard is too small to caption without writing over its own walls.
    assert "closet" not in svg
    # A sensor identifier following no convention keeps the name it has.
    assert "thermo living room" in svg
    assert "contact_ghost" not in svg


def test_a_home_with_no_dwelling_says_so_instead_of_drawing_nothing() -> None:
    home = _json_model(
        HomeModel,
        {
            "homeId": "elsewhere",
            "homeVersion": "1.0.0",
            "regions": [
                {
                    "regionId": "supermarket",
                    "kind": "external",
                    "boundary": _rectangle(0.0, 0.0, 4.0, 4.0),
                }
            ],
            "interactionPoints": [
                {
                    "interactionPointId": "point",
                    "regionId": "supermarket",
                    "position": {"x": 1.0, "y": 1.0},
                }
            ],
            "entities": [
                {
                    "entityId": "till",
                    "entityType": "till",
                    "regionId": "supermarket",
                    "interactionPointId": "point",
                    "capabilities": [{"capability": "pay", "supportedOperations": ["pay"]}],
                }
            ],
            "locationBindings": [
                {
                    "scenarioLocationId": "supermarket",
                    "regionIds": ["supermarket"],
                    "anchorInteractionPointId": "point",
                }
            ],
        },
    )

    assert "declares no dwelling to draw" in render_plan_svg(home)


def test_the_front_door_is_drawn_only_where_the_walls_allow_one() -> None:
    """Found by capability, placed on an exterior wall long enough to hold it, or not at all."""
    visible = dwelling_region_ids(_awkward_home())

    # Nothing in the home can be left through.
    assert front_door(_awkward_home(), visible) is None
    # A door whose interaction point was never materialized.
    assert front_door(_awkward_home("living_room", anchor="nowhere"), visible) is None
    # A cupboard has no wall a 90 cm door fits on.
    assert front_door(_awkward_home("closet", anchor="point_closet"), visible) is None

    door = front_door(_awkward_home("living_room"), visible)
    assert door is not None
    assert door.kind == "entrance"


def test_a_wall_with_no_length_is_not_a_wall() -> None:
    """Cutting openings out of the geometry has to tolerate the degenerate pieces feeding it."""
    assert cut_doorways([Wall(1.0, 1.0, 1.0, 1.0, exterior=True)], []) == []


def test_the_plan_draws_the_dwelling_and_leaves_the_supermarket_out(
    home: HomeModel, sensors: SensorModel
) -> None:
    inside = dwelling_region_ids(home)

    assert "kitchen" in inside
    # Reached through the hallway rather than declared a room, and still part of the flat.
    assert "balcony" in inside
    assert "supermarket" not in inside and "outside" not in inside

    svg = render_plan_svg(home, sensors)
    assert svg.startswith('<svg class="plan"')
    assert "kitchen" in svg and "supermarket" not in svg
    # Every deployed sensor of the dwelling is on the drawing, each with its own glyph.
    assert svg.count('class="sensor sensor-') == len(sensors.sensors)
    assert "Front door" in svg


def test_walls_are_told_apart_by_what_stands_behind_them_and_doors_cut_them(
    home: HomeModel,
) -> None:
    visible = dwelling_region_ids(home)
    walls = plan_walls(home, visible)
    doors = plan_doors(home, visible)

    assert any(item.exterior for item in walls), "the flat has an envelope"
    assert any(not item.exterior for item in walls), "and partitions inside it"
    # A partition is walked from both rooms it separates and drawn once.
    assert len(walls) < sum(len(item.boundary.vertices) for item in home.regions)

    cut = cut_doorways(walls, doors)
    total = sum(((w.x2 - w.x1) ** 2 + (w.y2 - w.y1) ** 2) ** 0.5 for w in walls)
    remaining = sum(((w.x2 - w.x1) ** 2 + (w.y2 - w.y1) ** 2) ** 0.5 for w in cut)
    assert remaining < total, "every doorway is a hole in the wall it crosses"

    entrance = front_door(home, visible)
    assert entrance is not None and entrance.kind == "entrance"


def test_a_room_the_model_never_measures_reports_its_own_area(home: HomeModel) -> None:
    kitchen = next(item for item in home.regions if item.region_id == "kitchen")

    assert polygon_area(kitchen.boundary.vertices) == pytest.approx(18.0, abs=0.5)


def test_the_page_states_the_flat_the_sensors_and_the_declared_person(
    inputs: SummaryInputs,
) -> None:
    page = render_summary_html(inputs)

    assert page.startswith("<!doctype html>")
    assert "<title>Three domestic days</title>" in page
    assert "The home" in page and "The sensor field" in page
    # The plan travels inside the page: no request for an image ever leaves it.
    assert 'class="plan"' in page and "http://" not in page.replace(
        "http://www.w3.org", "", 1
    ).replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "<script" not in page
    # The declared traits are rendered as words, not as JSON.
    assert "Walking speed meters per second" in page
    assert "pir_kitchen" in page
    # No outline behind this run, so the page says so rather than showing an empty section.
    assert "declares no habit bands" in page


def test_a_band_says_where_its_activity_actually_runs(inputs: SummaryInputs) -> None:
    page = render_summary_html(
        SummaryInputs(**{**vars(inputs), "habits": {"outlineId": "o", "habits": [_band()]}})
    )

    assert "Notte" in page
    assert "sleep" in page
    assert "actually runs 22:39–06:35" in page
    assert "covering 77.4% of the declared window" in page
    assert "18.2% of the band is time the outline named nothing for" in page


def test_a_band_no_activity_holds_claims_no_boundary(inputs: SummaryInputs) -> None:
    unsettled = _band(dominantIntent="eat_breakfast", effectiveStart=None, effectiveEnd=None)

    page = render_summary_html(
        SummaryInputs(**{**vars(inputs), "habits": {"outlineId": "o", "habits": [unsettled]}})
    )

    # The window is the only boundary the behaviour supports, and inventing a narrower one would
    # publish a target the run never produced.
    bands = page.split("The declared habits", 1)[1].split("The behaviour that actually", 1)[0]
    assert "no stretch of the band is held on most days" in bands
    assert "actually runs" not in bands


def test_a_band_nothing_dominates_reports_that_as_the_finding(inputs: SummaryInputs) -> None:
    """`dominantIntent` is null when no activity holds the band on most days.

    That is a result about the horizon, not a gap in the document, so the page states it rather
    than falling back on the largest slice of a mix that has no winner.
    """
    mixed = _band(dominantIntent=None, effectiveStart=None, effectiveEnd=None, effectiveShare=0.0)

    page = render_summary_html(
        SummaryInputs(**{**vars(inputs), "habits": {"outlineId": "o", "habits": [mixed]}})
    )

    assert "no single activity holds it on most days" in page
    assert "which is itself the finding" in page


def test_the_page_is_built_from_whatever_the_run_actually_carries(inputs: SummaryInputs) -> None:
    """A run without a home model, a sensor field or a scenario still gets a page.

    Older runs and merged horizons do not all carry the same artifacts, and a summary that refused
    to build for them would be a summary nobody could rely on.
    """
    bare = SummaryInputs(
        run_id=inputs.run_id,
        seed=inputs.seed,
        trace_digest=inputs.trace_digest,
        profile=inputs.profile,
        files=(),
    )

    page = render_summary_html(bare)

    assert "carries no home model" in page
    assert "carries no sensor model" in page
    assert "The behaviour that actually happened" in page


def test_the_page_carries_no_clock_reading(inputs: SummaryInputs) -> None:
    """Two renderings of one run are the same bytes, which is what makes an export rebuildable."""
    page = render_summary_html(inputs)

    assert page == render_summary_html(inputs)
    body = page.split("<body>", 1)[1]
    assert not re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d", body), "no generation timestamp"
