from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from smart_home_sim.domain.longitudinal import (
    LongitudinalCheckpoint,
    LongitudinalChunkRecord,
    LongitudinalSimulationIssue,
    LongitudinalSimulationManifest,
    LongitudinalSimulationReport,
)


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
