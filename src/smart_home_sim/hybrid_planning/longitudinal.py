from __future__ import annotations

import hashlib
import json
import os
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from smart_home_sim.domain.models import SimulationWindow
from smart_home_sim.hybrid_planning.behavioral_models import BehavioralProfile
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
    validate_behavioral_profile,
)
from smart_home_sim.hybrid_planning.habit_gates import initial_habit_ledger
from smart_home_sim.hybrid_planning.longitudinal_models import (
    LongitudinalCheckpoint,
    LongitudinalChunkRecord,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.longitudinal_quality import (
    evaluate_longitudinal_quality,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
)
from smart_home_sim.hybrid_planning.service import (
    CompletionClient,
    HybridPlanningError,
    HybridPlanningResult,
    _read_models,
    generate_hybrid_plan,
)

PROPOSAL_LIST = TypeAdapter(list[DailyProposal])


class ChunkGenerator(Protocol):
    def __call__(
        self,
        case_path: Path,
        output_dir: Path,
        config: HybridPlanningConfig,
        *,
        behavioral_profile_path: Path,
        ledger_path: Path | None,
        initial_memory: PlanningMemory,
        client: CompletionClient | None,
    ) -> HybridPlanningResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class LongitudinalPlanningResult:
    output_dir: Path
    checkpoint: LongitudinalCheckpoint
    quality: LongitudinalQualityReport


def one_month_end(start: date) -> date:
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def slice_planning_case(
    base: PlanningCase,
    *,
    end_exclusive: date,
    chunk_days: int,
) -> list[PlanningCase]:
    if not 1 <= chunk_days <= 7:
        raise ValueError("chunk_days must be between 1 and 7")
    start = base.dates()[0]
    if end_exclusive <= start:
        raise ValueError("end_exclusive must be after planning start")
    zone = ZoneInfo(base.time_zone)
    chunks: list[PlanningCase] = []
    current = start
    while current < end_exclusive:
        chunk_end = min(current + timedelta(days=chunk_days), end_exclusive)
        start_at = datetime.combine(current, time.min, tzinfo=zone)
        end_at = datetime.combine(chunk_end, time.min, tzinfo=zone)
        calendar = [item for item in base.calendar if current <= item.date < chunk_end]
        chunks.append(
            base.model_copy(
                update={
                    "planning_window": SimulationWindow(
                        start=start_at,
                        end=end_at,
                    ),
                    "initial_state": base.initial_state.model_copy(
                        update={"at": start_at}
                    ),
                    "calendar": calendar,
                }
            )
        )
        current = chunk_end
    return chunks


def _canonical_json(value: object) -> str:
    return json.dumps(
        to_jsonable_python(value, by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            to_jsonable_python(value, by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _configuration_digest(
    case_id: str,
    resident_id: str,
    profile_digest: str,
    start_date: date,
    end_date: date,
    chunk_days: int,
    config: HybridPlanningConfig,
) -> str:
    return _digest(
        {
            "caseId": case_id,
            "residentId": resident_id,
            "profileDigest": profile_digest,
            "startDate": start_date.isoformat(),
            "endDateExclusive": end_date.isoformat(),
            "chunkDays": chunk_days,
            "llm": config.model_dump(mode="json", by_alias=True),
        }
    )


def load_accepted_proposals(
    output_dir: Path,
    records: list[LongitudinalChunkRecord],
) -> list[DailyProposal]:
    proposals: list[DailyProposal] = []
    try:
        for record in records:
            artifact_dir = output_dir / record.artifact_path
            plan_path = artifact_dir / "planning" / "canonical-plan.json"
            if _file_digest(plan_path) != record.canonical_plan_sha256:
                raise HybridPlanningError(f"canonical plan digest mismatch: {plan_path}")
            proposals_path = artifact_dir / "accepted-proposals.json"
            if _file_digest(proposals_path) != record.accepted_proposals_sha256:
                raise HybridPlanningError(
                    f"accepted proposal digest mismatch: {proposals_path}"
                )
            proposals.extend(
                PROPOSAL_LIST.validate_json(proposals_path.read_text(encoding="utf-8"))
            )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise HybridPlanningError(f"cannot restore accepted proposals: {error}") from error
    proposals.sort(key=lambda item: item.date)
    dates = [item.date for item in proposals]
    if len(dates) != len(set(dates)):
        raise HybridPlanningError("accepted proposals contain duplicate dates")
    if dates and dates != [
        date.fromordinal(dates[0].toordinal() + offset) for offset in range(len(dates))
    ]:
        raise HybridPlanningError("accepted proposals contain a date gap")
    return proposals


def _read_profile(path: Path) -> BehavioralProfile:
    try:
        return BehavioralProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise HybridPlanningError(f"cannot load behavioral profile: {error}") from error


def _validate_resume(
    checkpoint: LongitudinalCheckpoint,
    *,
    configuration_digest: str,
    profile_digest: str,
    case_id: str,
    resident_id: str,
) -> None:
    identity = (
        checkpoint.configuration_digest,
        checkpoint.profile_digest,
        checkpoint.case_id,
        checkpoint.resident_id,
    )
    expected = (
        configuration_digest,
        profile_digest,
        case_id,
        resident_id,
    )
    if identity != expected:
        raise HybridPlanningError("resume checkpoint identity mismatch")
    expected_next = (
        checkpoint.chunks[-1].end_date_exclusive
        if checkpoint.chunks
        else checkpoint.start_date
    )
    if checkpoint.next_date != expected_next:
        raise HybridPlanningError("resume checkpoint progress mismatch")


def generate_one_month_plan(
    case_path: Path,
    behavioral_profile_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    chunk_days: int = 7,
    resume: bool = False,
    client: CompletionClient | None = None,
    chunk_generator: ChunkGenerator = generate_hybrid_plan,
) -> LongitudinalPlanningResult:
    base, catalog = _read_models(case_path)
    supplied_profile = _read_profile(behavioral_profile_path)
    profile_digest = behavioral_profile_digest(supplied_profile)
    profile_validation = validate_behavioral_profile(base, catalog, supplied_profile)
    if not profile_validation.valid:
        codes = ", ".join(item.code for item in profile_validation.issues)
        raise HybridPlanningError(f"behavioral profile is invalid: {codes}")
    start = base.dates()[0]
    end = one_month_end(start)
    chunks = slice_planning_case(base, end_exclusive=end, chunk_days=chunk_days)
    configuration_digest = _configuration_digest(
        base.case_id,
        base.resident.resident_id,
        profile_digest,
        start,
        end,
        chunk_days,
        config,
    )
    checkpoint_path = output_dir / "checkpoint.json"
    profile_snapshot_path = output_dir / "behavioral-profile-snapshot.json"
    if resume:
        if not checkpoint_path.is_file():
            raise HybridPlanningError("resume requires checkpoint.json")
        try:
            checkpoint = LongitudinalCheckpoint.model_validate_json(
                checkpoint_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, ValidationError) as error:
            raise HybridPlanningError(f"cannot load resume checkpoint: {error}") from error
        _validate_resume(
            checkpoint,
            configuration_digest=configuration_digest,
            profile_digest=profile_digest,
            case_id=base.case_id,
            resident_id=base.resident.resident_id,
        )
        frozen_profile = _read_profile(profile_snapshot_path)
        if behavioral_profile_digest(frozen_profile) != checkpoint.profile_digest:
            raise HybridPlanningError("frozen behavioral profile digest mismatch")
    else:
        if output_dir.exists():
            raise HybridPlanningError(f"output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True)
        (output_dir / "profile-snapshot.json").write_text(
            base.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        profile_snapshot_path.write_text(
            supplied_profile.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        checkpoint = LongitudinalCheckpoint(
            run_id=output_dir.name,
            case_id=base.case_id,
            resident_id=base.resident.resident_id,
            profile_digest=profile_digest,
            configuration_digest=configuration_digest,
            start_date=start,
            end_date_exclusive=end,
            next_date=start,
            planning_memory=PlanningMemory(),
            habit_ledger=initial_habit_ledger(profile_digest, supplied_profile),
        )
        _atomic_json(checkpoint_path, checkpoint)
        frozen_profile = supplied_profile

    manifest: dict[str, object] = {
        "documentType": "hybrid_longitudinal_run",
        "runVersion": "0.1.0",
        "status": "running",
        "caseId": base.case_id,
        "residentId": base.resident.resident_id,
        "profileDigest": profile_digest,
        "startDate": start.isoformat(),
        "endDateExclusive": end.isoformat(),
        "chunkDays": chunk_days,
        "executionPerformed": False,
        "baselineExposedToModel": False,
    }
    _atomic_json(output_dir / "run.json", manifest)
    try:
        accepted = load_accepted_proposals(output_dir, checkpoint.chunks)
        for index, chunk in enumerate(chunks, start=1):
            chunk_start = chunk.dates()[0]
            if chunk_start < checkpoint.next_date:
                continue
            chunk_root = output_dir / "chunks" / chunk_start.isoformat()
            attempt_number = len(list(chunk_root.glob("attempt-*"))) + 1
            attempt = chunk_root / f"attempt-{attempt_number:03d}"
            attempt.mkdir(parents=True)
            chunk_case_path = attempt / "planning-case.json"
            chunk_case_path.write_text(
                chunk.model_dump_json(indent=2, by_alias=True) + "\n",
                encoding="utf-8",
            )
            ledger_path = attempt / "habit-ledger-input.json"
            ledger_path.write_text(
                checkpoint.habit_ledger.model_dump_json(indent=2, by_alias=True) + "\n",
                encoding="utf-8",
            )
            result = chunk_generator(
                chunk_case_path,
                attempt / "planning",
                config,
                behavioral_profile_path=profile_snapshot_path,
                ledger_path=ledger_path,
                initial_memory=checkpoint.planning_memory,
                client=client,
            )
            candidate = [*accepted, *result.proposals]
            quality = evaluate_longitudinal_quality(frozen_profile, candidate)
            _atomic_json(attempt / "longitudinal-quality.json", quality)
            if not quality.valid:
                raise HybridPlanningError(
                    "longitudinal quality gate failed: " + ", ".join(quality.reasons)
                )
            proposals_path = attempt / "accepted-proposals.json"
            _atomic_json(proposals_path, list(result.proposals))
            relative = attempt.relative_to(output_dir).as_posix()
            record = LongitudinalChunkRecord(
                index=index,
                start_date=chunk_start,
                end_date_exclusive=chunk.dates()[-1] + timedelta(days=1),
                artifact_path=relative,
                canonical_plan_sha256=_file_digest(
                    attempt / "planning" / "canonical-plan.json"
                ),
                accepted_proposals_sha256=_file_digest(proposals_path),
            )
            if result.habit_ledger is None:
                raise HybridPlanningError("accepted chunk did not return a habit ledger")
            checkpoint = checkpoint.model_copy(
                update={
                    "next_date": record.end_date_exclusive,
                    "chunks": [*checkpoint.chunks, record],
                    "planning_memory": result.memory,
                    "habit_ledger": result.habit_ledger,
                }
            )
            _atomic_json(checkpoint_path, checkpoint)
            accepted = candidate
        quality = evaluate_longitudinal_quality(frozen_profile, accepted)
        if checkpoint.next_date != end or not quality.valid:
            raise HybridPlanningError("one-month plan is incomplete or failed quality")
        _atomic_json(output_dir / "quality-report.json", quality)
        manifest["status"] = "completed"
        manifest["acceptedChunks"] = len(checkpoint.chunks)
        manifest["dayCount"] = quality.day_count
        _atomic_json(output_dir / "run.json", manifest)
        return LongitudinalPlanningResult(output_dir, checkpoint, quality)
    except (OSError, ValueError, HybridPlanningError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        _atomic_json(output_dir / "run.json", manifest)
        if isinstance(error, HybridPlanningError):
            raise
        raise HybridPlanningError(str(error)) from error
