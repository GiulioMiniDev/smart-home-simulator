"""Which plan a home runs: the one a policy recommended, or the one its researcher approved.

Every home starts with a *recommended* plan — rooms, furniture and sensor field derived
deterministically from the scenario by ``generate_home`` and ``deploy_sensors``. That is a proposal,
not a decision: the researcher looks at the planimetry, and either accepts it as it stands or moves
a wall, drags the fridge, adds a PIR, widens a coverage.

The moment they do either, the published home and sensor models stop being a record of what the
policy suggested and become the home's own physical model. From then on every run of that home
executes them, instead of regenerating a plan the researcher already answered for. This module is
the single place that knows the difference, so no caller has to guess it from provenance keys.

Getting there also costs *canonical* plans, and used to cost three of them for one dataset: the
import compiles the scenario to validate it, the environment preview compiles it to build what the
researcher is shown, and the run compiles it again to execute. Deciding when that solve can be
inherited instead is the module's second job: the question has the same shape as the first (what
may a run take from the workspace rather than derive?) and a stricter answer, since nobody ever
looks at a canonical plan.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.compiler import CompilationResult
from smart_home_sim.compiler.fingerprint import compiler_fingerprint
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.application import JobStatus
from smart_home_sim.domain.compilation import CompilationReport
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.sensors import SensorModel

APPROVAL_KEY = "approval"
RECOMMENDED = "recommended"
RESEARCHER = "researcher"

# Marks the job event that records how a run got its canonical plan. A `log` event rather than an
# event type of its own: `JobEvent.event_type` is a published closed set, and one diagnostic is not
# a reason to widen it.
DECISION_KEY = "plan_reuse"

# How far back to look for a job of this home that already published a plan. A researcher imports,
# reviews and runs in one sitting; anything much older is a different one, and scanning a long
# history to save one solve is the wrong trade against reading every candidate's artifacts.
_REUSE_JOB_LOOKBACK = 20

Approval = Literal["recommended", "researcher"]

__all__ = [
    "APPROVAL_KEY",
    "Approval",
    "DECISION_KEY",
    "PlanReuse",
    "RECOMMENDED",
    "RESEARCHER",
    "approval_provenance",
    "approved_home_model",
    "approved_sensor_model",
    "plan_approval",
    "recorded_compiler_fingerprint",
    "reusable_compilation",
]


def approval_provenance(approval: Approval, **extra: Any) -> dict[str, Any]:
    """The provenance a home or sensor revision carries to record how it was decided."""
    return {APPROVAL_KEY: approval, **extra}


def _revision_approval(workspace: WorkspaceService, home_id: str, kind: str) -> Approval:
    revision = workspace.latest_revision(home_id, kind)
    if revision is None:
        return RECOMMENDED
    value = revision["provenance"].get(APPROVAL_KEY)
    return RESEARCHER if value == RESEARCHER else RECOMMENDED


def plan_approval(workspace: WorkspaceService, home_id: str) -> dict[str, Any]:
    """How the home's current plan and sensor field were decided, for the UI and the workers."""
    home = _revision_approval(workspace, home_id, "home")
    sensor = _revision_approval(workspace, home_id, "sensor")
    return {
        "home": home,
        "sensor": sensor,
        # One flag for the surface that asks the only question a researcher cares about: is what I
        # am looking at still only a recommendation?
        "approved": home == RESEARCHER,
    }


def approved_home_model(workspace: WorkspaceService, home_id: str) -> HomeModel | None:
    """The home's plan when the researcher stands behind it, or None to regenerate from policy."""
    if _revision_approval(workspace, home_id, "home") != RESEARCHER:
        return None
    artifact_id = workspace.get_home(home_id).current_home_artifact_id
    if artifact_id is None:
        return None
    return HomeModel.model_validate_json(workspace.read_artifact(artifact_id))


def approved_sensor_model(workspace: WorkspaceService, home_id: str) -> SensorModel | None:
    """The home's sensor field when the researcher stands behind it, or None to redeploy it."""
    if _revision_approval(workspace, home_id, "sensor") != RESEARCHER:
        return None
    artifact_id = workspace.get_home(home_id).current_sensor_artifact_id
    if artifact_id is None:
        return None
    return SensorModel.model_validate_json(workspace.read_artifact(artifact_id))


@dataclass(frozen=True)
class PlanReuse:
    """Whether a run may execute a plan an earlier job compiled, and the sentence that says why."""

    compilation: CompilationResult | None
    reason: str
    # Where the plan came from: a job id, or a phrase for a source that is not a job. Only ever
    # read back as a label, so it does not need to be resolvable.
    source: str | None = None

    def event_payload(self) -> dict[str, Any]:
        """What the job records about this decision, and what a later job reads back from it.

        The fingerprint is the compiler of the process taking the decision, so a job that compiled
        leaves behind the identity of the code that produced its plan. That is the whole mechanism:
        a later run compares its own against it and reuses nothing when they differ.
        """
        return {
            "decision": DECISION_KEY,
            "compilerFingerprint": compiler_fingerprint(),
            **({"planSource": self.source} if self.source else {}),
        }


def recorded_compiler_fingerprint(workspace: WorkspaceService, job_id: str) -> str | None:
    """The compiler a completed job used, as it recorded it, or None if it did not."""
    for event in workspace.list_events(job_id):
        if event.payload.get("decision") == DECISION_KEY:
            recorded = event.payload.get("compilerFingerprint")
            return recorded if isinstance(recorded, str) else None
    return None


def reusable_compilation(
    workspace: WorkspaceService, home_id: str, scenario: Scenario
) -> PlanReuse:
    """A canonical plan this home already published for this scenario, if it still holds.

    One dataset used to cost three solves of one document. Importing the bundle compiles it, for
    the deterministic-precondition gate; previewing the environment compiles it again, to build the
    plan the researcher looks at; and the run compiles it a third time. On five months that is
    roughly twenty minutes of CP-SAT producing one plan, twice over. Every one of those plans is in
    the workspace by the time the next step wants one.

    Reusing them is a statement about trust, and it is the same statement the app already makes for
    `approved_home_model`: what the workspace holds is what this home is. The difference is that a
    home is a drawing a researcher looked at, while a plan is four megabytes of timestamps nobody
    will ever read — so this refuses on anything short of proof, and every refusal simply costs the
    solve that would have happened anyway. Four things have to hold:

    - the artifacts are the ones the store registered — `read_artifact` re-hashes and refuses a
      file that changed underneath it, so this comes for free;
    - the plan names *this* scenario, by digest and not by identifier;
    - plan and report still agree, which is what `_accepted_compilation` checks again downstream;
    - the compiler has not changed since — see `compiler_fingerprint`, which is the only one of the
      four that the documents cannot answer on their own.

    Returns the reason either way: a run that took six minutes longer than the last one should be
    able to say which of these was not true.
    """
    fingerprint = compiler_fingerprint()
    digest = canonical_sha256(scenario)
    candidates = 0
    for source, plan_id, report_id, recorded in _plan_sources(workspace, home_id):
        candidates += 1
        if recorded != fingerprint:
            continue
        accepted = _accept(workspace, plan_id, report_id, digest)
        if accepted is None:
            continue
        return PlanReuse(
            compilation=accepted,
            reason=f"reused the canonical plan compiled by {source}",
            source=source,
        )
    if candidates == 0:
        return PlanReuse(None, "compiled the horizon: nothing earlier published a plan to reuse")
    return PlanReuse(
        None,
        "compiled the horizon: no earlier plan matches this scenario and compiler",
    )


def _plan_sources(
    workspace: WorkspaceService, home_id: str
) -> Iterator[tuple[str, str, str, str | None]]:
    """Every plan this home has already published, newest intent first.

    Two places produce one: importing the bundle, whose validation compiles the scenario for its
    deterministic-precondition gate, and any job that materialized the home. The import is tried
    first because it is one row rather than a scan of run artifacts, and because in the ordinary
    order of work it is the earliest and therefore the one that makes every later step free.
    """
    revision = workspace.latest_revision(home_id, "plan")
    if revision is not None and revision["artifactId"]:
        provenance = revision["provenance"]
        report_id = provenance.get("compilationReportArtifactId")
        if isinstance(report_id, str):
            yield (
                "the authoring import",
                revision["artifactId"],
                report_id,
                provenance.get("compilerFingerprint"),
            )
    for job in workspace.list_jobs(home_id=home_id, limit=_REUSE_JOB_LOOKBACK):
        if job.status is not JobStatus.completed:
            continue
        artifacts = workspace.run_artifacts(job.job_id)
        if "canonical_plan" not in artifacts or "compilation_report" not in artifacts:
            continue
        yield (
            job.job_id,
            artifacts["canonical_plan"].artifact_id,
            artifacts["compilation_report"].artifact_id,
            recorded_compiler_fingerprint(workspace, job.job_id),
        )


def _accept(
    workspace: WorkspaceService, plan_id: str, report_id: str, scenario_digest: str
) -> CompilationResult | None:
    """The stored pair, if it is this scenario's plan and still agrees with its own report."""
    try:
        plan = CanonicalPlan.model_validate_json(workspace.read_artifact(plan_id))
        if plan.source_scenario_sha256 != scenario_digest:
            return None
        report = CompilationReport.model_validate_json(workspace.read_artifact(report_id))
    except (WorkspaceError, ValidationError, ValueError):
        # A corrupt or unreadable artifact is a reason to compile, not a reason to fail: the caller
        # has everything it needs to produce the plan itself.
        return None
    if report.canonical_plan_sha256 != canonical_sha256(plan):
        return None
    return CompilationResult(plan=plan, report=report)
