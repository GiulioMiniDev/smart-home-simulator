from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay, HabitOccurrence
from smart_home_sim.hybrid_planning.day_generation import (
    DEFAULT_INTENT,
    build_day_plan,
    build_day_scenario,
    build_day_scenarios,
    habit_to_intent,
)
from smart_home_sim.hybrid_planning.habits import HabitKind, Weekday
from smart_home_sim.hybrid_planning.intents import intent_ids, intent_spec
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import build_planning_world

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _world():
    persona = Persona(
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
    return build_planning_world(persona, now=_NOW)


def _occ(label: str, target: str, kind: HabitKind = HabitKind.anchor) -> HabitOccurrence:
    return HabitOccurrence(
        habit_id=label.replace(" ", "_"),
        label=label,
        kind=kind,
        target_time=target,
        window_start="06:00",
        window_end="22:00",
    )


def _day(date_str: str, weekday: Weekday, occurrences: list[HabitOccurrence]) -> CalendarDay:
    return CalendarDay(date=date_str, weekday=weekday, occurrences=occurrences)


def _calendar(days: list[CalendarDay]) -> CadenceCalendar:
    return CadenceCalendar(
        calendar_id="cal",
        persona_id="luigi_bianchi",
        profile_id="luigi_bianchi_profile",
        start_date=days[0].date,
        end_date=days[-1].date,
        months=1,
        seed=1,
        timezone="Europe/Rome",
        days=days,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def test_habit_to_intent_keyword_matches() -> None:
    assert habit_to_intent("morning coffee") == "eat_breakfast"
    assert habit_to_intent("blood-pressure pill") == "take_morning_medication"
    assert habit_to_intent("evening walk") == "evening_walk"
    assert habit_to_intent("weekly groceries") == "buy_groceries"
    assert habit_to_intent("watch the news") == "watch_television"
    assert habit_to_intent("something idiosyncratic") == DEFAULT_INTENT


def test_build_day_plan_scaffolds_wake_and_sleep() -> None:
    day = _day(
        "2026-08-03",
        Weekday.monday,
        [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
    )
    plan = build_day_plan(day, timezone="Europe/Rome", actor_id="luigi_bianchi")
    intents = [activity.intent for activity in plan.activities]
    assert intents[0] == "wake_up"
    assert intents[-1] == "sleep"
    assert intents[1:3] == ["eat_breakfast", "take_morning_medication"]
    assert len(plan.activities) == 4
    sleep = plan.activities[-1]
    assert sleep.allow_boundary_truncation and not sleep.mandatory
    assert plan.activities[1].location_ids == [intent_spec("eat_breakfast").default_location]
    assert plan.activities[1].labels == ["habit:morning_coffee"]


def test_build_day_scenario_uses_vocabulary_intents() -> None:
    day = _day("2026-08-03", Weekday.monday, [_occ("groceries", "10:30", HabitKind.contextual)])
    scenario = build_day_scenario(_world(), day)
    assert scenario.scenario_id == "luigi_bianchi_scenario"
    assert len(scenario.days) == 1
    vocabulary = set(intent_ids())
    assert all(activity.intent in vocabulary for activity in scenario.days[0].activities)


def test_build_day_scenarios_slice_and_empty() -> None:
    calendar = _calendar(
        [
            _day("2026-08-03", Weekday.monday, [_occ("coffee", "07:10")]),
            _day("2026-08-04", Weekday.tuesday, [_occ("lunch", "12:30")]),
        ]
    )
    scenarios = build_day_scenarios(_world(), calendar)
    assert len(scenarios) == 2
    one = build_day_scenarios(_world(), calendar, start_index=0, days=1)
    assert one[0].days[0].date.isoformat() == "2026-08-03"
    with pytest.raises(ValueError):
        build_day_scenarios(_world(), calendar, start_index=5)


def test_generated_day_compiles() -> None:
    day = _day(
        "2026-08-03",
        Weekday.monday,
        [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00"), _occ("walk", "17:00")],
    )
    scenario = build_day_scenario(_world(), day)
    result = compile_scenario(scenario)
    assert result.plan is not None, [i.message for i in result.report.issues]


def test_cli_generate_days_writes_scenarios(tmp_path) -> None:
    calendar = _calendar(
        [
            _day("2026-08-03", Weekday.monday, [_occ("coffee", "07:10")]),
            _day("2026-08-04", Weekday.tuesday, [_occ("dinner", "19:30")]),
        ]
    )
    world_path = tmp_path / "world.json"
    calendar_path = tmp_path / "calendar.json"
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    calendar_path.write_text(calendar.model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "days"
    result = runner.invoke(
        cli.app,
        ["generate-days", str(world_path), str(calendar_path), "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    written = sorted(p.name for p in out.glob("*.scenario.json"))
    assert written == ["day-2026-08-03.scenario.json", "day-2026-08-04.scenario.json"]
    scenario = json.loads((out / written[0]).read_text(encoding="utf-8"))
    assert scenario["documentType"] == "life_scenario"


def test_cli_generate_days_rejects_bad_input(tmp_path) -> None:
    world_path = tmp_path / "world.json"
    world_path.write_text("{broken}", encoding="utf-8")
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["generate-days", str(world_path), str(calendar_path), "-o", str(tmp_path / "days")],
    )
    assert result.exit_code == 2
    assert "Cannot load inputs" in result.output
