from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay, HabitOccurrence
from smart_home_sim.hybrid_planning.habits import HabitKind, Weekday
from smart_home_sim.hybrid_planning.horizon import HorizonError, build_horizon
from smart_home_sim.hybrid_planning.package_authoring import build_reference_package
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import PlanningWorld, build_planning_world

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _persona() -> Persona:
    return Persona(
        persona_id="luigi_bianchi",
        name="Luigi Bianchi",
        age=72,
        sex="M",
        occupation="retired",
        household="lives alone",
        health=["arthritis"],
        city="Bologna",
        timezone="Europe/Rome",
        notes="quiet",
        routine_anchors=["morning walk", "evening tea"],
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


def _world() -> PlanningWorld:
    return build_planning_world(_persona(), now=_NOW)


def _occ(label: str, target: str) -> HabitOccurrence:
    return HabitOccurrence(
        habit_id=label.replace(" ", "_"),
        label=label,
        kind=HabitKind.anchor,
        target_time=target,
        window_start="06:00",
        window_end="22:00",
    )


def _calendar() -> CadenceCalendar:
    days = [
        CalendarDay(
            date="2026-08-03",
            weekday=Weekday.monday,
            occurrences=[_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
        ),
        CalendarDay(
            date="2026-08-04",
            weekday=Weekday.tuesday,
            occurrences=[_occ("groceries", "10:30")],
        ),
    ]
    return CadenceCalendar(
        calendar_id="cal",
        persona_id="luigi_bianchi",
        profile_id="luigi_bianchi_profile",
        start_date="2026-08-03",
        end_date="2026-08-04",
        months=1,
        seed=7,
        timezone="Europe/Rome",
        days=days,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def _package():
    return build_reference_package(_persona(), _world(), now=_NOW)


def test_build_horizon_writes_manifest_and_bundles(tmp_path) -> None:
    result = build_horizon(_world(), _package(), _calendar(), tmp_path)
    assert result.day_count == 2
    assert result.failed_days == []
    assert (tmp_path / "home.json").exists()
    assert (tmp_path / "package.json").exists()
    assert result.trace_path is not None and result.trace_path.exists()
    trace = json.loads((tmp_path / "planned-habit-trace.json").read_text(encoding="utf-8"))
    assert trace["documentType"] == "planned_habit_trace"
    assert len(trace["entries"]) == 3
    manifest = json.loads((tmp_path / "batch-manifest.json").read_text(encoding="utf-8"))
    assert [run["runId"] for run in manifest["runs"]] == ["day-2026-08-03", "day-2026-08-04"]
    for run in manifest["runs"]:
        assert (tmp_path / run["bundlePath"]).exists()
        assert run["seed"] == 7


def test_build_horizon_home_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import types

    import smart_home_sim.hybrid_planning.horizon as hz

    monkeypatch.setattr(
        hz, "generate_home", lambda scenario, package: types.SimpleNamespace(home=None)
    )
    with pytest.raises(HorizonError, match="home generation failed"):
        build_horizon(_world(), _package(), _calendar(), tmp_path)


def test_build_horizon_skips_uncompilable_days(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import types

    import smart_home_sim.hybrid_planning.horizon as hz

    monkeypatch.setattr(hz, "compile_scenario", lambda scenario: types.SimpleNamespace(plan=None))
    with pytest.raises(HorizonError, match="no simulatable days"):
        build_horizon(_world(), _package(), _calendar(), tmp_path)


def test_build_horizon_skips_unbindable_days(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import types

    import smart_home_sim.hybrid_planning.horizon as hz

    monkeypatch.setattr(
        hz, "build_bundle_files", lambda *paths: types.SimpleNamespace(bundle=None)
    )
    with pytest.raises(HorizonError, match="no simulatable days"):
        build_horizon(_world(), _package(), _calendar(), tmp_path)


def test_build_horizon_slice_and_empty(tmp_path) -> None:
    result = build_horizon(_world(), _package(), _calendar(), tmp_path, start_index=1, days=1)
    assert result.day_count == 1
    with pytest.raises(HorizonError):
        build_horizon(_world(), _package(), _calendar(), tmp_path, start_index=9)


def test_cli_generate_horizon(tmp_path) -> None:
    world_path = tmp_path / "world.json"
    package_path = tmp_path / "package.json"
    calendar_path = tmp_path / "calendar.json"
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    package_path.write_text(_package().model_dump_json(by_alias=True), encoding="utf-8")
    calendar_path.write_text(_calendar().model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "horizon"
    result = runner.invoke(
        cli.app,
        [
            "generate-horizon",
            str(world_path),
            str(package_path),
            str(calendar_path),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "simulate-batch" in result.output
    assert (out / "batch-manifest.json").exists()


def test_cli_generate_horizon_rejects_bad_input(tmp_path) -> None:
    world_path = tmp_path / "world.json"
    world_path.write_text("{broken}", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "generate-horizon",
            str(world_path),
            str(tmp_path / "p.json"),
            str(tmp_path / "c.json"),
            "-o",
            str(tmp_path / "h"),
        ],
    )
    assert result.exit_code == 2
    assert "Cannot load inputs" in result.output
