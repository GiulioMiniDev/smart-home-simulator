"""Il ciclo veloce: espande un outline, ne materializza pochi giorni e li stampa da leggere.

Uso:  giorni.py <bundle.json> [n_giorni] [--skip N]

Stampa, per ogni giornata: la sequenza di attivita' con stanza e postura, i buchi con dove
li passa, e in coda il conto dei movimenti. E' la stessa lettura che ha fatto emergere le due
ore in bagno, ma su tre giorni invece che su un anno.
"""

import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.materialization import HomeGenerationPolicy
from smart_home_sim.domain.models import SimulationWindow
from smart_home_sim.hybrid_planning.expander import expand_outline
from smart_home_sim.hybrid_planning.outline import HorizonOutline
from smart_home_sim.materialization import materialize_workspace

BUNDLE = Path(sys.argv[1])
COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SKIP = int(sys.argv[sys.argv.index("--skip") + 1]) if "--skip" in sys.argv else 1
POLICY = os.environ.get("HOME_POLICY")
ROOT = Path(os.environ.get("DAYS_ROOT", tempfile.mkdtemp(prefix="days-")))

raw = json.loads(BUNDLE.read_text(encoding="utf-8"))
raw["outline"]["months"] = 1
raw["outline"]["phases"] = []
raw["outline"]["events"] = []
outline = HorizonOutline.model_validate_json(json.dumps(raw["outline"]))
package = PersonalProcessPackage.model_validate_json(json.dumps(raw["personalProcessPackage"]))

expansion = expand_outline(outline, package, seed=1)
scenario = expansion.bundle.scenario
# Un giorno di coda oltre quelli da leggere: la sera dell'ultimo scorre oltre la mezzanotte e
# deve avere un piano dove atterrare. Il giorno di coda e' troncabile, come lo e' l'ultimo giorno
# di un orizzonte vero, e non viene stampato.
days = scenario.days[SKIP : SKIP + COUNT + 1]
days = [
    day.model_copy(
        update={
            "activities": [
                item.model_copy(update={"allow_boundary_truncation": True, "mandatory": False})
                for item in day.activities
            ]
        }
    )
    if day is days[-1]
    else day
    for day in days
]
readable = {day.date for day in days[:COUNT]}
tz = days[0].activities[0].start_window.preferred.tzinfo
# Due giorni di coda, non uno: la sera dell'ultimo giorno puo' finire oltre la mezzanotte, e
# l'orizzonte deve contenerla o la validazione la rifiuta.
window = SimulationWindow(
    start=datetime.combine(days[0].date, time.min, tz),
    end=datetime.combine(days[-1].date + timedelta(days=1), time.min, tz),
)
scenario = scenario.model_copy(
    update={
        "days": days,
        "simulation_window": window,
        "initial_state": scenario.initial_state.model_copy(update={"at": window.start}),
    }
)

staging = ROOT / "staging"
run = ROOT / "run"
staging.mkdir(parents=True, exist_ok=True)
if run.exists():
    shutil.rmtree(run)
(staging / "scenario.json").write_text(
    scenario.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
)
(staging / "personal-process-package.json").write_text(
    package.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
)
try:
    materialize_workspace(
        staging / "scenario.json",
        staging / "personal-process-package.json",
        run,
        home_policy=(
            HomeGenerationPolicy.model_validate_json(Path(POLICY).read_text(encoding="utf-8"))
            if POLICY
            else None
        ),
    )
except Exception as error:  # noqa: BLE001
    for issue in getattr(error, "issues", [])[:6]:
        print(f"  [{issue.get('code')}] {str(issue.get('message'))[:260]}")
    raise
trace = ExecutionTrace.model_validate_json((run / "execution-trace.json").read_text("utf-8"))

postures = sorted(
    (item.at, str(item.value))
    for item in trace.state_transitions
    if item.subject_type == "resident" and item.fact == "posture"
)
arrivals = sorted((item.ended_at, item.destination_region_id) for item in trace.movements)


def at_or_before(pairs, moment, default="?"):
    found = default
    for when, value in pairs:
        if when > moment:
            break
        found = value
    return found


done = sorted(
    (
        a
        for a in trace.activity_executions
        if a.status != "dropped" and a.actual_start.date() in readable
    ),
    key=lambda a: a.actual_start,
)
dropped = [a for a in trace.activity_executions if a.status == "dropped"]

previous_end = None
current_day = None
for activity in done:
    day = activity.actual_start.date()
    if day != current_day:
        current_day = day
        print(f"\n{'=' * 78}\n{day:%A %d %B %Y}\n{'=' * 78}")
        previous_end = None
    if previous_end is not None:
        gap = (activity.actual_start - previous_end).total_seconds() / 60
        if gap > 0.2:
            where = at_or_before(arrivals, previous_end)
            how = at_or_before(postures, previous_end + timedelta(seconds=1))
            print(f"          · · · {gap:5.0f} min in {where}, {how}")
        elif gap >= 0:
            print("          · · · a filo, nessuna pausa")
    minutes = (activity.actual_end - activity.actual_start).total_seconds() / 60
    room = at_or_before(arrivals, activity.actual_start + timedelta(seconds=5))
    how = at_or_before(postures, activity.actual_end - timedelta(seconds=1))
    print(
        f"{activity.actual_start:%H:%M}-{activity.actual_end:%H:%M} {minutes:6.1f}m  "
        f"{activity.intent:30s} {room:13s} {how}"
    )
    previous_end = activity.actual_end

print(f"\n{'=' * 78}")
span = (done[-1].actual_end - done[0].actual_start).total_seconds() / 86400
print(f"attivita' eseguite {len(done)} ({len(done)/span:.1f}/g), scartate dal drive {len(dropped)}")
print(f"movimenti {len(trace.movements)} ({len(trace.movements)/span:.0f}/g)")
print("intenti:", Counter(a.intent for a in done).most_common(6))
