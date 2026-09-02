from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from smart_home_sim.domain.application import (
    ApplicationReplayContract,
    ExportManifest,
    JobRecord,
    ObservableApplicationReplayContract,
    ObservableReplayResidentFrame,
    ObservableReplaySensorFrame,
    ObservationCause,
    ReplayEventView,
    ReplayEventWindow,
    ReplayFilters,
    ReplayFrame,
    ReplayResidentFrame,
    ReplaySensorFrame,
    ReplaySessionState,
    ReplayVerification,
    WorkspaceManifest,
    _is_observable_replay_redacted_key,
)
from smart_home_sim.domain.authoring import (
    AUTHORING_ISSUE_CODES,
    AuthoringIngestionReport,
    AuthoringRepairRequest,
    SimulationAuthoringBundle,
)
from smart_home_sim.domain.batch import SimulationBatchManifest, SimulationBatchReport
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    VariableCatalog,
)
from smart_home_sim.domain.behavior_report import (
    BEHAVIOR_ISSUE_CODES,
    BehaviorValidationReport,
)
from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES, CompilationReport
from smart_home_sim.domain.environment import (
    ENVIRONMENT_ISSUE_CODES,
    EnvironmentValidationReport,
    HomeModel,
    SimulationBundle,
)
from smart_home_sim.domain.materialization import (
    EnvironmentMaterializationManifest,
    SyntheticWorkspaceManifest,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.profile import ResidentProfile
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.domain.sensors import (
    ObservableSensorLog,
    OracleMapping,
    SensorModel,
    SensorProjectionReport,
)
from smart_home_sim.hybrid_planning.outline import (
    HabitGroundTruth,
    HorizonAuthoringBundle,
    HorizonOutline,
)
from smart_home_sim.validation.codes import STABLE_ISSUE_CODES

PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas/scenario-1.0.0.schema.json"
REPORT_SCHEMA_PATH = PROJECT_ROOT / "schemas/validation-report-1.0.0.schema.json"
PLAN_SCHEMA_PATH = PROJECT_ROOT / "schemas/canonical-plan-1.0.0.schema.json"
COMPILATION_SCHEMA_PATH = PROJECT_ROOT / "schemas/compilation-report-1.0.0.schema.json"
BEHAVIOR_SCHEMAS = {
    "activity-catalog-1.0.0.schema.json": ActivityCatalog,
    "variable-catalog-1.0.0.schema.json": VariableCatalog,
    "action-catalog-1.0.0.schema.json": ActionCatalog,
    "personal-process-package-1.0.0.schema.json": PersonalProcessPackage,
    "behavior-validation-report-1.0.0.schema.json": BehaviorValidationReport,
}
AUTHORING_SCHEMAS = {
    "simulation-authoring-bundle-1.0.0.schema.json": SimulationAuthoringBundle,
    "authoring-ingestion-report-1.1.0.schema.json": AuthoringIngestionReport,
    "authoring-repair-request-1.0.0.schema.json": AuthoringRepairRequest,
}
OUTLINE_SCHEMAS = {
    "horizon-outline-1.0.0.schema.json": HorizonOutline,
    "horizon-authoring-bundle-1.0.0.schema.json": HorizonAuthoringBundle,
    "habit-ground-truth-1.2.0.schema.json": HabitGroundTruth,
}
HISTORICAL_AUTHORING_REPORT_SCHEMA = (
    PROJECT_ROOT / "schemas/authoring-ingestion-report-1.0.0.schema.json"
)
ENVIRONMENT_SCHEMAS = {
    "home-model-1.0.0.schema.json": HomeModel,
    "environment-validation-report-1.0.0.schema.json": EnvironmentValidationReport,
    "simulation-bundle-1.0.0.schema.json": SimulationBundle,
}
BATCH_SCHEMAS = {
    "simulation-batch-manifest-1.0.0.schema.json": SimulationBatchManifest,
    "simulation-batch-report-1.0.0.schema.json": SimulationBatchReport,
}
SENSOR_SCHEMAS = {
    "sensor-model-1.0.0.schema.json": SensorModel,
    "observable-sensor-log-1.0.0.schema.json": ObservableSensorLog,
    "oracle-mapping-1.0.0.schema.json": OracleMapping,
    "sensor-projection-report-1.0.0.schema.json": SensorProjectionReport,
}
MATERIALIZATION_SCHEMAS = {
    "synthetic-workspace-manifest-1.0.0.schema.json": SyntheticWorkspaceManifest,
    "environment-materialization-manifest-1.0.0.schema.json": EnvironmentMaterializationManifest,
}
APPLICATION_SCHEMAS = {
    "application-workspace-manifest-1.0.0.schema.json": WorkspaceManifest,
    "application-job-1.0.0.schema.json": JobRecord,
    "application-export-manifest-1.1.0.schema.json": ExportManifest,
    "application-replay-1.0.0.schema.json": ReplayVerification,
    "application-replay-1.1.0.schema.json": ApplicationReplayContract,
    "resident-profile-1.0.0.schema.json": ResidentProfile,
}
# Exports written before the resident profile existed declare 1.0.0 and are still readable, so the
# schema that described them stays published beside the current one.
HISTORICAL_EXPORT_MANIFEST_SCHEMA = (
    PROJECT_ROOT / "schemas/application-export-manifest-1.0.0.schema.json"
)


def test_application_replay_contract_covers_windows_frames_and_sessions() -> None:
    schema = ReplayFrame.model_json_schema(by_alias=True)
    assert {"runId", "at", "traceStart", "traceEnd", "residents", "sensorStates"} <= set(
        schema["required"]
    )
    assert ReplayEventWindow.model_fields["items"].annotation is not None
    filters = ReplayFilters.model_validate(
        {
            "eventKinds": ["movement", "observation"],
            "detailMode": "analysis",
            "visibilityMode": "observable",
            "speed": 4,
        }
    )
    session = ReplaySessionState.model_validate_json(
        json.dumps(
            {
                "runId": "run_1",
                "verifiedDigest": "a" * 64,
                "positionAt": "2026-08-23T08:00:00+00:00",
                "filters": filters.model_dump(by_alias=True),
            }
        )
    )
    assert session.filters.speed == 4


_REPLAY_AT = datetime(2026, 8, 23, 8, tzinfo=UTC)
_REPLAY_DIGEST = "a" * 64


def _verified_replay_contract(*, playable: bool = True) -> ApplicationReplayContract:
    return ApplicationReplayContract(
        verification=ReplayVerification(
            run_id="run_1",
            verified_at=_REPLAY_AT,
            matches=True,
            expected_semantic_digest=_REPLAY_DIGEST,
            actual_semantic_digest=_REPLAY_DIGEST,
        ),
        event_window=ReplayEventWindow(
            items=[
                ReplayEventView(
                    at=_REPLAY_AT,
                    kind="movement",
                    event_id="movement_1",
                    label="Kitchen to bedroom",
                    actor_id="resident_1",
                )
            ],
            total=1,
            trace_start=_REPLAY_AT,
            trace_end=_REPLAY_AT,
            window_start=_REPLAY_AT,
            window_end=_REPLAY_AT,
        ),
        frame=ReplayFrame(
            run_id="run_1",
            at=_REPLAY_AT,
            trace_start=_REPLAY_AT,
            trace_end=_REPLAY_AT,
            residents=[
                ReplayResidentFrame(
                    resident_id="resident_1",
                    execution_state="executing",
                    activity_execution_id="activity_1",
                    action_execution_id="action_1",
                )
            ],
            sensor_states=[
                ReplaySensorFrame(
                    observation_id="observation_1",
                    sensor_id="sensor_1",
                    sensor_type="pir",
                    observed_at=_REPLAY_AT,
                    measurement="motion",
                    value=True,
                    quality="measured",
                    oracle_cause=ObservationCause(
                        origin="simulation",
                        cause_type="movement",
                        cause_ids=["movement_1"],
                        resident_ids=["resident_1"],
                        activity_execution_ids=["activity_1"],
                        action_execution_ids=["action_1"],
                    ),
                )
            ],
        ),
        session=ReplaySessionState(
            run_id="run_1",
            verified_digest=_REPLAY_DIGEST,
            playable=playable,
        ),
    )


def test_observable_replay_payload_excludes_identity_and_oracle_fields() -> None:
    payload = _verified_replay_contract().playback_payload()

    assert isinstance(payload, ObservableApplicationReplayContract)
    event = payload.event_window.items[0].model_dump(by_alias=True)
    resident = payload.frame.residents[0].model_dump(by_alias=True)
    sensor = payload.frame.sensor_states[0].model_dump(by_alias=True)
    filters = payload.session.filters.model_dump(by_alias=True)
    assert "actorId" not in event
    assert {"residentId", "activityExecutionId", "actionExecutionId"}.isdisjoint(resident)
    assert "oracleCause" not in sensor
    assert {"actorIds", "selectedResidentId"}.isdisjoint(filters)
    schema = ObservableApplicationReplayContract.model_json_schema(by_alias=True)
    assert "actorId" not in schema["$defs"]["ObservableReplayEventView"]["properties"]
    assert "residentId" not in schema["$defs"]["ObservableReplayResidentFrame"]["properties"]
    assert "oracleCause" not in schema["$defs"]["ObservableReplaySensorFrame"]["properties"]


def test_observable_resident_frame_keeps_activity_state_without_raw_activity_label() -> None:
    raw = ReplayResidentFrame(
        resident_id="resident_1",
        execution_state="performing_activity",
        activity_active=True,
        activity_label="Prepare breakfast",
    )
    observable = ObservableReplayResidentFrame.from_resident(raw).model_dump(by_alias=True)

    assert raw.activity_label == "Prepare breakfast"
    assert observable["activityActive"] is True
    assert "activityLabel" not in observable


def test_oracle_replay_payload_requires_explicit_opt_in() -> None:
    payload = _verified_replay_contract().playback_payload(include_oracle=True)

    assert isinstance(payload, ApplicationReplayContract)
    assert payload.event_window.items[0].actor_id == "resident_1"
    assert payload.frame.residents[0].resident_id == "resident_1"
    assert payload.frame.sensor_states[0].oracle_cause is not None


def test_observable_replay_payload_never_serializes_raw_event_labels() -> None:
    contract = _verified_replay_contract()
    raw_label = "Mario carries groceries to the bedroom"
    contract.event_window.items[0].label = raw_label
    contract.event_window.items.append(
        ReplayEventView(
            at=_REPLAY_AT,
            kind="activity",
            event_id="activity_1",
            label="Mario prepares dinner",
            actor_id="resident_1",
        )
    )

    observable = contract.playback_payload().model_dump(mode="json", by_alias=True)
    oracle = contract.playback_payload(include_oracle=True).model_dump(mode="json", by_alias=True)

    assert raw_label not in json.dumps(observable)
    assert "Mario prepares dinner" not in json.dumps(observable)
    assert [item["label"] for item in observable["eventWindow"]["items"]] == [
        "Movement event",
        "Activity event",
    ]
    assert raw_label in json.dumps(oracle)
    assert "Mario prepares dinner" in json.dumps(oracle)


def test_observable_replay_payload_sanitizes_nested_sensitive_metadata() -> None:
    contract = _verified_replay_contract()
    contract.event_window.items[0].details = {
        "safeLabel": "resident_1",
        "actorId": "resident_1",
        "nested": {
            "activity_execution_ids": ["activity_1"],
            "items": ["action_1", {"oracleCause": {"causeIds": ["movement_1"]}}],
        },
    }
    contract.frame.residents[0].facts = {
        "resident_id": "resident_1",
        "safe": {"actionExecutionId": "action_1", "label": "action_1"},
    }
    contract.frame.entity_states.update(
        {
            "entity_1": {
                "actor_id": "resident_1",
                "nested": [{"residentIds": ["resident_1"]}],
            }
        }
    )
    contract.frame.environment_facts.update(
        {
            "oracle_cause": {"causeIds": ["movement_1"]},
            "notes": ["resident_1", {"action_execution_id": "action_1"}],
        }
    )
    contract.frame.active_event_ids.extend(["activity_1", "benign-event"])

    payload = contract.playback_payload().model_dump(by_alias=True)

    assert payload["eventWindow"]["items"][0]["details"] == {
        "safeLabel": "resident_1",
        "nested": {"items": ["action_1", {}]},
    }
    assert payload["frame"]["residents"][0]["facts"] == {"safe": {"label": "action_1"}}
    assert payload["frame"]["entityStates"] == {"entity_1": {"nested": [{}]}}
    assert payload["frame"]["environmentFacts"] == {"notes": ["resident_1", {}]}
    assert "activeEventIds" not in payload["frame"]


def test_observable_replay_payload_sanitizes_normalized_identity_key_variants() -> None:
    contract = _verified_replay_contract()
    contract.event_window.items[0].details = {
        "activityId": "activity_1",
        "source_activity_ids": ["activity_2"],
        "heldResourceIds": ["cup_1"],
        "activityCount": 2,
        "nested": [
            {"ACTION-ID": "action_1"},
            {"sourceActionIds": ["action_2"]},
            {"actionable": True},
        ],
    }
    contract.frame.residents[0].facts = {
        "residentIds": ["resident_1"],
        "source-resident-id": "resident_2",
        "residentCount": 2,
        "nested": {"actor_ids": ["resident_1"], "actorLabel": "primary"},
    }
    contract.frame.entity_states.update(
        {
            "entity_1": {
                "activity_id": "activity_1",
                "source-activity-id": "activity_2",
                "nested": [{"action_ids": ["action_1"]}, {"activityLabel": "cook"}],
            }
        }
    )
    contract.frame.environment_facts.update(
        {
            "actor_id": "resident_1",
            "causeIds": ["movement_1"],
            "held_resource_ids": ["cup_1"],
            "nested": [{"source_action_id": "action_1"}, {"sourceActionCount": 1}],
        }
    )

    payload = contract.playback_payload().model_dump(by_alias=True)

    assert payload["eventWindow"]["items"][0]["details"] == {
        "heldResourceIds": ["cup_1"],
        "activityCount": 2,
        "nested": [{}, {}, {"actionable": True}],
    }
    assert payload["frame"]["residents"][0]["facts"] == {
        "residentCount": 2,
        "nested": {"actorLabel": "primary"},
    }
    assert payload["frame"]["entityStates"] == {
        "entity_1": {"nested": [{}, {"activityLabel": "cook"}]}
    }
    assert payload["frame"]["environmentFacts"] == {
        "held_resource_ids": ["cup_1"],
        "nested": [{}, {"sourceActionCount": 1}],
    }


@pytest.mark.parametrize(
    "key",
    [
        "sourceActivityExecutionIds",
        "source_action_execution_id",
        "targetResidentIdList",
        "parentActionIdentifier",
        "currentActorIdentities",
        "executionIdentifier",
        "sourceCauseIds",
        "oracleCause",
        "source_activity_execution_ids_list",
        "target-resident-ids-list",
        "parentActionExecutionIdsList",
        "causalLink",
        "causalLinks",
        "source_causal_links",
        "sourceCausalLinkCauseIds",
        "causal_link_oracle_cause_ids",
    ],
)
def test_observable_replay_classifier_redacts_semantic_identity_and_cause_keys(
    key: str,
) -> None:
    assert _is_observable_replay_redacted_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "interactionId",
        "transactionId",
        "actionable",
        "activityLevel",
        "actionCount",
        "residentCount",
        "sensorId",
        "runId",
        "replayId",
        "expectedSemanticDigest",
        "heldResourceIds",
        "causalScore",
        "linkQuality",
        "causalLinkQuality",
    ],
)
def test_observable_replay_classifier_preserves_benign_and_operational_keys(key: str) -> None:
    assert not _is_observable_replay_redacted_key(key)


def test_observable_replay_payload_sanitizes_composed_identity_keys_at_any_depth() -> None:
    contract = _verified_replay_contract()
    contract.event_window.items[0].details = {
        "sourceActivityExecutionIds": ["activity_execution_1"],
        "sensorId": "sensor_1",
        "nested": [{"parentActionIdentifier": "action_1"}],
    }
    contract.frame.residents[0].facts = {
        "targetResidentIdList": ["resident_1"],
        "residentCount": 1,
    }
    contract.frame.entity_states.update(
        {
            "entity_1": {
                "nested": [{"source_action_execution_id": "action_execution_1"}],
                "interactionId": "interaction_1",
            }
        }
    )
    contract.frame.environment_facts.update(
        {
            "sourceCauseIds": ["movement_1"],
            "nested": [{"currentActorIdentities": ["resident_1"]}],
            "runId": "run_1",
        }
    )

    payload = contract.playback_payload().model_dump(by_alias=True)

    assert payload["eventWindow"]["items"][0]["details"] == {
        "sensorId": "sensor_1",
        "nested": [{}],
    }
    assert payload["frame"]["residents"][0]["facts"] == {"residentCount": 1}
    assert payload["frame"]["entityStates"] == {
        "entity_1": {"nested": [{}], "interactionId": "interaction_1"}
    }
    assert payload["frame"]["environmentFacts"] == {
        "nested": [{}],
        "runId": "run_1",
    }


def test_observable_replay_payload_sanitizes_id_lists_and_causal_links() -> None:
    contract = _verified_replay_contract()
    contract.event_window.items[0].details = {
        "source_activity_execution_ids_list": ["activity_execution_1"],
        "causalScore": 0.9,
    }
    contract.frame.residents[0].facts = {
        "target-resident-ids-list": ["resident_1"],
        "linkQuality": "high",
    }
    contract.frame.entity_states.update(
        {
            "entity_1": {
                "parentActionExecutionIdsList": ["action_execution_1"],
                "nested": [{"causalLink": {"causeIds": ["movement_1"]}}],
            }
        }
    )
    contract.frame.environment_facts.update(
        {
            "sourceCausalLinks": [{"causeIds": ["movement_1"]}],
            "nested": [{"causal-links": [{"causeIds": ["movement_2"]}]}],
            "causalScore": 0.8,
            "linkQuality": "measured",
        }
    )

    payload = contract.playback_payload().model_dump(by_alias=True)

    assert payload["eventWindow"]["items"][0]["details"] == {"causalScore": 0.9}
    assert payload["frame"]["residents"][0]["facts"] == {"linkQuality": "high"}
    assert payload["frame"]["entityStates"] == {"entity_1": {"nested": [{}]}}
    assert payload["frame"]["environmentFacts"] == {
        "nested": [{}],
        "causalScore": 0.8,
        "linkQuality": "measured",
    }


def test_observable_sensor_frame_sanitizes_nested_measurement_value() -> None:
    sensor = ReplaySensorFrame(
        observation_id="observation_1",
        sensor_id="sensor_1",
        sensor_type="temperature",
        observed_at=_REPLAY_AT,
        measurement="temperature",
        value={
            "actorId": "resident_1",
            "reading": {"celsius": 21.5, "causalLinkQuality": "measured"},
            "nested": [
                {"sourceCausalLinkCauseIds": ["movement_1"]},
                {"causal_link_oracle_cause_ids": ["movement_2"]},
                {"measurement": {"celsius": 22.0}},
            ],
        },
        quality="measured",
    )

    observable = ObservableReplaySensorFrame.from_raw(sensor)

    assert observable.value == {
        "reading": {"celsius": 21.5, "causalLinkQuality": "measured"},
        "nested": [{}, {}, {"measurement": {"celsius": 22.0}}],
    }
    assert ObservableReplaySensorFrame.from_sensor(sensor).value == observable.value


def test_replay_event_window_rejects_more_than_5000_items() -> None:
    item = ReplayEventView(
        at=_REPLAY_AT,
        kind="movement",
        event_id="movement_1",
        label="Kitchen to bedroom",
    )

    with pytest.raises(ValidationError, match="at most 5000 items"):
        ReplayEventWindow(
            items=[item] * 5001,
            total=5001,
            trace_start=_REPLAY_AT,
            trace_end=_REPLAY_AT,
            window_start=_REPLAY_AT,
            window_end=_REPLAY_AT,
        )


@pytest.mark.parametrize(
    ("verification", "session"),
    [
        (
            ReplayVerification(
                run_id="run_2",
                verified_at=_REPLAY_AT,
                matches=True,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest=_REPLAY_DIGEST,
            ),
            ReplaySessionState(run_id="run_1", verified_digest=_REPLAY_DIGEST, playable=True),
        ),
        (
            ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=False,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest="b" * 64,
            ),
            ReplaySessionState(run_id="run_1", verified_digest=_REPLAY_DIGEST, playable=True),
        ),
        (
            ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=True,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest=_REPLAY_DIGEST,
            ),
            ReplaySessionState(run_id="run_1", playable=True),
        ),
        (
            ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=True,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest=_REPLAY_DIGEST,
            ),
            ReplaySessionState(run_id="run_1", verified_digest="b" * 64, playable=True),
        ),
    ],
)
def test_playable_replay_session_requires_matching_verification(
    verification: ReplayVerification, session: ReplaySessionState
) -> None:
    contract = _verified_replay_contract(playable=False)

    with pytest.raises(ValidationError):
        ApplicationReplayContract(
            verification=verification,
            event_window=contract.event_window,
            frame=contract.frame,
            session=session,
        )


def test_playable_replay_session_requires_expected_and_actual_digests_to_match() -> None:
    contract = _verified_replay_contract(playable=False)

    with pytest.raises(ValidationError, match="expected"):
        ApplicationReplayContract(
            verification=ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=True,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest="b" * 64,
            ),
            event_window=contract.event_window,
            frame=contract.frame,
            session=ReplaySessionState(
                run_id="run_1",
                verified_digest="b" * 64,
                playable=True,
            ),
        )


def test_playable_replay_session_requires_frame_run_to_match_verification() -> None:
    contract = _verified_replay_contract(playable=False)
    frame = ReplayFrame(
        run_id="run_2",
        at=_REPLAY_AT,
        trace_start=_REPLAY_AT,
        trace_end=_REPLAY_AT,
        residents=contract.frame.residents,
        sensor_states=contract.frame.sensor_states,
    )

    with pytest.raises(ValidationError, match="frame run"):
        ApplicationReplayContract(
            verification=contract.verification,
            event_window=contract.event_window,
            frame=frame,
            session=ReplaySessionState(
                run_id="run_1", verified_digest=_REPLAY_DIGEST, playable=True
            ),
        )


def test_non_playable_replay_session_can_represent_unverified_state() -> None:
    verified = _verified_replay_contract(playable=False)
    contract = ApplicationReplayContract(
        verification=ReplayVerification(
            run_id="run_1",
            verified_at=_REPLAY_AT,
            matches=False,
            expected_semantic_digest=_REPLAY_DIGEST,
            actual_semantic_digest="b" * 64,
        ),
        event_window=verified.event_window,
        frame=verified.frame,
        session=ReplaySessionState(run_id="run_1", playable=False),
    )

    assert contract.session.playable is False


def test_playable_replay_session_cannot_bypass_verification_by_mutation() -> None:
    contract = _verified_replay_contract()

    with pytest.raises(ValidationError):
        contract.verification.matches = False
    with pytest.raises(ValidationError):
        contract.session.verified_digest = "b" * 64
    with pytest.raises(ValidationError):
        contract.session = ReplaySessionState(run_id="run_1", playable=False)
    with pytest.raises(ValidationError):
        contract.frame.run_id = "run_2"


@pytest.mark.parametrize(
    "update",
    [
        {
            "frame": ReplayFrame(
                run_id="run_2",
                at=_REPLAY_AT,
                trace_start=_REPLAY_AT,
                trace_end=_REPLAY_AT,
                residents=[],
                sensor_states=[],
            )
        },
        {
            "session": ReplaySessionState(
                run_id="run_2", verified_digest=_REPLAY_DIGEST, playable=True
            )
        },
        {
            "verification": ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=False,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest="b" * 64,
            )
        },
        {"session": ReplaySessionState(run_id="run_1", verified_digest="b" * 64, playable=True)},
        {
            "verification": ReplayVerification(
                run_id="run_1",
                verified_at=_REPLAY_AT,
                matches=True,
                expected_semantic_digest=_REPLAY_DIGEST,
                actual_semantic_digest="b" * 64,
            ),
            "session": ReplaySessionState(
                run_id="run_1",
                verified_digest="b" * 64,
                playable=True,
            ),
        },
    ],
)
def test_playable_replay_model_copy_revalidates_invariant_updates(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _verified_replay_contract().model_copy(update=update)


def test_playable_replay_model_copy_retains_normal_copy_semantics() -> None:
    contract = _verified_replay_contract()

    copied = contract.model_copy()
    deep_copied = contract.model_copy(deep=True)

    assert copied is not contract
    assert copied.frame is contract.frame
    assert deep_copied.frame is not contract.frame
    assert copied.session.playable is True


def load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_distributed_schema_is_valid_draft_2020_12() -> None:
    schema = load_schema()

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:smart-home-simulator:schema:scenario:1.0.0"


def test_distributed_schema_exactly_matches_the_models() -> None:
    assert load_schema() == Scenario.model_json_schema(by_alias=True)
    report_schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert report_schema == ValidationReport.model_json_schema(by_alias=True)
    Draft202012Validator.check_schema(report_schema)
    assert set(report_schema["$defs"]["ValidationIssue"]["properties"]["code"]["enum"]) == (
        STABLE_ISSUE_CODES
    )


def test_frozen_schema_checksums_match() -> None:
    for schema_path in (
        SCHEMA_PATH,
        REPORT_SCHEMA_PATH,
        PLAN_SCHEMA_PATH,
        COMPILATION_SCHEMA_PATH,
        *(PROJECT_ROOT / "schemas" / name for name in BEHAVIOR_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in AUTHORING_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in OUTLINE_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in ENVIRONMENT_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in BATCH_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in SENSOR_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in MATERIALIZATION_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in APPLICATION_SCHEMAS),
        HISTORICAL_AUTHORING_REPORT_SCHEMA,
        HISTORICAL_EXPORT_MANIFEST_SCHEMA,
    ):
        checksum_path = schema_path.with_suffix(".sha256")
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        assert b"\r\n" not in schema_path.read_bytes()
        assert sha256(schema_path.read_bytes()).hexdigest() == expected


def test_application_schemas_match_models_and_are_valid() -> None:
    for name, model in (APPLICATION_SCHEMAS | MATERIALIZATION_SCHEMAS).items():
        schema = json.loads((PROJECT_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)


def test_golden_report_satisfies_its_distributed_schema() -> None:
    schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(
        (PROJECT_ROOT / "tests/golden/unknown_references.report.json").read_text(encoding="utf-8")
    )

    assert list(Draft202012Validator(schema).iter_errors(report)) == []


def test_compiler_schemas_match_models_and_compiled_examples() -> None:
    plan_schema = json.loads(PLAN_SCHEMA_PATH.read_text())
    report_schema = json.loads(COMPILATION_SCHEMA_PATH.read_text())
    assert plan_schema == CanonicalPlan.model_json_schema(by_alias=True)
    assert report_schema == CompilationReport.model_json_schema(by_alias=True)
    Draft202012Validator.check_schema(plan_schema)
    Draft202012Validator.check_schema(report_schema)
    assert set(report_schema["$defs"]["CompilationIssue"]["properties"]["code"]["enum"]) == (
        COMPILATION_ISSUE_CODES
    )
    plan = json.loads((PROJECT_ROOT / "examples/compiled/mario_week.plan.json").read_text())
    report = json.loads(
        (PROJECT_ROOT / "examples/compiled/mario_week.compilation-report.json").read_text()
    )
    assert list(Draft202012Validator(plan_schema).iter_errors(plan)) == []
    assert list(Draft202012Validator(report_schema).iter_errors(report)) == []


def test_both_valid_examples_satisfy_distributed_schema() -> None:
    validator = Draft202012Validator(load_schema())

    for path in sorted((PROJECT_ROOT / "examples/valid").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert list(validator.iter_errors(payload)) == [], path


def test_distributed_schema_forbids_unknown_properties() -> None:
    validator = Draft202012Validator(load_schema())
    payload = json.loads((PROJECT_ROOT / "examples/valid/minimal.json").read_text())
    payload["typo"] = True

    assert any(
        error.validator == "additionalProperties" for error in validator.iter_errors(payload)
    )


def test_behavior_schemas_match_models_and_are_valid() -> None:
    for filename, model in BEHAVIOR_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/behavior-validation-report-1.0.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["BehaviorValidationIssue"]["properties"]["code"]["enum"])
        == BEHAVIOR_ISSUE_CODES
    )


def test_distributed_catalogs_and_behavior_examples_satisfy_schemas() -> None:
    catalog_files = {
        "activity-catalog-1.0.0.json": "activity-catalog-1.0.0.schema.json",
        "variable-catalog-1.0.0.json": "variable-catalog-1.0.0.schema.json",
        "action-catalog-1.0.0.json": "action-catalog-1.0.0.schema.json",
    }
    for catalog_name, schema_name in catalog_files.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / schema_name).read_text())
        payload = json.loads(
            (PROJECT_ROOT / "src/smart_home_sim/catalogs" / catalog_name).read_text()
        )
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    package_schema = json.loads(
        (PROJECT_ROOT / "schemas/personal-process-package-1.0.0.schema.json").read_text()
    )
    for path in sorted((PROJECT_ROOT / "examples/behavior").glob("*.json")):
        payload = json.loads(path.read_text())
        assert list(Draft202012Validator(package_schema).iter_errors(payload)) == [], path


def test_authoring_schemas_match_models_and_example_bundle() -> None:
    for filename, model in AUTHORING_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/authoring-ingestion-report-1.1.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["AuthoringIngestionIssue"]["properties"]["code"]["enum"])
        == AUTHORING_ISSUE_CODES
    )
    bundle_schema = json.loads(
        (PROJECT_ROOT / "schemas/simulation-authoring-bundle-1.0.0.schema.json").read_text()
    )
    bundle = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text()
    )
    assert list(Draft202012Validator(bundle_schema).iter_errors(bundle)) == []
    historical_report_schema = json.loads(
        HISTORICAL_AUTHORING_REPORT_SCHEMA.read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(historical_report_schema)
    assert historical_report_schema["properties"]["ingestorVersion"]["const"] == "1.0.0"


def test_environment_schemas_match_models_and_golden_artifacts() -> None:
    for filename, model in ENVIRONMENT_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/environment-validation-report-1.0.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["EnvironmentValidationIssue"]["properties"]["code"]["enum"])
        == ENVIRONMENT_ISSUE_CODES
    )
    artifacts = [
        ("home-model-1.0.0.schema.json", "examples/environment/mario_monteverde.home.json"),
        (
            "environment-validation-report-1.0.0.schema.json",
            "examples/bundles/mario_week.environment-report.json",
        ),
        (
            "simulation-bundle-1.0.0.schema.json",
            "examples/bundles/mario_week.simulation-bundle.json",
        ),
    ]
    for schema_name, artifact_name in artifacts:
        schema = json.loads((PROJECT_ROOT / "schemas" / schema_name).read_text())
        payload = json.loads((PROJECT_ROOT / artifact_name).read_text())
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_batch_schemas_match_models_and_manifest_example() -> None:
    for filename, model in BATCH_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    manifest_schema = json.loads(
        (PROJECT_ROOT / "schemas/simulation-batch-manifest-1.0.0.schema.json").read_text()
    )
    manifest = json.loads((PROJECT_ROOT / "examples/batch/mario_week.seed-sweep.json").read_text())
    assert list(Draft202012Validator(manifest_schema).iter_errors(manifest)) == []


def test_sensor_schemas_match_models_and_golden_artifacts() -> None:
    artifacts = {
        "sensor-model-1.0.0.schema.json": "mario_monteverde.sensor-model.json",
        "observable-sensor-log-1.0.0.schema.json": "mario_week.observable-sensor-log.json",
        "oracle-mapping-1.0.0.schema.json": "mario_week.oracle-mapping.json",
        "sensor-projection-report-1.0.0.schema.json": "mario_week.sensor-projection-report.json",
    }
    for filename, model in SENSOR_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
        payload = json.loads((PROJECT_ROOT / "examples/sensors" / artifacts[filename]).read_text())
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_outline_schemas_match_models_and_the_published_example() -> None:
    """The prompt embeds these, so a model drifting from its schema must break the build."""
    for name, model in OUTLINE_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)

    outline_schema = json.loads(
        (PROJECT_ROOT / "schemas/horizon-outline-1.0.0.schema.json").read_text(encoding="utf-8")
    )
    example = json.loads(
        (PROJECT_ROOT / "examples/authoring/meredith.horizon-outline.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(outline_schema).iter_errors(example)) == []
