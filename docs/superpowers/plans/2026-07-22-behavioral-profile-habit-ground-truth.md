# Behavioral Profile and Habit Ground Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and freeze an LLM-authored behavioral identity, then constrain each hybrid weekly plan so its habits are statistically mineable, causally coherent, and measurable against separate ground truth.

**Architecture:** Add focused behavioral-profile contracts, deterministic validation, a profile-generation service, and longitudinal habit budget/gate services inside the isolated `hybrid_planning` package. The existing planner consumes a frozen profile and ledger, lets LM Studio propose semantics, then repairs or rejects proposals before compiling a plan.

**Tech Stack:** Python 3.12, Pydantic 2.13, Typer, LM Studio OpenAI-compatible structured output, pytest 9, pytest-cov 7, Ruff.

## Global Constraints

- Generate plans only; never call simulation execution or sensor materialization.
- Use `qwen2.5-coder-7b-instruct` as the default local model.
- Accept no unknown activity or location identifiers from the LLM.
- Permit at most two explicit profile repairs and two explicit habit-plan repairs.
- Never silently patch LLM output.
- Freeze each accepted profile by canonical SHA-256 digest; ledgers must reference it.
- Open comparison baselines only after all gates pass; never include them in prompts.
- Keep the executable slice at seven days while making cadence and ledger longitudinal.
- Persist prompts, responses, proposals, digests, gate reports, and failure manifests.
- Separate intended, planned, and future realized ground truth from observable data.
- Add no runtime dependency and maintain at least 95 percent package coverage.
- Do not build UI in this increment; expose reusable services and CLI commands.

---

## File Responsibility Map

- `behavioral_models.py`: profile, cadence, ledger, budget, violation, and trace contracts.
- `behavioral_validation.py`: deterministic profile validation and canonical digest.
- `profile_service.py`: LM Studio profile generation, repair, provenance, and freezing.
- `habit_gates.py`: budget derivation, plan evaluation, planned trace, and ledger update.
- `prompts.py`: profile, profile-repair, profile-aware planning, and habit-repair prompts.
- `models.py`: structured weekly goal intents and repair-count configuration.
- `service.py`: profile-aware weekly orchestration without behavioral rule ownership.
- `cli.py`: unattended profile and plan commands.
- `test_behavioral_profile.py`: profile contracts, validation, generation, CLI, provenance.
- `test_habit_gates.py`: cadence, cooldown, completeness, chains, goals, trace, ledger.
- `test_hybrid_planning.py`: orchestration, repair, failure, baseline isolation.

### Task 1: Checkpoint the Existing Hybrid Planning Slice

**Files:**
- Modify: `README.md`
- Modify: `src/smart_home_sim/cli.py`
- Create: `src/smart_home_sim/hybrid_planning/`
- Create: `examples/hybrid/tommaso_bianchi_week.planning-case.json`
- Create: `tests/test_hybrid_planning.py`
- Create: `docs/plans/2026-07-22-hybrid-local-planning-implementation-plan.md`

**Interfaces:**
- Produces: `generate_hybrid_plan(case_path, output_dir, config, *, baseline_path=None, client=None) -> HybridPlanningResult`.
- Produces: the plan-only artifact directory used by later tasks.

- [ ] **Step 1: Verify the existing slice**

```powershell
.\.venv\Scripts\ruff.exe check src/smart_home_sim/cli.py src/smart_home_sim/hybrid_planning tests/test_hybrid_planning.py
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_hybrid_planning.py -q --cov=src/smart_home_sim/hybrid_planning --cov-report=term-missing --cov-fail-under=95
```

Expected: Ruff passes; pytest reports 11 passing tests and coverage of at least 95 percent.

- [ ] **Step 2: Confirm isolation**

```powershell
rg -n "run_simulation|simulation\.service" src/smart_home_sim/hybrid_planning
```

Expected: no simulation execution import or call.

- [ ] **Step 3: Commit without generated experiment directories**

```powershell
git add -- README.md src/smart_home_sim/cli.py src/smart_home_sim/hybrid_planning examples/hybrid tests/test_hybrid_planning.py docs/plans/2026-07-22-hybrid-local-planning-implementation-plan.md
git commit -m "feat: add isolated hybrid local planner"
```

Expected: commit succeeds; `generated/hybrid-planning/` remains untracked.

### Task 2: Define Behavioral Identity and Longitudinal Contracts

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/behavioral_models.py`
- Modify: `src/smart_home_sim/hybrid_planning/models.py`
- Create: `tests/test_behavioral_profile.py`

**Interfaces:**
- Consumes: `TimeBand` from `hybrid_planning.models`.
- Produces: `BehavioralProfile`, `HabitLedger`, `HabitBudget`, `HabitGateReport`, and `PlannedHabitTrace`.
- Produces: `WeeklyDayBrief.goal_intents` and `HybridPlanningConfig.max_habit_repairs`.

- [ ] **Step 1: Write failing strict-contract tests**

```python
from datetime import date

import pytest
from pydantic import ValidationError

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralHabit,
    BehavioralProfile,
    HabitCadence,
    HabitKind,
)
from smart_home_sim.hybrid_planning.models import TimeBand


def habit() -> BehavioralHabit:
    return BehavioralHabit(
        habit_id="daily_medication",
        intent="take_morning_medication",
        kind=HabitKind.anchor,
        rationale="Tommaso manages type 1 diabetes every morning.",
        cadence=HabitCadence(
            minimum_occurrences=1,
            typical_occurrences=1,
            maximum_occurrences=1,
            period_days=1,
        ),
        applicable_day_types=[],
        preferred_time_bands=[TimeBand.early_morning],
        temporal_jitter_minutes=20,
        execution_probability=0.98,
        exception_probability=0.02,
        cooldown_days=0,
        location_ids=["bedroom_01"],
        predecessor_intents=[],
        successor_intents=[],
        incompatible_habit_ids=[],
        seasonality="stable",
        mining_difficulty="easy",
    )


def test_cadence_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError, match="typicalOccurrences"):
        HabitCadence(
            minimum_occurrences=2,
            typical_occurrences=1,
            maximum_occurrences=3,
            period_days=7,
        )


def test_profile_rejects_duplicate_habit_ids_and_intents() -> None:
    repeated = habit()
    with pytest.raises(ValidationError, match="habitId and intent"):
        BehavioralProfile(
            profile_id="tommaso_behavior",
            profile_version="1.0.0",
            source_case_id="tommaso_bianchi_2026_08_10",
            resident_id="tommaso_bianchi",
            effective_from=date(2026, 8, 10),
            immutable_facts={"occupation": "gardener"},
            synthetic_traits={
                "socialStyle": "family-oriented",
                "wakeStyle": "early",
                "mealStyle": "regular",
                "exerciseStyle": "active",
                "domesticStyle": "orderly",
                "noveltyStyle": "moderate",
            },
            habits=[repeated, repeated.model_copy(update={"habit_id": "other"})] * 4,
        )
```

- [ ] **Step 2: Run tests and observe the missing module**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py -q
```

Expected: collection fails with `ModuleNotFoundError` for `behavioral_models`.

- [ ] **Step 3: Implement focused contracts**

Create `behavioral_models.py` with strict `ContractModel` classes using these exact fields:

```python
class HabitKind(StrEnum):
    anchor = "anchor"
    contextual = "contextual"
    optional = "optional"
    rare = "rare"


class HabitCondition(ContractModel):
    dimension: Literal["calendar_day_type", "season", "weather", "social", "custom"]
    operator: Literal["eq", "not_eq", "in", "not_in"]
    value: JsonValue


class HabitCadence(ContractModel):
    minimum_occurrences: int = Field(ge=0, le=31)
    typical_occurrences: int = Field(ge=1, le=31)
    maximum_occurrences: int = Field(ge=1, le=31)
    period_days: int = Field(ge=1, le=366)

    @model_validator(mode="after")
    def check_bounds(self) -> HabitCadence:
        if not self.minimum_occurrences <= self.typical_occurrences <= self.maximum_occurrences:
            raise ValueError(
                "minimumOccurrences <= typicalOccurrences <= maximumOccurrences is required"
            )
        return self


class BehavioralHabit(ContractModel):
    habit_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    kind: HabitKind
    rationale: str = Field(min_length=12)
    cadence: HabitCadence
    applicable_day_types: list[str] = Field(default_factory=list)
    preferred_time_bands: list[TimeBand] = Field(min_length=1)
    temporal_jitter_minutes: int = Field(ge=0, le=240)
    execution_probability: float = Field(ge=0, le=1)
    exception_probability: float = Field(ge=0, le=1)
    cooldown_days: int = Field(ge=0, le=366)
    location_ids: list[str] = Field(min_length=1)
    predecessor_intents: list[str] = Field(default_factory=list)
    successor_intents: list[str] = Field(default_factory=list)
    incompatible_habit_ids: list[str] = Field(default_factory=list)
    context_conditions: list[HabitCondition] = Field(default_factory=list)
    seasonality: str = Field(min_length=1)
    mining_difficulty: Literal["easy", "medium", "hard"]

    @model_validator(mode="after")
    def check_probabilities(self) -> BehavioralHabit:
        if self.execution_probability + self.exception_probability > 1.000001:
            raise ValueError("executionProbability + exceptionProbability must not exceed 1")
        return self


class BehavioralProfile(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["behavioral_profile"] = "behavioral_profile"
    profile_id: str
    profile_version: str
    source_case_id: str
    resident_id: str
    effective_from: date
    immutable_facts: dict[str, JsonValue]
    synthetic_traits: dict[str, JsonValue] = Field(min_length=6)
    habits: list[BehavioralHabit] = Field(min_length=8, max_length=24)

    @model_validator(mode="after")
    def check_unique_habits(self) -> BehavioralProfile:
        ids = [item.habit_id for item in self.habits]
        intents = [item.intent for item in self.habits]
        if len(ids) != len(set(ids)) or len(intents) != len(set(intents)):
            raise ValueError("habitId and intent must be unique within a behavioral profile")
        return self
```

Define `HabitDrift` before `BehavioralHabit`, add `drifts: list[HabitDrift] = Field(default_factory=list)` to `BehavioralHabit`, and define the remaining contracts exactly as follows. The validator for `HabitDrift` requires at least one override field.

```python
class HabitDrift(ContractModel):
    effective_from: date
    rationale: str = Field(min_length=12)
    cadence_override: HabitCadence | None = None
    preferred_time_bands_override: list[TimeBand] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_override(self) -> HabitDrift:
        if self.cadence_override is None and not self.preferred_time_bands_override:
            raise ValueError("habit drift requires a cadence or time-band override")
        return self


class HabitLedgerEntry(ContractModel):
    habit_id: str = Field(min_length=1)
    total_occurrences: int = Field(default=0, ge=0)
    last_seen: date | None = None
    cadence_carry: float = 0.0


class HabitLedger(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["habit_ledger"] = "habit_ledger"
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    through_date: date | None = None
    entries: list[HabitLedgerEntry]


class HabitBudgetItem(ContractModel):
    habit_id: str
    intent: str
    required_occurrences: int = Field(ge=0)
    target_occurrences: int = Field(ge=0)
    maximum_occurrences: int = Field(ge=0)
    forbidden_until: date | None = None


class HabitBudget(ContractModel):
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_date: date
    end_date: date
    items: list[HabitBudgetItem]


class HabitViolation(ContractModel):
    code: str
    message: str
    date: date | None = None
    habit_id: str | None = None
    intent: str | None = None


class HabitGateReport(ContractModel):
    valid: bool
    violations: list[HabitViolation] = Field(default_factory=list)


class PlannedHabitOccurrence(ContractModel):
    habit_id: str
    intent: str
    date: date
    time_band: TimeBand


class HabitTraceMetric(ContractModel):
    habit_id: str
    expected_occurrences: float = Field(ge=0)
    planned_occurrences: int = Field(ge=0)
    temporal_adherence: float = Field(ge=0, le=1)
    sequence_adherence: float = Field(ge=0, le=1)
    mining_difficulty: Literal["easy", "medium", "hard"]


class PlannedHabitTrace(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["planned_habit_trace"] = "planned_habit_trace"
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurrences: list[PlannedHabitOccurrence]
    metrics: list[HabitTraceMetric]
```

- [ ] **Step 4: Extend planning models**

Add:

```python
goal_intents: list[str] = Field(default_factory=list, max_length=5)
```

to `WeeklyDayBrief`, and:

```python
max_habit_repairs: int = Field(default=2, ge=0, le=2)
```

to `HybridPlanningConfig`.

- [ ] **Step 5: Run tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py -q
.\.venv\Scripts\ruff.exe check src/smart_home_sim/hybrid_planning/behavioral_models.py src/smart_home_sim/hybrid_planning/models.py tests/test_behavioral_profile.py
```

Expected: both tests and Ruff pass.

- [ ] **Step 6: Commit contracts**

```powershell
git add -- src/smart_home_sim/hybrid_planning/behavioral_models.py src/smart_home_sim/hybrid_planning/models.py tests/test_behavioral_profile.py
git commit -m "feat: define behavioral habit contracts"
```

### Task 3: Generate, Repair, Validate, and Freeze Behavioral Profiles

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/behavioral_validation.py`
- Create: `src/smart_home_sim/hybrid_planning/profile_service.py`
- Modify: `src/smart_home_sim/hybrid_planning/prompts.py`
- Modify: `src/smart_home_sim/hybrid_planning/__init__.py`
- Modify: `tests/test_behavioral_profile.py`

**Interfaces:**
- Consumes: `PlanningCase`, `ActivityCatalog`, `HybridPlanningConfig`, `LMStudioClient`, and `BehavioralProfile`.
- Produces: `behavioral_profile_digest(profile) -> str`.
- Produces: `validate_behavioral_profile(case, catalog, profile) -> ProfileValidationReport`.
- Produces: `generate_behavioral_profile(case_path, output_dir, config, *, client=None) -> BehavioralProfileResult`.

- [ ] **Step 1: Write failing validator and repair tests**

Add tests using the Tommaso case and a valid fixture:

```python
def test_profile_validator_reports_identity_catalog_and_portfolio_errors() -> None:
    planning_case, catalog = _read_models(CASE)
    invalid_habits = [
        habit().model_copy(
            update={"habit_id": f"bad_{index}", "intent": f"invented_{index}"}
        )
        for index in range(8)
    ]
    invalid = valid_profile().model_copy(
        update={"resident_id": "someone_else", "habits": invalid_habits}
    )
    report = validate_behavioral_profile(planning_case, catalog, invalid)
    assert {issue.code for issue in report.issues} >= {
        "PROFILE_RESIDENT_MISMATCH",
        "PROFILE_UNKNOWN_INTENT",
        "PROFILE_MISSING_ROUTINE_ANCHOR",
        "PROFILE_PORTFOLIO_UNBALANCED",
    }


def test_profile_generation_repairs_then_freezes(tmp_path: Path) -> None:
    invalid = valid_profile().model_copy(update={"resident_id": "someone_else"})
    valid = valid_profile()
    client = FakeClient([invalid, valid])
    result = generate_behavioral_profile(
        CASE,
        tmp_path / "profile",
        HybridPlanningConfig(model="fake"),
        client=client,
    )
    assert result.profile == valid
    assert len(client.prompts) == 2
    assert (result.output_dir / "behavioral-profile.json").is_file()
    assert (result.output_dir / "intended-habits.json").is_file()
    assert (result.output_dir / "profile.sha256").read_text().strip() == result.profile_digest
```

- [ ] **Step 2: Run tests and verify missing symbols**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py -q
```

Expected: collection fails because `behavioral_validation` and `profile_service` do not exist.

- [ ] **Step 3: Implement canonical digest and deterministic validation**

Create strict `ProfileIssue(code, message, habit_id=None)` and `ProfileValidationReport(valid, issues)` models. Implement canonical hashing:

```python
def behavioral_profile_digest(profile: BehavioralProfile) -> str:
    payload = profile.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

Implement `validate_behavioral_profile` with these stable codes:

```python
PROFILE_CODES = {
    "PROFILE_CASE_MISMATCH",
    "PROFILE_RESIDENT_MISMATCH",
    "PROFILE_FACTS_MISMATCH",
    "PROFILE_EFFECTIVE_DATE_MISMATCH",
    "PROFILE_UNKNOWN_INTENT",
    "PROFILE_UNKNOWN_CHAIN_INTENT",
    "PROFILE_UNKNOWN_LOCATION",
    "PROFILE_SELF_INCOMPATIBLE",
    "PROFILE_MISSING_ROUTINE_ANCHOR",
    "PROFILE_PORTFOLIO_UNBALANCED",
    "PROFILE_DAILY_OVERLOAD",
}
```

Compare `immutableFacts` exactly with `planning_case.resident.profile`. Require at least three anchors, two contextual habits, two optional habits, and one rare habit. Require every `RoutineRequirement.intent` to have an anchor habit whose preferred time bands contain the required band. Reject more than 12 maximum daily anchor occurrences for any applicable day type.

- [ ] **Step 4: Add constrained profile prompts**

Add `PROFILE_SYSTEM_PROMPT`, `behavioral_profile_prompt`, and `behavioral_profile_repair_prompt` to `prompts.py`. The prompt must include resident, dates, locations, routine requirements, and allowed intent/category pairs. Include this instruction verbatim:

```text
Supplied facts are immutable. Generate synthetic traits and formal habits that make this one
person longitudinally recognizable. Prefer a small number of strong, mineable habits over many
decorative claims. Every causal predecessor and successor must use an allowed intent identifier.
```

The repair prompt includes the rejected profile and full issue list, requests a complete replacement, and contains no comparison baseline.

- [ ] **Step 5: Implement profile generation and freezing**

Create:

```python
@dataclass(frozen=True, slots=True)
class BehavioralProfileResult:
    output_dir: Path
    profile: BehavioralProfile
    profile_digest: str
    validation: ProfileValidationReport


def generate_behavioral_profile(
    case_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    client: CompletionClient | None = None,
) -> BehavioralProfileResult:
```

Before the call write a running manifest. Constrain habit intent, chain intent, and location fields in the response schema. Persist attempts under `attempts/attempt-N/`. On each invalid proposal, pass the report to the next repair prompt. On success write `behavioral-profile.json`, `intended-habits.json`, `validation-report.json`, and `profile.sha256`. After two failed repairs, write a failed manifest and raise `HybridPlanningError` listing the issue codes.

- [ ] **Step 6: Export public service types**

Set:

```python
__all__ = [
    "BehavioralProfileResult",
    "HybridPlanningError",
    "HybridPlanningResult",
    "generate_behavioral_profile",
    "generate_hybrid_plan",
]
```

- [ ] **Step 7: Run tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py -q
.\.venv\Scripts\ruff.exe check src/smart_home_sim/hybrid_planning tests/test_behavioral_profile.py
```

Expected: profile tests and Ruff pass.

- [ ] **Step 8: Commit the profile generator**

```powershell
git add -- src/smart_home_sim/hybrid_planning/behavioral_validation.py src/smart_home_sim/hybrid_planning/profile_service.py src/smart_home_sim/hybrid_planning/prompts.py src/smart_home_sim/hybrid_planning/__init__.py tests/test_behavioral_profile.py
git commit -m "feat: generate and freeze behavioral profiles"
```

### Task 4: Derive Longitudinal Budgets and Enforce Mineable Plans

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/habit_gates.py`
- Create: `tests/test_habit_gates.py`

**Interfaces:**
- Consumes: `BehavioralProfile`, `HabitLedger`, `PlanningCase`, `WeeklyBrief`, and daily proposals.
- Produces: `initial_habit_ledger`, `derive_habit_budget`, `evaluate_habit_plan`, `planned_habit_trace`, and `update_habit_ledger`.

- [ ] **Step 1: Write failing budget and gate tests**

Use a profile containing daily medication, weekday work, weekly groceries, monthly mother visit with five-day cooldown and travel chain, optional reading, and a rare pharmacy visit:

```python
def test_budget_turns_cadence_into_chunk_counts() -> None:
    profile = valid_profile()
    digest = behavioral_profile_digest(profile)
    ledger = initial_habit_ledger(digest, profile)
    planning_case, _ = _read_models(CASE)
    dates = planning_case.dates()
    budget = derive_habit_budget(
        profile,
        ledger,
        dates,
        {value: planning_case.calendar_day(value).day_type for value in dates},
    )
    items = {item.intent: item for item in budget.items}
    assert items["take_morning_medication"].required_occurrences == 7
    assert items["work_shift"].required_occurrences == 5
    assert items["visit_mother_and_have_dinner"].maximum_occurrences == 1


def test_gate_reports_missing_anchor_chain_cooldown_and_goal() -> None:
    report = evaluate_habit_plan(profile, ledger, budget, brief, broken_proposals)
    assert {item.code for item in report.violations} >= {
        "HABIT_REQUIRED_MISSING",
        "HABIT_DAILY_ANCHOR_MISSING",
        "HABIT_CHAIN_PREDECESSOR_MISSING",
        "HABIT_CHAIN_SUCCESSOR_MISSING",
        "HABIT_COOLDOWN_VIOLATION",
        "WEEKLY_GOAL_UNREALIZED",
    }


def test_trace_and_ledger_record_planned_occurrences() -> None:
    trace = planned_habit_trace(profile, digest, budget, valid_proposals)
    updated = update_habit_ledger(profile, digest, ledger, valid_proposals)
    assert sum(item.intent == "take_morning_medication" for item in trace.occurrences) == 7
    medication = next(item for item in updated.entries if item.habit_id == "daily_medication")
    assert medication.total_occurrences == 7
    assert medication.last_seen == date(2026, 8, 16)
```

- [ ] **Step 2: Run tests and verify the missing module**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_habit_gates.py -q
```

Expected: collection fails with `ModuleNotFoundError` for `habit_gates`.

- [ ] **Step 3: Implement cadence budgeting**

For each habit calculate eligible days from `applicable_day_types` and use:

```python
expected = habit.cadence.typical_occurrences * eligible_days / habit.cadence.period_days
minimum = math.floor(
    habit.cadence.minimum_occurrences * eligible_days / habit.cadence.period_days
)
target = max(minimum, math.floor(entry.cadence_carry + expected))
maximum = math.ceil(
    habit.cadence.maximum_occurrences * eligible_days / habit.cadence.period_days
)
```

For daily anchors enforce the minimum on every eligible day. For non-anchor positive cadence preserve `maximum >= 1`. Set `forbiddenUntil` from `lastSeen + cooldownDays` when it overlaps the chunk. Reject a ledger whose digest differs.

- [ ] **Step 4: Implement stable gate codes and evidence**

Evaluate these exact codes:

```python
GATE_CODES = (
    "HABIT_REQUIRED_MISSING",
    "HABIT_FREQUENCY_EXCEEDED",
    "HABIT_DAILY_ANCHOR_MISSING",
    "HABIT_DAILY_ANCHOR_EXCEEDED",
    "HABIT_COOLDOWN_VIOLATION",
    "HABIT_CHAIN_PREDECESSOR_MISSING",
    "HABIT_CHAIN_SUCCESSOR_MISSING",
    "HABIT_INCOMPATIBLE_PAIR",
    "WEEKLY_GOAL_UNREALIZED",
)
```

Predecessors require a lower activity index and successors a higher index on the same day. Every violation gets a repair date: affected day, last excess occurrence, or first eligible day for a missing habit. Trace goals via `goal_intents`, never fuzzy narrative matching.

- [ ] **Step 5: Implement trace and ledger update**

Create a planned occurrence for each activity mapped to a profile habit. Create one trace metric per habit using the budget target as expected support, the fraction of occurrences inside preferred time bands as temporal adherence, and the fraction with complete predecessor/successor chains as sequence adherence. Update count and last date. Carry uses:

```python
new_carry = old_entry.cadence_carry + expected_for_chunk - actual_occurrences
```

Preserve negative carry and set `throughDate` to the last proposal date. Do not create a realized trace.

- [ ] **Step 6: Run tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_habit_gates.py -q
.\.venv\Scripts\ruff.exe check src/smart_home_sim/hybrid_planning/habit_gates.py tests/test_habit_gates.py
```

Expected: all habit-gate tests and Ruff pass.

- [ ] **Step 7: Commit longitudinal controls**

```powershell
git add -- src/smart_home_sim/hybrid_planning/habit_gates.py tests/test_habit_gates.py
git commit -m "feat: enforce longitudinal habit budgets"
```

### Task 5: Integrate Profile-Aware Prompts, Gate Repair, and Artifacts

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/prompts.py`
- Modify: `src/smart_home_sim/hybrid_planning/service.py`
- Modify: `tests/test_hybrid_planning.py`

**Interfaces:**
- Consumes: frozen profile and optional prior ledger paths.
- Changes: `generate_hybrid_plan` gains `behavioral_profile_path` and `ledger_path` keyword arguments.
- Produces: habit budget, gate report, planned trace, and updated ledger artifacts.

- [ ] **Step 1: Write failing orchestration tests**

Supply a valid profile and fake output containing an excessive mother visit followed by a repaired day. Assert:

```python
assert result.habit_gate is not None and result.habit_gate.valid
assert (output / "habit-budget.json").is_file()
assert (output / "habit-gate-report.json").is_file()
assert (output / "planned-habit-trace.json").is_file()
assert (output / "habit-ledger.json").is_file()
assert (output / "days/2026-08-16/habit-repair-1/proposal.json").is_file()
assert json.loads((output / "run.json").read_text())["executionPerformed"] is False
assert "barcelona_tommaso_gardener_week" not in "\n".join(client.prompts)
```

Add a digest-mismatch test and a repair-exhaustion test. The latter must assert a failed manifest containing `habit gate`.

- [ ] **Step 2: Run focused tests and verify missing behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_hybrid_planning.py -q
```

Expected: new tests fail because profile paths and habit artifacts are unsupported.

- [ ] **Step 3: Make planning prompts profile-aware**

Add `behavioralProfile` and `habitBudget` to weekly and daily payloads. Add a dynamic weekly schema constraining every `goalIntents` value to a catalog intent and requiring at least one per day when a profile exists. Add `habit_repair_prompt` with the profile, budget, target day, other days, and target violations. Require the smallest complete-day replacement while preserving valid anchors and unrelated choices.

- [ ] **Step 4: Load frozen context before any LLM call**

Use this signature:

```python
def generate_hybrid_plan(
    case_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    behavioral_profile_path: Path | None = None,
    ledger_path: Path | None = None,
    baseline_path: Path | None = None,
    client: CompletionClient | None = None,
) -> HybridPlanningResult:
```

When supplied, parse and validate the profile, calculate its digest, parse or initialize the ledger, and derive the budget before invoking LM Studio. Persist profile snapshot, digest, ledger input, and budget. A profile or ledger error must create no exchange directory.

- [ ] **Step 5: Add deterministic habit repair after diversity repair**

Evaluate and persist the full-week gate. Use the first violation's repair date to select one day. Call `habit_repair_prompt`, persist under `days/<date>/habit-repair-N/`, structurally validate the replacement, replace only that day, and re-evaluate habit plus diversity gates. After two invalid repairs, write reports and fail before materialization or compilation.

Use this seed and schema policy:

```python
replacement, exchange = active_client.complete_json(
    schema_name="habit_daily_repair",
    output_model=DailyProposal,
    system_prompt=SYSTEM_PROMPT,
    user_prompt=repair_prompt,
    seed=planning_case.seed + 200 + repair_number,
    schema_override=_daily_schema(planning_case, catalog, target_date),
)
```

- [ ] **Step 6: Persist planned truth after all gates pass**

Write `planned-habit-trace.json` and updated `habit-ledger.json` before scenario materialization. Add `behavioralProfileDigest`, `habitGatePassed`, and `plannedGroundTruthWritten` to the manifest. Extend `HybridPlanningResult` with `habit_gate: HabitGateReport | None`; retain `None` only for legacy direct Python calls without a profile.

- [ ] **Step 7: Run integration coverage and lint**

```powershell
.\.venv\Scripts\ruff.exe check src/smart_home_sim/hybrid_planning tests/test_hybrid_planning.py
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py tests/test_habit_gates.py tests/test_hybrid_planning.py -q --cov=src/smart_home_sim/hybrid_planning --cov-report=term-missing --cov-fail-under=95
```

Expected: all targeted tests pass and coverage is at least 95 percent.

- [ ] **Step 8: Commit planner integration**

```powershell
git add -- src/smart_home_sim/hybrid_planning/prompts.py src/smart_home_sim/hybrid_planning/service.py tests/test_hybrid_planning.py
git commit -m "feat: constrain hybrid plans by behavioral truth"
```

### Task 6: Expose the Unattended CLI Workflow

**Files:**
- Modify: `src/smart_home_sim/cli.py`
- Modify: `README.md`
- Modify: `tests/test_behavioral_profile.py`
- Modify: `tests/test_hybrid_planning.py`

**Interfaces:**
- Produces: `generate-behavioral-profile CASE --output-dir DIR`.
- Changes: `generate-hybrid-plan` requires `--behavioral-profile` and accepts `--habit-ledger`.

- [ ] **Step 1: Write failing CLI tests**

```python
profile_result = runner.invoke(
    app,
    [
        "generate-behavioral-profile",
        str(CASE),
        "--output-dir",
        str(tmp_path / "profile"),
    ],
)
assert profile_result.exit_code == 0
assert "Frozen behavioral profile written" in profile_result.stdout

plan_result = runner.invoke(
    app,
    [
        "generate-hybrid-plan",
        str(CASE),
        "--output-dir",
        str(tmp_path / "plan"),
        "--behavioral-profile",
        str(tmp_path / "profile/behavioral-profile.json"),
    ],
)
assert plan_result.exit_code == 0
```

Also invoke plan generation without `--behavioral-profile`; assert Typer exits with code 2 and identifies the missing option.

- [ ] **Step 2: Run tests and verify missing command/option failures**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py tests/test_hybrid_planning.py -q
```

Expected: the profile command is missing and the planner does not require a profile yet.

- [ ] **Step 3: Implement CLI commands**

Use the 7B model, base URL, and temperature defaults for both. Make behavioral profile a required Typer option, add optional habit ledger, and pass both paths to the service. Print absolute paths for frozen profile, digest, canonical plan, habit gate, and updated ledger.

- [ ] **Step 4: Document two-command use**

Add:

```powershell
.\.venv\Scripts\smart-home-sim.exe generate-behavioral-profile `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --output-dir generated/hybrid-planning/tommaso-profile

.\.venv\Scripts\smart-home-sim.exe generate-hybrid-plan `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --output-dir generated/hybrid-planning/tommaso-week `
  --behavioral-profile generated/hybrid-planning/tommaso-profile/behavioral-profile.json `
  --compare-with generated/tommaso_bianchi/tommaso_bianchi.json
```

State that LM Studio and the 7B model must be running, no Codex supervision is needed, simulation is not executed, and intended/planned truth files must not be mining inputs.

- [ ] **Step 5: Run tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py tests/test_hybrid_planning.py -q
.\.venv\Scripts\ruff.exe check src/smart_home_sim/cli.py tests/test_behavioral_profile.py tests/test_hybrid_planning.py
```

Expected: CLI tests and Ruff pass.

- [ ] **Step 6: Commit CLI, docs, and plans**

```powershell
git add -- src/smart_home_sim/cli.py README.md tests/test_behavioral_profile.py tests/test_hybrid_planning.py docs/plans/2026-07-22-behavioral-profile-habit-ground-truth-implementation-plan.md docs/superpowers/plans/2026-07-22-behavioral-profile-habit-ground-truth.md
git commit -m "docs: add behavioral planning workflow"
```

### Task 7: Verify and Run Live Tommaso Acceptance

**Files:**
- Runtime output: `generated/hybrid-planning/tommaso-behavioral-profile-20260722/`
- Runtime output: `generated/hybrid-planning/tommaso-habit-aware-week-20260722/`

**Interfaces:**
- Consumes: both CLI commands and the loaded LM Studio 7B model.
- Produces: acceptance evidence without source edits.

- [ ] **Step 1: Run final static and targeted checks**

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py tests/test_habit_gates.py tests/test_hybrid_planning.py -q --cov=src/smart_home_sim/hybrid_planning --cov-report=term-missing --cov-fail-under=95
git diff --check
```

Expected: lint and tests pass, coverage is at least 95 percent, and diff check is silent.

- [ ] **Step 2: Confirm the model state**

```powershell
lms ps
```

Expected: only `qwen2.5-coder-7b-instruct`, context 16384, parallelism 1.

- [ ] **Step 3: Generate the frozen profile**

```powershell
.\.venv\Scripts\smart-home-sim.exe generate-behavioral-profile `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --output-dir generated/hybrid-planning/tommaso-behavioral-profile-20260722
```

Expected: valid profile, at least eight habits spanning four kinds, and a 64-character digest.

- [ ] **Step 4: Generate the habit-aware plan**

```powershell
.\.venv\Scripts\smart-home-sim.exe generate-hybrid-plan `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --output-dir generated/hybrid-planning/tommaso-habit-aware-week-20260722 `
  --behavioral-profile generated/hybrid-planning/tommaso-behavioral-profile-20260722/behavioral-profile.json `
  --compare-with generated/tommaso_bianchi/tommaso_bianchi.json
```

Expected: `executionPerformed` is false; profile, diversity, validation, compilation, and habit gates pass; comparison reports the same resident and window.

- [ ] **Step 5: Inspect acceptance metrics**

The read-only report must show:

```text
daily medication: 7
weekday work shifts: 5
sleep: 7
mother visits: within behavioral maximum
causal-chain violations: 0
goal violations: 0
distinct daily sequences: at least 5 of 7
```

Verify no request artifact contains `barcelona_tommaso_gardener_week` or comparison content. If generation fails, preserve artifacts and report the exact violation instead of weakening a gate.

- [ ] **Step 6: Record final status without generated artifacts**

```powershell
git status --short
git log -6 --oneline
```

Expected: source and tests are committed; experiment directories remain outside commits; no unrelated user change is staged.
