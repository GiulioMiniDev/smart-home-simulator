"""Passata sistematica su un run: posizioni, durate, posture, stanze, orari, camminate, notte.

Non stampa un giudizio: stampa ogni violazione delle attese, con l'esempio che la mostra. Le
attese sono dichiarate qui sopra in tabella, cosi' si discutono invece di essere implicite.

Uso:  audit.py <run-dir>
"""

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from smart_home_sim.domain.execution import ExecutionTrace

RUN = Path(sys.argv[1])
trace = ExecutionTrace.model_validate_json((RUN / "execution-trace.json").read_text("utf-8"))
home = json.loads((RUN / "home-model.json").read_text("utf-8"))

points = {item["interactionPointId"]: item for item in home["interactionPoints"]}
furniture = [
    (
        entity["entityType"],
        entity["regionId"],
        points[entity["interactionPointId"]]["position"]["x"],
        points[entity["interactionPointId"]]["position"]["y"],
    )
    for entity in home["entities"]
    if entity.get("interactionPointId") in points
    and entity["entityType"] != "generated_environment_service"
]

# --- le attese, dichiarate ----------------------------------------------------------------
# intento -> (mobili plausibili, stanze plausibili, posture plausibili, min/max minuti)
EXPECT = {
    "sleep": ({"bed"}, {"bedroom"}, {"lying"}, 240, 660),
    "wake_up": (set(), {"bedroom"}, {"standing", "sitting", "lying"}, 1, 45),
    "night_toilet_visit": ({"toilet"}, {"bathroom"}, {"standing", "sitting"}, 1, 15),
    "use_toilet": ({"toilet"}, {"bathroom"}, {"standing", "sitting"}, 1, 15),
    "morning_toilet_and_shower": ({"toilet", "shower", "washbasin"}, {"bathroom"},
                                  {"standing"}, 5, 50),
    "eat_breakfast": ({"table", "chair"}, {"kitchen"}, {"sitting"}, 5, 45),
    "eat_lunch": ({"table", "chair"}, {"kitchen"}, {"sitting"}, 10, 60),
    "eat_dinner": ({"table", "chair"}, {"kitchen"}, {"sitting"}, 10, 75),
    "prepare_and_drink_hot_drink": ({"moka_coffee_maker", "table", "chair", "sink"},
                                    {"kitchen"}, {"standing", "sitting"}, 3, 35),
    "weekly_meal_preparation": ({"stove", "sink", "table"}, {"kitchen"}, {"standing"}, 10, 90),
    "clean_kitchen": ({"sink", "stove", "table"}, {"kitchen"}, {"standing"}, 8, 70),
    "work_from_home": ({"table", "chair"}, {"living_room"}, {"sitting"}, 15, 240),
    "read_and_rest": ({"sofa", "armchair"}, {"living_room"}, {"sitting", "lying"}, 8, 160),
    "watch_television": ({"sofa", "television"}, {"living_room"}, {"sitting", "lying"}, 8, 150),
    "phone_call": (set(), {"living_room", "kitchen", "bedroom"},
                   {"sitting", "standing", "lying"}, 3, 75),
    "tidy_living_room_and_hallway": (set(), {"living_room"}, {"standing"}, 8, 60),
    "take_morning_medication": ({"storage_cabinet", "sink", "table"}, {"kitchen"},
                                {"standing", "sitting"}, 2, 25),
    "start_laundry": ({"washing_machine"}, {"bathroom"}, {"standing"}, 5, 40),
    "hang_laundry": (set(), {"balcony"}, {"standing"}, 5, 40),
    "evening_walk": (set(), {"outdoors"}, {"standing"}, 15, 100),
    "leave_home": (set(), {"outdoors"}, {"standing"}, 15, 180),
    "social_drink_out": (set(), {"outdoors"}, {"standing"}, 20, 200),
    "visit_relative_and_have_dinner": (set(), {"outdoors"}, {"standing"}, 60, 700),
    "rest_or_nap": ({"sofa", "bed"}, {"living_room", "bedroom"}, {"lying"}, 15, 90),
}
# Quante volte al giorno e' plausibile, per una persona
PER_DAY = {
    "sleep": (0.8, 1.4), "wake_up": (0.8, 1.4), "eat_breakfast": (0.8, 1.2),
    "eat_lunch": (0.8, 1.2), "eat_dinner": (0.8, 1.2), "use_toilet": (3, 9),
    "morning_toilet_and_shower": (0.8, 1.2),
}
WALK_MIN_KMH, WALK_MAX_KMH = 2.0, 6.5

postures = sorted(
    (item.at, str(item.value))
    for item in trace.state_transitions
    if item.subject_type == "resident" and item.fact == "posture"
)
places = sorted((item.ended_at, item.destination_region_id) for item in trace.movements)
spots = sorted(
    (item.ended_at, (item.waypoints[-1].position.x, item.waypoints[-1].position.y))
    for item in trace.movements
)


def sample(pairs, moment, default=None):
    found = default
    for when, value in pairs:
        if when > moment:
            break
        found = value
    return found


def nearest(spot, region):
    if spot is None:
        return None, 99.0
    best, distance = None, 99.0
    for kind, where, x, y in furniture:
        if where != region:
            continue
        d = math.hypot(x - spot[0], y - spot[1])
        if d < distance:
            best, distance = kind, d
    return best, distance


done = sorted(
    (a for a in trace.activity_executions if a.status != "dropped"), key=lambda a: a.actual_start
)
days = len({a.actual_start.date() for a in done})
problems = defaultdict(list)

for a in done:
    centre = a.actual_start + (a.actual_end - a.actual_start) / 2
    minutes = (a.actual_end - a.actual_start).total_seconds() / 60
    region = sample(places, centre, "?")
    posture = sample(postures, centre, "?")
    spot = sample(spots, centre)
    kind, distance = nearest(spot, region)
    if a.intent not in EXPECT:
        problems["intento non previsto dall'audit"].append(f"{a.intent}")
        continue
    ok_furniture, ok_rooms, ok_postures, low, high = EXPECT[a.intent]
    when = f"{a.actual_start:%d/%m %H:%M}"
    if ok_rooms and region not in ok_rooms and region != "?":
        problems["stanza implausibile"].append(f"{when} {a.intent} in {region}")
    if posture not in ok_postures and posture != "?":
        problems["postura implausibile"].append(f"{when} {a.intent} {posture}")
    if not (low <= minutes <= high):
        problems["durata implausibile"].append(
            f"{when} {a.intent} {minutes:.0f} min (atteso {low}-{high})"
        )
    if ok_furniture and region in ok_rooms:
        if kind is None or distance > 1.2:
            problems["lontana da qualunque mobile adatto"].append(
                f"{when} {a.intent}: piu' vicino {kind} a {distance:.1f} m"
            )
        elif kind not in ok_furniture:
            problems["mobile sbagliato"].append(
                f"{when} {a.intent} accanto a {kind} (atteso {'/'.join(sorted(ok_furniture))})"
            )

counts = Counter(a.intent for a in done)
for intent, (low, high) in PER_DAY.items():
    rate = counts.get(intent, 0) / days
    if not (low <= rate <= high):
        problems["frequenza giornaliera implausibile"].append(
            f"{intent}: {rate:.1f}/giorno (atteso {low}-{high})"
        )

inplace = sum(1 for m in trace.movements if m.origin_region_id == m.destination_region_id)
speeds = []
for m in trace.movements:
    seconds = m.duration_microseconds / 1e6
    if seconds > 0 and m.distance_meters > 0.5:
        kmh = m.distance_meters / seconds * 3.6
        speeds.append(kmh)
        outside = "outdoors" in {m.destination_region_id, m.origin_region_id}
        if not outside and not (WALK_MIN_KMH <= kmh <= WALK_MAX_KMH):
            problems["velocita' implausibile"].append(
                f"{m.started_at:%d/%m %H:%M} {m.origin_region_id}->{m.destination_region_id} "
                f"{kmh:.1f} km/h"
                )

nights = defaultdict(float)
for a in done:
    if a.intent == "sleep":
        nights[(a.actual_start - timedelta(hours=12)).date()] += (
            a.actual_end - a.actual_start
        ).total_seconds() / 3600
for night, hours in sorted(nights.items()):
    if not (5.0 <= hours <= 11.0):
        problems["notte implausibile"].append(f"{night}: {hours:.1f} h")

print(f"run {RUN.name}: {len(done)} attivita' su {days} giornate, {len(trace.movements)} movimenti")
print(f"movimenti sul posto (stessa stanza): {inplace} ({inplace/len(trace.movements):.0%})")
if speeds:
    print(f"andatura interna: mediana {statistics.median(speeds):.2f} km/h, "
          f"da {min(speeds):.2f} a {max(speeds):.2f}")
indoor = sum(
    m.distance_meters
    for m in trace.movements
    if "outdoors" not in {m.destination_region_id, m.origin_region_id}
)
print(f"distanza percorsa in casa: {indoor / days:.0f} m/giorno")
print()
print("intenti al giorno: " + ", ".join(f"{k} {v/days:.1f}" for k, v in counts.most_common(10)))

print("\n" + "=" * 78)
if not problems:
    print("nessuna violazione delle attese dichiarate")
for title, items in problems.items():
    print(f"\n### {title}  ({len(items)})")
    for item in items[:8]:
        print(f"    {item}")
    if len(items) > 8:
        print(f"    ... e altre {len(items) - 8}")
