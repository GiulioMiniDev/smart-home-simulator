from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import JsonValue, ValidationError
from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint
from shapely.ops import nearest_points, unary_union

from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import ExecutionTrace, StateTransition
from smart_home_sim.domain.sensors import (
    ContactSensor,
    ObservableSensorLog,
    ObservableSensorRecord,
    OracleMapping,
    OracleObservationLink,
    PirSensor,
    SensorDefinition,
    SensorModel,
    SensorProjectionIssue,
    SensorProjectionReport,
    SensorProjectionResult,
    SensorProjectionSensorSummary,
    SensorProjectionSummary,
    TemperatureSensor,
    TemperatureSource,
)
from smart_home_sim.validation.service import (
    MAX_SCENARIO_BYTES,
    DuplicateJsonKeyError,
    InvalidJsonConstantError,
    _exceeds_json_nesting_limit,
    _json_path,
    _reject_duplicate_keys,
    _reject_non_finite_constant,
)

SUPPORTED_SENSOR_MODEL_VERSION = "1.0.0"
SUPPORTED_TRACE_VERSION = "1.0.0"
SUPPORTED_BUNDLE_VERSION = "1.0.0"
ENHANCED_SENSOR_MODEL_VERSION = "1.1.0"
REALISTIC_SENSOR_MODEL_VERSION = "1.2.0"
PIR_ACTIVITY_ACTION_TYPES = frozenset(
    {
        "activate",
        "change_posture",
        "clean",
        "close",
        "consume",
        "deactivate",
        "exercise",
        "inspect",
        "laundry_step",
        "manage_medication",
        "open",
        "organize",
        "personal_care",
        "prepare_food",
        "put_item",
        "take_item",
    }
)
PIR_RETRIGGER_MEAN_SECONDS = 18.0
PIR_RETRIGGER_LOG_SIGMA = 0.6
TEMPERATURE_DAILY_AMPLITUDE_CELSIUS = 1.0
TEMPERATURE_QUANTUM_CELSIUS = 0.5


@dataclass(frozen=True)
class Candidate:
    at: datetime
    value: JsonValue
    measurement: str
    unit: str | None
    origin: str
    cause_type: str
    cause_ids: tuple[str, ...] = ()
    resident_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    group_id: str | None = None
    group_start: bool = False
    applies_cooldown: bool = True
    applies_false_negative: bool = True


@dataclass
class Counters:
    candidate_count: int = 0
    observation_count: int = 0
    dropout_count: int = 0
    false_negative_count: int = 0
    cooldown_suppressed_count: int = 0
    failure_suppressed_count: int = 0
    false_positive_count: int = 0
    noisy_observation_count: int = 0


@dataclass(frozen=True)
class TemperatureDelta:
    at: datetime
    amount: float
    transition: StateTransition


def _canonical_digest(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _trace_semantic_digest(trace: ExecutionTrace) -> str:
    payload = trace.model_dump(mode="json", by_alias=True)
    semantic = {
        key: payload[key]
        for key in (
            "sourceBundleId",
            "seed",
            "activityExecutions",
            "actionExecutions",
            "movements",
            "stateTransitions",
            "resourceEvents",
            "runtimeEvents",
            "planDeviations",
            "finalState",
        )
    }
    return _canonical_digest(semantic)


def _stream(seed: int, sensor_id: str, concern: str) -> random.Random:
    name = f"sensor:{sensor_id}:{concern}"
    material = f"{seed}:sha256-named-streams-1.0.0:{name}".encode()
    derived = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
    return random.Random(derived)


def _lognormal_milliseconds(
    trace: ExecutionTrace,
    sensor_id: str,
    concern: str,
    median_milliseconds: float,
    log_sigma: float,
) -> float:
    if log_sigma == 0:
        return median_milliseconds
    sampled = _stream(trace.seed, sensor_id, concern).lognormvariate(
        math.log(median_milliseconds), log_sigma
    )
    return max(100.0, min(sampled, median_milliseconds * 8))


def _in_failure(sensor: SensorDefinition, at: datetime) -> bool:
    return any(item.starts_at <= at < item.ends_at for item in sensor.failure_windows)


def _causal_context(
    trace: ExecutionTrace,
    cause_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    actions = {item.action_execution_id: item for item in trace.action_executions}
    activities = {item.activity_execution_id: item for item in trace.activity_executions}
    if cause_id in actions:
        action = actions[cause_id]
        activity = activities.get(action.activity_execution_id)
        return (
            (action.actor_id,),
            (action.activity_execution_id,),
            (action.action_execution_id,),
        )
    if cause_id in activities:
        activity = activities[cause_id]
        return ((activity.actor_id,), (activity.activity_execution_id,), ())
    return (), (), ()


def _pir_candidates(
    trace: ExecutionTrace,
    bundle: SimulationBundle,
    sensor: PirSensor,
    *,
    enhanced: bool,
) -> list[Candidate]:
    coverage = Polygon([(item.x, item.y) for item in sensor.coverage.vertices])
    candidates: list[Candidate] = []
    actions = {item.action_execution_id: item for item in trace.action_executions}
    for movement in trace.movements:
        detected_at: datetime | None = None
        first = movement.waypoints[0]
        if first.region_id in sensor.region_ids and coverage.covers(
            ShapelyPoint(first.position.x, first.position.y)
        ):
            detected_at = first.at
        for left, right in zip(movement.waypoints, movement.waypoints[1:], strict=False):
            if detected_at is not None:
                break
            if left.region_id not in sensor.region_ids and right.region_id not in sensor.region_ids:
                continue
            line = LineString(
                [(left.position.x, left.position.y), (right.position.x, right.position.y)]
            )
            intersection = line.intersection(coverage)
            if intersection.is_empty:
                continue
            if line.length == 0:
                detected_at = left.at
                break
            entry = nearest_points(ShapelyPoint(line.coords[0]), intersection)[1]
            fraction = max(0.0, min(1.0, line.project(entry) / line.length))
            detected_at = left.at + (right.at - left.at) * fraction
        if detected_at is None:
            continue
        action = actions.get(movement.action_execution_id)
        hold_milliseconds = _lognormal_milliseconds(
            trace,
            sensor.sensor_id,
            f"pir-hold:{movement.movement_id}",
            sensor.hold_milliseconds,
            sensor.hold_log_sigma,
        )
        common = dict(
            origin="simulated_cause",
            cause_type="movement",
            cause_ids=(movement.movement_id,),
            resident_ids=(movement.actor_id,),
            activity_ids=(action.activity_execution_id,) if action else (),
            action_ids=(movement.action_execution_id,),
            group_id=movement.movement_id,
        )
        candidates.extend(
            [
                Candidate(
                    at=detected_at,
                    value="ON",
                    measurement="motion",
                    unit=None,
                    group_start=True,
                    **common,
                ),
                Candidate(
                    at=detected_at + timedelta(milliseconds=hold_milliseconds),
                    value="OFF",
                    measurement="motion",
                    unit=None,
                    applies_cooldown=False,
                    applies_false_negative=False,
                    **common,
                ),
            ]
        )
    if not enhanced:
        return candidates

    entities = {item.entity_id: item for item in bundle.home_model.entities}
    points = {item.interaction_point_id: item for item in bundle.home_model.interaction_points}
    retrigger = _stream(trace.seed, sensor.sensor_id, "activity-pir-timing")
    for action in trace.action_executions:
        if action.action_type not in PIR_ACTIVITY_ACTION_TYPES or action.status != "completed":
            continue
        entity = next(
            (
                entities[provider_id]
                for provider_id in action.provider_ids
                if provider_id in entities
            ),
            None,
        )
        point = points.get(entity.interaction_point_id) if entity is not None else None
        if (
            point is None
            or point.region_id not in sensor.region_ids
            or not coverage.covers(ShapelyPoint(point.position.x, point.position.y))
        ):
            continue
        pulse_at = action.started_at
        pulse_index = 0
        while pulse_at <= action.ended_at:
            group_id = f"{action.action_execution_id}:pir:{pulse_index}"
            hold = timedelta(
                milliseconds=_lognormal_milliseconds(
                    trace,
                    sensor.sensor_id,
                    f"pir-hold:{group_id}",
                    sensor.hold_milliseconds,
                    sensor.hold_log_sigma,
                )
            )
            common = dict(
                origin="simulated_cause",
                cause_type="action_execution",
                cause_ids=(action.action_execution_id,),
                resident_ids=(action.actor_id,),
                activity_ids=(action.activity_execution_id,),
                action_ids=(action.action_execution_id,),
                group_id=group_id,
            )
            candidates.extend(
                [
                    Candidate(
                        at=pulse_at,
                        value="ON",
                        measurement="motion",
                        unit=None,
                        group_start=True,
                        **common,
                    ),
                    Candidate(
                        at=min(pulse_at + hold, action.ended_at),
                        value="OFF",
                        measurement="motion",
                        unit=None,
                        applies_cooldown=False,
                        applies_false_negative=False,
                        **common,
                    ),
                ]
            )
            pulse_index += 1
            interval = retrigger.lognormvariate(
                math.log(PIR_RETRIGGER_MEAN_SECONDS) - PIR_RETRIGGER_LOG_SIGMA**2 / 2,
                PIR_RETRIGGER_LOG_SIGMA,
            )
            minimum_interval = sensor.hold_milliseconds / 1000 + 0.5
            pulse_at += timedelta(seconds=max(minimum_interval, min(60.0, interval)))
    return candidates


def _contact_candidates(trace: ExecutionTrace, sensor: ContactSensor) -> list[Candidate]:
    candidates: list[Candidate] = []
    if sensor.fact is None:
        for action in trace.action_executions:
            if (
                action.action_type not in sensor.action_types
                or sensor.entity_id not in action.provider_ids
            ):
                continue
            at = action.started_at if sensor.action_trigger == "started" else action.ended_at
            pulse_milliseconds = _lognormal_milliseconds(
                trace,
                sensor.sensor_id,
                f"contact-pulse:{action.action_execution_id}",
                sensor.pulse_milliseconds,
                sensor.pulse_log_sigma,
            )
            common = dict(
                origin="simulated_cause",
                cause_type="action_execution",
                cause_ids=(action.action_execution_id,),
                resident_ids=(action.actor_id,),
                activity_ids=(action.activity_execution_id,),
                action_ids=(action.action_execution_id,),
                group_id=action.action_execution_id,
            )
            candidates.extend(
                [
                    Candidate(
                        at=at,
                        value="OPEN",
                        measurement="contact",
                        unit=None,
                        group_start=True,
                        **common,
                    ),
                Candidate(
                    at=at + timedelta(milliseconds=pulse_milliseconds),
                        value="CLOSED",
                        measurement="contact",
                        unit=None,
                        applies_cooldown=False,
                        applies_false_negative=False,
                        **common,
                    ),
                ]
            )
        return candidates
    for transition in trace.state_transitions:
        if (
            transition.subject_type != "entity"
            or transition.subject_id != sensor.entity_id
            or transition.fact != sensor.fact
        ):
            continue
        if transition.value == sensor.open_value:
            value: JsonValue = "OPEN"
        elif transition.value == sensor.closed_value:
            value = "CLOSED"
        else:
            continue
        residents, activities, actions = _causal_context(trace, transition.causality.cause_id)
        candidates.append(
            Candidate(
                at=transition.at,
                value=value,
                measurement="contact",
                unit=None,
                origin="simulated_cause",
                cause_type="state_transition",
                cause_ids=(transition.transition_id,),
                resident_ids=residents,
                activity_ids=activities,
                action_ids=actions,
            )
        )
    return candidates


def _matching_source(
    transition: StateTransition, sensor: TemperatureSensor
) -> TemperatureSource | None:
    for source in sensor.sources:
        if transition.subject_id == source.entity_id and transition.fact == source.fact:
            return source
    return None


def _temperature_deltas(trace: ExecutionTrace, sensor: TemperatureSensor) -> list[TemperatureDelta]:
    deltas: list[TemperatureDelta] = []
    for transition in trace.state_transitions:
        if transition.subject_type != "entity":
            continue
        source = _matching_source(transition, sensor)
        if source is None:
            continue
        was_active = transition.previous_value == source.active_value
        is_active = transition.value == source.active_value
        if was_active == is_active:
            continue
        activating = is_active
        duration = source.rise_duration_seconds if activating else source.decay_duration_seconds
        sample_count = max(1, math.ceil(duration / source.sample_interval_seconds))
        total_delta = source.delta_celsius if activating else -source.delta_celsius
        for sample_index in range(1, sample_count + 1):
            elapsed = duration * sample_index / sample_count
            deltas.append(
                TemperatureDelta(
                    at=transition.at + timedelta(seconds=source.response_delay_seconds + elapsed),
                    amount=total_delta / sample_count,
                    transition=transition,
                )
            )

    return sorted(deltas, key=lambda item: (item.at, item.transition.transition_id))


CITY_CLIMATE_PARAMETERS: dict[str, tuple[float, float, float, int]] = {
    # annual mean, seasonal amplitude, daily amplitude, warmest day of year
    "barcelona": (18.2, 7.2, 3.8, 205),
    "rome": (16.8, 7.8, 4.2, 205),
    "roma": (16.8, 7.8, 4.2, 205),
    "milan": (13.2, 9.8, 4.5, 205),
    "milano": (13.2, 9.8, 4.5, 205),
    "london": (11.3, 6.4, 3.0, 205),
    "paris": (12.8, 7.2, 3.5, 205),
    "madrid": (15.0, 10.2, 5.8, 205),
}


def _scenario_city(bundle: SimulationBundle) -> str:
    for resident in bundle.scenario.residents:
        city = resident.profile.get("city")
        if isinstance(city, str) and city.strip():
            return city.strip().casefold()
    return "generic"


def _climate_parameters(city: str) -> tuple[float, float, float, int]:
    return next(
        (values for name, values in CITY_CLIMATE_PARAMETERS.items() if name in city),
        (15.0, 8.0, 4.0, 205),
    )


def _daily_climate_mean(at: datetime, city: str) -> float:
    annual_mean, seasonal_amplitude, _, warmest_day = _climate_parameters(city)
    day = at.timetuple().tm_yday
    return annual_mean + seasonal_amplitude * math.cos(
        2 * math.pi * (day - warmest_day) / 365.25
    )


def _weather_anomaly(seed: int, city: str, at: datetime) -> float:
    # A short deterministic moving average produces weather spells instead of white noise.
    anomaly = 0.0
    total_weight = 0.0
    for lag, weight in ((0, 1.0), (1, 0.65), (2, 0.35)):
        day = (at - timedelta(days=lag)).date().isoformat()
        anomaly += weight * _stream(seed, city, f"weather:{day}").gauss(0, 1.15)
        total_weight += weight
    return anomaly / total_weight


def _outdoor_temperature(trace: ExecutionTrace, city: str, at: datetime) -> float:
    mean = _daily_climate_mean(at, city) + _weather_anomaly(trace.seed, city, at)
    _, _, daily_amplitude, _ = _climate_parameters(city)
    local_hour = at.hour + at.minute / 60 + at.second / 3600
    return mean + daily_amplitude * math.sin(2 * math.pi * (local_hour - 9) / 24)


def _temperature_candidates(
    trace: ExecutionTrace,
    bundle: SimulationBundle,
    sensor: TemperatureSensor,
    *,
    enhanced: bool,
) -> list[Candidate]:
    deltas = _temperature_deltas(trace, sensor)
    current = sensor.baseline_celsius
    if enhanced:
        interval = min(source.sample_interval_seconds for source in sensor.sources)
        candidates: list[Candidate] = []
        delta_index = 0
        sample_at = trace.started_at + timedelta(seconds=sensor.sample_phase_seconds)
        city = _scenario_city(bundle)
        initial_ambient = bundle.scenario.initial_state.environment_facts.get(
            "ambient_temperature"
        )
        if (
            sensor.climate_profile == "city_seasonal"
            and isinstance(initial_ambient, (int, float))
            and not isinstance(initial_ambient, bool)
        ):
            current = float(initial_ambient) + sensor.room_offset_celsius
        source_adjustment = 0.0
        while sample_at <= trace.ended_at:
            sample_transition: StateTransition | None = None
            while delta_index < len(deltas) and deltas[delta_index].at <= sample_at:
                delta = deltas[delta_index]
                if sensor.climate_profile == "city_seasonal":
                    source_adjustment += delta.amount
                else:
                    current += delta.amount
                sample_transition = delta.transition
                delta_index += 1
            if sensor.climate_profile == "city_seasonal":
                outdoor = _outdoor_temperature(trace, city, sample_at)
                climate_mean = _daily_climate_mean(sample_at, city)
                target = (
                    sensor.baseline_celsius
                    + sensor.room_offset_celsius
                    + 0.32 * (outdoor - climate_mean)
                    + source_adjustment
                )
                if sensor.thermal_time_constant_hours > 0:
                    alpha = 1 - math.exp(
                        -interval / (sensor.thermal_time_constant_hours * 3600)
                    )
                    current += alpha * (target - current)
                else:
                    current = target
                value = current
            else:
                local_hour = sample_at.hour + sample_at.minute / 60 + sample_at.second / 3600
                daily_component = TEMPERATURE_DAILY_AMPLITUDE_CELSIUS * math.sin(
                    2 * math.pi * (local_hour - 9) / 24
                )
                value = current + daily_component
            value = (
                round(value / sensor.quantization_celsius) * sensor.quantization_celsius
            )
            if sample_transition is None:
                common = dict(
                    origin="environment_model",
                    cause_type="trace",
                    cause_ids=(trace.trace_id,),
                )
            else:
                residents, activities, actions = _causal_context(
                    trace, sample_transition.causality.cause_id
                )
                common = dict(
                    origin="simulated_cause",
                    cause_type="state_transition",
                    cause_ids=(sample_transition.transition_id,),
                    resident_ids=residents,
                    activity_ids=activities,
                    action_ids=actions,
                )
            candidates.append(
                Candidate(
                    at=sample_at,
                    value=round(value, 6),
                    measurement="temperature",
                    unit="celsius",
                    **common,
                )
            )
            sample_at += timedelta(seconds=interval)
        return candidates

    candidates = [
        Candidate(
            at=trace.started_at,
            value=current,
            measurement="temperature",
            unit="celsius",
            origin="initial_state",
            cause_type="trace",
            cause_ids=(trace.trace_id,),
        )
    ]
    for delta in deltas:
        current += delta.amount
        transition = delta.transition
        residents, activities, actions = _causal_context(trace, transition.causality.cause_id)
        candidates.append(
            Candidate(
                at=delta.at,
                value=round(current, 6),
                measurement="temperature",
                unit="celsius",
                origin="simulated_cause",
                cause_type="state_transition",
                cause_ids=(transition.transition_id,),
                resident_ids=residents,
                activity_ids=activities,
                action_ids=actions,
            )
        )
    return candidates


def _false_positive_candidates(
    trace: ExecutionTrace,
    sensor: SensorDefinition,
    seed: int,
    *,
    realistic: bool,
) -> list[Candidate]:
    probability = sensor.error_model.false_positive_probability_per_day
    if probability == 0:
        return []
    selection = _stream(seed, sensor.sensor_id, "false-positive-selection")
    timing = _stream(seed, sensor.sensor_id, "false-positive-timing")
    value_stream = _stream(seed, sensor.sensor_id, "false-positive-value")
    duration_seconds = max(0.0, (trace.ended_at - trace.started_at).total_seconds())
    days = max(1, math.ceil(duration_seconds / 86_400))
    candidates: list[Candidate] = []
    for day_index in range(days):
        if selection.random() >= probability:
            continue
        start = trace.started_at + timedelta(days=day_index)
        remaining = max(0.0, (trace.ended_at - start).total_seconds())
        if remaining == 0:
            continue
        at = start + timedelta(seconds=timing.random() * min(86_400, remaining))
        if isinstance(sensor, PirSensor):
            group_id = f"false-positive:{sensor.sensor_id}:{day_index}"
            candidates.extend(
                [
                    Candidate(
                        at=at,
                        value="ON",
                        measurement="motion",
                        unit=None,
                        origin="false_positive",
                        cause_type="noise",
                        group_id=group_id,
                        group_start=True,
                    ),
                    Candidate(
                        at=at + timedelta(milliseconds=sensor.hold_milliseconds),
                        value="OFF",
                        measurement="motion",
                        unit=None,
                        origin="false_positive",
                        cause_type="noise",
                        group_id=group_id,
                        applies_cooldown=False,
                        applies_false_negative=False,
                    ),
                ]
            )
            continue
        elif isinstance(sensor, ContactSensor):
            if not realistic:
                candidates.append(
                    Candidate(
                        at=at,
                        value=value_stream.choice(("OPEN", "CLOSED")),
                        measurement="contact",
                        unit=None,
                        origin="false_positive",
                        cause_type="noise",
                    )
                )
                continue
            group_id = f"false-positive:{sensor.sensor_id}:{day_index}"
            pulse = _lognormal_milliseconds(
                trace,
                sensor.sensor_id,
                f"false-positive-contact:{day_index}",
                sensor.pulse_milliseconds,
                sensor.pulse_log_sigma,
            )
            candidates.extend(
                [
                    Candidate(
                        at=at,
                        value="OPEN",
                        measurement="contact",
                        unit=None,
                        origin="false_positive",
                        cause_type="noise",
                        group_id=group_id,
                        group_start=True,
                    ),
                    Candidate(
                        at=at + timedelta(milliseconds=pulse),
                        value="CLOSED",
                        measurement="contact",
                        unit=None,
                        origin="false_positive",
                        cause_type="noise",
                        group_id=group_id,
                        applies_cooldown=False,
                        applies_false_negative=False,
                    ),
                ]
            )
            continue
        else:
            measurement = "temperature"
            deviation = max(0.5, sensor.error_model.measurement_noise_standard_deviation * 3)
            value = round(sensor.baseline_celsius + value_stream.choice((-deviation, deviation)), 6)
            unit = "celsius"
        candidates.append(
            Candidate(
                at=at,
                value=value,
                measurement=measurement,
                unit=unit,
                origin="false_positive",
                cause_type="noise",
            )
        )
    return candidates


def _reconcile_binary_candidates(
    candidates: list[Candidate], *, on_value: str, off_value: str
) -> list[Candidate]:
    """Collapse overlapping pulses into one coherent state-machine transition stream."""
    if not candidates or not all(item.group_id is not None for item in candidates):
        result: list[Candidate] = []
        state: JsonValue = off_value
        for candidate in candidates:
            if candidate.value not in {on_value, off_value} or candidate.value != state:
                result.append(candidate)
                state = candidate.value
        return result

    by_time: dict[datetime, list[Candidate]] = {}
    for candidate in candidates:
        by_time.setdefault(candidate.at, []).append(candidate)
    active_groups: set[str] = set()
    current_output_group: str | None = None
    sequence = 0
    result = []
    for at in sorted(by_time):
        batch = by_time[at]
        was_on = bool(active_groups)
        for candidate in batch:
            if candidate.value == off_value and candidate.group_id is not None:
                active_groups.discard(candidate.group_id)
        for candidate in batch:
            if candidate.value == on_value and candidate.group_id is not None:
                active_groups.add(candidate.group_id)
        is_on = bool(active_groups)
        if was_on == is_on:
            continue
        desired = on_value if is_on else off_value
        representative = next(item for item in batch if item.value == desired)
        if is_on:
            current_output_group = f"reconciled:{sequence}"
            sequence += 1
            result.append(
                replace(
                    representative,
                    group_id=current_output_group,
                    group_start=True,
                )
            )
        else:
            result.append(
                replace(
                    representative,
                    group_id=current_output_group,
                    group_start=False,
                    applies_cooldown=False,
                    applies_false_negative=False,
                )
            )
            current_output_group = None
    return result


def _sensor_candidates(
    trace: ExecutionTrace,
    bundle: SimulationBundle,
    sensor: SensorDefinition,
    seed: int,
    *,
    enhanced: bool,
    realistic: bool,
) -> list[Candidate]:
    if isinstance(sensor, PirSensor):
        nominal = _pir_candidates(trace, bundle, sensor, enhanced=enhanced)
    elif isinstance(sensor, ContactSensor):
        nominal = _contact_candidates(trace, sensor)
    else:
        nominal = _temperature_candidates(trace, bundle, sensor, enhanced=enhanced)
    candidates = sorted(
        [
            *nominal,
            *_false_positive_candidates(trace, sensor, seed, realistic=realistic),
        ],
        key=lambda item: (item.at, item.origin, item.cause_ids),
    )
    if realistic and isinstance(sensor, PirSensor):
        return _reconcile_binary_candidates(candidates, on_value="ON", off_value="OFF")
    if realistic and isinstance(sensor, ContactSensor):
        return _reconcile_binary_candidates(candidates, on_value="OPEN", off_value="CLOSED")
    return candidates


def _observation_identifier(sensor_id: str, index: int, candidate: Candidate) -> str:
    material = f"{sensor_id}:{index}:{candidate.at.isoformat()}:{candidate.origin}"
    return f"observation_{hashlib.sha256(material.encode()).hexdigest()[:16]}"


def _project_sensor(
    trace: ExecutionTrace,
    bundle: SimulationBundle,
    sensor: SensorDefinition,
    seed: int,
    *,
    enhanced: bool,
    realistic: bool,
) -> tuple[list[ObservableSensorRecord], list[OracleObservationLink], Counters]:
    candidates = _sensor_candidates(
        trace,
        bundle,
        sensor,
        seed,
        enhanced=enhanced,
        realistic=realistic,
    )
    counters = Counters(candidate_count=len(candidates))
    dropout = _stream(seed, sensor.sensor_id, "dropout")
    false_negative = _stream(seed, sensor.sensor_id, "false-negative")
    jitter = _stream(seed, sensor.sensor_id, "clock-jitter")
    measurement_noise = _stream(seed, sensor.sensor_id, "measurement-noise")
    records: list[ObservableSensorRecord] = []
    links: list[OracleObservationLink] = []
    last_cooldown_event_at: datetime | None = None
    suppressed_groups: dict[str, str] = {}
    cooldown = timedelta(milliseconds=sensor.timing.cooldown_milliseconds)
    for candidate in candidates:
        suppressed_reason = (
            suppressed_groups.get(candidate.group_id) if candidate.group_id is not None else None
        )
        if suppressed_reason is not None:
            setattr(counters, suppressed_reason, getattr(counters, suppressed_reason) + 1)
            continue
        if _in_failure(sensor, candidate.at):
            counters.failure_suppressed_count += 1
            if candidate.group_start and candidate.group_id is not None:
                suppressed_groups[candidate.group_id] = "failure_suppressed_count"
            continue
        if (
            candidate.applies_cooldown
            and last_cooldown_event_at is not None
            and candidate.at - last_cooldown_event_at < cooldown
        ):
            counters.cooldown_suppressed_count += 1
            if candidate.group_start and candidate.group_id is not None:
                suppressed_groups[candidate.group_id] = "cooldown_suppressed_count"
            continue
        if (
            candidate.applies_false_negative
            and candidate.origin != "false_positive"
            and (false_negative.random() < sensor.error_model.false_negative_probability)
        ):
            counters.false_negative_count += 1
            if candidate.group_start and candidate.group_id is not None:
                suppressed_groups[candidate.group_id] = "false_negative_count"
            continue
        if dropout.random() < sensor.error_model.dropout_probability:
            counters.dropout_count += 1
            if candidate.group_start and candidate.group_id is not None:
                suppressed_groups[candidate.group_id] = "dropout_count"
            continue
        latency = sensor.timing.latency_milliseconds
        jitter_bound = sensor.timing.clock_jitter_milliseconds
        observed_at = candidate.at + timedelta(
            milliseconds=max(0.0, latency + jitter.uniform(-jitter_bound, jitter_bound))
        )
        value = candidate.value
        noisy = candidate.origin == "false_positive"
        standard_deviation = sensor.error_model.measurement_noise_standard_deviation
        if (
            isinstance(sensor, TemperatureSensor)
            and isinstance(value, (int, float))
            and standard_deviation > 0
        ):
            noisy_value = float(value) + measurement_noise.gauss(0, standard_deviation)
            value = round(
                round(noisy_value / sensor.quantization_celsius)
                * sensor.quantization_celsius,
                6,
            )
            noisy = True
        observation_id = _observation_identifier(sensor.sensor_id, len(records), candidate)
        records.append(
            ObservableSensorRecord(
                observation_id=observation_id,
                sensor_id=sensor.sensor_id,
                sensor_type=sensor.sensor_type,
                observed_at=observed_at,
                measurement=candidate.measurement,  # type: ignore[arg-type]
                value=value,
                unit=candidate.unit,  # type: ignore[arg-type]
                quality="noisy" if noisy else "nominal",
            )
        )
        links.append(
            OracleObservationLink(
                observation_id=observation_id,
                origin=candidate.origin,  # type: ignore[arg-type]
                cause_type=candidate.cause_type,  # type: ignore[arg-type]
                cause_ids=list(candidate.cause_ids),
                resident_ids=list(candidate.resident_ids),
                activity_execution_ids=list(candidate.activity_ids),
                action_execution_ids=list(candidate.action_ids),
            )
        )
        counters.observation_count += 1
        counters.false_positive_count += candidate.origin == "false_positive"
        counters.noisy_observation_count += noisy
        if candidate.applies_cooldown:
            last_cooldown_event_at = candidate.at
    return records, links, counters


def _issue(code: str, stage: str, path: str, message: str) -> SensorProjectionIssue:
    return SensorProjectionIssue(code=code, stage=stage, path=path, message=message)  # type: ignore[arg-type]


def _summary(
    sensors: Iterable[SensorProjectionSensorSummary],
    issues: list[SensorProjectionIssue],
) -> SensorProjectionSummary:
    items = list(sensors)
    return SensorProjectionSummary(
        sensor_count=len(items),
        candidate_count=sum(item.candidate_count for item in items),
        observation_count=sum(item.observation_count for item in items),
        dropout_count=sum(item.dropout_count for item in items),
        false_negative_count=sum(item.false_negative_count for item in items),
        cooldown_suppressed_count=sum(item.cooldown_suppressed_count for item in items),
        failure_suppressed_count=sum(item.failure_suppressed_count for item in items),
        false_positive_count=sum(item.false_positive_count for item in items),
        noisy_observation_count=sum(item.noisy_observation_count for item in items),
        error_count=sum(item.severity == "error" for item in issues),
        warning_count=sum(item.severity == "warning" for item in issues),
    )


def _failed_result(
    issues: list[SensorProjectionIssue],
    *,
    trace: ExecutionTrace | None = None,
    model: SensorModel | None = None,
    bundle: SimulationBundle | None = None,
) -> SensorProjectionResult:
    return SensorProjectionResult(
        report=SensorProjectionReport(
            success=False,
            source_bundle_id=trace.source_bundle_id if trace else None,
            source_bundle_sha256=trace.source_bundle_sha256 if trace else None,
            source_home_id=bundle.home_model.home_id if bundle else None,
            source_home_version=bundle.home_model.home_version if bundle else None,
            source_home_sha256=canonical_sha256(bundle.home_model) if bundle else None,
            source_trace_id=trace.trace_id if trace else None,
            source_trace_sha256=canonical_sha256(trace) if trace else None,
            source_trace_semantic_digest=trace.semantic_digest if trace else None,
            sensor_model_id=model.sensor_model_id if model else None,
            sensor_model_version=model.sensor_model_version if model else None,
            sensor_model_sha256=canonical_sha256(model) if model else None,
            projection_policy_version=(
                "event-driven-sensors-1.2.0"
                if model and model.sensor_model_version == REALISTIC_SENSOR_MODEL_VERSION
                else "event-driven-sensors-1.1.0"
                if model and model.sensor_model_version == ENHANCED_SENSOR_MODEL_VERSION
                else "event-driven-sensors-1.0.0"
            ),
            projected_at=trace.ended_at if trace else datetime(1970, 1, 1, tzinfo=UTC),
            issues=issues,
            summary=_summary([], issues),
        )
    )


def project_sensors(
    trace: ExecutionTrace, bundle: SimulationBundle, model: SensorModel
) -> SensorProjectionResult:
    issues: list[SensorProjectionIssue] = []
    if (
        bundle.bundle_id != trace.source_bundle_id
        or canonical_sha256(bundle) != trace.source_bundle_sha256
        or bundle.seed != trace.seed
    ):
        issues.append(
            _issue(
                "BUNDLE_TRACE_MISMATCH",
                "compatibility",
                "$.sourceBundleSha256",
                "Simulation bundle identity, digest or seed does not match the execution trace.",
            )
        )
    if model.source_bundle_id != trace.source_bundle_id:
        issues.append(
            _issue(
                "MODEL_TRACE_MISMATCH",
                "compatibility",
                "$.sourceBundleId",
                "Sensor model sourceBundleId does not match the execution trace.",
            )
        )
    if model.source_bundle_sha256 != trace.source_bundle_sha256:
        issues.append(
            _issue(
                "MODEL_TRACE_MISMATCH",
                "compatibility",
                "$.sourceBundleSha256",
                "Sensor model sourceBundleSha256 does not match the execution trace.",
            )
        )
    if model.seed != trace.seed:
        issues.append(
            _issue(
                "MODEL_TRACE_MISMATCH",
                "compatibility",
                "$.seed",
                "Sensor model seed must equal the authoritative execution trace seed.",
            )
        )
    if trace.semantic_digest != _trace_semantic_digest(trace):
        issues.append(
            _issue(
                "TRACE_DIGEST_MISMATCH",
                "compatibility",
                "$.semanticDigest",
                "Execution trace semanticDigest does not match its authoritative content.",
            )
        )
    home = bundle.home_model
    regions = {item.region_id: item for item in home.regions}
    entities = {item.entity_id: item for item in home.entities}
    region_shapes = {
        region_id: Polygon([(point.x, point.y) for point in region.boundary.vertices])
        for region_id, region in regions.items()
    }
    if set(model.region_ids) != set(regions):
        issues.append(
            _issue(
                "HOME_SENSOR_MISMATCH",
                "compatibility",
                "$.regionIds",
                "Sensor model regionIds must exactly match the source home model.",
            )
        )
    if set(model.entity_ids) != set(entities):
        issues.append(
            _issue(
                "HOME_SENSOR_MISMATCH",
                "compatibility",
                "$.entityIds",
                "Sensor model entityIds must exactly match the source home model.",
            )
        )
    for index, sensor in enumerate(model.sensors):
        position = ShapelyPoint(sensor.position.x, sensor.position.y)
        if isinstance(sensor, PirSensor):
            coverage = Polygon([(item.x, item.y) for item in sensor.coverage.vertices])
            monitored_shapes = [
                region_shapes[region_id]
                for region_id in sensor.region_ids
                if region_id in region_shapes
            ]
            monitored_area = unary_union(monitored_shapes) if monitored_shapes else Polygon()
            if (
                not coverage.is_valid
                or coverage.is_empty
                or coverage.area <= 0
                or not coverage.covers(position)
                or not monitored_area.covers(position)
                or coverage.difference(monitored_area).area > 1e-9
            ):
                issues.append(
                    _issue(
                        "HOME_SENSOR_MISMATCH",
                        "compatibility",
                        f"$.sensors[{index}].coverage",
                        f"PIR sensor '{sensor.sensor_id}' position or coverage is "
                        "outside its source-home regions.",
                    )
                )
        elif isinstance(sensor, ContactSensor):
            entity = entities.get(sensor.entity_id)
            region_shape = region_shapes.get(entity.region_id) if entity else None
            if region_shape is None or not region_shape.covers(position):
                issues.append(
                    _issue(
                        "HOME_SENSOR_MISMATCH",
                        "compatibility",
                        f"$.sensors[{index}].position",
                        f"Contact sensor '{sensor.sensor_id}' is outside its entity's "
                        "source-home region.",
                    )
                )
        else:
            region_shape = region_shapes.get(sensor.region_id)
            if region_shape is None or not region_shape.covers(position):
                issues.append(
                    _issue(
                        "HOME_SENSOR_MISMATCH",
                        "compatibility",
                        f"$.sensors[{index}].position",
                        f"Temperature sensor '{sensor.sensor_id}' is outside its "
                        "source-home region.",
                    )
                )
    if issues:
        return _failed_result(issues, trace=trace, model=model, bundle=bundle)

    enhanced = model.sensor_model_version in {
        ENHANCED_SENSOR_MODEL_VERSION,
        REALISTIC_SENSOR_MODEL_VERSION,
    }
    realistic = model.sensor_model_version == REALISTIC_SENSOR_MODEL_VERSION
    projection_policy_version = (
        (
            "event-driven-sensors-1.2.0"
            if model.sensor_model_version == REALISTIC_SENSOR_MODEL_VERSION
            else "event-driven-sensors-1.1.0"
        )
        if enhanced
        else "event-driven-sensors-1.0.0"
    )
    records: list[ObservableSensorRecord] = []
    links: list[OracleObservationLink] = []
    sensor_summaries: list[SensorProjectionSensorSummary] = []
    try:
        for sensor in model.sensors:
            sensor_records, sensor_links, counters = _project_sensor(
                trace,
                bundle,
                sensor,
                trace.seed,
                enhanced=enhanced,
                realistic=realistic,
            )
            records.extend(sensor_records)
            links.extend(sensor_links)
            sensor_summaries.append(
                SensorProjectionSensorSummary(sensor_id=sensor.sensor_id, **vars(counters))
            )
    except (ArithmeticError, TypeError, ValueError) as error:
        return _failed_result(
            [
                _issue(
                    "PROJECTION_FAILED",
                    "projection",
                    "$",
                    f"Sensor projection failed: {error}",
                )
            ],
            trace=trace,
            model=model,
            bundle=bundle,
        )
    records.sort(key=lambda item: (item.observed_at, item.sensor_id, item.observation_id))
    link_by_id = {item.observation_id: item for item in links}
    links = [link_by_id[item.observation_id] for item in records]
    semantic = {
        "sensorModelId": model.sensor_model_id,
        "sensorModelVersion": model.sensor_model_version,
        "records": [item.model_dump(mode="json", by_alias=True) for item in records],
    }
    log_id = f"sensor_log_{_canonical_digest(semantic)[:16]}"
    ended_at = max([trace.ended_at, *(item.observed_at for item in records)])
    observable_log = ObservableSensorLog(
        log_id=log_id,
        sensor_model_id=model.sensor_model_id,
        sensor_model_version=model.sensor_model_version,
        started_at=trace.started_at,
        ended_at=ended_at,
        records=records,
        semantic_digest=_canonical_digest(semantic),
    )
    oracle_digest = _canonical_digest([item.model_dump(mode="json") for item in links])
    oracle_mapping = OracleMapping(
        mapping_id=f"oracle_{oracle_digest[:16]}",
        observable_log_id=log_id,
        source_trace_id=trace.trace_id,
        source_trace_semantic_digest=trace.semantic_digest,
        links=links,
    )
    report = SensorProjectionReport(
        success=True,
        source_bundle_id=trace.source_bundle_id,
        source_bundle_sha256=trace.source_bundle_sha256,
        source_home_id=home.home_id,
        source_home_version=home.home_version,
        source_home_sha256=canonical_sha256(home),
        source_trace_id=trace.trace_id,
        source_trace_sha256=canonical_sha256(trace),
        source_trace_semantic_digest=trace.semantic_digest,
        sensor_model_id=model.sensor_model_id,
        sensor_model_version=model.sensor_model_version,
        sensor_model_sha256=canonical_sha256(model),
        projection_policy_version=projection_policy_version,
        observable_log_sha256=canonical_sha256(observable_log),
        oracle_mapping_sha256=canonical_sha256(oracle_mapping),
        projected_at=trace.ended_at,
        sensors=sensor_summaries,
        summary=_summary(sensor_summaries, []),
    )
    return SensorProjectionResult(
        report=report,
        observable_log=observable_log,
        oracle_mapping=oracle_mapping,
    )


def _load_contract(
    path: Path, model_type: type[Any], label: str
) -> tuple[Any | None, list[SensorProjectionIssue]]:
    try:
        encoded = path.read_bytes()
    except FileNotFoundError:
        return None, [_issue("FILE_NOT_FOUND", "input", "$", f"{label} not found: {path}")]
    except OSError as error:
        return None, [_issue("FILE_READ_ERROR", "input", "$", f"Cannot read {label}: {error}")]
    if len(encoded) > MAX_SCENARIO_BYTES * 20:
        return None, [_issue("FILE_TOO_LARGE", "input", "$", f"{label} exceeds the input limit.")]
    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError:
        return None, [_issue("FILE_ENCODING_ERROR", "input", "$", f"{label} must be UTF-8.")]
    if _exceeds_json_nesting_limit(raw):
        return None, [
            _issue("JSON_NESTING_TOO_DEEP", "input", "$", f"{label} is nested too deeply.")
        ]
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except (DuplicateJsonKeyError, InvalidJsonConstantError, json.JSONDecodeError) as error:
        return None, [_issue("JSON_SYNTAX", "input", "$", f"Invalid {label} JSON: {error}")]
    if not isinstance(payload, dict):
        return None, [_issue("STRUCTURE_INVALID", "input", "$", f"{label} must be an object.")]
    expected = (
        SUPPORTED_TRACE_VERSION
        if model_type is ExecutionTrace
        else SUPPORTED_BUNDLE_VERSION
        if model_type is SimulationBundle
        else SUPPORTED_SENSOR_MODEL_VERSION
    )
    if payload.get("schemaVersion") != expected:
        return None, [
            _issue(
                "UNSUPPORTED_SCHEMA_VERSION",
                "input",
                "$.schemaVersion",
                f"Expected {label} schemaVersion '{expected}'.",
            )
        ]
    try:
        return model_type.model_validate_json(raw), []
    except ValidationError as error:
        return None, [
            _issue("STRUCTURE_INVALID", "input", _json_path(item["loc"]), item["msg"])
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]


def project_sensor_files(
    trace_path: Path, bundle_path: Path, model_path: Path
) -> SensorProjectionResult:
    trace, trace_issues = _load_contract(trace_path, ExecutionTrace, "Execution trace")
    if trace is None:
        return _failed_result(trace_issues)
    bundle, bundle_issues = _load_contract(bundle_path, SimulationBundle, "Simulation bundle")
    if bundle is None:
        return _failed_result(bundle_issues, trace=trace)
    model, model_issues = _load_contract(model_path, SensorModel, "Sensor model")
    if model is None:
        return _failed_result(model_issues, trace=trace, bundle=bundle)
    return project_sensors(trace, bundle, model)
