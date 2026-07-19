from __future__ import annotations

import random
from collections.abc import Callable, Generator
from datetime import datetime, timedelta

import simpy

from smart_home_sim.domain.models import PirSensorConfig, RawSensorEvent


class PirSensor:
    def __init__(
        self,
        env: simpy.Environment,
        config: PirSensorConfig,
        origin: datetime,
        rng: random.Random,
        emit: Callable[[RawSensorEvent], None],
    ) -> None:
        self._env = env
        self.config = config
        self._origin = origin
        self._rng = rng
        self._emit = emit
        self._active = False
        self._last_motion_minute = float("-inf")
        self._blocked_until_minute = float("-inf")
        self._reset_process_running = False

    def detect_motion(self) -> None:
        if self._rng.random() < self.config.false_negative_probability:
            return

        now = float(self._env.now)
        if not self._active and now < self._blocked_until_minute:
            return

        self._last_motion_minute = now
        if not self._active:
            self._active = True
            self._emit_event("ON")

        if not self._reset_process_running:
            self._reset_process_running = True
            self._env.process(self._reset_after_quiet_period())

    def _reset_after_quiet_period(self) -> Generator[simpy.Event, None, None]:
        reset_minutes = self.config.reset_seconds / 60
        while True:
            target = self._last_motion_minute + reset_minutes
            yield self._env.timeout(max(0, target - float(self._env.now)))
            if float(self._env.now) >= self._last_motion_minute + reset_minutes:
                self._active = False
                self._blocked_until_minute = (
                    float(self._env.now) + self.config.cooldown_seconds / 60
                )
                self._emit_event("OFF")
                self._reset_process_running = False
                return

    def _emit_event(self, value: str) -> None:
        self._emit(
            RawSensorEvent(
                timestamp=self._origin + timedelta(minutes=float(self._env.now)),
                sensor_id=self.config.sensor_id,
                value=value,
            )
        )
