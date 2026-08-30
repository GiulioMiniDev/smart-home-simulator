"""Designing the home the persona lives in, instead of handing everybody the same flat.

`world.py` used to declare a constant: five rooms, seventeen objects, one storey, identical for
every persona ever generated. Its own module note called that deliberate and asked for the swap to
be kept open — "a later version may generate a per-persona world … keep that swap open". This is
that later version.

A dwelling is chosen in three steps, all deterministic in the seed:

1. an **archetype** — a small flat, a family flat, a maisonette, a townhouse, a bungalow — weighted
   by what the persona says about themselves. Somebody who lives alone is not given four bedrooms;
   somebody of eighty-two with a mobility note is not given a staircase;
2. its **rooms**, which are the five the activity catalog places intents in plus the archetype's own
   extras, each assigned to a storey;
3. its **furniture**, which is a fixed core plus a seeded draw from what each kind of room can hold.

The core is fixed on purpose and is exactly the seventeen objects the standard flat had. Every one
of them answers a role some reference process model names — the moka is `coffee_equipment`, the
wardrobe is `laundry_collection`, the cabinet is where medication lives — so dropping one at random
would not make the dataset more varied, it would make a behaviour unbindable. Variety is added
around that core, never taken out of it.

What this module does *not* do is invent rooms the activity catalog cannot place an intent in:
`expander._check_locations` rejects a world missing any of them, and rightly.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

# The rooms `INTENT_CATALOG` places intents in. Every dwelling has all of them,
# whatever else it has besides.
CORE_ROOMS: tuple[str, ...] = ("bedroom", "kitchen", "bathroom", "living_room", "balcony")

# The objects the reference process models bind against by role. Not optional, not shuffled: a
# generated home without a moka is a generated home where making coffee cannot be simulated.
CORE_RESOURCES: tuple[tuple[str, str, str], ...] = (
    ("bed_01", "bed", "bedroom"),
    ("wardrobe_01", "wardrobe", "bedroom"),
    ("stove_01", "stove", "kitchen"),
    ("moka_01", "moka_coffee_maker", "kitchen"),
    ("refrigerator_01", "refrigerator", "kitchen"),
    ("sink_01", "sink", "kitchen"),
    ("kitchen_table_01", "table", "kitchen"),
    ("kitchen_chair_01", "chair", "kitchen"),
    ("medication_cabinet_01", "storage_cabinet", "kitchen"),
    ("shower_01", "shower", "bathroom"),
    ("toilet_01", "toilet", "bathroom"),
    ("washbasin_01", "washbasin", "bathroom"),
    ("washing_machine_01", "washing_machine", "bathroom"),
    ("sofa_01", "sofa", "living_room"),
    ("television_01", "television", "living_room"),
    ("radio_01", "radio", "living_room"),
    ("planter_01", "garden_planter", "balcony"),
)


@dataclass(frozen=True)
class Archetype:
    archetype_id: str
    label: str
    storeys: int
    # How much bigger or smaller than the reference flat the plan is drawn. It multiplies the
    # per-room target areas, which already add up over the room list — a family flat is larger than
    # a studio because it has eleven rooms, not because of this — so the range here is narrow. At
    # 1.45 the same flat came out as a warehouse with a bed in one corner of it.
    scale: float
    # Rooms this kind of home always has, beyond the core five.
    extras: tuple[str, ...]
    # Rooms it may have, each with the chance that it does.
    optional: tuple[tuple[str, float], ...] = ()


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "studio_flat",
        "One-room flat",
        storeys=1,
        scale=0.78,
        extras=(),
        optional=(("storage", 0.3),),
    ),
    Archetype(
        "small_flat",
        "Small flat",
        storeys=1,
        scale=0.92,
        extras=("hallway",),
        optional=(("storage", 0.4), ("study", 0.25)),
    ),
    Archetype(
        "two_bedroom_flat",
        "Two-bedroom flat",
        storeys=1,
        scale=1.0,
        extras=("hallway", "second_bedroom"),
        optional=(("study", 0.35), ("storage", 0.4), ("laundry_room", 0.25)),
    ),
    Archetype(
        "family_flat",
        "Family flat",
        storeys=1,
        scale=1.08,
        extras=("hallway", "corridor", "second_bedroom", "second_bathroom"),
        optional=(("dining_room", 0.5), ("study", 0.4), ("laundry_room", 0.35)),
    ),
    Archetype(
        "maisonette",
        "Two-storey maisonette",
        storeys=2,
        scale=1.0,
        extras=("hallway", "landing", "second_bedroom"),
        optional=(("study", 0.4), ("storage", 0.35)),
    ),
    Archetype(
        "townhouse",
        "Townhouse",
        storeys=2,
        scale=1.15,
        extras=("hallway", "landing", "second_bedroom", "second_bathroom", "dining_room"),
        optional=(("study", 0.6), ("laundry_room", 0.4), ("storage", 0.4), ("terrace", 0.5)),
    ),
    Archetype(
        "bungalow",
        "Bungalow",
        storeys=1,
        scale=1.1,
        extras=("hallway", "second_bedroom"),
        optional=(("study", 0.45), ("terrace", 0.55), ("storage", 0.5), ("laundry_room", 0.3)),
    ),
)

# What goes upstairs when there is an upstairs. Everything else stays on the ground, which is where
# the front door is: `_ENTRANCE_REGION` in materialization puts it in a circulation space, and a
# flat whose only hallway was upstairs would put its front door on the first floor.
_UPPER_ROOMS = frozenset(
    {"bedroom", "second_bedroom", "bathroom", "landing", "study", "second_bathroom"}
)

# Furniture a kind of room may hold beyond the core, each with the chance that it does and how many
# of it there are. Nothing here answers a role the reference behaviours name; these are the objects
# that make a room a room, and their job is to be in the way, be walked round, and be looked at.
_OPTIONAL_FURNITURE: dict[str, tuple[tuple[str, float, int], ...]] = {
    "living_room": (
        ("coffee_table", 0.9, 1),
        ("armchair", 0.8, 2),
        ("tv_stand", 0.55, 1),
        ("bookshelf", 0.75, 2),
        ("sideboard", 0.5, 1),
        ("floor_lamp", 0.7, 1),
        ("houseplant", 0.65, 1),
    ),
    "bedroom": (
        ("nightstand", 0.9, 2),
        ("chest_of_drawers", 0.65, 1),
        ("armchair", 0.4, 1),
        ("bookshelf", 0.35, 1),
        ("mirror", 0.45, 1),
        ("floor_lamp", 0.45, 1),
        ("houseplant", 0.35, 1),
    ),
    "second_bedroom": (
        ("single_bed", 1.0, 1),
        ("wardrobe", 0.8, 1),
        ("nightstand", 0.75, 1),
        ("desk", 0.6, 1),
        ("chair", 0.6, 1),
        ("bookshelf", 0.5, 1),
        ("chest_of_drawers", 0.4, 1),
    ),
    "kitchen": (
        ("kitchen_counter", 0.9, 2),
        ("chair", 0.9, 3),
        ("microwave", 0.5, 1),
        ("dishwasher", 0.4, 1),
        ("oven", 0.3, 1),
        ("kettle", 0.35, 1),
        ("houseplant", 0.3, 1),
    ),
    "bathroom": (
        ("mirror", 0.6, 1),
        ("bathtub", 0.25, 1),
        ("bidet", 0.55, 1),
        ("medicine_cabinet", 0.45, 1),
    ),
    "second_bathroom": (
        ("toilet", 1.0, 1),
        ("washbasin", 1.0, 1),
        ("shower", 0.55, 1),
        ("mirror", 0.5, 1),
    ),
    "hallway": (
        ("shoe_rack", 0.7, 1),
        ("coat_rack", 0.65, 1),
        ("mirror", 0.45, 1),
        ("sideboard", 0.35, 1),
        ("bench", 0.35, 1),
        ("houseplant", 0.35, 1),
    ),
    "corridor": (("bookshelf", 0.4, 1), ("houseplant", 0.4, 1)),
    "landing": (("bookshelf", 0.5, 1), ("houseplant", 0.45, 1), ("chest_of_drawers", 0.3, 1)),
    "study": (
        ("desk", 1.0, 1),
        ("chair", 1.0, 1),
        ("bookshelf", 0.9, 3),
        ("armchair", 0.4, 1),
        ("chest_of_drawers", 0.35, 1),
        ("floor_lamp", 0.55, 1),
        ("houseplant", 0.35, 1),
    ),
    "dining_room": (
        ("table", 1.0, 1),
        ("chair", 1.0, 4),
        ("sideboard", 0.65, 1),
        ("bookshelf", 0.35, 1),
        ("houseplant", 0.45, 1),
    ),
    "laundry_room": (("drying_rack", 0.8, 1), ("storage_cabinet", 0.5, 1)),
    "storage": (("storage_cabinet", 1.0, 1), ("bookshelf", 0.35, 1)),
    "balcony": (("garden_chair", 0.6, 1), ("drying_rack", 0.45, 1), ("houseplant", 0.5, 1)),
    "terrace": (("garden_chair", 0.8, 2), ("garden_planter", 0.7, 1), ("table", 0.4, 1)),
}


@dataclass(frozen=True)
class DwellingRoom:
    location_id: str
    level: int


@dataclass(frozen=True)
class DwellingResource:
    resource_id: str
    resource_type: str
    location_id: str


@dataclass(frozen=True)
class Dwelling:
    archetype_id: str
    label: str
    storeys: int
    scale: float
    rooms: tuple[DwellingRoom, ...]
    resources: tuple[DwellingResource, ...]

    @property
    def room_ids(self) -> tuple[str, ...]:
        return tuple(room.location_id for room in self.rooms)

    def summary(self) -> str:
        """One line for provenance and for the researcher reading a generation report."""
        return (
            f"{self.label}, {self.storeys} storey"
            f"{'' if self.storeys == 1 else 's'}, {len(self.rooms)} rooms, "
            f"{len(self.resources)} objects"
        )


@dataclass(frozen=True)
class Household:
    """What the persona tells us about the home they need, reduced to what changes the plan."""

    age: int
    alone: bool
    with_children: bool
    works_at_home: bool
    avoids_stairs: bool

    @classmethod
    def from_persona(cls, persona: object | None) -> Household:
        if persona is None:
            return cls(
                45,
                alone=True,
                with_children=False,
                works_at_home=False,
                avoids_stairs=False,
            )
        age = int(getattr(persona, "age", 45) or 45)
        household = str(getattr(persona, "household", "") or "").lower()
        occupation = str(getattr(persona, "occupation", "") or "").lower()
        health = " ".join(str(item).lower() for item in getattr(persona, "health", ()) or ())
        children_words = ("child", "children", "kid", "son", "daughter", "figl", "bambin")
        alone_words = ("alone", "solo", "sola", "single", "by herself", "by himself")
        home_work_words = (
            "freelance",
            "remote",
            "writer",
            "translator",
            "artist",
            "researcher",
            "consultant",
            "student",
            "designer",
            "developer",
            "teacher",
        )
        stair_words = (
            "mobility",
            "wheelchair",
            "walking",
            "hip",
            "knee",
            "arthr",
            "frail",
            "balance",
            "stroke",
        )
        return cls(
            age=age,
            alone=any(word in household for word in alone_words) or not household,
            with_children=any(word in household for word in children_words),
            works_at_home=any(word in occupation for word in home_work_words),
            # Above eighty a staircase is a fall risk whatever the health note says;
            # below it, the note decides. A generated home is somewhere a body has to
            # live for a simulated year.
            avoids_stairs=age >= 80 or any(word in health for word in stair_words),
        )


def design_dwelling(persona: object | None = None, *, seed: int = 1) -> Dwelling:
    """Choose a home for this persona: deterministic in the seed, plausible for the person."""
    random = Random(f"dwelling:{seed}:{getattr(persona, 'persona_id', '')}")
    household = Household.from_persona(persona)
    archetype = _choose_archetype(household, random)
    rooms = _choose_rooms(archetype, household, random)
    resources = _furnish(rooms, random)
    return Dwelling(
        archetype_id=archetype.archetype_id,
        label=archetype.label,
        storeys=max(room.level for room in rooms) + 1,
        scale=archetype.scale,
        rooms=rooms,
        resources=resources,
    )


def _choose_archetype(household: Household, random: Random) -> Archetype:
    """Weight the catalogue by the household, then draw. Nothing here is a hard rule except the
    staircase: everything else only shifts the odds, so two people with the same answers still end
    up in different homes."""
    weights: dict[str, float] = {
        "studio_flat": 1.0,
        "small_flat": 2.0,
        "two_bedroom_flat": 2.0,
        "family_flat": 1.0,
        "maisonette": 1.0,
        "townhouse": 0.8,
        "bungalow": 1.0,
    }
    if household.alone:
        weights["studio_flat"] *= 2.2
        weights["small_flat"] *= 1.8
        weights["family_flat"] *= 0.3
        weights["townhouse"] *= 0.4
    if household.with_children:
        weights["studio_flat"] *= 0.05
        weights["small_flat"] *= 0.2
        weights["family_flat"] *= 3.0
        weights["townhouse"] *= 2.5
        weights["two_bedroom_flat"] *= 1.5
    if household.age >= 70:
        weights["bungalow"] *= 2.0
        weights["studio_flat"] *= 1.3
    if household.age <= 30:
        weights["studio_flat"] *= 1.6
        weights["bungalow"] *= 0.4
    if household.avoids_stairs:
        weights["maisonette"] = 0.0
        weights["townhouse"] = 0.0
    ordered = [item for item in ARCHETYPES if weights[item.archetype_id] > 0]
    return random.choices(ordered, weights=[weights[item.archetype_id] for item in ordered])[0]


def _choose_rooms(
    archetype: Archetype, household: Household, random: Random
) -> tuple[DwellingRoom, ...]:
    names = list(CORE_ROOMS) + [item for item in archetype.extras if item not in CORE_ROOMS]
    for name, chance in archetype.optional:
        if name in names:
            continue
        # Somebody who works from home gets the study far more often than the dice alone would
        # give it, because that is the room their day is actually spent in.
        odds = min(chance * (2.0 if name == "study" and household.works_at_home else 1.0), 0.95)
        if random.random() < odds:
            names.append(name)
    if archetype.storeys > 1:
        # A staircase needs somewhere to arrive. `landing` is in every two-storey archetype's
        # extras, but an archetype is a table and tables get edited, so the invariant is asserted
        # here rather than trusted there.
        if "landing" not in names:
            names.append("landing")
        if "hallway" not in names:
            names.append("hallway")
    levels = {name: (1 if archetype.storeys > 1 and name in _UPPER_ROOMS else 0) for name in names}
    # A balcony belongs to the storey it opens off. On two floors that is the bedroom floor as often
    # as not, and putting it always downstairs is what would make every generated house identical
    # in the one place a plan is read first.
    if archetype.storeys > 1 and random.random() < 0.45:
        levels["balcony"] = 1
    return tuple(
        DwellingRoom(location_id=name, level=levels[name]) for name in _ordered(names, levels)
    )


def _ordered(names: list[str], levels: dict[str, int]) -> list[str]:
    """Ground floor first, then core rooms before extras, so the world reads in a stable order."""
    core = {name: index for index, name in enumerate(CORE_ROOMS)}
    return sorted(names, key=lambda name: (levels[name], core.get(name, len(core)), name))


def _furnish(rooms: tuple[DwellingRoom, ...], random: Random) -> tuple[DwellingResource, ...]:
    present = {room.location_id for room in rooms}
    resources = [
        DwellingResource(resource_id, resource_type, location_id)
        for resource_id, resource_type, location_id in CORE_RESOURCES
    ]
    # A home with a utility room does its laundry there. The machine is the same machine and the
    # same role; only the room it stands in changes, and the binder follows the object.
    if "laundry_room" in present:
        resources = [
            DwellingResource(item.resource_id, item.resource_type, "laundry_room")
            if item.resource_type == "washing_machine"
            else item
            for item in resources
        ]
    # Ids are qualified by the room they stand in. Numbering the extras on their own gave the guest
    # room's `wardrobe_01`, which is the id the master bedroom's core wardrobe already had, and the
    # home model rejected the whole dwelling for a duplicate identifier. It also reads better: the
    # bookshelf on the landing and the bookshelf in the study are told apart by name.
    used = {item.resource_id for item in resources}
    counters: dict[str, int] = {}
    for room in rooms:
        for entity_type, chance, count in _OPTIONAL_FURNITURE.get(room.location_id, ()):
            if random.random() >= chance:
                continue
            # How many of a thing a room gets is itself variable: four dining chairs in one house,
            # two in the next.
            wanted = count if count == 1 else random.randint(max(count - 2, 1), count)
            for _ in range(wanted):
                key = f"{entity_type}_{room.location_id}"
                counters[key] = counters.get(key, 0) + 1
                resource_id = f"{key}_{counters[key]:02d}"
                if resource_id in used:
                    continue
                used.add(resource_id)
                resources.append(
                    DwellingResource(
                        resource_id=resource_id,
                        resource_type=entity_type,
                        location_id=room.location_id,
                    )
                )
    return tuple(sorted(resources, key=lambda item: item.resource_id))


__all__ = [
    "ARCHETYPES",
    "CORE_RESOURCES",
    "CORE_ROOMS",
    "Archetype",
    "Dwelling",
    "DwellingResource",
    "DwellingRoom",
    "Household",
    "design_dwelling",
]
