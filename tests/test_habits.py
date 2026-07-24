from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.habits import (
    BehavioralProfile,
    CadencePeriod,
    Habit,
    HabitCadence,
    HabitKind,
    HabitsGenerationError,
    Weekday,
    _assemble_profile,
    _build_cadence,
    _coerce_kind,
    _coerce_weekdays,
    _normalise_habits,
    generate_habits,
    validate_portfolio,
)
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig, LMStudioError
from smart_home_sim.hybrid_planning.persona import Persona

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _client(*payloads: object) -> LMStudioClient:
    responses = [p if isinstance(p, str) else json.dumps(p) for p in payloads] or ["{}"]
    state = {"i": 0}

    def transport(url: str, body: bytes, timeout: float) -> str:
        index = min(state["i"], len(responses) - 1)
        state["i"] += 1
        message = {"content": responses[index]}
        envelope = {"choices": [{"message": message, "finish_reason": "stop"}]}
        return json.dumps(envelope)

    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


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
        provenance=Provenance(
            author_type=AuthorType.external_llm,
            generator_name="g",
            generator_version="1",
            model_name="m",
            prompt_template_version="p",
            generated_at=_NOW,
        ),
    )


def _balanced(**extra: object) -> dict[str, object]:
    habits = [
        {
            "label": "morning coffee",
            "kind": "anchor",
            "frequency": "daily",
            "time_band": "early_morning",
        },
        {"label": "evening pill", "kind": "anchor", "frequency": "daily", "time_band": "evening"},
        {"label": "morning walk", "kind": "anchor", "frequency": "daily", "time_band": "morning"},
        {
            "label": "groceries",
            "kind": "contextual",
            "frequency": "weekly",
            "time_band": "morning",
            "weekdays": ["Tue", "Fri"],
        },
        {"label": "laundry", "kind": "contextual", "frequency": "weekly", "time_band": "afternoon"},
        {
            "label": "call friend",
            "kind": "optional",
            "frequency": "few_times_week",
            "time_band": "evening",
            "note": "keeps in touch",
        },
        {"label": "cinema", "kind": "optional", "frequency": "biweekly", "time_band": "evening"},
        {"label": "doctor visit", "kind": "rare", "frequency": "monthly", "time_band": "morning"},
    ]
    payload: dict[str, object] = {"habits": habits}
    payload.update(extra)
    return payload


def _unbalanced_only_anchor() -> dict[str, object]:
    return {
        "habits": [
            {"label": f"anchor {i}", "kind": "anchor", "frequency": "daily", "time_band": "morning"}
            for i in range(8)
        ]
    }


def test_generate_habits_happy_path() -> None:
    result = generate_habits(_persona(), _client(_balanced()), now=_NOW)
    profile = result.profile
    assert result.repair_attempts == 0
    assert profile.persona_id == "luigi_bianchi"
    assert profile.profile_id == "luigi_bianchi_profile"
    assert len(profile.habits) == 8
    by_label = {habit.label: habit for habit in profile.habits}
    coffee = by_label["morning coffee"]
    assert coffee.cadence.period is CadencePeriod.day
    assert coffee.cadence.window_start == "06:00"
    assert coffee.mining_difficulty == "easy"
    groceries = by_label["groceries"]
    assert groceries.cadence.weekdays == [Weekday.tuesday, Weekday.friday]
    assert groceries.cadence.times_per_period == 2
    assert by_label["call friend"].cadence.times_per_period == 3
    assert by_label["cinema"].cadence.every_n_periods == 2
    assert by_label["doctor visit"].mining_difficulty == "hard"
    assert by_label["call friend"].note == "keeps in touch"


def test_generate_habits_repairs_unbalanced_then_succeeds() -> None:
    client = _client(_unbalanced_only_anchor(), _balanced())
    result = generate_habits(_persona(), client, now=_NOW)
    assert result.repair_attempts == 1
    assert len(result.profile.habits) == 8


def test_generate_habits_fails_after_exhausting_repairs() -> None:
    client = _client(_unbalanced_only_anchor(), _unbalanced_only_anchor())
    with pytest.raises(HabitsGenerationError):
        generate_habits(_persona(), client, max_repairs=1, now=_NOW)


def test_generate_habits_fails_immediately_when_no_repairs_allowed() -> None:
    with pytest.raises(HabitsGenerationError):
        generate_habits(_persona(), _client(_unbalanced_only_anchor()), max_repairs=0, now=_NOW)


def test_validate_portfolio_reports_missing_kinds() -> None:
    habits = [_habit(f"a{i}", HabitKind.anchor) for i in range(3)]
    issues = validate_portfolio(habits)
    assert any("total habits" in issue for issue in issues)
    assert any("contextual" in issue for issue in issues)
    assert any("rare" in issue for issue in issues)


def test_normalise_accepts_top_level_list_and_singular_key() -> None:
    entry = {"label": "walk", "kind": "anchor", "frequency": "daily", "time_band": "morning"}
    assert _normalise_habits([entry])[0].label == "walk"
    assert _normalise_habits({"habit": [entry]})[0].label == "walk"


def test_normalise_skips_bad_entries_and_dedupes_ids() -> None:
    habits = _normalise_habits(
        [
            "not a dict",
            {"kind": "anchor"},
            {"label": "  "},
            {"label": "walk", "kind": "anchor", "frequency": "daily", "time_band": "morning"},
            {"label": "walk", "kind": "anchor", "frequency": "daily", "time_band": "morning"},
            {"label": "!!!", "kind": "optional", "frequency": "weekly", "time_band": "night"},
        ]
    )
    ids = [habit.habit_id for habit in habits]
    assert ids == ["walk", "walk_2", "habit"]


def test_normalise_skips_habit_when_construction_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import smart_home_sim.hybrid_planning.habits as habits_mod

    def boom(**kwargs: object) -> Habit:
        raise ValueError("forced")

    monkeypatch.setattr(habits_mod, "Habit", boom)
    entry = {"label": "walk", "kind": "anchor", "frequency": "daily", "time_band": "morning"}
    with pytest.raises(HabitsGenerationError):
        _normalise_habits([entry])


def test_normalise_rejects_non_object() -> None:
    with pytest.raises(HabitsGenerationError):
        _normalise_habits(42)


def test_normalise_rejects_empty_array() -> None:
    with pytest.raises(HabitsGenerationError):
        _normalise_habits({"habits": []})


def test_normalise_rejects_all_invalid_entries() -> None:
    with pytest.raises(HabitsGenerationError):
        _normalise_habits(["x", {"kind": "anchor"}])


def test_build_cadence_defaults_and_mappings() -> None:
    rare = _build_cadence("rarely", "night", None)
    assert rare.period is CadencePeriod.month
    assert rare.every_n_periods == 3
    assert rare.window_start == "21:00"

    fallback = _build_cadence("sometimes", "dawn", None)
    assert fallback.period is CadencePeriod.week
    assert fallback.window_start == "08:00"

    weekly = _build_cadence("weekly", "morning", ["Tue", "tue", "garbage", 5])
    assert weekly.weekdays == [Weekday.tuesday]
    assert weekly.times_per_period == 1


def test_coerce_kind_and_weekdays_edge_cases() -> None:
    assert _coerce_kind("Rare") is HabitKind.rare
    assert _coerce_kind("nonsense") is HabitKind.optional
    assert _coerce_kind(7) is HabitKind.optional
    assert _coerce_weekdays("monday") == []


def test_cadence_rejects_bad_window() -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        HabitCadence(
            period=CadencePeriod.day, times_per_period=1, window_start="25:00", window_end="26:00"
        )
    with pytest.raises(ValueError, match="before end"):
        HabitCadence(
            period=CadencePeriod.day, times_per_period=1, window_start="10:00", window_end="09:00"
        )


def _habit(habit_id: str, kind: HabitKind = HabitKind.anchor) -> Habit:
    return Habit(
        habit_id=habit_id,
        label=habit_id,
        kind=kind,
        cadence=HabitCadence(
            period=CadencePeriod.day, times_per_period=1, window_start="07:00", window_end="08:00"
        ),
    )


def test_profile_rejects_duplicate_habit_ids() -> None:
    habits = [_habit(f"h{i}") for i in range(7)] + [_habit("h0")]
    with pytest.raises(ValueError, match="unique"):
        BehavioralProfile(
            profile_id="p",
            persona_id="q",
            habits=habits,
            provenance=Provenance(author_type=AuthorType.human, generated_at=_NOW),
        )


def test_assemble_profile_wraps_validation_error() -> None:
    habits = [_habit(f"h{i}") for i in range(7)] + [_habit("h0")]
    with pytest.raises(HabitsGenerationError):
        _assemble_profile(_persona(), habits, client=_client(), seed=None, now=_NOW)


def test_cli_generate_habits_writes_profile(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def fake_generate(persona, client, *, max_repairs, seed):
        return generate_habits(persona, _client(_balanced()), now=_NOW)

    monkeypatch.setattr(cli, "generate_habits", fake_generate)
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    output = tmp_path / "profile.json"
    result = runner.invoke(cli.app, ["generate-habits", str(persona_path), "-o", str(output)])
    assert result.exit_code == 0, result.output
    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["personaId"] == "luigi_bianchi"
    assert len(profile["habits"]) == 8


def test_cli_generate_habits_rejects_bad_persona(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text("{not json}", encoding="utf-8")
    result = runner.invoke(
        cli.app, ["generate-habits", str(persona_path), "-o", str(tmp_path / "p.json")]
    )
    assert result.exit_code == 2
    assert "Cannot load persona" in result.output


def test_cli_generate_habits_reports_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_generate(*args, **kwargs):
        raise HabitsGenerationError("unbalanced")

    monkeypatch.setattr(cli, "generate_habits", fake_generate)
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app, ["generate-habits", str(persona_path), "-o", str(tmp_path / "p.json")]
    )
    assert result.exit_code == 1
    assert "Habit generation failed" in result.output


def test_cli_generate_habits_reports_lmstudio_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_generate(*args, **kwargs):
        raise LMStudioError("down")

    monkeypatch.setattr(cli, "generate_habits", fake_generate)
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app, ["generate-habits", str(persona_path), "-o", str(tmp_path / "p.json")]
    )
    assert result.exit_code == 2
    assert "LM Studio generation failed" in result.output


def test_cli_generate_habits_rejects_colliding_outputs(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    output = tmp_path / "profile.json"
    result = runner.invoke(
        cli.app,
        [
            "generate-habits",
            str(persona_path),
            "-o",
            str(output),
            "--exchange-output",
            str(output),
        ],
    )
    assert result.exit_code != 0
