"""Legge una giornata gia' simulata come la leggerebbe una persona.

Uso:  leggi.py <run-dir> [n_giorni]

Stanza e postura sono campionate a meta' dell'intervallo che descrivono, non al suo inizio:
al suo inizio si vede da dove viene, che e' la domanda sbagliata.
"""

import sys
from collections import Counter
from pathlib import Path

from smart_home_sim.domain.execution import ExecutionTrace

RUN = Path(sys.argv[1])
COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 2

trace = ExecutionTrace.model_validate_json(
    (RUN / "execution-trace.json").read_text(encoding="utf-8")
)
postures = sorted(
    (item.at, str(item.value))
    for item in trace.state_transitions
    if item.subject_type == "resident" and item.fact == "posture"
)
# Dove si trova, minuto per minuto: l'arrivo di ogni movimento la lascia li' fino al successivo.
places = sorted((item.ended_at, item.destination_region_id) for item in trace.movements)
# E in che punto della stanza, che e' la meta' della domanda che il diario non sapeva porre: una
# persona sdraiata in soggiorno e' sul divano o per terra a seconda di dove si trova.
spots = sorted(
    (item.ended_at, (item.waypoints[-1].position.x, item.waypoints[-1].position.y))
    for item in trace.movements
)
furniture = []  # riempito sotto se il modello di casa e' accanto alla traccia
HOME = RUN / "home-model.json"
if HOME.is_file():
    import json

    home = json.loads(HOME.read_text(encoding="utf-8"))
    points = {p["interactionPointId"]: p for p in home["interactionPoints"]}
    furniture = [
        (
            entity["entityType"],
            points[entity["interactionPointId"]]["position"]["x"],
            points[entity["interactionPointId"]]["position"]["y"],
        )
        for entity in home["entities"]
        if entity.get("interactionPointId") in points
        and entity["entityType"] != "generated_environment_service"
    ]


def near(spot):
    """Il mobile piu' vicino, se e' a portata.

    E' cosi' che si distingue un divano da un pavimento.
    """
    if spot is None or not furniture:
        return ""
    best, distance = "", 99.0
    for kind, x, y in furniture:
        d = ((x - spot[0]) ** 2 + (y - spot[1]) ** 2) ** 0.5
        if d < distance:
            best, distance = kind, d
    return best if distance <= 0.9 else "(niente vicino)"


def sample(pairs, moment, default="?"):
    found = default
    for when, value in pairs:
        if when > moment:
            break
        found = value
    return found


def middle(start, end):
    return start + (end - start) / 2


done = sorted(
    (a for a in trace.activity_executions if a.status != "dropped"), key=lambda a: a.actual_start
)
days = sorted({a.actual_start.date() for a in done})[:COUNT]
done = [a for a in done if a.actual_start.date() in days]

# Le ore prima della prima attivita' esistono e finora non le guardavo: un orizzonte comincia a
# mezzanotte e la sua prima attivita' e' la sveglia, quindi sei ore restavano fuori dalla lettura.
opening = trace.started_at
first = done[0].actual_start
if (first - opening).total_seconds() > 60:
    minutes = (first - opening).total_seconds() / 60
    print()
    print("=" * 76)
    print("PRIMA DI TUTTO")
    print("=" * 76)
    print(
        f"{opening:%H:%M}-{first:%H:%M}{minutes:6.0f}m  "
        f"{'(nessuna attivita)':30s} {sample(places, first, '?'):13s} "
        f"{sample(postures, first, '?')}"
    )

previous = None
current = None
flush = 0
for activity in done:
    if activity.actual_start.date() != current:
        current = activity.actual_start.date()
        previous = None
        print(f"\n{'=' * 76}\n{current:%A %d %B %Y}\n{'=' * 76}")
    if previous is not None:
        gap = (activity.actual_start - previous).total_seconds() / 60
        if gap > 0.2:
            centre = middle(previous, activity.actual_start)
            spot = sample(spots, centre, None)
            print(
                f"         · · · {gap:5.0f} min  "
                f"{sample(places, centre):13s} {sample(postures, centre):9s} {near(spot)}"
            )
        else:
            flush += 1
            print("         · · · a filo")
    centre = middle(activity.actual_start, activity.actual_end)
    minutes = (activity.actual_end - activity.actual_start).total_seconds() / 60
    spot = sample(spots, centre, None)
    print(
        f"{activity.actual_start:%H:%M}-{activity.actual_end:%H:%M}{minutes:6.0f}m  "
        f"{activity.intent:30s} {sample(places, centre):13s} "
        f"{sample(postures, centre):9s} {near(spot)}"
    )
    previous = activity.actual_end

print(f"\n{'=' * 76}")
print(f"attivita' {len(done)} su {len(days)} giorni  |  partenze a filo: {flush}")
print("intenti:", Counter(a.intent for a in done).most_common(8))
