"""Deterministically build a persona's planning world (stage A2a): no LLM.

A ``PlanningWorld`` is the reusable, window-agnostic environment for one persona: locations,
resources, the resident, and the initial placement — everything a scenario needs except the days.
It is the deterministic front half of the machinery. The personal process package (stage A2b) is
authored against this world, and the executable home is materialised from it afterwards, because the
home's entity capabilities are derived from the package's actions (so the home cannot precede it).
``assemble_scenario`` later combines a world with generated days and a window into a full scenario.

The apartment used to be a fixed template: five rooms and seventeen objects, byte-identical for
every persona ever generated, with a note asking for the swap to a per-persona world to be kept
open. ``hybrid_planning/dwelling.py`` is that swap. The home is now chosen for the person — a studio
for somebody living alone, a townhouse for a family, no staircase for somebody who should not be
climbing one — while the five rooms the activity catalog places intents in, and the objects the
reference process models bind by role, are guaranteed in every one of them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import (
    AuthorType,
    DayPlan,
    ExternalPerson,
    InitialState,
    Location,
    LocationKind,
    ModelReferences,
    Provenance,
    Resident,
    ResidentInitialState,
    Resource,
    Scenario,
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.dwelling import (
    CORE_RESOURCES,
    CORE_ROOMS,
    Dwelling,
    design_dwelling,
)
from smart_home_sim.hybrid_planning.persona import Persona

GENERATOR_NAME = "smart-home-sim.hybrid_planning.world"
GENERATOR_VERSION = "1.1.0"

HOME_COMPOSITE_ID = "home"
# Kept as names because tests, tools and the intent catalog all speak of "the standard rooms". They
# are now the *guaranteed* rooms rather than the only ones: every generated dwelling has these, and
# most have more.
STANDARD_ROOMS: tuple[str, ...] = CORE_ROOMS
STANDARD_EXTERNAL: tuple[str, ...] = ("outdoors",)
STANDARD_RESOURCES: tuple[tuple[str, str, str], ...] = CORE_RESOURCES


class PlanningWorld(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["planning_world"] = "planning_world"
    world_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str = "en"
    time_zone: str = Field(min_length=1)
    seed: int
    home_model: VersionedReference
    activity_catalog: VersionedReference
    residents: list[Resident] = Field(min_length=1)
    external_people: list[ExternalPerson] = Field(default_factory=list)
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    resident_placements: list[ResidentInitialState] = Field(min_length=1)
    resource_facts: dict[str, dict[str, object]] = Field(default_factory=dict)
    environment_facts: dict[str, object] = Field(default_factory=dict)
    provenance: Provenance

    @model_validator(mode="after")
    def check_location_references(self) -> PlanningWorld:
        primitive = {
            loc.location_id for loc in self.locations if loc.kind is not LocationKind.composite
        }
        known = {loc.location_id for loc in self.locations}
        for location in self.locations:
            for member in location.member_location_ids:
                if member not in known:
                    raise ValueError(f"composite location references unknown member {member!r}")
        for resource in self.resources:
            if resource.location_id not in primitive:
                raise ValueError(f"resource {resource.resource_id!r} references unknown location")
        for placement in self.resident_placements:
            if placement.location_id not in primitive:
                raise ValueError("resident placement references unknown location")
        return self


def build_planning_world(
    persona: Persona,
    *,
    seed: int = 1,
    activity_catalog_version: str = "1.0.0",
    home_model_version: str = "1.0.0",
    now: datetime | None = None,
    dwelling: Dwelling | None = None,
) -> PlanningWorld:
    """Build the world for one persona, in a home chosen for them.

    `dwelling` is normally left to the designer, which derives it from the persona and the seed; it
    is a parameter so a caller who wants a particular home — a fixture, a comparison against an
    earlier run — can hand one in rather than searching for a seed that produces it.
    """
    home = dwelling or design_dwelling(persona, seed=seed)
    locations = [
        Location(
            location_id=room.location_id,
            kind=LocationKind.room,
            # The storey rides in `attributes` because it is a fact about this dwelling rather than
            # a new dimension of the location contract, and because everything written before
            # houses had storeys means the ground floor and should keep meaning it.
            attributes={"level": room.level} if room.level else {},
        )
        for room in home.rooms
    ]
    locations.extend(
        Location(location_id=name, kind=LocationKind.external) for name in STANDARD_EXTERNAL
    )
    locations.append(
        Location(
            location_id=HOME_COMPOSITE_ID,
            kind=LocationKind.composite,
            member_location_ids=list(home.room_ids),
        )
    )
    resources = [
        Resource(
            resource_id=item.resource_id,
            resource_type=item.resource_type,
            location_id=item.location_id,
        )
        for item in home.resources
    ]
    resource_facts = {resource.resource_id: {"available": True} for resource in resources}

    resident = Resident(
        resident_id=persona.persona_id,
        display_name=persona.name,
        profile={
            "age": persona.age,
            "sex": persona.sex,
            "occupation": persona.occupation,
            "household": persona.household,
            "health": persona.health,
            "city": persona.city,
        },
    )
    relative = ExternalPerson(
        external_person_id="relative_01",
        display_name="Relative",
        relationship_to_residents={persona.persona_id: "family"},
    )
    placement = ResidentInitialState(
        resident_id=persona.persona_id, location_id="bedroom", facts={"awake": False}
    )
    provenance = Provenance(
        author_type=AuthorType.rule_generator,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        generated_at=now or datetime.now(UTC),
        parameters={"seed": seed, "dwelling": home.archetype_id},
    )
    return PlanningWorld(
        world_id=f"{persona.persona_id}_world",
        persona_id=persona.persona_id,
        scenario_id=f"{persona.persona_id}_scenario",
        title=f"Synthetic life of {persona.name}",
        time_zone=persona.timezone,
        seed=seed,
        home_model=VersionedReference(
            reference_id=f"{persona.persona_id}_home", version=home_model_version
        ),
        activity_catalog=VersionedReference(
            reference_id="activity_catalog", version=activity_catalog_version
        ),
        residents=[resident],
        external_people=[relative],
        locations=locations,
        resources=resources,
        resident_placements=[placement],
        resource_facts=resource_facts,
        # Read back by materialization: `dwelling_scale` is how big the plan is drawn, and the rest
        # is what the researcher sees in the report when they ask what kind of home this run is in.
        environment_facts={
            "dwelling_archetype": home.archetype_id,
            "dwelling_label": home.label,
            "dwelling_storeys": home.storeys,
            "dwelling_scale": home.scale,
        },
        provenance=provenance,
    )


def assemble_scenario(
    world: PlanningWorld,
    *,
    days: list[DayPlan],
    window: SimulationWindow,
    seed: int | None = None,
    provenance: Provenance | None = None,
) -> Scenario:
    """Combine a world with generated days and a window into a full, structurally valid scenario."""
    return Scenario(
        schema_version="1.0.0",
        scenario_id=world.scenario_id,
        title=world.title,
        language=world.language,
        time_zone=world.time_zone,
        simulation_window=window,
        seed=world.seed if seed is None else seed,
        provenance=provenance
        or Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=window.start,
        ),
        model_references=ModelReferences(
            activity_catalog=world.activity_catalog, home_model=world.home_model
        ),
        residents=world.residents,
        external_people=world.external_people,
        locations=world.locations,
        resources=world.resources,
        initial_state=InitialState(
            at=window.start,
            residents=world.resident_placements,
            resource_facts=world.resource_facts,
            environment_facts=world.environment_facts,
        ),
        days=days,
    )
