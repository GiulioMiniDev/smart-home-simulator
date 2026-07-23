from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.hybrid_planning.behavioral_models import HabitLedger
from smart_home_sim.hybrid_planning.models import PlanningMemory


class QualityViolation(ContractModel):
    code: str = Field(min_length=1)
    date: date
    intent: str = Field(min_length=1)
    message: str = Field(min_length=1)


CausalViolation = QualityViolation


class LongitudinalQualityReport(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["longitudinal_planning_quality"] = (
        "longitudinal_planning_quality"
    )
    valid: bool
    day_count: int = Field(ge=0)
    maximum_consecutive_identical_days: int = Field(ge=0)
    optional_windows_without_variation: list[date] = Field(default_factory=list)
    causal_violations: list[QualityViolation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class LongitudinalChunkRecord(ContractModel):
    index: int = Field(ge=1)
    start_date: date
    end_date_exclusive: date
    artifact_path: str = Field(min_length=1)
    canonical_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_proposals_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LongitudinalCheckpoint(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["hybrid_longitudinal_checkpoint"] = (
        "hybrid_longitudinal_checkpoint"
    )
    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_date: date
    end_date_exclusive: date
    next_date: date
    chunks: list[LongitudinalChunkRecord] = Field(default_factory=list)
    planning_memory: PlanningMemory
    habit_ledger: HabitLedger
