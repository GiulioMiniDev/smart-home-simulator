"""Audit an execution trace for actions no body could have performed.

`measure_observable_realism.py` asks whether the sensor half looks generated. This asks something
prior and cheaper to check: whether the resident it was generated from is doing possible things.
Every finding here is a statement the trace makes that a person could not have made true — walking
away from the fixture the process just crossed the room to reach, eating at the refrigerator while
seated at the table, carrying a saucepan while lying in bed.

They matter because the trace is the ground truth. A hygiene action attributed to the shower is a
label a segmentation algorithm is asked to learn, and a resident recorded as sitting while she
crosses the flat is a posture feature that means nothing. None of it fails validation: every one of
these traces is schema-valid, compiles, and replays.

The seven checks, and the defect each was written for:

`APPROACH_UNDONE`      an action whose provider is not the fixture the process last walked to. Where
                       a process names no object — `personal_care` names a procedure — the binder
                       had only the capability to choose by and took the first candidate by entity
                       id: 32 of 32 hygiene actions in a bathroom went to the shower.
`WALKED_WITHOUT_STANDING`  a movement performed sitting or lying. Resting processes put the resident
                       down and never stood her back up, so the next activity walked her across the
                       flat seated.
`POSTURE_IMPOSSIBLE`   an action a body in that posture cannot perform.
`PROVIDER_OUT_OF_ROOM` an object used from outside every room the activity declares. This is how the
                       kitchen sink came to be the only tap in the flat.
`LEFT_RUNNING`         a tap or an appliance switched on and not off before the activity ended.
`LEFT_OPEN`            a container opened and not closed.
`TELEPORT`             an action on an object in a region the resident is not standing in.

Reads a batch manifest and simulates each day, or a single simulation bundle. Exits non-zero when
anything is found, so it can gate a change.

    python tools/audit_physical_consistency.py path/to/batch-manifest.json
    python tools/audit_physical_consistency.py path/to/simulation-bundle.json --examples 10
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from smart_home_sim.domain.batch import SimulationBatchManifest
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.simulation import simulate_bundle

# Actions whose process node names no object, so nothing but the capability says which one it is.
UNPARAMETERISED = frozenset(
    {
        "personal_care",
        "laundry_step",
        "dress",
        "manage_medication",
        "perform_work",
        "exercise",
        "leisure",
        "prepare_food",
    }
)
# What a posture rules out. Deliberately conservative: reading and watching are fine seated, and
# `wait` is fine in any of them.
POSTURE_FORBIDS: dict[str, frozenset[str]] = {
    "lying": frozenset(
        {
            "consume",
            "prepare_food",
            "clean",
            "open",
            "close",
            "take_item",
            "put_item",
            "personal_care",
            "laundry_step",
            "dress",
            "organize",
            "shop",
        }
    ),
    "sitting": frozenset({"prepare_food", "clean", "laundry_step", "shop"}),
}
PAIRED = {"activate": "deactivate", "open": "close"}
# Below this a "movement" is the resident shifting her weight, not crossing anything.
STEP_METRES = 0.05
# The role a requirement names says whether its provider is a place or a thing in the hand. The
# glass she carries to the sink is provided by the cupboard it came from, and that is not a claim
# about where she is standing — so it settles nothing about the body and every check here ignores
# it. Reading it as a position is what made the first version of this audit report a resident in
# two rooms at once for a sequence that was correct.
_CARRIED_ROLE = "item"


class Findings:
    def __init__(self, examples: int) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)
        self.limit = examples

    def note(self, code: str, example: str) -> None:
        self.counts[code] += 1
        if len(self.examples[code]) < self.limit:
            self.examples[code].append(example)

    def render(self, days: int, actions: int) -> str:
        lines = [f"days audited: {days}   actions: {actions}", ""]
        if not self.counts:
            return "\n".join([*lines, "nothing found."])
        lines.append(f"{'finding':24s} {'count':>7s}")
        for code, count in self.counts.most_common():
            lines.append(f"{code:24s} {count:7d}")
        for code in self.counts:
            lines.extend(["", f"--- {code}"])
            lines.extend(f"    {item}" for item in self.examples[code])
        return "\n".join(lines)


def _posture_reader(trace: Any):
    """Posture in force at a moment, from the resident's own transitions."""
    changes = sorted(
        (
            item
            for item in trace.state_transitions
            if item.subject_type == "resident" and item.fact == "posture"
        ),
        key=lambda item: item.at,
    )

    def at(moment: datetime) -> str:
        # The opening posture is the first transition's `previousValue`: a day bundle seeds the
        # resident asleep, and reading "standing" before the first change would hide every action
        # she performs before getting up.
        current = str(changes[0].previous_value) if changes else "standing"
        for change in changes:
            if change.at > moment:
                break
            current = str(change.value)
        return current

    return at


def audit_bundle(bundle: SimulationBundle, findings: Findings) -> int:
    region_of = {item.entity_id: item.region_id for item in bundle.home_model.entities}
    point_of = {item.entity_id: item.interaction_point_id for item in bundle.home_model.entities}
    rooms_of = {
        item.scenario_location_id: set(item.region_ids)
        for item in bundle.home_model.location_bindings
    }
    planned = {a.activity_id: a for day in bundle.scenario.days for a in day.activities}
    placed_providers = {
        (binding.source_activity_id, binding.node_id): [
            item.provider_id
            for item in binding.capability_bindings
            if item.provider_type == "entity" and item.role != _CARRIED_ROLE
        ]
        for binding in bundle.action_bindings
    }

    outcome = simulate_bundle(bundle)
    if outcome.trace is None:
        findings.note("SIMULATION_FAILED", "; ".join(item.message for item in outcome.issues[:2]))
        return 0
    trace = outcome.trace
    activity_of = {item.activity_execution_id: item for item in trace.activity_executions}
    moves_by_action: dict[str, list[Any]] = defaultdict(list)
    for movement in trace.movements:
        moves_by_action[movement.action_execution_id].append(movement)
    posture_at = _posture_reader(trace)

    by_activity: dict[str, list[Any]] = defaultdict(list)
    for action in sorted(
        trace.action_executions, key=lambda item: (item.started_at, item.action_execution_id)
    ):
        by_activity[action.activity_execution_id].append(action)

    total = 0
    for execution_id, actions in by_activity.items():
        activity = activity_of[execution_id]
        source = planned.get(activity.source_activity_id)
        rooms: set[str] = set()
        for location_id in source.location_ids if source else []:
            rooms |= rooms_of.get(location_id, set())

        standing_at: str | None = None
        pending: dict[str, str] = {}
        for action in actions:
            total += 1
            key = (activity.source_activity_id, action.node_id)
            providers = [item for item in placed_providers.get(key, []) if item in region_of]
            entity = providers[0] if providers else None
            where = f"{activity.intent}/{action.node_id}"

            if (
                action.action_type in UNPARAMETERISED
                and standing_at is not None
                and entity is not None
                and entity != standing_at
                and point_of.get(entity)
            ):
                findings.note(
                    "APPROACH_UNDONE",
                    f"{where}: walked to {standing_at}, then {action.action_type} used {entity}",
                )

            # Leaving and entering go through the front door, which is in the hallway and never in
            # the supermarket the activity is declared at. That is the door doing its job.
            if (
                entity is not None
                and rooms
                and action.action_type not in {"leave_home", "enter_home"}
                and region_of.get(entity) not in rooms
            ):
                findings.note(
                    "PROVIDER_OUT_OF_ROOM",
                    f"{where}: declared in {sorted(rooms)}, {action.action_type} used {entity} "
                    f"in {region_of.get(entity)}",
                )

            posture = posture_at(action.started_at)
            if action.action_type in POSTURE_FORBIDS.get(posture, frozenset()):
                findings.note(
                    "POSTURE_IMPOSSIBLE", f"{where}: {action.action_type} while {posture}"
                )

            walked = moves_by_action.get(action.action_execution_id, [])
            if walked and posture != "standing" and walked[0].distance_meters > STEP_METRES:
                findings.note(
                    "WALKED_WITHOUT_STANDING",
                    f"{where}: {walked[0].distance_meters:.1f} m from "
                    f"{walked[0].origin_region_id} to {walked[0].destination_region_id} "
                    f"while {posture}",
                )

            if action.action_type in PAIRED and entity is not None:
                pending[f"{action.action_type}:{entity}"] = action.node_id
            for opener, closer in PAIRED.items():
                if action.action_type == closer and entity is not None:
                    pending.pop(f"{opener}:{entity}", None)

            if entity is not None and point_of.get(entity):
                standing_at = entity
            elif action.action_type == "move_to":
                standing_at = None

        for key, node_id in pending.items():
            kind, entity = key.split(":", 1)
            findings.note(
                "LEFT_RUNNING" if kind == "activate" else "LEFT_OPEN",
                f"{activity.intent}/{node_id}: {kind} {entity}, never undone in the activity",
            )

    region: str | None = None
    for action in sorted(trace.action_executions, key=lambda item: item.started_at):
        movements = moves_by_action.get(action.action_execution_id, [])
        if movements:
            region = movements[-1].destination_region_id
            continue
        activity = activity_of[action.activity_execution_id]
        key = (activity.source_activity_id, action.node_id)
        providers = [item for item in placed_providers.get(key, []) if item in region_of]
        if providers and region is not None and region_of.get(providers[0]) != region:
            findings.note(
                "TELEPORT",
                f"{activity.intent}/{action.node_id}: {action.action_type} on {providers[0]} "
                f"in {region_of.get(providers[0])} while standing in {region}",
            )
    return total


def _bundles(target: Path) -> list[SimulationBundle]:
    payload = target.read_text(encoding="utf-8")
    if target.name.endswith("batch-manifest.json") or '"runs"' in payload[:400]:
        manifest = SimulationBatchManifest.model_validate_json(payload)
        return [
            SimulationBundle.model_validate_json(
                (target.parent / run.bundle_path).resolve().read_text(encoding="utf-8")
            )
            for run in manifest.runs
        ]
    return [SimulationBundle.model_validate_json(payload)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="a batch-manifest.json or a simulation bundle")
    parser.add_argument("--examples", type=int, default=4, help="examples printed per finding")
    parser.add_argument("--days", type=int, default=0, help="audit only the first N days")
    arguments = parser.parse_args()

    bundles = _bundles(arguments.target)
    if arguments.days:
        bundles = bundles[: arguments.days]
    findings = Findings(arguments.examples)
    actions = sum(audit_bundle(bundle, findings) for bundle in bundles)
    print(findings.render(len(bundles), actions))
    return 1 if findings.counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
