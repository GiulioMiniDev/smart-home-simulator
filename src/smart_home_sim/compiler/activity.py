from __future__ import annotations

from smart_home_sim.domain.models import ActivityPlan
from smart_home_sim.microexecution.primitives import Primitive
from smart_home_sim.microexecution.templates import ActivityTemplateRegistry
from smart_home_sim.world.graph import HomeGraph


class ActivityCompiler:
    def __init__(
        self,
        home: HomeGraph,
        templates: ActivityTemplateRegistry,
        room_transition_minutes: float = 0.25,
    ) -> None:
        self._home = home
        self._templates = templates
        self._room_transition_minutes = room_transition_minutes

    def compile(self, activity: ActivityPlan, current_room: str) -> list[Primitive]:
        primitives: list[Primitive] = []
        route = self._home.route(current_room, activity.destination)
        for origin, destination in zip(route, route[1:], strict=False):
            primitives.append(
                Primitive(
                    label=f"move:{origin}->{destination}",
                    room=destination,
                    duration_minutes=self._room_transition_minutes,
                    movement_interval_seconds=3,
                )
            )

        profile = self._templates.get(activity.intent)
        interaction_count = len(profile.interaction_labels)
        interaction_duration = min(
            1.0,
            activity.duration_minutes / max(2 * (interaction_count + 1), 1),
        )
        remaining_duration = activity.duration_minutes

        for label in profile.interaction_labels:
            primitives.append(
                Primitive(
                    label=label,
                    room=activity.destination,
                    duration_minutes=interaction_duration,
                    movement_interval_seconds=profile.movement_interval_seconds,
                )
            )
            remaining_duration -= interaction_duration

        if remaining_duration > 0:
            primitives.append(
                Primitive(
                    label=activity.intent,
                    room=activity.destination,
                    duration_minutes=remaining_duration,
                    movement_interval_seconds=profile.movement_interval_seconds,
                )
            )

        return primitives
