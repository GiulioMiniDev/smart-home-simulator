"""Which home a persona gets.

Every persona used to get the same five-room flat with the same seventeen objects in it. What has
to be true now is both halves of the change: the home varies, and what the rest of the machinery
needs from it does not.
"""

from __future__ import annotations

from collections import Counter

from smart_home_sim.hybrid_planning.dwelling import (
    ARCHETYPES,
    CORE_RESOURCES,
    CORE_ROOMS,
    Household,
    design_dwelling,
)
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG


class _Persona:
    """The four fields the designer reads. A real `Persona` has many more."""

    def __init__(
        self,
        persona_id: str = "somebody",
        age: int = 45,
        household: str = "lives alone",
        occupation: str = "clerk",
        health: tuple[str, ...] = (),
    ) -> None:
        self.persona_id = persona_id
        self.age = age
        self.household = household
        self.occupation = occupation
        self.health = list(health)


def _seeds(count: int = 30) -> range:
    return range(1, count + 1)


def test_every_dwelling_has_the_rooms_the_activity_catalog_places_intents_in() -> None:
    """`expander._check_locations` rejects a world missing one of these, and rightly."""
    required = {spec.default_location for spec in INTENT_CATALOG} - {"outdoors"}
    assert required <= set(CORE_ROOMS)
    for seed in _seeds():
        rooms = {room.location_id for room in design_dwelling(_Persona(), seed=seed).rooms}
        assert required <= rooms, seed


def test_every_dwelling_holds_the_objects_the_process_models_bind_by_role() -> None:
    core = {resource_type for _, resource_type, _ in CORE_RESOURCES}
    for seed in _seeds():
        present = Counter(
            item.resource_type for item in design_dwelling(_Persona(), seed=seed).resources
        )
        assert core <= set(present), seed


def test_resource_identifiers_are_unique() -> None:
    """A duplicate id is not a cosmetic problem: the home model refuses to be built at all."""
    for seed in _seeds(60):
        resources = design_dwelling(
            _Persona(household="family with two children"), seed=seed
        ).resources
        identifiers = [item.resource_id for item in resources]
        assert len(identifiers) == len(set(identifiers)), seed


def test_the_same_seed_designs_the_same_home_and_different_seeds_do_not() -> None:
    persona = _Persona()
    assert design_dwelling(persona, seed=7) == design_dwelling(persona, seed=7)
    shapes = {
        (
            design_dwelling(persona, seed=seed).archetype_id,
            design_dwelling(persona, seed=seed).room_ids,
        )
        for seed in _seeds()
    }
    assert len(shapes) > 3, "one flat with the ornaments shuffled is not variation"


def test_who_lives_there_moves_the_odds() -> None:
    def archetypes(persona: _Persona) -> Counter[str]:
        return Counter(design_dwelling(persona, seed=seed).archetype_id for seed in _seeds(80))

    alone = archetypes(_Persona(persona_id="alone", household="lives alone"))
    family = archetypes(
        _Persona(persona_id="family", household="lives with partner and two children")
    )
    assert alone["studio_flat"] > family["studio_flat"]
    assert family["family_flat"] + family["townhouse"] > alone["family_flat"] + alone["townhouse"]


def test_somebody_who_should_not_climb_stairs_is_never_given_a_staircase() -> None:
    """Not a preference. A generated home is somewhere a body lives for a simulated year."""
    for persona in (
        _Persona(persona_id="frail", age=84),
        _Persona(persona_id="hip", age=61, health=("hip replacement",)),
        _Persona(persona_id="chair", age=48, health=("wheelchair user",)),
    ):
        for seed in _seeds(40):
            dwelling = design_dwelling(persona, seed=seed)
            assert dwelling.storeys == 1, (persona.persona_id, seed, dwelling.archetype_id)
            assert all(room.level == 0 for room in dwelling.rooms)


def test_a_two_storey_home_puts_the_front_door_downstairs_and_the_beds_up() -> None:
    seen = 0
    for seed in _seeds(60):
        dwelling = design_dwelling(_Persona(persona_id="young", age=31), seed=seed)
        if dwelling.storeys < 2:
            continue
        seen += 1
        levels = {room.location_id: room.level for room in dwelling.rooms}
        assert levels["bedroom"] == 1
        assert levels["kitchen"] == 0 and levels["living_room"] == 0
        # Something to arrive on, and something to leave from.
        assert levels.get("landing") == 1
        assert levels.get("hallway") == 0
    assert seen > 0, "no two-storey home was ever designed, so nothing was checked"


def test_a_study_follows_the_work_rather_than_the_dice() -> None:
    def studies(occupation: str) -> int:
        return sum(
            "study" in design_dwelling(_Persona(occupation=occupation), seed=seed).room_ids
            for seed in _seeds(80)
        )

    assert studies("freelance translator") > studies("bus driver")


def test_every_archetype_is_reachable_and_describes_itself() -> None:
    reachable = {
        design_dwelling(_Persona(age=age, household=household), seed=seed).archetype_id
        for seed in _seeds(40)
        for age, household in (
            (28, "lives alone"),
            (44, "lives with partner and two children"),
            (74, "lives alone"),
        )
    }
    assert reachable == {item.archetype_id for item in ARCHETYPES}
    summary = design_dwelling(_Persona(), seed=1).summary()
    assert "storey" in summary and "rooms" in summary


def test_a_household_reads_what_the_persona_says_about_itself() -> None:
    household = Household.from_persona(
        _Persona(age=37, household="lives with her two children", occupation="remote developer")
    )
    assert household.with_children and household.works_at_home and not household.avoids_stairs
    # No persona at all is the fixture case, and it must not blow up.
    assert Household.from_persona(None).alone
