from __future__ import annotations

import random
from collections.abc import Generator
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import simpy

from smart_home_sim.compiler.activity import ActivityCompiler
from smart_home_sim.domain.models import (
    ActivityExecution,
    GroundTruthEvent,
    RawSensorEvent,
    Scenario,
    SimulationResult,
)
from smart_home_sim.microexecution.primitives import Primitive
from smart_home_sim.microexecution.templates import ActivityTemplateRegistry
from smart_home_sim.sensors.pir import PirSensor
from smart_home_sim.validation.scenario import require_valid_scenario
from smart_home_sim.world.graph import HomeGraph


def run_simulation(scenario: Scenario) -> SimulationResult:
    require_valid_scenario(scenario)

    env = simpy.Environment()
    rng = random.Random(scenario.seed)
    origin = datetime.combine(
        scenario.simulation_date,
        time.min,
        tzinfo=ZoneInfo(scenario.time_zone),
    )
    raw_events: list[RawSensorEvent] = []
    ground_truth: list[GroundTruthEvent] = []
    activity_executions: list[ActivityExecution] = []

    sensors_by_room: dict[str, list[PirSensor]] = {}
    for config in scenario.sensors:
        sensor = PirSensor(env, config, origin, rng, raw_events.append)
        sensors_by_room.setdefault(config.room, []).append(sensor)

    compiler = ActivityCompiler(HomeGraph(scenario.rooms), ActivityTemplateRegistry())

    def execute_primitive(
        primitive: Primitive,
        activity_id: str,
    ) -> Generator[simpy.Event, None, None]:
        primitive_start = float(env.now)
        primitive_end = primitive_start + primitive.duration_minutes

        if primitive.movement_interval_seconds is None:
            yield env.timeout(primitive.duration_minutes)
        else:
            while float(env.now) < primitive_end:
                for sensor in sensors_by_room.get(primitive.room, []):
                    sensor.detect_motion()

                base_interval = primitive.movement_interval_seconds / 60
                jittered_interval = base_interval * rng.uniform(0.8, 1.2)
                remaining = primitive_end - float(env.now)
                yield env.timeout(min(jittered_interval, remaining))

        ground_truth.append(
            GroundTruthEvent(
                start=origin + timedelta(minutes=primitive_start),
                end=origin + timedelta(minutes=float(env.now)),
                actor_id=scenario.resident.resident_id,
                activity_id=activity_id,
                primitive=primitive.label,
                room=primitive.room,
            )
        )

    def resident_process() -> Generator[simpy.Event, None, None]:
        current_room = scenario.resident.initial_room
        for activity in sorted(scenario.activities, key=lambda item: item.start_minute):
            if float(env.now) < activity.start_minute:
                yield env.timeout(activity.start_minute - float(env.now))

            actual_start = float(env.now)
            for primitive in compiler.compile(activity, current_room):
                yield env.process(execute_primitive(primitive, activity.activity_id))
                current_room = primitive.room

            activity_executions.append(
                ActivityExecution(
                    activity_id=activity.activity_id,
                    planned_start=origin + timedelta(minutes=activity.start_minute),
                    actual_start=origin + timedelta(minutes=actual_start),
                    actual_end=origin + timedelta(minutes=float(env.now)),
                )
            )

    env.process(resident_process())
    env.run()

    return SimulationResult(
        scenario_id=scenario.scenario_id,
        raw_sensor_events=raw_events,
        ground_truth=ground_truth,
        activity_executions=activity_executions,
    )
