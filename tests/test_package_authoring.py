from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.behavior.issues import behavior_issue
from smart_home_sim.domain.behavior_report import BehaviorValidationReport
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning import package_authoring as pa
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, intent_ids, reference_model
from smart_home_sim.hybrid_planning.lmstudio import (
    LMStudioClient,
    LMStudioConfig,
    LMStudioUnavailableError,
    extract_json_value,
)
from smart_home_sim.hybrid_planning.package_authoring import (
    PackageAuthoringError,
    _action_vocabulary,
    _ModelParseError,
    _parse_model,
    author_process_package,
    build_probe_scenario,
    build_reference_package,
)
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import build_planning_world


def _reply_client(transport) -> LMStudioClient:
    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


def _echo_reference_client() -> LMStudioClient:
    """An LLM that echoes back the reference model embedded in the prompt (a valid variant)."""

    def transport(url: str, body: bytes, timeout: float) -> str:
        request = json.loads(body)
        prompt = next(
            m["content"]
            for m in request["messages"]
            if "reference process model" in m["content"]
        )
        reference = extract_json_value(prompt)
        message = {"content": json.dumps(reference)}
        return json.dumps({"choices": [{"message": message, "finish_reason": "stop"}]})

    return _reply_client(transport)


def _fixed_reply_client(content: str) -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    return _reply_client(transport)

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


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


def _world():
    return build_planning_world(_persona(), now=_NOW)


def test_build_reference_package_retargets_to_persona() -> None:
    package = build_reference_package(_persona(), _world(), now=_NOW)
    assert len(package.process_models) == len(INTENT_CATALOG)
    assert len(package.bindings) == len(INTENT_CATALOG)
    assert package.source_scenario_id == "luigi_bianchi_scenario"
    assert {binding.intent for binding in package.bindings} == set(intent_ids())
    assert all(model.resident_id == "luigi_bianchi" for model in package.process_models)
    assert all(binding.resident_id == "luigi_bianchi" for binding in package.bindings)
    assert package.catalogs.action_catalog.version == "1.1.0"


def test_probe_scenario_has_one_activity_per_intent() -> None:
    scenario = build_probe_scenario(_world())
    assert scenario.scenario_id == "luigi_bianchi_scenario"
    intents = [activity.intent for activity in scenario.days[0].activities]
    assert intents == intent_ids()


def test_author_process_package_passes_the_behavior_gate() -> None:
    result = author_process_package(_persona(), _world(), now=_NOW)
    assert result.report.valid
    assert len(result.package.process_models) == len(INTENT_CATALOG)


def test_author_process_package_raises_on_gate_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = BehaviorValidationReport.from_issues(
        [behavior_issue("INPUT_SCENARIO_INVALID", "compatibility", "$", "forced failure")]
    )
    monkeypatch.setattr(pa, "gate_package", lambda package, scenario: invalid)
    with pytest.raises(PackageAuthoringError, match="INPUT_SCENARIO_INVALID"):
        author_process_package(_persona(), _world(), now=_NOW)


def test_llm_echo_accepts_every_reference_variant() -> None:
    result = author_process_package(
        _persona(), _world(), client=_echo_reference_client(), now=_NOW
    )
    assert result.report.valid
    assert result.llm_authored_count == len(INTENT_CATALOG)
    assert result.fallback_count == 0


def test_llm_unparseable_output_falls_back_to_reference() -> None:
    result = author_process_package(
        _persona(), _world(), client=_fixed_reply_client("no json here"), now=_NOW
    )
    assert result.report.valid
    assert result.llm_authored_count == 0
    assert result.fallback_count == len(INTENT_CATALOG)


def test_llm_invalid_model_falls_back_to_reference() -> None:
    result = author_process_package(
        _persona(), _world(), client=_fixed_reply_client("{}"), now=_NOW
    )
    assert result.report.valid
    assert result.llm_authored_count == 0


def test_llm_transport_failure_propagates() -> None:
    import urllib.error

    def transport(url: str, body: bytes, timeout: float) -> str:
        raise urllib.error.URLError("down")

    with pytest.raises(LMStudioUnavailableError):
        author_process_package(_persona(), _world(), client=_reply_client(transport), now=_NOW)


def test_parse_model_retargets_and_validates() -> None:
    reference = reference_model("sleep")
    data = json.loads(reference.model_dump_json(by_alias=True))
    model = _parse_model(data, "sleep", reference, _action_vocabulary(), "luigi_bianchi")
    assert model.process_model_id == "luigi_bianchi__sleep"
    assert model.resident_id == "luigi_bianchi"


def test_parse_model_rejects_non_object_and_unknown_actions() -> None:
    reference = reference_model("sleep")
    data = json.loads(reference.model_dump_json(by_alias=True))
    with pytest.raises(_ModelParseError):
        _parse_model("nope", "sleep", reference, _action_vocabulary(), "rid")
    with pytest.raises(_ModelParseError):
        _parse_model({}, "sleep", reference, _action_vocabulary(), "rid")
    with pytest.raises(_ModelParseError, match="unknown action"):
        _parse_model(data, "sleep", reference, set(), "rid")


def test_cli_author_package_writes_file(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    world_path = tmp_path / "world.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    output = tmp_path / "package.json"
    result = runner.invoke(
        cli.app,
        ["author-process-package", str(persona_path), str(world_path), "-o", str(output)],
    )
    assert result.exit_code == 0, result.output
    package = json.loads(output.read_text(encoding="utf-8"))
    assert package["documentType"] == "personal_process_package"
    assert len(package["processModels"]) == len(INTENT_CATALOG)


def test_cli_author_package_rejects_bad_input(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    persona_path.write_text("{broken}", encoding="utf-8")
    world_path = tmp_path / "world.json"
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "author-process-package",
            str(persona_path),
            str(world_path),
            "-o",
            str(tmp_path / "p.json"),
        ],
    )
    assert result.exit_code == 2
    assert "Cannot load inputs" in result.output


def test_cli_author_package_rejects_colliding_output(tmp_path) -> None:
    persona_path = tmp_path / "persona.json"
    world_path = tmp_path / "world.json"
    persona_path.write_text(_persona().model_dump_json(by_alias=True), encoding="utf-8")
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["author-process-package", str(persona_path), str(world_path), "-o", str(world_path)],
    )
    assert result.exit_code != 0
