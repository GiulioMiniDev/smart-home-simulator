"""Optional local generation front-end: invent a persona, its recurring activities, and simulatable
days.

This subsystem sits in front of Phase 1. It may call the existing validation, compilation,
environment, and simulation services as gates, but those packages must not import it. Accepted
artifacts remain replayable and simulatable without LM Studio.
"""

from __future__ import annotations

from smart_home_sim.hybrid_planning.activity_trace import (
    ActivityTraceEntry,
    PlannedActivityTrace,
    build_planned_trace,
)
from smart_home_sim.hybrid_planning.cadence import (
    ActivityOccurrence,
    CadenceCalendar,
    CadenceCalendarResult,
    CadenceError,
    CalendarDay,
    build_cadence_calendar,
)
from smart_home_sim.hybrid_planning.day_generation import (
    build_day_plan,
    build_day_scenario,
    build_day_scenarios,
    label_to_intent,
)
from smart_home_sim.hybrid_planning.horizon import (
    HorizonError,
    HorizonResult,
    build_horizon,
)
from smart_home_sim.hybrid_planning.llm_days import (
    LlmDaysResult,
    generate_llm_day_plans,
)
from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioConfig,
    LMStudioContentError,
    LMStudioError,
    LMStudioResponseError,
    LMStudioUnavailableError,
    extract_json_value,
)
from smart_home_sim.hybrid_planning.outline import (
    OUTLINE_SCHEMA_VERSION,
    ActivityOverride,
    Displacement,
    FixedCommitment,
    HabitGroundTruth,
    HabitSegment,
    HorizonAuthoringBundle,
    HorizonOutline,
    OutlineError,
    OutlineEvent,
    OutlinePhase,
    OutlineWorld,
)
from smart_home_sim.hybrid_planning.package_authoring import (
    PackageAuthoringError,
    ProcessPackageResult,
    author_process_package,
    build_reference_package,
)
from smart_home_sim.hybrid_planning.persona import (
    MAX_ROUTINE_ANCHORS,
    Persona,
    PersonaGenerationError,
    PersonaGenerationResult,
    generate_persona,
)
from smart_home_sim.hybrid_planning.pipeline import STAGES, run_generation
from smart_home_sim.hybrid_planning.recurring_activities import (
    BehavioralProfile,
    ProfileGenerationError,
    ProfileGenerationResult,
    RecurringActivity,
    generate_recurring_activities,
    validate_portfolio,
)
from smart_home_sim.hybrid_planning.world import (
    PlanningWorld,
    assemble_scenario,
    build_planning_world,
)

__all__ = [
    "MAX_ROUTINE_ANCHORS",
    "OUTLINE_SCHEMA_VERSION",
    "HabitGroundTruth",
    "HabitSegment",
    "BehavioralProfile",
    "Displacement",
    "FixedCommitment",
    "ActivityOverride",
    "HorizonAuthoringBundle",
    "HorizonOutline",
    "OutlineError",
    "OutlineEvent",
    "OutlinePhase",
    "OutlineWorld",
    "CadenceCalendar",
    "CadenceCalendarResult",
    "CadenceError",
    "CalendarDay",
    "ChatMessage",
    "RecurringActivity",
    "ActivityOccurrence",
    "ProfileGenerationError",
    "ProfileGenerationResult",
    "ActivityTraceEntry",
    "HorizonError",
    "HorizonResult",
    "LlmDaysResult",
    "PlannedActivityTrace",
    "build_horizon",
    "build_planned_trace",
    "generate_llm_day_plans",
    "build_cadence_calendar",
    "LMStudioClient",
    "LMStudioConfig",
    "LMStudioContentError",
    "LMStudioError",
    "LMStudioResponseError",
    "LMStudioUnavailableError",
    "Persona",
    "PersonaGenerationError",
    "PersonaGenerationResult",
    "PackageAuthoringError",
    "STAGES",
    "PlanningWorld",
    "ProcessPackageResult",
    "assemble_scenario",
    "author_process_package",
    "build_day_plan",
    "build_day_scenario",
    "build_day_scenarios",
    "build_planning_world",
    "build_reference_package",
    "label_to_intent",
    "extract_json_value",
    "generate_recurring_activities",
    "generate_persona",
    "run_generation",
    "validate_portfolio",
]
