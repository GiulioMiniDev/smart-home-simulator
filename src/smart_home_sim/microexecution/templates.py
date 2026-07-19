from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActivityExecutionProfile:
    movement_interval_seconds: float | None
    interaction_labels: tuple[str, ...] = ()


class ActivityTemplateRegistry:
    """Initial hand-authored profiles; these parameters require empirical calibration."""

    def __init__(self) -> None:
        self._profiles = {
            "wake_up": ActivityExecutionProfile(20, ("leave_bed",)),
            "morning_toilet_and_shower": ActivityExecutionProfile(15, ("use_toilet", "use_shower")),
            "prepare_breakfast": ActivityExecutionProfile(
                12, ("open_fridge", "use_kettle", "prepare_food")
            ),
            "eat_breakfast": ActivityExecutionProfile(150, ("sit_at_table",)),
            "take_morning_medication": ActivityExecutionProfile(30, ("take_tablet",)),
            "wash_dishes": ActivityExecutionProfile(10, ("use_sink",)),
            "dress": ActivityExecutionProfile(18, ("open_wardrobe", "get_dressed")),
            "watch_television": ActivityExecutionProfile(300, ("sit_down",)),
            "read": ActivityExecutionProfile(240, ("sit_down",)),
            "sleep": ActivityExecutionProfile(1800),
        }
        self._default = ActivityExecutionProfile(45)

    def get(self, intent: str) -> ActivityExecutionProfile:
        return self._profiles.get(intent, self._default)
