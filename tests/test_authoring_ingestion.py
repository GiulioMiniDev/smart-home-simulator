from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smart_home_sim.authoring.service import (
    AuthoringValidationResult,
    ingest_authoring_file,
    prepare_authoring_repair_file,
    validate_authoring_file,
    validate_authoring_payload,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/authoring/minimal.authoring-bundle.json"


def _payload() -> dict[str, object]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _append_actions(
    payload: dict[str, object], intent: str, actions: list[dict[str, object]]
) -> None:
    package = payload["personalProcessPackage"]  # type: ignore[index]
    binding = next(item for item in package["bindings"] if item["intent"] == intent)
    model = next(
        item
        for item in package["processModels"]
        if item["processModelId"] == binding["processModelId"]
    )
    edge = next(item for item in model["edges"] if item["targetNodeId"] == "end")
    previous = edge["sourceNodeId"]
    model["edges"].remove(edge)
    for index, action in enumerate(actions, start=1):
        node_id = f"preflight_extra_{index}"
        model["nodes"].append(
            {
                "nodeId": node_id,
                "kind": "action",
                "actionType": action["actionType"],
                "arguments": action.get("arguments", {}),
                "durationWeight": 1,
            }
        )
        model["edges"].append({"sourceNodeId": previous, "targetNodeId": node_id})
        previous = node_id
    model["edges"].append({"sourceNodeId": previous, "targetNodeId": "end"})


def test_valid_bundle_is_published_as_two_valid_canonical_documents(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated/mario"

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert report.valid
    assert report.scenario_id == "minimal_valid_scenario"
    assert report.package_id == "minimal_valid_scenario__behavior"
    assert report.ingestor_version == "1.1.0"
    assert report.canonical_plan_sha256 is not None
    assert report.summary.compilation_error_count == 0
    assert {item.filename for item in report.artifacts} == {
        "scenario.json",
        "personal-process-package.json",
    }
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "personal-process-package.json",
        "scenario.json",
    ]
    scenario = json.loads((output_dir / "scenario.json").read_text(encoding="utf-8"))
    behavior = json.loads(
        (output_dir / "personal-process-package.json").read_text(encoding="utf-8")
    )
    assert scenario["scenarioId"] == behavior["sourceScenarioId"]
    for artifact in report.artifacts:
        content = (output_dir / artifact.filename).read_bytes()
        assert b"\r\n" not in content
        assert sha256(content).hexdigest() == artifact.sha256


def test_validation_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    first = validate_authoring_file(EXAMPLE)
    second = validate_authoring_file(EXAMPLE)

    assert first == second
    assert list(tmp_path.iterdir()) == []


def test_preflight_rejects_provably_false_cross_action_state() -> None:
    payload = _payload()
    _append_actions(
        payload,
        "eat_breakfast",
        [
            {"actionType": "leave_home"},
            {"actionType": "leave_home"},
            {
                "actionType": "put_item",
                "arguments": {"itemRole": {"source": "literal", "value": "never_taken"}},
            },
        ],
    )

    report = validate_authoring_payload(payload).report

    findings = [item for item in report.issues if item.code == "DETERMINISTIC_PRECONDITION_FAILED"]
    assert not report.valid
    assert len(findings) == 2
    assert {item.details["actionType"] for item in findings} == {"leave_home", "put_item"}
    assert {item.details["actual"] for item in findings} == {False, "absent"}
    assert all(item.stage == "behavior" for item in findings)
    assert all(item.path.startswith("$.personalProcessPackage.processModels[") for item in findings)


def test_preflight_preserves_unknown_home_generated_entity_state() -> None:
    payload = _payload()
    _append_actions(
        payload,
        "eat_breakfast",
        [
            {
                "actionType": "close",
                "arguments": {"target": {"source": "literal", "value": "generated_cabinet"}},
            }
        ],
    )

    report = validate_authoring_payload(payload).report

    assert report.valid
    assert "DETERMINISTIC_PRECONDITION_FAILED" not in {item.code for item in report.issues}


def test_invalid_scenario_blocks_behavior_validation_and_output(tmp_path: Path) -> None:
    payload = _payload()
    payload["scenario"]["residents"] = []  # type: ignore[index]
    path = tmp_path / "invalid-scenario.json"
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert report.summary.scenario_error_count > 0
    assert report.summary.compilation_error_count == 1
    assert {item.code for item in report.issues} >= {
        "STRUCTURE_INVALID",
        "COMPILATION_VALIDATION_SKIPPED",
        "BEHAVIOR_VALIDATION_SKIPPED",
    }


def test_compilation_failure_rejects_bundle_even_when_nested_contracts_are_valid(
    tmp_path: Path,
) -> None:
    payload = _payload()
    first_activity = payload["scenario"]["days"][0]["activities"][0]  # type: ignore[index]
    first_activity["activation"] = {
        "mode": "conditional",
        "condition": {"fact": "rain", "operator": "truthy"},
    }
    path = tmp_path / "cross-branch.json"
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert report.summary.scenario_error_count == 0
    assert report.summary.compilation_error_count > 0
    assert report.summary.behavior_error_count == 0
    assert "CROSS_BRANCH_DEPENDENCY" in {item.code for item in report.issues}
    assert all(
        item.path.startswith("$.scenario") for item in report.issues if item.stage == "compilation"
    )
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("invalid_package", "expected_code"),
    [
        ("missing_binding.json", "MISSING_PROCESS_BINDING"),
        ("unbounded_cycle.json", "GRAPH_CYCLE_UNBOUNDED"),
        ("unknown_action.json", "UNKNOWN_ACTION_TYPE"),
    ],
)
def test_behavior_failures_reject_whole_bundle(
    tmp_path: Path,
    invalid_package: str,
    expected_code: str,
) -> None:
    payload = _payload()
    payload["personalProcessPackage"] = json.loads(
        (ROOT / "examples/behavior/invalid" / invalid_package).read_text(encoding="utf-8")
    )
    path = tmp_path / invalid_package
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert expected_code in {item.code for item in report.issues}
    assert all(
        item.path.startswith("$.personalProcessPackage")
        for item in report.issues
        if item.stage == "behavior"
    )


def test_existing_output_directory_is_never_modified(tmp_path: Path) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert not report.valid
    # Errors only: the report also carries content warnings about the bundle itself, which are
    # true whether or not publishing succeeded and are not what rejected it.
    assert [item.code for item in report.issues if item.severity == "error"] == [
        "OUTPUT_DIRECTORY_EXISTS"
    ]
    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert sorted(path.name for path in output_dir.iterdir()) == ["keep.txt"]


def test_publish_failure_removes_temporary_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "result"

    def fail_rename(source: Path, destination: Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr("smart_home_sim.authoring.service.os.rename", fail_rename)

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert not report.valid
    # Errors only: the report also carries content warnings about the bundle itself, which are
    # true whether or not publishing succeeded and are not what rejected it.
    assert [item.code for item in report.issues if item.severity == "error"] == [
        "OUTPUT_WRITE_ERROR"
    ]
    assert not output_dir.exists()
    assert list(tmp_path.glob(".result.tmp-*")) == []


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '{"schemaVersion":"1.0.0","schemaVersion":"1.0.0"}',
        '{"value":NaN}',
    ],
)
def test_unsafe_or_malformed_json_is_rejected_without_output(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert report.issues[0].stage == "bundle"


def test_envelope_rejects_unknown_and_missing_properties(tmp_path: Path) -> None:
    payload = _payload()
    del payload["documentType"]
    payload["explanation"] = "not allowed"
    path = tmp_path / "wrong-envelope.json"
    _write(path, payload)

    report = validate_authoring_file(path).report

    assert not report.valid
    paths = {item.path for item in report.issues}
    assert "$.documentType" in paths
    assert "$.explanation" in paths


def test_distributed_prompt_1_2_is_single_self_contained_authoring_request() -> None:
    prompt = (ROOT / "prompts/generate-simulation-inputs-1.2.0.md").read_text(encoding="utf-8")

    assert "{{BUNDLE_SCHEMA_JSON}}" not in prompt
    assert "{{ACTIVITY_CATALOG_JSON}}" not in prompt
    assert "{{VARIABLE_CATALOG_JSON}}" not in prompt
    assert "{{ACTION_CATALOG_JSON}}" not in prompt
    assert "{{PERSON_AND_CASE_DESCRIPTION}}" in prompt
    assert "Return exactly one JSON object and nothing else." in prompt
    assert "`generatorVersion`: `1.2.0`" in prompt
    assert "A fallback may replace only an activity whose activation mode is `always`." in prompt
    assert "Do not return a wake-up model" in prompt
    assert "full plan compilation" in prompt
    assert "Mandatory ValueExpression and reference-kind compatibility" in prompt
    assert "A scenario resource is not automatically a" in prompt
    assert '"itemRole": {"source": "literal", "value": "coffee_preparation_item"}' in prompt
    assert '"itemRole": {"source": "activity_resource", "index": 0}' in prompt
    assert "zero `ACTION_ARGUMENT_TYPE_MISMATCH` possibilities" in prompt
    compact_schema = json.dumps(
        json.loads((ROOT / "schemas/simulation-authoring-bundle-1.0.0.schema.json").read_text()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert compact_schema in prompt
    for filename in (
        "activity-catalog-1.0.0.json",
        "variable-catalog-1.0.0.json",
        "action-catalog-1.0.0.json",
    ):
        compact = json.dumps(
            json.loads((ROOT / "src/smart_home_sim/catalogs" / filename).read_text()),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert compact in prompt


def test_distributed_prompt_1_3_teaches_the_replayed_action_state_contract() -> None:
    """1.3.0 is 1.2.0 plus the contract the deterministic replay enforces.

    A 1.2.0 bundle passed schema, compilation and behavior validation and was still rejected by
    `DETERMINISTIC_PRECONDITION_FAILED`, because no prompt stated that action preconditions carry
    across activities and days. The precondition lines are asserted against the catalog so a new
    precondition cannot ship with the prompt silently omitting it.
    """
    prompt = (ROOT / "prompts/generate-simulation-inputs-1.3.0.md").read_text(encoding="utf-8")
    frozen = (ROOT / "prompts/generate-simulation-inputs-1.2.0.md").read_text(encoding="utf-8")

    assert "`generatorVersion`: `1.3.0`" in prompt
    assert "`promptTemplateVersion`: `generate-simulation-inputs-1.3.0`" in prompt
    assert "1.2.0" not in prompt.split("## Authoritative output schema", 1)[0]
    # Everything 1.2.0 already taught has to survive the new version.
    assert "Mandatory ValueExpression and reference-kind compatibility" in prompt
    assert "zero `ACTION_ARGUMENT_TYPE_MISMATCH` possibilities" in prompt
    assert "## Mandatory action state continuity" in prompt
    assert "DETERMINISTIC_PRECONDITION_FAILED" in prompt
    assert "The state is not reset between activities and not reset between days." in prompt
    assert "move_to_capability(home_entrance) -> enter_home [bridge]" in prompt
    assert "PROCESS_COMPONENT_MISMATCH" in prompt
    assert "## Mandatory action state continuity" not in frozen

    action_catalog = json.loads(
        (ROOT / "src/smart_home_sim/catalogs/action-catalog-1.0.0.json").read_text()
    )
    contract = prompt.split("## Mandatory action state continuity", 1)[1].split(
        "## Required final consistency checks", 1
    )[0]
    for action in action_catalog["actions"]:
        for precondition in action["preconditions"]:
            assert (
                f"{action['actionType']:19} requires {precondition['factTemplate']} "
                f"{precondition['operator']} {json.dumps(precondition['value'])}"
            ) in contract


def test_simplified_prompt_1_2_3_is_regenerated_from_the_catalogs() -> None:
    """The committed prompt must equal a fresh render.

    The 1.2.2 prompt taught `call_sister_lucia` for days after catalog 1.2.0 dropped it, because
    the section was retyped by hand and only ever checked against the catalog it was written from.
    Comparing against a fresh render turns any future catalog move into a failing test.
    """
    sys.path.insert(0, str(ROOT))
    from tools.build_authoring_artifacts import (
        SIMPLIFIED_ACTIVITY_CATALOG_VERSION,
        SIMPLIFIED_PROMPT_PATH,
        SIMPLIFIED_REFERENCE_MODELS,
        render_simplified_prompt,
    )

    committed = SIMPLIFIED_PROMPT_PATH.read_text(encoding="utf-8")
    assert committed == render_simplified_prompt(), (
        "prompts/generate-simulation-inputs-1.2.3-simplified.md is stale; "
        "run `make authoring-artifacts`"
    )

    catalog_dir = ROOT / "src/smart_home_sim/catalogs"
    activity_catalog = json.loads(
        (catalog_dir / f"activity-catalog-{SIMPLIFIED_ACTIVITY_CATALOG_VERSION}.json").read_text()
    )
    reference_models = json.loads((catalog_dir / SIMPLIFIED_REFERENCE_MODELS).read_text())

    # Every catalog intent is offered, and every proven recipe is shown rather than guessed at.
    intent_section = committed.split("## 4. Intent ammessi e componenti esatti", 1)[1].split(
        "## 5. Componenti e sequenze obbligatorie di azioni", 1
    )[0]
    documented_intents = {
        line.split(" = ", 1)[0]: line.split(" = ", 1)[1].split(", ")
        for line in intent_section.splitlines()
        if " = " in line and not line.startswith("Ogni ")
    }
    assert documented_intents == {
        item["intent"]: item["components"] for item in activity_catalog["activities"]
    }

    reference_section = committed.split("## 5.1 Modelli di riferimento provati", 1)[1].split(
        "## 6. Grafo e catalogo azioni", 1
    )[0]
    for intent in reference_models["models"]:
        assert f"{intent}  [" in reference_section

    # The container openings the reference models gained are what the prompt exists to teach.
    assert "open(cleaning_product_storage) -> take_item(cleaning_tool)" in reference_section
    # Read from the constant, not retyped: pinning the version by hand is the same mistake as
    # retyping the intent list, and it fired the moment the catalog moved to 1.3.0.
    assert f'version: "{SIMPLIFIED_ACTIVITY_CATALOG_VERSION}"' in committed
    assert "call_sister_lucia" not in committed


def test_simplified_prompt_1_2_2_tracks_frozen_catalogs_and_state_contract() -> None:
    prompt = (ROOT / "prompts/generate-simulation-inputs-1.2.2-simplified.md").read_text(
        encoding="utf-8"
    )
    activity_catalog = json.loads(
        (ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json").read_text()
    )

    intent_section = prompt.split("## 4. Intent ammessi e componenti esatti", 1)[1].split(
        "## 5. Componenti e sequenze obbligatorie di azioni", 1
    )[0]
    documented_intents = {
        line.split(" = ", 1)[0]: line.split(" = ", 1)[1].split(", ")
        for line in intent_section.splitlines()
        if " = " in line and not line.startswith("Ogni ")
    }
    assert documented_intents == {
        item["intent"]: item["components"] for item in activity_catalog["activities"]
    }

    component_section = prompt.split("## 5. Componenti e sequenze obbligatorie di azioni", 1)[
        1
    ].split("## 6. Grafo e catalogo azioni", 1)[0]
    documented_components = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1].split(" -> ")
        for line in component_section.splitlines()
        if ": " in line and not line.startswith(("Per ", "Attenzione"))
    }
    assert documented_components == {
        item["componentId"]: item["requiredActionTypes"] for item in activity_catalog["components"]
    }

    assert 'documentType: "personal_process_package"' in prompt
    assert "language: string;" in prompt
    assert 'referenceId: "activity_catalog"' in prompt
    assert 'catalogId: "smart_home_action_catalog"' in prompt
    assert "La fine di `simulationWindow` e esclusiva" in prompt
    assert "Registro cronologico di stato: obbligatorio" in prompt
    assert "move_to_capability(home_entrance) -> enter_home [ponte]" in prompt
    assert "operation = take | refill | store" in prompt
    assert "operation = collect | load | start | unload | hang | iron" in prompt
    assert "take_dose" not in prompt
    assert 'referenceId: "smart_home_activity_catalog"' not in prompt


def test_invalid_bundle_produces_deterministic_self_contained_repair_request(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["personalProcessPackage"]["bindings"] = []  # type: ignore[index]
    path = tmp_path / "rejected.json"
    _write(path, payload)

    first = prepare_authoring_repair_file(path, attempt=2)
    second = prepare_authoring_repair_file(path, attempt=2)

    assert first == second
    assert not first.report.valid
    assert first.request is not None
    request = first.request
    assert request.attempt == 2
    assert request.repair_request_id.endswith("_attempt_2")
    assert request.source.bundle_text == path.read_text(encoding="utf-8")
    assert request.source.sha256 == sha256(path.read_bytes()).hexdigest()
    assert request.validation_report == first.report
    assert request.policy.preserve_valid_content is True
    assert request.policy.return_complete_bundle is True
    assert request.policy.return_json_only is True
    assert "STRUCTURE_INVALID" in {issue.code for issue in request.validation_report.issues}
    assert request.authoritative_context.simulation_authoring_bundle_schema["$id"].endswith(
        "simulation-authoring-bundle:1.0.0"
    )
    assert request.authoritative_context.action_catalog["catalogId"] == "smart_home_action_catalog"
    serialized = request.model_dump_json(by_alias=True)
    assert "source.bundleText" in request.instructions[0]
    assert "Return exactly one JSON object and nothing else." in serialized
    repair_schema = json.loads(
        (ROOT / "schemas/authoring-repair-request-1.0.0.schema.json").read_text()
    )
    assert list(Draft202012Validator(repair_schema).iter_errors(json.loads(serialized))) == []


def test_repair_request_supports_malformed_but_bounded_utf8_json(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text('{"schemaVersion":"1.0.0",', encoding="utf-8")

    preparation = prepare_authoring_repair_file(path)

    assert preparation.request is not None
    assert preparation.request.source.bundle_text == path.read_text(encoding="utf-8")
    assert [issue.code for issue in preparation.request.validation_report.issues] == ["JSON_SYNTAX"]


def test_an_accepted_bundle_with_warnings_still_gets_a_request(tmp_path: Path) -> None:
    """A warning is the finding no gate will reject a document over, and it used to go nowhere.

    Gating the request on the report being invalid meant the only route back to an author was
    closed for exactly the defects that survive validation: a resident who ran the washing machine
    104 times without opening it was told the bundle needed no repair.
    """
    accepted = prepare_authoring_repair_file(EXAMPLE)

    assert accepted.report.valid
    assert [issue.severity for issue in accepted.report.issues] == ["warning"]
    assert accepted.request is not None
    assert accepted.unavailable_reason is None
    instructions = accepted.request.instructions
    assert any("This bundle was accepted" in line for line in instructions)
    # The error directive would send the author hunting for a structural fault that is not there.
    assert not any("severity is error" in line for line in instructions)


def test_a_bundle_with_nothing_to_say_about_it_gets_no_request(monkeypatch, tmp_path: Path) -> None:
    report = prepare_authoring_repair_file(EXAMPLE).report
    silent = report.model_copy(update={"issues": []})
    monkeypatch.setattr(
        "smart_home_sim.authoring.service.validate_authoring_file",
        lambda path: AuthoringValidationResult(report=silent),
    )

    preparation = prepare_authoring_repair_file(EXAMPLE)

    assert preparation.request is None
    assert "already valid" in (preparation.unavailable_reason or "")


def test_an_unembeddable_bundle_does_not_create_repair_request(tmp_path: Path) -> None:
    non_utf8_path = tmp_path / "binary.json"
    non_utf8_path.write_bytes(b"\xff")
    non_utf8 = prepare_authoring_repair_file(non_utf8_path)
    assert non_utf8.request is None
    assert not non_utf8.report.valid
    assert "not UTF-8" in (non_utf8.unavailable_reason or "")


def test_repair_attempt_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        prepare_authoring_repair_file(EXAMPLE, attempt=0)


def test_repaired_full_bundle_reenters_normal_ingestion(tmp_path: Path) -> None:
    payload = _payload()
    valid_bindings = payload["personalProcessPackage"]["bindings"]  # type: ignore[index]
    payload["personalProcessPackage"]["bindings"] = []  # type: ignore[index]
    rejected_path = tmp_path / "rejected.json"
    _write(rejected_path, payload)

    preparation = prepare_authoring_repair_file(rejected_path)
    assert preparation.request is not None

    repaired_payload = json.loads(preparation.request.source.bundle_text)
    repaired_payload["personalProcessPackage"]["bindings"] = valid_bindings
    repaired_path = tmp_path / "repaired.json"
    _write(repaired_path, repaired_payload)

    report = ingest_authoring_file(repaired_path, tmp_path / "accepted")
    assert report.valid
    assert report.summary.error_count == 0


def test_distributed_outline_prompt_is_self_contained_and_cannot_drift() -> None:
    """The outline prompt embeds its schema and restates nothing it could restate wrongly.

    Its habit portfolio, its room identifiers and its whole process-package half are rendered from
    the code and from the frozen 1.3.0 prompt. A catalog that gains a room, or a portfolio gate
    that changes its counts, is then a build failure here rather than a prompt that quietly teaches
    the old contract — which is exactly how requirement 11 survived two versions unenforced.
    """
    prompt = (ROOT / "prompts/generate-horizon-outline-1.1.0.md").read_text(encoding="utf-8")
    frozen = (ROOT / "prompts/generate-simulation-inputs-1.3.0.md").read_text(encoding="utf-8")

    assert "{{PERSON_AND_CASE_DESCRIPTION}}" in prompt
    assert "{{BUNDLE_SCHEMA_JSON}}" not in prompt
    assert "{{CATALOG_INTENTS}}" not in prompt
    assert "{{ACTIVITY_PORTFOLIO}}" not in prompt
    assert "Return exactly one JSON object and nothing else." in prompt
    assert "`promptTemplateVersion`: `generate-horizon-outline-1.1.0`" in prompt
    assert "**Do not write the days of the horizon.**" in prompt
    # 1.1.0 teaches that splitting a band is only half the job. A generated year produced a weekend
    # band with 68% of its minutes undeclared and a dominant intent at 5.8%, because it was authored
    # as the weekday band with the work removed and nothing put back.
    assert "every band names at least one recurring activity of `kind: anchor`" in prompt
    assert "`unaccountedShare`" in prompt

    schema = json.loads(
        (ROOT / "schemas/horizon-authoring-bundle-1.0.0.schema.json").read_text(encoding="utf-8")
    )
    assert json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in prompt

    from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG
    from smart_home_sim.hybrid_planning.recurring_activities import (
        MIN_RECURRING_ACTIVITIES,
        REQUIRED_KINDS,
    )

    assert f"Author at least {MIN_RECURRING_ACTIVITIES} recurring activities" in prompt
    for kind, count in REQUIRED_KINDS.items():
        assert f"- `{kind}`: {count}" in prompt
    for room in {spec.default_location for spec in INTENT_CATALOG}:
        assert f"`{room}`" in prompt
    # Every catalog intent is listed, so a habit can declare one instead of having it guessed.
    for spec in INTENT_CATALOG:
        assert f"- `{spec.intent_id}` — {spec.default_location}" in prompt

    from tools.build_authoring_artifacts import _retarget_action_state_contract

    start = frozen.index("## Personal ADL process-model rules")
    end = frozen.index("## Required final consistency checks", start)
    section = frozen[start:end].rstrip()
    # Reused whole, save for the replayed state contract. The two prompts embed different action
    # catalogs — 1.0.0 there, 1.1.0 here — and lifting that part verbatim described the wrong one:
    # its table omitted `prepare_food`, `shop` and `dress`, the three actions that hand the
    # resident a role, and the rule above it said no such action existed.
    assert _retarget_action_state_contract(section) in prompt
    assert section not in prompt
