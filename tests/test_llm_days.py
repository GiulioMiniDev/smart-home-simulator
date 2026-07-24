from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning import llm_days as ld
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay, HabitOccurrence
from smart_home_sim.hybrid_planning.day_generation import build_day_plan
from smart_home_sim.hybrid_planning.habits import HabitKind, Weekday
from smart_home_sim.hybrid_planning.intents import intent_ids
from smart_home_sim.hybrid_planning.llm_days import (
    LlmDaysResult,
    _entries_from_timeline,
    _parse_week,
    _WeekParseError,
    generate_llm_day_plans,
)
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig
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
            date="2026-08-03", weekday=Weekday.monday, occurrences=[_occ("morning coffee", "07:10")]
        ),
        CalendarDay(
            date="2026-08-04", weekday=Weekday.tuesday, occurrences=[_occ("groceries", "10:30")]
        ),
    ]
    return CadenceCalendar(
        calendar_id="cal",
        persona_id="luigi_bianchi",
        profile_id="luigi_bianchi_profile",
        start_date="2026-08-03",
        end_date="2026-08-04",
        months=1,
        seed=3,
        timezone="Europe/Rome",
        days=days,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def _fixed_client(content: str) -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


_CANNED = json.dumps(
    {
        "days": [
            {
                "date": "2026-08-03",
                "timeline": [
                    {"intent": "eat_breakfast", "around": "07:30", "habit": "morning_coffee"},
                    {"intent": "eat_lunch", "around": "12:30"},
                    {"intent": "watch_television", "around": "21:00"},
                ],
            },
            {
                "date": "2026-08-04",
                "timeline": [
                    {"intent": "eat_breakfast", "around": "08:00"},
                    {"intent": "buy_groceries", "around": "10:30", "habit": "groceries"},
                ],
            },
        ]
    }
)


def test_generate_llm_day_plans_accepts_compiling_days() -> None:
    result = generate_llm_day_plans(_world(), _calendar(), _fixed_client(_CANNED))
    assert result.llm_authored_count == 2
    assert result.fallback_count == 0
    plan = result.day_plans["2026-08-03"]
    intents = [activity.intent for activity in plan.activities]
    assert intents[0] == "wake_up"
    assert intents[-1] == "sleep"
    assert "eat_breakfast" in intents and "watch_television" in intents


def test_generate_llm_day_plans_falls_back_on_bad_output() -> None:
    result = generate_llm_day_plans(_world(), _calendar(), _fixed_client("not json at all"))
    assert result.llm_authored_count == 0
    assert result.fallback_count == 2
    assert set(result.day_plans) == {"2026-08-03", "2026-08-04"}


def test_generate_llm_day_plans_falls_back_when_uncompilable(monkeypatch) -> None:
    import types

    monkeypatch.setattr(
        ld, "compile_scenario", lambda scenario: types.SimpleNamespace(plan=None)
    )
    result = generate_llm_day_plans(_world(), _calendar(), _fixed_client(_CANNED))
    assert result.llm_authored_count == 0


def test_generate_llm_day_plans_empty_slice_raises() -> None:
    with pytest.raises(ValueError):
        generate_llm_day_plans(_world(), _calendar(), _fixed_client(_CANNED), start_index=9)


def test_entries_from_timeline_filters_and_frames() -> None:
    vocabulary = set(intent_ids())
    entries = _entries_from_timeline(
        [
            {"intent": "eat_lunch", "around": "12:00"},
            {"intent": "sleep", "around": "22:00"},
            {"intent": "bogus", "around": "10:00"},
            {"intent": "eat_breakfast", "around": "not-a-time"},
            "not a dict",
            {"intent": "rest_or_nap", "around": "14:00", "habit": "h1"},
        ],
        vocabulary,
    )
    ids = [entry.intent_id for entry in entries]
    assert ids[0] == "wake_up" and ids[-1] == "sleep"
    assert ids[1:3] == ["eat_lunch", "rest_or_nap"]  # sorted by time, junk dropped
    assert entries[2].habit_id == "h1"
    assert _entries_from_timeline("not a list", vocabulary) == []


def test_parse_week_variants() -> None:
    week = _calendar().days
    vocabulary = set(intent_ids())
    parsed = _parse_week(json.loads(_CANNED), week, vocabulary)
    assert set(parsed) == {"2026-08-03", "2026-08-04"}
    # top-level array, and non-dict items skipped
    top_level = [
        "junk",
        {"date": "2026-08-03", "timeline": [{"intent": "eat_lunch", "around": "12:00"}]},
    ]
    assert set(_parse_week(top_level, week, vocabulary)) == {"2026-08-03"}
    with pytest.raises(_WeekParseError):
        _parse_week(42, week, vocabulary)
    with pytest.raises(_WeekParseError):
        _parse_week({"days": "not-a-list"}, week, vocabulary)
    with pytest.raises(_WeekParseError):
        _parse_week({"days": [{"date": "1999-01-01", "timeline": []}]}, week, vocabulary)


def test_cli_generate_horizon_use_llm(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from smart_home_sim.hybrid_planning.package_authoring import build_reference_package

    world = _world()
    calendar = _calendar()
    actor_id = world.residents[0].resident_id
    plans = {
        day.date: build_day_plan(day, timezone=world.time_zone, actor_id=actor_id)
        for day in calendar.days
    }

    def fake_llm(world_arg, calendar_arg, client, *, start_index, days, seed):
        return LlmDaysResult(day_plans=plans, llm_authored_count=2, fallback_count=0)

    monkeypatch.setattr(cli, "generate_llm_day_plans", fake_llm)
    package = build_reference_package(_persona(), world, now=_NOW)
    world_path = tmp_path / "world.json"
    package_path = tmp_path / "package.json"
    calendar_path = tmp_path / "calendar.json"
    world_path.write_text(world.model_dump_json(by_alias=True), encoding="utf-8")
    package_path.write_text(package.model_dump_json(by_alias=True), encoding="utf-8")
    calendar_path.write_text(calendar.model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "generate-horizon",
            str(world_path),
            str(package_path),
            str(calendar_path),
            "-o",
            str(tmp_path / "h"),
            "--use-llm",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "LLM-authored" in result.output


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
