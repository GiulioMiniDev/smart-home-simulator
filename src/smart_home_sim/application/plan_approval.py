"""Which plan a home runs: the one a policy recommended, or the one its researcher approved.

Every home starts with a *recommended* plan — rooms, furniture and sensor field derived
deterministically from the scenario by ``generate_home`` and ``deploy_sensors``. That is a proposal,
not a decision: the researcher looks at the planimetry, and either accepts it as it stands or moves
a wall, drags the fridge, adds a PIR, widens a coverage.

The moment they do either, the published home and sensor models stop being a record of what the
policy suggested and become the home's own physical model. From then on every run of that home
executes them, instead of regenerating a plan the researcher already answered for. This module is
the single place that knows the difference, so no caller has to guess it from provenance keys.
"""

from __future__ import annotations

from typing import Any, Literal

from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.sensors import SensorModel

APPROVAL_KEY = "approval"
RECOMMENDED = "recommended"
RESEARCHER = "researcher"

Approval = Literal["recommended", "researcher"]

__all__ = [
    "APPROVAL_KEY",
    "Approval",
    "RECOMMENDED",
    "RESEARCHER",
    "approval_provenance",
    "approved_home_model",
    "approved_sensor_model",
    "plan_approval",
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
