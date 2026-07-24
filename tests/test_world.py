from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.domain.models import (
    Activity,
    AuthorType,
    DateTimeWindow,
    DayContext,
    DayPlan,
    DurationRange,
    Provenance,
    Scenario,
    SimulationWindow,
)
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import (
    HOME_COMPOSITE_ID,
    STANDARD_RESOURCES,
    STANDARD_ROOMS,
    PlanningWorld,
    assemble_scenario,
    build_planning_world,
)

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
_TZ = ZoneInfo("Europe/Rome")


def _persona() -> Persona:
    return Persona(
        persona_id="luigi_bianchi",
        name="Luigi Bianchi",
        age=72,
        sex="M",
        occupation="retired railway worker",
        household="lives alone",
        health=["arthritis"],
        city="Bologna",
        timezone="Europe/Rome",
        notes="quiet",
        routine_anchors=["morning walk", "evening tea"],
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


def test_build_world_standard_apartment() -> None:
    world = build_planning_world(_persona(), now=_NOW)
    room_ids = [loc.location_id for loc in world.locations if loc.location_id in STANDARD_ROOMS]
    assert room_ids == list(STANDARD_ROOMS)
    assert len(world.locations) == len(STANDARD_ROOMS) + 2  # rooms + outdoors + composite home
    composite = next(loc for loc in world.locations if loc.location_id == HOME_COMPOSITE_ID)
    assert composite.member_location_ids == list(STANDARD_ROOMS)
    assert len(world.resources) == len(STANDARD_RESOURCES)
    primitive = {loc.location_id for loc in world.locations if not loc.member_location_ids}
    assert all(resource.location_id in primitive for resource in world.resources)
    assert world.residents[0].resident_id == "luigi_bianchi"
    assert world.residents[0].display_name == "Luigi Bianchi"
    assert world.external_people[0].relationship_to_residents == {"luigi_bianchi": "family"}
    assert world.scenario_id == "luigi_bianchi_scenario"
    assert world.home_model.reference_id == "luigi_bianchi_home"
    assert world.time_zone == "Europe/Rome"
    assert world.provenance.author_type is AuthorType.rule_generator
    assert all(fact == {"available": True} for fact in world.resource_facts.values())


def test_build_world_is_deterministic() -> None:
    first = build_planning_world(_persona(), now=_NOW)
    second = build_planning_world(_persona(), now=_NOW)
    assert first.model_dump_json() == second.model_dump_json()


def test_world_rejects_unknown_resource_location() -> None:
    data = build_planning_world(_persona(), now=_NOW).model_dump()
    data["resources"][0]["location_id"] = "nowhere"
    with pytest.raises(ValueError, match="unknown location"):
        PlanningWorld.model_validate(data)


def test_world_rejects_unknown_composite_member() -> None:
    data = build_planning_world(_persona(), now=_NOW).model_dump()
    composite = next(loc for loc in data["locations"] if loc["location_id"] == HOME_COMPOSITE_ID)
    composite["member_location_ids"] = ["ghost_room"]
    with pytest.raises(ValueError, match="unknown member"):
        PlanningWorld.model_validate(data)


def test_world_rejects_unknown_placement_location() -> None:
    data = build_planning_world(_persona(), now=_NOW).model_dump()
    data["resident_placements"][0]["location_id"] = "nowhere"
    with pytest.raises(ValueError, match="unknown location"):
        PlanningWorld.model_validate(data)


def _probe_day() -> DayPlan:
    activity = Activity(
        activity_id="a1",
        actor_id="luigi_bianchi",
        intent="rest",
        location_ids=["bedroom"],
        start_window=DateTimeWindow(
            earliest=datetime(2026, 8, 3, 8, 0, tzinfo=_TZ),
            preferred=datetime(2026, 8, 3, 8, 0, tzinfo=_TZ),
            latest=datetime(2026, 8, 3, 8, 0, tzinfo=_TZ),
        ),
        duration=DurationRange(minimum_minutes=30, preferred_minutes=30, maximum_minutes=30),
    )
    return DayPlan(
        date=date(2026, 8, 3),
        context=DayContext(day_type="working_day"),
        activities=[activity],
    )


def test_assemble_scenario_produces_valid_scenario() -> None:
    world = build_planning_world(_persona(), now=_NOW)
    window = SimulationWindow(
        start=datetime(2026, 8, 3, 0, 0, tzinfo=_TZ),
        end=datetime(2026, 8, 4, 0, 0, tzinfo=_TZ),
    )
    scenario = assemble_scenario(world, days=[_probe_day()], window=window)
    assert scenario.scenario_id == "luigi_bianchi_scenario"
    assert scenario.initial_state.at == window.start
    assert len(scenario.days) == 1
    assert scenario.model_references.home_model.reference_id == "luigi_bianchi_home"
    # round-trips through the frozen scenario contract
    reloaded = Scenario.model_validate_json(scenario.model_dump_json())
    assert reloaded.scenario_id == scenario.scenario_id


def test_cli_build_world_writes_file(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    output = tmp_path / "world.json"
    result = runner.invoke(cli.app, ["build-planning-world", str(persona_path), "-o", str(output)])
    assert result.exit_code == 0, result.output
    world = json.loads(output.read_text(encoding="utf-8"))
    assert world["documentType"] == "planning_world"
    assert world["scenarioId"] == "luigi_bianchi_scenario"


def test_cli_build_world_rejects_bad_persona(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text("{broken}", encoding="utf-8")
    result = runner.invoke(
        cli.app, ["build-planning-world", str(persona_path), "-o", str(tmp_path / "w.json")]
    )
    assert result.exit_code == 2
    assert "Cannot load persona" in result.output


def test_cli_build_world_rejects_overwriting_persona(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app, ["build-planning-world", str(persona_path), "-o", str(persona_path)]
    )
    assert result.exit_code != 0
