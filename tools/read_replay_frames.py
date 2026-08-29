"""Il replay, letto invece che guardato.

Campiona `ReplayService.frame` — la stessa funzione che alimenta l'animazione nell'app — a una
cadenza fissa, e stampa ogni fotogramma: ora, stanza, posizione, postura, stato, cosa sta facendo
e quali sensori sono accesi. Quello che si legge qui e' quello che si vede li'.

Uso:  replay_testuale.py <run-dir> <YYYY-MM-DDTHH:MM> <YYYY-MM-DDTHH:MM> [passo-secondi]
"""

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus

RUN = Path(sys.argv[1])
FROM = sys.argv[2]
TO = sys.argv[3]
STEP = int(sys.argv[4]) if len(sys.argv) > 4 else 120
SCRATCH = Path(os.environ.get("REPLAY_SCRATCH", tempfile.mkdtemp(prefix="replay-")))

if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
workspace = WorkspaceService.create(SCRATCH, "Lettura del replay")
home = workspace.create_home("casa")
job = workspace.create_job("simulation", home_id=home.home_id, seed=1)
workspace.update_job(
    job.job_id, JobStatus.running, JobProgress(phase="execution", percent=50, message="import")
)
shutil.copytree(RUN, workspace.runs_path / job.job_id)
workspace.import_run_directory(job.job_id, workspace.runs_path / job.job_id)
workspace.update_job(
    job.job_id,
    JobStatus.completed,
    JobProgress(phase="completed", percent=100, message="ok"),
    result_reference=job.job_id,
)

replay = ReplayService(workspace)
tz = ZoneInfo(os.environ.get("REPLAY_TZ", "Europe/Rome"))
start = datetime.fromisoformat(FROM).replace(tzinfo=tz)
end = datetime.fromisoformat(TO).replace(tzinfo=tz)

print(f"replay {RUN.name}  {start:%d/%m %H:%M} -> {end:%H:%M}, un fotogramma ogni {STEP}s\n")
print(
    f"{'ora':>8}  {'stanza':13} {'posizione':>14}  "
    f"{'postura':9} {'stato':19} attivita' / sensori"
)
print("-" * 118)

previous = None
at = start
while at <= end:
    frame = replay.frame(job.job_id, at=at)
    person = frame.residents[0]
    where = person.region_id or "-"
    place = person.position
    spot = f"({place.x:5.2f},{place.y:5.2f})" if place else "      -     "
    doing = person.activity_label or "-"
    lit = sorted(
        item.sensor_id
        for item in frame.sensor_states
        if item.sensor_type != "temperature" and str(item.value).upper() in {"ON", "OPEN"}
    )
    line = (
        f"{at:%H:%M:%S}  {where:13} {spot:>14}  {person.posture or '-':9} "
        f"{person.execution_state:19} {doing}"
    )
    if lit:
        line += "   « " + " ".join(lit)
    signature = (where, person.posture, person.execution_state, doing)
    print(("  " if signature == previous else "* ") + line)
    previous = signature
    at += timedelta(seconds=STEP)
