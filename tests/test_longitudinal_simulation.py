from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

import smart_home_sim.simulation.service as sim_service
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.environment import Point2D
from smart_home_sim.domain.execution import FinalWorldState, ResidentFinalState
from smart_home_sim.domain.longitudinal import (
    LongitudinalCheckpoint,
    LongitudinalChunkRecord,
    LongitudinalSimulationIssue,
    LongitudinalSimulationManifest,
    LongitudinalSimulationReport,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.environment import build_bundle_files
from smart_home_sim.materialization import deploy_sensors, generate_home
from smart_home_sim.sensors import project_sensors
from smart_home_sim.simulation import (
    run_longitudinal_file,
    simulate_bundle,
    verify_longitudinal_run,
)
from smart_home_sim.simulation.longitudinal_aggregate import (
    aggregate_execution_traces,
    aggregate_oracle_mappings,
    aggregate_sensor_logs,
)
from smart_home_sim.simulation.longitudinal_state import validate_handoff
from smart_home_sim.simulation.longitudinal_validation import (
    load_and_validate_longitudinal_manifest,
)

PROJECT_ROOT = Path(__file__).parents[1]
MINIMAL_SCENARIO_PATH = PROJECT_ROOT / "examples/valid/minimal.json"
PPP_PATH = PROJECT_ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"


def _make_minimal_scenario(
    scenario_id: str = "minimal_valid_scenario",
    start: str = "2026-10-12T00:00:00+02:00",
    end: str = "2026-10-13T00:00:00+02:00",
    initial_at: str = "2026-10-12T00:00:00+02:00",
    activity_prefix: str = "",
    seed: int = 1,
) -> dict[str, object]:
    data = json.loads(MINIMAL_SCENARIO_PATH.read_text(encoding="utf-8"))
    data["scenarioId"] = scenario_id
    data["simulationWindow"]["start"] = start
    data["simulationWindow"]["end"] = end
    data["initialState"]["at"] = initial_at
    data["seed"] = seed

    if data.get("days"):
        data["days"][0]["date"] = start.split("T")[0]
        for act in data["days"][0]["activities"]:
            act["activityId"] = f"{activity_prefix}{act['activityId']}"
            act["startWindow"]["earliest"] = start.replace("00:00:00", "08:00:00")
            act["startWindow"]["preferred"] = start.replace("00:00:00", "08:00:00")
            act["startWindow"]["latest"] = start.replace("00:00:00", "08:00:00")
            if "dependencyGroups" in act:
                for grp in act["dependencyGroups"]:
                    grp["activityIds"] = [f"{activity_prefix}{aid}" for aid in grp["activityIds"]]

    if data.get("commitments"):
        for com in data["commitments"]:
            com["start"] = start.replace("00:00:00", "08:00:00")
            com["end"] = start.replace("00:00:00", "08:30:00")

    if data.get("runtimeEventCandidates"):
        for ev in data["runtimeEventCandidates"]:
            ev["eventId"] = f"{activity_prefix}{ev['eventId']}"
            ev["triggerActivityId"] = f"{activity_prefix}{ev['triggerActivityId']}"
            for eff in ev["effects"]:
                if "targetId" in eff:
                    eff["targetId"] = f"{activity_prefix}{eff['targetId']}"

    return data


def _make_ppp(source_scenario_id: str = "minimal_valid_scenario") -> dict[str, object]:
    data = json.loads(PPP_PATH.read_text(encoding="utf-8"))
    data["sourceScenarioId"] = source_scenario_id
    return data


def test_longitudinal_manifest_parsing_and_validations() -> None:
    manifest = LongitudinalSimulationManifest(
        run_id="test_run",
        scenario_paths=["chunks/0001/scenario.json", "chunks/0002/scenario.json"],
        personal_process_package_path="ppp.json",
        home_policy_path=None,
        sensor_policy_path=None,
        seed=42,
    )
    assert manifest.run_id == "test_run"
    assert manifest.scenario_paths == ["chunks/0001/scenario.json", "chunks/0002/scenario.json"]

    # Duplicate scenario paths
    with pytest.raises(ValidationError, match="scenarioPaths must be unique"):
        LongitudinalSimulationManifest(
            run_id="test_run",
            scenario_paths=["chunks/0001/scenario.json", "chunks/0001/scenario.json"],
            personal_process_package_path="ppp.json",
            seed=42,
        )

    # Absolute path
    with pytest.raises(ValidationError, match="safe relative path"):
        LongitudinalSimulationManifest(
            run_id="test_run",
            scenario_paths=["/abs/path/scenario.json"],
            personal_process_package_path="ppp.json",
            seed=42,
        )

    # Traversal path ..
    with pytest.raises(ValidationError, match="safe relative path"):
        LongitudinalSimulationManifest(
            run_id="test_run",
            scenario_paths=["chunks/../scenario.json"],
            personal_process_package_path="ppp.json",
            seed=42,
        )


def test_longitudinal_checkpoint_validation() -> None:
    fake_sha = "a" * 64
    chunk1 = LongitudinalChunkRecord(
        chunk_index=1,
        scenario_path="c1.json",
        scenario_sha256=fake_sha,
        input_state_sha256=None,
        artifact_path="chunks/0001",
        bundle_sha256=fake_sha,
        trace_sha256=fake_sha,
        terminal_state_sha256=fake_sha,
        sensor_log_sha256=fake_sha,
        oracle_mapping_sha256=fake_sha,
    )

    # Inconsistent count
    with pytest.raises(ValidationError, match="completedChunkCount must match"):
        LongitudinalCheckpoint(
            run_id="test_run",
            manifest_sha256=fake_sha,
            configuration_sha256=fake_sha,
            completed_chunk_count=2,
            chunks=[chunk1],
        )


def test_longitudinal_report_validation() -> None:
    now = datetime.now(timezone.utc)
    fake_sha = "a" * 64

    # Success with issues should fail
    with pytest.raises(ValidationError, match="successful longitudinal report cannot contain issues"):
        LongitudinalSimulationReport(
            success=True,
            run_id="test_run",
            manifest_sha256=fake_sha,
            started_at=now,
            ended_at=now,
            issues=[
                LongitudinalSimulationIssue(
                    code="LONGITUDINAL_MANIFEST_INVALID",
                    stage="input",
                    path="manifest.json",
                    message="error",
                )
            ],
        )


def test_sequence_validation_valid_two_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure simulate_bundle is never called during validation
    def _sentinel_simulate(*args: object, **kwargs: object) -> None:
        pytest.fail("simulate_bundle should never be called during manifest validation")

    monkeypatch.setattr(sim_service, "simulate_bundle", _sentinel_simulate)

    sc1 = _make_minimal_scenario(
        start="2026-10-12T00:00:00+02:00",
        end="2026-10-13T00:00:00+02:00",
        initial_at="2026-10-12T00:00:00+02:00",
        activity_prefix="c1_",
        seed=1,
    )
    sc2 = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    ppp = _make_ppp()

    (tmp_path / "sc1.json").write_text(json.dumps(sc1), encoding="utf-8")
    (tmp_path / "sc2.json").write_text(json.dumps(sc2), encoding="utf-8")
    (tmp_path / "ppp.json").write_text(json.dumps(ppp), encoding="utf-8")

    manifest_data = {
        "schemaVersion": "1.0.0",
        "documentType": "longitudinal_simulation_manifest",
        "runId": "valid_run",
        "scenarioPaths": ["sc1.json", "sc2.json"],
        "personalProcessPackagePath": "ppp.json",
        "seed": 1,
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    resolved = load_and_validate_longitudinal_manifest(manifest_file)
    assert len(resolved.scenarios) == 2
    assert resolved.manifest.run_id == "valid_run"
    assert resolved.scenarios[0].simulation_window.start.isoformat() == "2026-10-12T00:00:00+02:00"
    assert resolved.scenarios[1].simulation_window.start.isoformat() == "2026-10-13T00:00:00+02:00"


def test_sequence_validation_failures(tmp_path: Path) -> None:
    sc1 = _make_minimal_scenario(
        start="2026-10-12T00:00:00+02:00",
        end="2026-10-13T00:00:00+02:00",
        initial_at="2026-10-12T00:00:00+02:00",
        activity_prefix="c1_",
        seed=1,
    )
    sc2 = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    ppp = _make_ppp()

    (tmp_path / "ppp.json").write_text(json.dumps(ppp), encoding="utf-8")

    # 1. Missing scenario file
    manifest_data = {
        "schemaVersion": "1.0.0",
        "documentType": "longitudinal_simulation_manifest",
        "runId": "fail_run",
        "scenarioPaths": ["missing.json"],
        "personalProcessPackagePath": "ppp.json",
        "seed": 1,
    }
    mf = tmp_path / "manifest_missing.json"
    mf.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ValueError, match="scenario file not found"):
        load_and_validate_longitudinal_manifest(mf)

    # 2. Non-contiguous gap
    sc2_gap = _make_minimal_scenario(
        start="2026-10-14T00:00:00+02:00",
        end="2026-10-15T00:00:00+02:00",
        initial_at="2026-10-14T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    (tmp_path / "sc1.json").write_text(json.dumps(sc1), encoding="utf-8")
    (tmp_path / "sc2_gap.json").write_text(json.dumps(sc2_gap), encoding="utf-8")

    manifest_data["scenarioPaths"] = ["sc1.json", "sc2_gap.json"]
    mf_gap = tmp_path / "manifest_gap.json"
    mf_gap.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ValueError, match="not contiguous"):
        load_and_validate_longitudinal_manifest(mf_gap)

    # 3. Duplicate activity IDs across chunks
    sc2_dup = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c1_",  # Same prefix creates duplicate activity IDs
        seed=1,
    )
    (tmp_path / "sc2_dup.json").write_text(json.dumps(sc2_dup), encoding="utf-8")
    manifest_data["scenarioPaths"] = ["sc1.json", "sc2_dup.json"]
    mf_dup = tmp_path / "manifest_dup.json"
    mf_dup.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate activityId"):
        load_and_validate_longitudinal_manifest(mf_dup)

    # 4. PPP sourceScenarioId mismatch
    ppp_bad = _make_ppp(source_scenario_id="wrong_id")
    (tmp_path / "ppp_bad.json").write_text(json.dumps(ppp_bad), encoding="utf-8")
    (tmp_path / "sc2.json").write_text(json.dumps(sc2), encoding="utf-8")
    manifest_data["scenarioPaths"] = ["sc1.json", "sc2.json"]
    manifest_data["personalProcessPackagePath"] = "ppp_bad.json"
    mf_bad_ppp = tmp_path / "manifest_bad_ppp.json"
    mf_bad_ppp.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ValueError, match="sourceScenarioId"):
        load_and_validate_longitudinal_manifest(mf_bad_ppp)

    # 5. Later initialState.at mismatch
    sc2_bad_at = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-12T00:00:00+02:00",  # Mismatched initial_at for chunk 2
        activity_prefix="c2_",
        seed=1,
    )
    (tmp_path / "sc2_bad_at.json").write_text(json.dumps(sc2_bad_at), encoding="utf-8")
    manifest_data["personalProcessPackagePath"] = "ppp.json"
    manifest_data["scenarioPaths"] = ["sc1.json", "sc2_bad_at.json"]
    mf_bad_at = tmp_path / "manifest_bad_at.json"
    mf_bad_at.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ValueError, match="initialState.at"):
        load_and_validate_longitudinal_manifest(mf_bad_at)


def test_longitudinal_state_handoff_and_validation(tmp_path: Path) -> None:
    sc2_dict = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    ppp_dict = _make_ppp()

    sc2_file = tmp_path / "sc2.json"
    ppp_file = tmp_path / "ppp.json"
    sc2_file.write_text(json.dumps(sc2_dict), encoding="utf-8")
    ppp_file.write_text(json.dumps(ppp_dict), encoding="utf-8")

    sc2_obj = Scenario.model_validate_json(json.dumps(sc2_dict))
    ppp_obj = PersonalProcessPackage.model_validate_json(json.dumps(ppp_dict))

    compilation = compile_scenario(sc2_obj)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(compilation.plan.model_dump_json(by_alias=True), encoding="utf-8")

    home_res = generate_home(sc2_obj, ppp_obj)
    home_file = tmp_path / "home.json"
    home_file.write_text(home_res.home.model_dump_json(by_alias=True), encoding="utf-8")

    bundle_res = build_bundle_files(sc2_file, plan_file, ppp_file, home_file)
    assert bundle_res.bundle is not None
    bundle = bundle_res.bundle

    start_dt = bundle.scenario.simulation_window.start

    # Valid handoff state with custom position, posture sitting, facts and entity states
    handoff_state = FinalWorldState(
        at=start_dt,
        residents=[
            ResidentFinalState(
                resident_id="resident_1",
                region_id="bedroom",
                position=Point2D(x=1.5, y=1.5),
                posture="sitting",
                execution_state="idle",
                facts={"awake": True, "custom_fact": "test_val"},
                held_resource_ids=[],
            )
        ],
        entity_states={"world": {"ambient_temperature_celsius": 22.5}},
        environment_facts={"custom_env_fact": True},
        resource_available_units={"kettle_1": 1},
    )

    handoff_issues = validate_handoff(bundle, handoff_state)
    assert len(handoff_issues) == 0

    # Execute simulation with authoritative handoff state
    sim_res = simulate_bundle(bundle, initial_world_state=handoff_state)
    assert sim_res.report.success is True
    assert sim_res.trace is not None
    assert sim_res.trace.final_state.residents[0].facts.get("custom_fact") == "test_val"

    # Mismatched timestamp validation failure
    bad_time_state = handoff_state.model_copy(
        update={"at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    )
    issues_time = validate_handoff(bundle, bad_time_state)
    assert any(i.code == "INITIAL_WORLD_STATE_INVALID" for i in issues_time)

    # Missing resident validation failure
    bad_res_state = handoff_state.model_copy(update={"residents": []})
    issues_res = validate_handoff(bundle, bad_res_state)
    assert any("missing resident" in i.message.lower() for i in issues_res)

    # Mismatched resource capacity validation failure
    bad_res_cap = handoff_state.model_copy(update={"resource_available_units": {"kettle_1": 0}})
    issues_cap = validate_handoff(bundle, bad_res_cap)
    assert any("capacity" in i.message.lower() for i in issues_cap)


def test_longitudinal_aggregation(tmp_path: Path) -> None:
    # Build 2 consecutive chunks and run simulation + projection
    sc1_dict = _make_minimal_scenario(
        start="2026-10-12T00:00:00+02:00",
        end="2026-10-13T00:00:00+02:00",
        initial_at="2026-10-12T00:00:00+02:00",
        activity_prefix="c1_",
        seed=1,
    )
    sc2_dict = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    ppp_dict = _make_ppp()

    sc1_file, sc2_file, ppp_file = tmp_path / "sc1.json", tmp_path / "sc2.json", tmp_path / "ppp.json"
    sc1_file.write_text(json.dumps(sc1_dict), encoding="utf-8")
    sc2_file.write_text(json.dumps(sc2_dict), encoding="utf-8")
    ppp_file.write_text(json.dumps(ppp_dict), encoding="utf-8")

    sc1_obj = Scenario.model_validate_json(json.dumps(sc1_dict))
    sc2_obj = Scenario.model_validate_json(json.dumps(sc2_dict))
    ppp_obj = PersonalProcessPackage.model_validate_json(json.dumps(ppp_dict))

    plan1 = tmp_path / "p1.json"
    plan1.write_text(compile_scenario(sc1_obj).plan.model_dump_json(by_alias=True))
    plan2 = tmp_path / "p2.json"
    plan2.write_text(compile_scenario(sc2_obj).plan.model_dump_json(by_alias=True))

    home_res = generate_home(sc1_obj, ppp_obj)
    home_file = tmp_path / "home.json"
    home_file.write_text(home_res.home.model_dump_json(by_alias=True))

    bundle1 = build_bundle_files(sc1_file, plan1, ppp_file, home_file).bundle
    bundle2 = build_bundle_files(sc2_file, plan2, ppp_file, home_file).bundle

    sim1 = simulate_bundle(bundle1)
    sim2 = simulate_bundle(bundle2, initial_world_state=sim1.trace.final_state)

    sensor_model = deploy_sensors(bundle1).sensor_model
    proj1 = project_sensors(sim1.trace, bundle1, sensor_model)
    proj2 = project_sensors(sim2.trace, bundle2, sensor_model)

    agg_trace = aggregate_execution_traces("test_run", 1, [sim1.trace, sim2.trace])
    assert agg_trace.started_at == sim1.trace.started_at
    assert agg_trace.ended_at == sim2.trace.ended_at
    assert agg_trace.final_state == sim2.trace.final_state
    assert len(agg_trace.activity_executions) == len(sim1.trace.activity_executions) + len(sim2.trace.activity_executions)

    agg_log = aggregate_sensor_logs([proj1.observable_log, proj2.observable_log])
    assert agg_log.started_at == proj1.observable_log.started_at
    assert agg_log.ended_at == proj2.observable_log.ended_at
    assert len(agg_log.records) == len(proj1.observable_log.records) + len(proj2.observable_log.records)

    agg_oracle = aggregate_oracle_mappings(agg_trace, agg_log, [proj1.oracle_mapping, proj2.oracle_mapping])
    assert agg_oracle.observable_log_id == agg_log.log_id
    assert agg_oracle.source_trace_id == agg_trace.trace_id
    assert len(agg_oracle.links) == len(proj1.oracle_mapping.links) + len(proj2.oracle_mapping.links)

    # Rejection of non-chronological order
    with pytest.raises(ValueError, match="is before"):
        aggregate_execution_traces("test_run", 1, [sim2.trace, sim1.trace])


def test_run_longitudinal_file_full_orchestration_and_resume(tmp_path: Path) -> None:
    sc1_dict = _make_minimal_scenario(
        start="2026-10-12T00:00:00+02:00",
        end="2026-10-13T00:00:00+02:00",
        initial_at="2026-10-12T00:00:00+02:00",
        activity_prefix="c1_",
        seed=1,
    )
    sc2_dict = _make_minimal_scenario(
        start="2026-10-13T00:00:00+02:00",
        end="2026-10-14T00:00:00+02:00",
        initial_at="2026-10-13T00:00:00+02:00",
        activity_prefix="c2_",
        seed=1,
    )
    ppp_dict = _make_ppp()

    sc1_file = tmp_path / "sc1.json"
    sc2_file = tmp_path / "sc2.json"
    ppp_file = tmp_path / "ppp.json"
    sc1_file.write_text(json.dumps(sc1_dict), encoding="utf-8")
    sc2_file.write_text(json.dumps(sc2_dict), encoding="utf-8")
    ppp_file.write_text(json.dumps(ppp_dict), encoding="utf-8")

    manifest_data = {
        "schemaVersion": "1.0.0",
        "documentType": "longitudinal_simulation_manifest",
        "runId": "full_test_run",
        "scenarioPaths": ["sc1.json", "sc2.json"],
        "personalProcessPackagePath": "ppp.json",
        "seed": 1,
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    output_dir = tmp_path / "run_out"

    # Full orchestration run
    report = run_longitudinal_file(manifest_file, output_directory=output_dir)
    assert report.success is True
    assert len(report.chunks) == 2
    assert (output_dir / "home-model.json").is_file()
    assert (output_dir / "sensor-model.json").is_file()
    assert (output_dir / "checkpoint.json").is_file()
    assert (output_dir / "run.json").is_file()
    assert (output_dir / "chunks/0001/execution-trace.json").is_file()
    assert (output_dir / "chunks/0002/execution-trace.json").is_file()
    assert (output_dir / "aggregate/execution-trace.json").is_file()
    assert (output_dir / "aggregate/observable-sensor-log.json").is_file()
    assert (output_dir / "aggregate/oracle-mapping.json").is_file()
    assert (output_dir / "workspace-manifest.json").is_file()

    # Replay verification
    verify_res = verify_longitudinal_run(output_dir)
    assert verify_res.matches is True

    # Resumption test: modify chunk 2 completed record to test resume
    cp_text = (output_dir / "checkpoint.json").read_text(encoding="utf-8")
    cp_data = json.loads(cp_text)
    cp_data["completedChunkCount"] = 1
    cp_data["chunks"] = cp_data["chunks"][:1]
    (output_dir / "checkpoint.json").write_text(json.dumps(cp_data), encoding="utf-8")

    resume_report = run_longitudinal_file(manifest_file, output_directory=output_dir, resume=True)
    assert resume_report.success is True
    assert len(resume_report.chunks) == 2

    # Tampered checkpoint test
    cp_data["manifestSha256"] = "0" * 64
    (output_dir / "checkpoint.json").write_text(json.dumps(cp_data), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        run_longitudinal_file(manifest_file, output_directory=output_dir, resume=True)



