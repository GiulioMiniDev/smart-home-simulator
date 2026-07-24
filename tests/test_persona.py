from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig, LMStudioError
from smart_home_sim.hybrid_planning.persona import (
    MAX_ROUTINE_ANCHORS,
    PersonaGenerationError,
    generate_persona,
)

runner = CliRunner()

_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _client(payload: object, *, model: str = "qwen2.5-coder-7b-instruct") -> LMStudioClient:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    envelope = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}

    def transport(url: str, body: bytes, timeout: float) -> str:
        return json.dumps(envelope)

    return LMStudioClient(LMStudioConfig(model=model), transport=transport)


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Elena Bruni",
        "age": 72,
        "sex": "female",
        "occupation": "retired teacher",
        "household": "lives alone",
        "health": ["arthritis", "hypertension"],
        "city": "Bologna",
        "notes": "early riser, routine-driven",
        "routine_anchors": ["morning coffee", "evening pill", "afternoon rest"],
    }
    payload.update(overrides)
    return payload


def test_generate_persona_happy_path() -> None:
    result = generate_persona("elderly woman living alone", _client(_valid_payload()), now=_NOW)
    persona = result.persona
    assert persona.persona_id == "elena_bruni"
    assert persona.name == "Elena Bruni"
    assert persona.age == 72
    assert persona.sex == "F"
    assert persona.health == ["arthritis", "hypertension"]
    assert persona.timezone == "Europe/Rome"
    assert persona.routine_anchors == ["morning coffee", "evening pill", "afternoon rest"]
    assert persona.provenance.model_name == "qwen2.5-coder-7b-instruct"
    assert persona.provenance.generated_at == _NOW
    assert persona.provenance.parameters["seed"] is None


def test_generate_persona_coerces_scalar_health_and_float_age() -> None:
    payload = _valid_payload(health="diabetes", age=68.0, sex="unknown")
    persona = generate_persona("brief", _client(payload), now=_NOW).persona
    assert persona.health == ["diabetes"]
    assert persona.age == 68
    assert persona.sex == "X"


def test_generate_persona_caps_routine_anchors() -> None:
    payload = _valid_payload(routine_anchors=["a", "b", "c", "d", "e"])
    persona = generate_persona("brief", _client(payload), now=_NOW).persona
    assert persona.routine_anchors == ["a", "b", "c"]
    assert len(persona.routine_anchors) == MAX_ROUTINE_ANCHORS


def test_generate_persona_fills_defaults_for_missing_optionals() -> None:
    payload = {"name": "Mo", "age": 40, "sex": "M", "routine_anchors": ["walk"]}
    persona = generate_persona("brief", _client(payload), now=_NOW).persona
    assert persona.occupation == "unspecified"
    assert persona.household == "unspecified"
    assert persona.city == "unspecified"
    assert persona.notes == ""
    assert persona.health == []


def test_generate_persona_rejects_empty_brief() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("   ", _client(_valid_payload()), now=_NOW)


def test_generate_persona_rejects_non_object() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client([1, 2, 3]), now=_NOW)


def test_generate_persona_requires_name() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client(_valid_payload(name="  ")), now=_NOW)


def test_generate_persona_requires_an_anchor() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client(_valid_payload(routine_anchors=[])), now=_NOW)


def test_generate_persona_rejects_non_integer_age() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client(_valid_payload(age="old")), now=_NOW)


def test_generate_persona_rejects_out_of_range_age() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client(_valid_payload(age=999)), now=_NOW)


def test_generate_persona_coerces_digit_string_age_and_explicit_sex() -> None:
    payload = _valid_payload(age="70", sex="X", health=5)
    persona = generate_persona("brief", _client(payload), now=_NOW).persona
    assert persona.age == 70
    assert persona.sex == "X"
    assert persona.health == []


def test_generate_persona_rejects_boolean_age() -> None:
    with pytest.raises(PersonaGenerationError):
        generate_persona("brief", _client(_valid_payload(age=True)), now=_NOW)


def test_slug_falls_back_when_name_has_no_alphanumerics() -> None:
    persona = generate_persona("brief", _client(_valid_payload(name="!!!")), now=_NOW).persona
    assert persona.persona_id == "persona"


def test_cli_generate_persona_writes_files(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def fake_generate(brief, client, *, timezone, seed):
        return generate_persona(brief, _client(_valid_payload()), timezone=timezone, now=_NOW)

    monkeypatch.setattr(cli, "generate_persona", fake_generate)
    output = tmp_path / "persona.json"
    exchange = tmp_path / "exchange.json"
    result = runner.invoke(
        cli.app,
        [
            "generate-persona",
            "an elderly woman",
            "-o",
            str(output),
            "--exchange-output",
            str(exchange),
        ],
    )
    assert result.exit_code == 0, result.output
    persona = json.loads(output.read_text(encoding="utf-8"))
    assert persona["personaId"] == "elena_bruni"
    assert json.loads(exchange.read_text(encoding="utf-8"))["request"]["model"]


def test_cli_generate_persona_reports_lmstudio_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_generate(*args, **kwargs):
        raise LMStudioError("endpoint down")

    monkeypatch.setattr(cli, "generate_persona", fake_generate)
    result = runner.invoke(
        cli.app, ["generate-persona", "brief", "-o", str(tmp_path / "p.json")]
    )
    assert result.exit_code == 2
    assert "LM Studio generation failed" in result.output


def test_cli_generate_persona_reports_generation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_generate(*args, **kwargs):
        raise PersonaGenerationError("bad output")

    monkeypatch.setattr(cli, "generate_persona", fake_generate)
    result = runner.invoke(
        cli.app, ["generate-persona", "brief", "-o", str(tmp_path / "p.json")]
    )
    assert result.exit_code == 1
    assert "Persona generation failed" in result.output


def test_cli_generate_persona_rejects_colliding_exchange_output(tmp_path) -> None:
    same = tmp_path / "same.json"
    result = runner.invoke(
        cli.app,
        ["generate-persona", "brief", "-o", str(same), "--exchange-output", str(same)],
    )
    assert result.exit_code != 0
