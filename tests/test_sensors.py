from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smart_home_sim.domain.environment import Point2D, Polygon2D, SimulationBundle
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.sensors import (
    ContactSensor,
    ObservableSensorLog,
    OracleMapping,
    OracleObservationLink,
    PirSensor,
    SensorErrorModel,
    SensorFailureWindow,
    SensorModel,
    SensorProjectionIssue,
    SensorProjectionResult,
    SensorTiming,
    TemperatureSensor,
    TemperatureSource,
)
from smart_home_sim.sensors import project_sensor_files
from smart_home_sim.sensors import project_sensors as project_sensors_with_bundle

ROOT = Path(__file__).parents[1]
TRACE_PATH = ROOT / "examples/execution/mario_week.execution-trace.json"
BUNDLE_PATH = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
MODEL_PATH = ROOT / "examples/sensors/mario_monteverde.sensor-model.json"
BUNDLE = SimulationBundle.model_validate_json(BUNDLE_PATH.read_text(encoding="utf-8"))


def project_sensors(trace: ExecutionTrace, model: SensorModel) -> SensorProjectionResult:
    return project_sensors_with_bundle(trace, BUNDLE, model)


@pytest.fixture(scope="module")
def trace() -> ExecutionTrace:
    return ExecutionTrace.model_validate_json(TRACE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sensor_model() -> SensorModel:
    return SensorModel.model_validate_json(MODEL_PATH.read_text(encoding="utf-8"))


def test_acceptance_projection_is_deterministic_and_separates_oracle(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    first = project_sensors(trace, sensor_model)
    second = project_sensors(trace, sensor_model)

    assert first == second
    assert first.report.success
    assert first.report.source_home_id == BUNDLE.home_model.home_id
    assert first.report.source_home_sha256 is not None
    assert first.observable_log is not None
    assert first.oracle_mapping is not None
    assert first.report.summary.sensor_count == 8
    assert first.report.summary.observation_count == len(first.observable_log.records)
    assert len(first.observable_log.records) == len(first.oracle_mapping.links)
    assert {item.sensor_type for item in first.observable_log.records} == {
        "pir",
        "contact",
        "temperature",
    }
    public = first.observable_log.model_dump(mode="json", by_alias=True)
    public_text = json.dumps(public)
    for forbidden in (
        "residentId",
        "activityExecutionId",
        "actionExecutionId",
        "causeId",
        trace.trace_id,
    ):
        assert forbidden not in public_text
    assert any(item.resident_ids for item in first.oracle_mapping.links)
    assert any(item.origin == "false_positive" for item in first.oracle_mapping.links)


def test_each_sensor_has_an_independent_random_stream(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    complete = project_sensors(trace, sensor_model).observable_log
    reduced_model = sensor_model.model_copy(update={"sensors": sensor_model.sensors[1:]})
    reduced = project_sensors(trace, reduced_model).observable_log
    assert complete is not None and reduced is not None
    removed_id = sensor_model.sensors[0].sensor_id
    assert [item for item in complete.records if item.sensor_id != removed_id] == reduced.records
    assert (
        trace.semantic_digest
        == ExecutionTrace.model_validate_json(
            TRACE_PATH.read_text(encoding="utf-8")
        ).semantic_digest
    )


def _one_sensor_model(sensor_model: SensorModel, sensor: object) -> SensorModel:
    return sensor_model.model_copy(update={"sensors": [sensor]})


def test_pir_coverage_polygon_and_cooldown(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    source = sensor_model.sensors[0]
    assert isinstance(source, PirSensor)
    outside = source.model_copy(
        update={
            "position": Point2D(x=100.25, y=100.25),
            "coverage": Polygon2D(
                vertices=[
                    Point2D(x=100, y=100),
                    Point2D(x=101, y=100),
                    Point2D(x=101, y=101),
                ]
            ),
            "error_model": SensorErrorModel(),
        }
    )
    empty = project_sensors(trace, _one_sensor_model(sensor_model, outside))
    assert empty.report.summary.observation_count == 0

    cooldown = source.model_copy(
        update={
            "timing": SensorTiming(cooldown_milliseconds=8 * 24 * 60 * 60 * 1000),
            "error_model": SensorErrorModel(),
        }
    )
    result = project_sensors(trace, _one_sensor_model(sensor_model, cooldown))
    assert result.report.summary.observation_count == 2
    assert result.report.summary.cooldown_suppressed_count > 0

    invalid_coverage = source.model_copy(
        update={
            "coverage": Polygon2D(
                vertices=[
                    Point2D(x=0, y=0),
                    Point2D(x=1, y=1),
                    Point2D(x=0, y=1),
                    Point2D(x=1, y=0),
                ]
            )
        }
    )
    invalid = project_sensors(trace, _one_sensor_model(sensor_model, invalid_coverage))
    assert invalid.report.issues[0].code == "HOME_SENSOR_MISMATCH"


def test_pir_detects_segment_crossing_without_a_waypoint_inside(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    source = sensor_model.sensors[0]
    assert isinstance(source, PirSensor)
    narrow = source.model_copy(
        update={
            "position": Point2D(x=5.8, y=8.75),
            "coverage": Polygon2D(
                vertices=[
                    Point2D(x=5.7, y=8.6),
                    Point2D(x=5.9, y=8.6),
                    Point2D(x=5.9, y=8.9),
                    Point2D(x=5.7, y=8.9),
                ]
            ),
            "timing": SensorTiming(),
            "error_model": SensorErrorModel(),
            "failure_windows": [],
        }
    )
    result = project_sensors(trace, _one_sensor_model(sensor_model, narrow))
    assert result.observable_log is not None
    waypoint_times = {
        waypoint.at for movement in trace.movements for waypoint in movement.waypoints
    }
    activations = [item for item in result.observable_log.records if item.value == "ON"]
    assert activations
    assert any(item.observed_at not in waypoint_times for item in activations)


def test_dropout_false_negative_failure_and_false_positive_counters(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    source = sensor_model.sensors[0]
    assert isinstance(source, PirSensor)
    dropout = source.model_copy(
        update={
            "error_model": SensorErrorModel(dropout_probability=1),
            "failure_windows": [],
        }
    )
    dropped = project_sensors(trace, _one_sensor_model(sensor_model, dropout))
    assert dropped.report.summary.observation_count == 0
    assert dropped.report.summary.dropout_count == dropped.report.summary.candidate_count

    paired_source = sensor_model.sensors[1]
    assert isinstance(paired_source, PirSensor)
    partial_dropout = paired_source.model_copy(
        update={
            "timing": SensorTiming(),
            "error_model": SensorErrorModel(dropout_probability=0.5),
            "failure_windows": [],
        }
    )
    paired = project_sensors(trace, _one_sensor_model(sensor_model, partial_dropout))
    assert paired.observable_log is not None and paired.oracle_mapping is not None
    values_by_cause: dict[str, set[object]] = {}
    for record, link in zip(
        paired.observable_log.records, paired.oracle_mapping.links, strict=True
    ):
        for cause_id in link.cause_ids:
            values_by_cause.setdefault(cause_id, set()).add(record.value)
    assert values_by_cause
    assert all(values != {"OFF"} for values in values_by_cause.values())

    false_negative = source.model_copy(
        update={
            "error_model": SensorErrorModel(false_negative_probability=1),
            "failure_windows": [],
        }
    )
    missed = project_sensors(trace, _one_sensor_model(sensor_model, false_negative))
    assert missed.report.summary.false_negative_count == missed.report.summary.candidate_count

    failed = source.model_copy(
        update={
            "error_model": SensorErrorModel(),
            "failure_windows": [
                SensorFailureWindow(starts_at=trace.started_at, ends_at=trace.ended_at)
            ],
        }
    )
    unavailable = project_sensors(trace, _one_sensor_model(sensor_model, failed))
    assert unavailable.report.summary.failure_suppressed_count > 0
    assert unavailable.report.summary.observation_count == 0

    false_positive = source.model_copy(
        update={
            "coverage": Polygon2D(
                vertices=[
                    Point2D(x=0.1, y=6.1),
                    Point2D(x=0.2, y=6.1),
                    Point2D(x=0.1, y=6.2),
                ]
            ),
            "position": Point2D(x=0.12, y=6.12),
            "error_model": SensorErrorModel(false_positive_probability_per_day=1),
            "failure_windows": [],
        }
    )
    noisy = project_sensors(trace, _one_sensor_model(sensor_model, false_positive))
    assert noisy.report.summary.false_positive_count == 16
    assert noisy.observable_log is not None
    assert all(item.quality == "noisy" for item in noisy.observable_log.records)


def test_contact_and_temperature_semantics(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    contact = next(
        item
        for item in sensor_model.sensors
        if isinstance(item, ContactSensor) and item.fact is not None
    )
    contact = contact.model_copy(update={"error_model": SensorErrorModel()})
    contact_result = project_sensors(trace, _one_sensor_model(sensor_model, contact))
    assert contact_result.observable_log is not None
    assert {item.value for item in contact_result.observable_log.records} == {"OPEN", "CLOSED"}
    timed_contact = contact.model_copy(
        update={
            "timing": SensorTiming(
                latency_milliseconds=100,
                clock_jitter_milliseconds=10,
            )
        }
    )
    timed_result = project_sensors(trace, _one_sensor_model(sensor_model, timed_contact))
    assert timed_result.observable_log is not None and timed_result.oracle_mapping is not None
    transition_times = {item.transition_id: item.at for item in trace.state_transitions}
    records_by_id = {item.observation_id: item for item in timed_result.observable_log.records}
    for link in timed_result.oracle_mapping.links:
        latency = (
            records_by_id[link.observation_id].observed_at - transition_times[link.cause_ids[0]]
        ).total_seconds()
        assert 0.09 <= latency <= 0.11
    contact_with_noise = contact.model_copy(
        update={"error_model": SensorErrorModel(false_positive_probability_per_day=1)}
    )
    contact_noise = project_sensors(trace, _one_sensor_model(sensor_model, contact_with_noise))
    assert contact_noise.report.summary.false_positive_count == 8

    door = next(
        item
        for item in sensor_model.sensors
        if isinstance(item, ContactSensor) and item.fact is None
    )
    door = door.model_copy(update={"error_model": SensorErrorModel(), "timing": SensorTiming()})
    door_result = project_sensors(trace, _one_sensor_model(sensor_model, door))
    assert door_result.observable_log is not None and door_result.oracle_mapping is not None
    assert len(door_result.observable_log.records) == 52
    assert [item.value for item in door_result.observable_log.records[:2]] == ["OPEN", "CLOSED"]
    assert (
        door_result.observable_log.records[1].observed_at
        - door_result.observable_log.records[0].observed_at
    ).total_seconds() == pytest.approx(1)
    assert {item.cause_type for item in door_result.oracle_mapping.links} == {"action_execution"}

    temperature = next(item for item in sensor_model.sensors if isinstance(item, TemperatureSensor))
    curve_temperature = temperature.model_copy(
        update={"error_model": SensorErrorModel(), "timing": SensorTiming()}
    )
    curve_result = project_sensors(trace, _one_sensor_model(sensor_model, curve_temperature))
    assert curve_result.observable_log is not None
    curve_values = [float(item.value) for item in curve_result.observable_log.records]
    assert len(curve_values) == 113
    assert curve_values[0] == pytest.approx(20.5)
    assert max(curve_values) == pytest.approx(22.9)
    assert curve_values[-1] == pytest.approx(20.5)

    temperature = temperature.model_copy(
        update={
            "error_model": SensorErrorModel(measurement_noise_standard_deviation=0.1),
            "timing": SensorTiming(),
        }
    )
    temperature_result = project_sensors(trace, _one_sensor_model(sensor_model, temperature))
    assert temperature_result.observable_log is not None
    values = [float(item.value) for item in temperature_result.observable_log.records]
    assert len(values) == 113
    assert min(values) < max(values)
    assert all(item.unit == "celsius" for item in temperature_result.observable_log.records)
    temperature_with_noise = temperature.model_copy(
        update={"error_model": SensorErrorModel(false_positive_probability_per_day=1)}
    )
    temperature_noise = project_sensors(
        trace, _one_sensor_model(sensor_model, temperature_with_noise)
    )
    assert temperature_noise.report.summary.false_positive_count == 8


def test_projection_rejects_mismatched_or_tampered_trace(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    wrong_model = sensor_model.model_copy(update={"source_bundle_id": "other"})
    mismatch = project_sensors(trace, wrong_model)
    assert mismatch.observable_log is None
    assert mismatch.report.issues[0].code == "MODEL_TRACE_MISMATCH"

    tampered = trace.model_copy(update={"seed": trace.seed + 1})
    invalid = project_sensors(tampered, sensor_model)
    assert invalid.oracle_mapping is None
    assert {item.code for item in invalid.report.issues} == {
        "BUNDLE_TRACE_MISMATCH",
        "MODEL_TRACE_MISMATCH",
        "TRACE_DIGEST_MISMATCH",
    }

    wrong_digest = sensor_model.model_copy(update={"source_bundle_sha256": "0" * 64})
    digest_mismatch = project_sensors(trace, wrong_digest)
    assert digest_mismatch.report.issues[0].code == "MODEL_TRACE_MISMATCH"

    wrong_seed = sensor_model.model_copy(update={"seed": trace.seed + 1})
    seed_mismatch = project_sensors(trace, wrong_seed)
    assert seed_mismatch.report.issues[0].path == "$.seed"

    wrong_bundle = BUNDLE.model_copy(update={"seed": BUNDLE.seed + 1})
    bundle_mismatch = project_sensors_with_bundle(trace, wrong_bundle, sensor_model)
    assert bundle_mismatch.report.issues[0].code == "BUNDLE_TRACE_MISMATCH"


def test_sensor_placement_is_validated_against_source_home(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    source = sensor_model.sensors[0]
    assert isinstance(source, PirSensor)
    crossing_wall = source.model_copy(
        update={
            "coverage": Polygon2D(
                vertices=[
                    Point2D(x=-1, y=6),
                    Point2D(x=7, y=6),
                    Point2D(x=7, y=12),
                    Point2D(x=-1, y=12),
                ]
            )
        }
    )
    invalid_coverage = project_sensors(trace, _one_sensor_model(sensor_model, crossing_wall))
    assert invalid_coverage.observable_log is None
    assert invalid_coverage.report.issues[0].code == "HOME_SENSOR_MISMATCH"
    assert invalid_coverage.report.issues[0].path.endswith(".coverage")

    contact = next(item for item in sensor_model.sensors if isinstance(item, ContactSensor))
    misplaced_contact = contact.model_copy(update={"position": Point2D(x=2, y=9)})
    invalid_contact = project_sensors(trace, _one_sensor_model(sensor_model, misplaced_contact))
    assert invalid_contact.report.issues[0].code == "HOME_SENSOR_MISMATCH"
    assert invalid_contact.report.issues[0].path.endswith(".position")

    incomplete_catalog = sensor_model.model_copy(
        update={"region_ids": sensor_model.region_ids[:-1]}
    )
    invalid_catalog = project_sensors(trace, incomplete_catalog)
    assert invalid_catalog.report.issues[0].path == "$.regionIds"


def test_sensor_model_rejects_unknown_references(sensor_model: SensorModel) -> None:
    payload = sensor_model.model_dump(mode="json", by_alias=True)
    payload["sensors"][0]["regionIds"] = ["unknown"]
    with pytest.raises(ValidationError):
        SensorModel.model_validate(payload)
    payload = sensor_model.model_dump(mode="json", by_alias=True)
    contact = next(item for item in payload["sensors"] if item["sensorType"] == "contact")
    contact["entityId"] = "unknown"
    with pytest.raises(ValidationError):
        SensorModel.model_validate(payload)


def test_projection_failure_does_not_publish_partial_artifacts(
    trace: ExecutionTrace, sensor_model: SensorModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> None:
        raise ValueError("synthetic projection failure")

    monkeypatch.setattr("smart_home_sim.sensors.service._project_sensor", fail)
    result = project_sensors(trace, sensor_model)
    assert result.observable_log is None
    assert result.oracle_mapping is None
    assert result.report.issues[0].code == "PROJECTION_FAILED"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("{bad", "JSON_SYNTAX"),
        ("[]", "STRUCTURE_INVALID"),
        ('{"schemaVersion":"9.0.0"}', "UNSUPPORTED_SCHEMA_VERSION"),
        ('{"schemaVersion":"1.0.0"}', "STRUCTURE_INVALID"),
        ('{"schemaVersion":"1.0.0","schemaVersion":"1.0.0"}', "JSON_SYNTAX"),
        ('{"schemaVersion":NaN}', "JSON_SYNTAX"),
    ],
)
def test_sensor_file_loader_reports_invalid_model(tmp_path: Path, content: str, code: str) -> None:
    path = tmp_path / "model.json"
    path.write_text(content, encoding="utf-8")
    result = project_sensor_files(TRACE_PATH, BUNDLE_PATH, path)
    assert result.report.issues[0].code == code


def test_sensor_file_loader_reports_io_encoding_depth_and_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert project_sensor_files(tmp_path / "missing", BUNDLE_PATH, MODEL_PATH).report.issues[
        0
    ].code == ("FILE_NOT_FOUND")
    assert project_sensor_files(tmp_path, BUNDLE_PATH, MODEL_PATH).report.issues[0].code == (
        "FILE_READ_ERROR"
    )
    encoded = tmp_path / "encoded.json"
    encoded.write_bytes(b"\xff")
    assert project_sensor_files(TRACE_PATH, BUNDLE_PATH, encoded).report.issues[0].code == (
        "FILE_ENCODING_ERROR"
    )
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 300 + "]" * 300, encoding="utf-8")
    assert project_sensor_files(TRACE_PATH, BUNDLE_PATH, deep).report.issues[0].code == (
        "JSON_NESTING_TOO_DEEP"
    )
    monkeypatch.setattr("smart_home_sim.sensors.service.MAX_SCENARIO_BYTES", 0)
    assert project_sensor_files(TRACE_PATH, BUNDLE_PATH, MODEL_PATH).report.issues[0].code == (
        "FILE_TOO_LARGE"
    )


def test_sensor_contract_validators() -> None:
    point = Point2D(x=0, y=0)
    with pytest.raises(ValidationError):
        SensorModel(
            sensor_model_id="m",
            sensor_model_version="1",
            source_bundle_id="b",
            source_bundle_sha256="0" * 64,
            seed=1,
            region_ids=["r"],
            entity_ids=["e"],
            sensors=[
                PirSensor(sensor_id="same", position=point, region_ids=["r"]),
                PirSensor(sensor_id="same", position=point, region_ids=["r"]),
            ],
        )
    with pytest.raises(ValidationError):
        PirSensor(sensor_id="p", position=point, region_ids=["r", "r"])
    with pytest.raises(ValidationError):
        PirSensor(
            sensor_id="p",
            position=point,
            region_ids=["r"],
            coverage=Polygon2D(vertices=[Point2D(x=0, y=0), Point2D(x=1, y=0), Point2D(x=0, y=1)]),
            error_model=SensorErrorModel(measurement_noise_standard_deviation=1),
        )
    with pytest.raises(ValidationError):
        ContactSensor(
            sensor_id="c", position=point, entity_id="e", open_value=True, closed_value=True
        )
    with pytest.raises(ValidationError):
        ContactSensor(
            sensor_id="c",
            position=point,
            entity_id="e",
            error_model=SensorErrorModel(measurement_noise_standard_deviation=1),
        )
    with pytest.raises(ValidationError):
        TemperatureSensor(
            sensor_id="t",
            position=point,
            region_id="r",
            baseline_celsius=20,
            sources=[
                TemperatureSource(entity_id="e", fact="active", delta_celsius=1),
                TemperatureSource(entity_id="e", fact="active", delta_celsius=2),
            ],
        )
    with pytest.raises(ValidationError):
        SensorFailureWindow(starts_at="2026-01-02T00:00:00Z", ends_at="2026-01-01T00:00:00Z")
    with pytest.raises(ValidationError):
        SensorProjectionIssue(code="UNKNOWN", stage="input", path="$", message="invalid")


def test_public_artifact_contracts_reject_inconsistent_content(
    trace: ExecutionTrace, sensor_model: SensorModel
) -> None:
    result = project_sensors(trace, sensor_model)
    assert result.observable_log is not None and result.oracle_mapping is not None
    payload = result.observable_log.model_dump(mode="json", by_alias=True)
    payload["records"][0]["measurement"] = "motion"
    with pytest.raises(ValidationError):
        ObservableSensorLog.model_validate(payload)
    payload = result.observable_log.model_dump(mode="json", by_alias=True)
    payload["semanticDigest"] = "0" * 64
    with pytest.raises(ValidationError):
        ObservableSensorLog.model_validate(payload)
    record = result.observable_log.records[0]
    with pytest.raises(ValidationError):
        ObservableSensorLog(
            log_id="sensor_log_0000000000000000",
            sensor_model_id="m",
            sensor_model_version="1",
            started_at=record.observed_at,
            ended_at=record.observed_at,
            records=[record, record],
            semantic_digest="0" * 64,
        )
    oracle_payload = result.oracle_mapping.model_dump(mode="json", by_alias=True)
    oracle_payload["links"].append(oracle_payload["links"][0])
    with pytest.raises(ValidationError):
        OracleMapping.model_validate(oracle_payload)
    with pytest.raises(ValidationError):
        OracleObservationLink(
            observation_id="o",
            origin="false_positive",
            cause_type="movement",
            cause_ids=["movement"],
        )
