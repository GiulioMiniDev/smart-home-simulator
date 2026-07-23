# Guarded Hybrid Month A/B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hybrid monthly plans obey exact habit targets, daily-life completeness,
preferred habit fields, and semantic dependencies, then regenerate Tommaso Bianchi's
same month and compare it with the first hybrid month.

**Architecture:** Keep the frozen behavioral profile and LLM inputs unchanged. Add a
deterministic guardrail layer around daily generation, make chunk habit targets binding,
extend longitudinal quality metrics, and add a reusable comparison command. The LLM
continues to choose narratives and optional variation; the software owns acceptance.

**Tech Stack:** Python 3.12, Pydantic v2 contract models, Typer CLI, pytest, Ruff,
LM Studio OpenAI-compatible endpoint.

## Global Constraints

- Do not execute simulations; generate plans and compiled scenarios only.
- Never include `generated/tommaso_bianchi/tommaso_bianchi.json` in an LLM request.
- Reuse the frozen profile whose digest is
  `7aacbd51b11bd7bad262f8e714edae13925b33d9b9079c25a0304a5331a64c28`.
- Reuse `qwen2.5-coder-7b-instruct`, 2026-08-10 through 2026-09-09, and seven-day chunks.
- Write the guarded run to a new ignored output directory.
- Preserve all existing non-hybrid simulation behavior.
- Use TDD for every production behavior change.
- Commit each task independently and do not merge the branch.

---

### Task 1: Make non-anchor habit targets binding

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/habit_gates.py`
- Modify: `tests/test_habit_gates.py`

**Interfaces:**
- Consumes: existing `HabitBudgetItem.target_occurrences`.
- Produces: exact non-anchor target enforcement in
  `constrain_daily_habit_limits(...)` and `evaluate_habit_plan(...)`.

- [ ] **Step 1: Write failing target-cap tests**

Add tests that prove a second occurrence is removed even when it remains below the
cadence maximum, and that target zero removes the first occurrence:

```python
def test_daily_constraint_uses_target_as_non_anchor_cap() -> None:
    profile, _, ledger, budget = context()
    groceries = activity(
        "buy_groceries",
        "supermarket_barcelona",
        TimeBand.afternoon,
    )
    first = proposals()[0].model_copy(
        update={"activities": [*proposals()[0].activities, groceries]}
    )
    second = proposals()[1].model_copy(
        update={"activities": [*proposals()[1].activities, groceries]}
    )

    constrained, changes = constrain_daily_habit_limits(
        profile,
        ledger,
        budget,
        [first],
        second,
    )

    assert "buy_groceries" not in {item.intent for item in constrained.activities}
    assert changes[-1]["reason"] == "target_occurrences"


def test_daily_constraint_forbids_zero_target_habit() -> None:
    profile, _, ledger, budget = context()
    refill = activity(
        "collect_medication_refill",
        "pharmacy_barcelona",
        TimeBand.afternoon,
    )
    day = proposals()[0].model_copy(
        update={"activities": [*proposals()[0].activities, refill]}
    )

    constrained, changes = constrain_daily_habit_limits(
        profile,
        ledger,
        budget,
        [],
        day,
    )

    assert "collect_medication_refill" not in {
        item.intent for item in constrained.activities
    }
    assert changes[-1]["reason"] == "target_occurrences"
```

- [ ] **Step 2: Run the cap tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_habit_gates.py::test_daily_constraint_uses_target_as_non_anchor_cap `
  tests/test_habit_gates.py::test_daily_constraint_forbids_zero_target_habit -q
```

Expected: both tests fail because `maximum_occurrences`, not
`target_occurrences`, is the active cap.

- [ ] **Step 3: Implement the binding cap**

In `constrain_daily_habit_limits`, keep anchors unchanged and use:

```python
        target_cap = min(item.target_occurrences, item.maximum_occurrences)
        if item.forbidden_until is not None and proposal.date <= item.forbidden_until:
            reason = "forbidden_until"
        elif counts[habit.habit_id] >= target_cap:
            reason = "target_occurrences"
        elif (
            previous is not None
            and habit.cooldown_days
            and proposal.date <= previous + timedelta(days=habit.cooldown_days)
        ):
            reason = "cooldown"
```

Do not retain the former `maximum_occurrences` branch for non-anchor habits.

- [ ] **Step 4: Add failing exact-target gate tests**

```python
def test_gate_rejects_non_anchor_count_below_target() -> None:
    profile, _, ledger, budget = context()
    report = evaluate_habit_plan(
        profile,
        ledger,
        budget,
        weekly_brief(),
        proposals(),
    )
    assert "HABIT_TARGET_MISSING" in {item.code for item in report.violations}


def test_gate_rejects_non_anchor_count_above_target() -> None:
    profile, _, ledger, budget = context()
    groceries = activity(
        "buy_groceries",
        "supermarket_barcelona",
        TimeBand.afternoon,
    )
    days = proposals()
    days[5] = days[5].model_copy(
        update={"activities": [*days[5].activities, groceries, groceries]}
    )
    report = evaluate_habit_plan(
        profile,
        ledger,
        budget,
        weekly_brief(),
        days,
    )
    assert "HABIT_TARGET_EXCEEDED" in {item.code for item in report.violations}
```

- [ ] **Step 5: Run the gate tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_habit_gates.py::test_gate_rejects_non_anchor_count_below_target `
  tests/test_habit_gates.py::test_gate_rejects_non_anchor_count_above_target -q
```

Expected: failures because the two codes do not exist.

- [ ] **Step 6: Implement exact-target violations**

Add the codes to `GATE_CODES`:

```python
    "HABIT_TARGET_MISSING",
    "HABIT_TARGET_EXCEEDED",
```

Inside the non-anchor branch of `evaluate_habit_plan`, append:

```python
        if habit.kind is not HabitKind.anchor and len(dates) < item.target_occurrences:
            violations.append(
                HabitViolation(
                    code="HABIT_TARGET_MISSING",
                    message=(
                        f"{habit.intent} targets {item.target_occurrences}; "
                        f"found {len(dates)}"
                    ),
                    date=_repair_date(habit, proposals, day_types),
                    habit_id=habit.habit_id,
                    intent=habit.intent,
                )
            )
        if habit.kind is not HabitKind.anchor and len(dates) > item.target_occurrences:
            violations.append(
                HabitViolation(
                    code="HABIT_TARGET_EXCEEDED",
                    message=(
                        f"{habit.intent} targets {item.target_occurrences}; "
                        f"found {len(dates)}"
                    ),
                    date=dates[-1],
                    habit_id=habit.habit_id,
                    intent=habit.intent,
                )
            )
```

Retain required, maximum, cooldown, chain, incompatibility, and weekly-goal checks.

- [ ] **Step 7: Verify Task 1**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_habit_gates.py -q
.\.venv\Scripts\python.exe -m ruff check `
  src/smart_home_sim/hybrid_planning/habit_gates.py tests/test_habit_gates.py
```

Expected: all habit-gate tests and Ruff pass.

- [ ] **Step 8: Commit Task 1**

```powershell
git add src/smart_home_sim/hybrid_planning/habit_gates.py tests/test_habit_gates.py
git commit -m "feat: make hybrid habit targets binding"
```

---

### Task 2: Add reusable daily and semantic guardrails

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/guardrails.py`
- Create: `tests/test_hybrid_guardrails.py`
- Modify: `src/smart_home_sim/hybrid_planning/longitudinal_models.py`

**Interfaces:**
- Produces:
  - `daily_life_violations(day_type, proposal) -> list[QualityViolation]`
  - `semantic_violations(profile, proposal) -> list[QualityViolation]`
  - `normalize_habit_preferences(profile, proposal) -> tuple[DailyProposal, list[dict[str, object]]]`
  - `guardrail_prompt_payload(catalog) -> dict[str, object]`

- [ ] **Step 0: Create the test module imports**

Start `tests/test_hybrid_guardrails.py` with:

```python
from datetime import date

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import activity

from smart_home_sim.hybrid_planning.guardrails import (
    daily_life_violations,
    guardrail_prompt_payload,
    normalize_habit_preferences,
    semantic_violations,
)
from smart_home_sim.hybrid_planning.longitudinal_models import QualityViolation
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    ProposedActivity,
    TimeBand,
)
```

The imports from the missing production module are expected to fail during the first
RED run.

- [ ] **Step 1: Add the shared violation contract**

Write a failing serialization test in `tests/test_hybrid_guardrails.py`:

```python
def test_quality_violation_serializes_with_aliases() -> None:
    violation = QualityViolation(
        code="MISSING_NOURISHMENT",
        date=date(2026, 8, 10),
        intent="nourishment",
        message="day requires a nourishment activity",
    )
    assert violation.model_dump(by_alias=True)["date"] == date(2026, 8, 10)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_hybrid_guardrails.py::test_quality_violation_serializes_with_aliases -q
```

Expected: import failure for `QualityViolation`.

Replace the existing `CausalViolation` declaration in `longitudinal_models.py` while
retaining its import-compatible alias:

```python
class QualityViolation(ContractModel):
    code: str = Field(min_length=1)
    date: date
    intent: str = Field(min_length=1)
    message: str = Field(min_length=1)


CausalViolation = QualityViolation
```

Change `LongitudinalQualityReport.causal_violations` to
`list[QualityViolation]`. Existing imports of `CausalViolation` continue to work and
the serialized contract remains unchanged.

- [ ] **Step 2: Write failing daily-life tests**

Use real `DailyProposal` objects:

```python
def test_daily_life_requires_nourishment_hygiene_and_density() -> None:
    sparse = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="An implausibly sparse Sunday",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )
    assert {item.code for item in daily_life_violations("weekend", sparse)} == {
        "MISSING_NOURISHMENT",
        "MISSING_HYGIENE",
        "DAILY_DENSITY_TOO_LOW",
    }


def test_daily_life_accepts_complete_variable_day() -> None:
    complete = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Complete Sunday with room for variation",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("prepare_weekend_breakfast", "kitchen_01", "morning"),
            activity("evening_hygiene", "bathroom_01", "evening"),
            activity("read_and_rest", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )
    assert daily_life_violations("weekend", complete) == []
```

Run both tests. Expected: import failures for the missing functions.

- [ ] **Step 3: Implement daily-life intent groups and density**

Create `guardrails.py` with explicit reusable sets:

```python
NOURISHMENT_INTENTS = frozenset(
    {
        "cook_dinner",
        "eat_breakfast",
        "eat_breakfast_and_listen_to_radio",
        "eat_breakfast_and_read_news",
        "eat_breakfast_with_radio_news",
        "eat_dinner",
        "eat_light_dinner",
        "eat_lunch",
        "prepare_and_eat_breakfast",
        "prepare_breakfast",
        "prepare_light_dinner",
        "prepare_simple_lunch",
        "prepare_sunday_lunch",
        "prepare_weekend_breakfast",
        "reheat_leftover_dinner_and_prepare_salad",
        "visit_mother_and_have_dinner",
        "weekly_meal_preparation",
    }
)
HYGIENE_INTENTS = frozenset(
    {
        "evening_hygiene",
        "morning_toilet_and_shower",
        "morning_toilet_and_wash",
        "post_walk_shower",
        "shower_and_get_ready_to_go_out",
    }
)
WALK_INTENTS = frozenset(
    {"evening_walk", "long_sunday_walk", "short_evening_walk"}
)
MINIMUM_ACTIVITY_COUNT = {"workday": 6, "weekend": 5}
```

Implement `daily_life_violations` by checking set intersection and the applicable
density floor. Use codes and messages exactly as asserted by the tests.

- [ ] **Step 4: Write failing semantic-chain tests**

Cover every rule independently:

```python
@pytest.mark.parametrize(
    ("activities", "code"),
    [
        (
            [
                activity("post_walk_shower", "bathroom_01", "evening"),
                activity("sleep", "bedroom_01", "night"),
            ],
            "SHOWER_WITHOUT_WALK",
        ),
        (
            [
                activity(
                    "visit_mother_and_have_dinner",
                    "mother_house_barcelona",
                    "evening",
                ),
                activity("sleep", "bedroom_01", "night"),
            ],
            "MOTHER_VISIT_CHAIN_INCOMPLETE",
        ),
        (
            [
                activity("work_shift", "garden_workplace", "morning"),
                activity("sleep", "bedroom_01", "night"),
            ],
            "WORK_SHIFT_CHAIN_INCOMPLETE",
        ),
    ],
)
def test_semantic_rules_reject_incomplete_chains(
    activities: list[ProposedActivity],
    code: str,
) -> None:
    proposal = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Incomplete semantic chain",
        activities=activities,
    )
    assert code in {
        item.code for item in semantic_violations(valid_profile(), proposal)
    }
```

Run the parameterized test. Expected: import failure for `semantic_violations`.

- [ ] **Step 5: Implement semantic rules**

For each activity position:

```python
if intent == "post_walk_shower" and not WALK_INTENTS.intersection(intents[:position]):
    add("SHOWER_WITHOUT_WALK", intent, "post_walk_shower requires an earlier walk")
if intent == "visit_mother_and_have_dinner":
    if "travel_to_mothers_home" not in intents[:position] or "travel_home" not in intents[position + 1:]:
        add(
            "MOTHER_VISIT_CHAIN_INCOMPLETE",
            intent,
            "visit_mother_and_have_dinner requires earlier travel_to_mothers_home and later travel_home",
        )
if intent == "work_shift":
    if "commute_to_work" not in intents[:position] or "commute_home" not in intents[position + 1:]:
        add(
            "WORK_SHIFT_CHAIN_INCOMPLETE",
            intent,
            "work_shift requires earlier commute_to_work and later commute_home",
        )
if intent == "commute_to_work" and "work_shift" not in intents[position + 1:]:
    add("WORK_TRAVEL_WITHOUT_SHIFT", intent, "outbound work travel requires a later work_shift")
if intent == "commute_home" and "work_shift" not in intents[:position]:
    add("RETURN_TRAVEL_WITHOUT_SHIFT", intent, "return work travel requires an earlier work_shift")
```

Then append profile-declared missing predecessors and successors using the existing
order semantics. De-duplicate violations by `(code, date, intent, message)`.

- [ ] **Step 6: Write failing preference-normalization test**

```python
def test_profile_habit_preferences_are_normalized() -> None:
    profile = valid_profile()
    wrong = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Wrong habit preferences",
        activities=[
            activity("buy_groceries", "living_room_01", "morning"),
        ],
    )
    normalized, changes = normalize_habit_preferences(profile, wrong)
    item = normalized.activities[0]
    assert item.time_band is TimeBand.afternoon
    assert item.location_id == "supermarket_barcelona"
    assert {change["field"] for change in changes} == {"timeBand", "locationId"}
```

Run the test. Expected: missing function.

- [ ] **Step 7: Implement preference normalization and prompt payload**

For each profile-mapped activity, update only fields outside the profile envelope:

```python
updates: dict[str, object] = {}
if activity.time_band not in habit.preferred_time_bands:
    updates["time_band"] = habit.preferred_time_bands[0]
if activity.location_id not in habit.location_ids:
    updates["location_id"] = habit.location_ids[0]
```

Write one change record per modified field with date, habit ID, intent, field,
old value, new value, and reason `profile_preference`.

`guardrail_prompt_payload(catalog)` must return only catalog-present intents:

```python
{
    "minimumActivities": {"workday": 6, "weekend": 5},
    "requiredDailyCategories": {
        "nourishment": sorted(NOURISHMENT_INTENTS & known),
        "hygiene": sorted(HYGIENE_INTENTS & known),
    },
    "semanticRules": [
        "post_walk_shower requires an earlier walking intent",
        "visit_mother_and_have_dinner requires travel_to_mothers_home before and travel_home after",
        "work_shift requires commute_to_work before and commute_home after",
    ],
}
```

- [ ] **Step 8: Verify and commit Task 2**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_hybrid_guardrails.py -q
.\.venv\Scripts\python.exe -m ruff check `
  src/smart_home_sim/hybrid_planning/guardrails.py `
  src/smart_home_sim/hybrid_planning/longitudinal_models.py `
  tests/test_hybrid_guardrails.py
git add src/smart_home_sim/hybrid_planning/guardrails.py `
  src/smart_home_sim/hybrid_planning/longitudinal_models.py `
  tests/test_hybrid_guardrails.py
git commit -m "feat: add hybrid daily semantic guardrails"
```

---

### Task 3: Integrate guardrails into prompts, normalization, and repair

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/prompts.py`
- Modify: `src/smart_home_sim/hybrid_planning/service.py`
- Modify: `tests/test_hybrid_planning.py`

**Interfaces:**
- Consumes Task 2 guardrail functions.
- Produces prompt guidance, preference artifacts, and immediate daily repair.

- [ ] **Step 1: Write a failing prompt-policy test**

```python
def test_daily_prompt_contains_guardrail_policy() -> None:
    planning_case, catalog = _read_models(CASE)
    brief = weekly_brief()
    prompt = daily_prompt(
        planning_case,
        catalog,
        brief,
        brief.days[0],
        PlanningMemory(),
        valid_profile(),
        derive_habit_budget(
            valid_profile(),
            initial_habit_ledger(
                behavioral_profile_digest(valid_profile()),
                valid_profile(),
            ),
            planning_case.dates(),
            {
                value: planning_case.calendar_day(value).day_type
                for value in planning_case.dates()
            },
        ),
    )
    assert '"dailyGuardrails"' in prompt
    assert '"minimumActivities"' in prompt
    assert "post_walk_shower requires an earlier walking intent" in prompt
```

Run this test. Expected: the payload has no `dailyGuardrails`.

- [ ] **Step 2: Add policy payloads to prompts**

Import `guardrail_prompt_payload` and add:

```python
"dailyGuardrails": guardrail_prompt_payload(catalog),
```

to `daily_prompt`, `structural_repair_prompt`, `diversity_repair_prompt`, and
`habit_repair_prompt`. Change the daily instruction from the generic
`Return 6 to 12 activities` to:

```text
Meet the supplied daily guardrails without turning the day into a fixed template.
Use the minimum as a floor, not as a target, and preserve meaningful optional variation.
```

- [ ] **Step 3: Write failing validator tests**

```python
def test_daily_validator_rejects_missing_daily_life_categories() -> None:
    planning_case, catalog = _read_models(CASE)
    sparse = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Sparse Sunday",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )
    with pytest.raises(HybridPlanningError, match="MISSING_NOURISHMENT"):
        _validate_daily_proposal(
            planning_case,
            catalog,
            sparse.date,
            sparse,
            behavioral_profile=valid_profile(),
        )


def test_daily_validator_rejects_semantic_chain_error() -> None:
    planning_case, catalog = _read_models(CASE)
    daily = proposal(date(2026, 8, 10), "read")
    daily = daily.model_copy(
        update={
            "activities": [
                item for item in daily.activities if item.intent != "commute_home"
            ]
        }
    )
    with pytest.raises(HybridPlanningError, match="WORK_SHIFT_CHAIN_INCOMPLETE"):
        _validate_daily_proposal(
            planning_case,
            catalog,
            daily.date,
            daily,
            behavioral_profile=valid_profile(),
        )
```

Run both tests. Expected: the sparse day reaches a different validation result and the
missing return commute is accepted.

- [ ] **Step 4: Replace one-day longitudinal validation with guardrails**

In `_validate_daily_proposal`, after routines and before materialization:

```python
if behavioral_profile is not None:
    guardrail_violations = [
        *daily_life_violations(day_type, proposal),
        *semantic_violations(behavioral_profile, proposal),
    ]
    if guardrail_violations:
        details = "; ".join(
            f"{item.code}: {item.message}" for item in guardrail_violations
        )
        raise HybridPlanningError(f"daily proposal violates guardrails: {details}")
```

Remove the one-day `evaluate_longitudinal_quality` call from the service.

- [ ] **Step 5: Write a failing preference-artifact integration test**

Extend a fake-client hybrid-plan test so the model returns `buy_groceries` with a
wrong band and location. Assert:

```python
accepted = DailyProposal.model_validate_json(
    (tmp_path / "run/days/2026-08-10/accepted-proposal.json").read_text(
        encoding="utf-8"
    )
)
groceries = next(item for item in accepted.activities if item.intent == "buy_groceries")
assert groceries.time_band is TimeBand.afternoon
assert groceries.location_id == "supermarket_barcelona"
artifact = json.loads(
    (
        tmp_path
        / "run/days/2026-08-10/attempt-1/habit-preference-normalizations.json"
    ).read_text(encoding="utf-8")
)
assert {item["field"] for item in artifact["changes"]} == {
    "timeBand",
    "locationId",
}
```

Run the test. Expected: fields remain wrong and the artifact is absent.

- [ ] **Step 6: Integrate preference normalization in every proposal path**

After future-goal reservation and target constraint, call:

```python
proposal, preference_changes = normalize_habit_preferences(
    behavioral_profile,
    proposal,
)
_write_json(
    attempt_dir / "habit-preference-normalizations.json",
    {"changes": preference_changes},
)
```

Apply the same sequence to initial generation, diversity repair, and habit repair.
Use the corresponding attempt directory in each branch. Validation must always happen
after normalization.

- [ ] **Step 7: Update shared test proposals to obey semantic chains**

In the `proposal(...)` helper, wrap a weekday work shift with:

```python
activity("commute_to_work", "garden_workplace", "morning", "short"),
activity("work_shift", "garden_workplace", "morning", "extended"),
activity("commute_home", "living_room_01", "afternoon", "short"),
```

The current tests assert routine presence rather than a fixed activity count, so no
expected sequence should be removed or weakened after this fixture change.

- [ ] **Step 8: Verify and commit Task 3**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_hybrid_planning.py tests/test_hybrid_guardrails.py -q
.\.venv\Scripts\python.exe -m ruff check `
  src/smart_home_sim/hybrid_planning/prompts.py `
  src/smart_home_sim/hybrid_planning/service.py `
  tests/test_hybrid_planning.py
git add src/smart_home_sim/hybrid_planning/prompts.py `
  src/smart_home_sim/hybrid_planning/service.py tests/test_hybrid_planning.py
git commit -m "feat: enforce guardrails during hybrid repair"
```

---

### Task 4: Extend longitudinal quality with mining-fidelity metrics

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/longitudinal_models.py`
- Modify: `src/smart_home_sim/hybrid_planning/longitudinal_quality.py`
- Modify: `src/smart_home_sim/hybrid_planning/habit_gates.py`
- Modify: `tests/test_longitudinal_hybrid_planning.py`

**Interfaces:**
- Produces:
  - `effective_habit_cadence(habit, on_date) -> HabitCadence`
  - `effective_habit_time_bands(habit, on_date) -> list[TimeBand]`
  - extended `LongitudinalQualityReport`.

- [ ] **Step 1: Expose effective habit fields with tests**

Add:

```python
def test_effective_habit_fields_follow_latest_drift() -> None:
    habit = valid_profile().habits[-1]
    drifted = habit.model_copy(
        update={
            "drifts": [
                HabitDrift(
                    effective_from=date(2026, 9, 1),
                    rationale="A sustained change in the synthetic routine.",
                    cadence_override=HabitCadence(
                        minimum_occurrences=0,
                        typical_occurrences=2,
                        maximum_occurrences=2,
                        period_days=30,
                    ),
                    preferred_time_bands_override=[TimeBand.evening],
                )
            ]
        }
    )
    assert effective_habit_cadence(
        drifted, date(2026, 9, 2)
    ).typical_occurrences == 2
    assert effective_habit_time_bands(
        drifted, date(2026, 9, 2)
    ) == [TimeBand.evening]
```

Run and verify import failures. Rename `_effective_cadence` to
`effective_habit_cadence`, update internal calls, and implement the time-band helper:

```python
def effective_habit_time_bands(
    habit: BehavioralHabit,
    on_date: date,
) -> list[TimeBand]:
    active = [item for item in habit.drifts if item.effective_from <= on_date]
    if not active:
        return list(habit.preferred_time_bands)
    latest = max(active, key=lambda item: item.effective_from)
    return (
        list(latest.preferred_time_bands_override)
        or list(habit.preferred_time_bands)
    )
```

- [ ] **Step 2: Add longitudinal metric contracts**

Write a failing model test, then add:

```python
class LongitudinalHabitMetric(ContractModel):
    habit_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    expected_occurrences: float = Field(ge=0)
    lower_occurrences: int = Field(ge=0)
    upper_occurrences: int = Field(ge=0)
    observed_occurrences: int = Field(ge=0)
    target_deviation: float
    temporal_adherence: float = Field(ge=0, le=1)
    location_adherence: float = Field(ge=0, le=1)
```

Extend `LongitudinalQualityReport` with defaults:

```python
mean_daily_activities: float = Field(default=0, ge=0)
minimum_daily_activities: int = Field(default=0, ge=0)
maximum_daily_activities: int = Field(default=0, ge=0)
daily_life_violations: list[QualityViolation] = Field(default_factory=list)
habit_metrics: list[LongitudinalHabitMetric] = Field(default_factory=list)
```

- [ ] **Step 3: Write failing quality tests**

Add separate tests for:

```python
def test_longitudinal_quality_rejects_sparse_daily_life() -> None:
    sparse = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Sparse Sunday",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )
    report = evaluate_longitudinal_quality(valid_profile(), [sparse])
    assert "DAILY_LIFE_VIOLATIONS" in report.reasons
    assert report.minimum_daily_activities == 3


def test_longitudinal_quality_reports_habit_frequency_and_time_deviation() -> None:
    days = guarded_month_fixture()
    days[0] = replace_habit_band(
        days[0],
        "buy_groceries",
        TimeBand.morning,
    )
    report = evaluate_longitudinal_quality(valid_profile(), days)
    groceries = next(
        item for item in report.habit_metrics if item.intent == "buy_groceries"
    )
    assert groceries.temporal_adherence < 1
    assert "HABIT_TEMPORAL_DEVIATION" in report.reasons
```

Add this exact fixture beside the tests:

```python
def guarded_month_fixture() -> list[DailyProposal]:
    start = date(2026, 8, 10)
    variable_intents = [
        "clean_kitchen",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    grocery_dates = {
        date(2026, 8, 10),
        date(2026, 8, 17),
        date(2026, 8, 24),
        date(2026, 8, 31),
        date(2026, 9, 7),
    }
    mother_dates = {
        date(2026, 8, 15),
        date(2026, 8, 23),
        date(2026, 9, 5),
    }
    result: list[DailyProposal] = []
    for offset in range(31):
        value = start + timedelta(days=offset)
        daily = proposal(
            value,
            variable_intents[offset % len(variable_intents)],
        )
        additions: list[ProposedActivity] = []
        if value in grocery_dates:
            additions.append(
                activity(
                    "buy_groceries",
                    "supermarket_barcelona",
                    "afternoon",
                )
            )
        if value.weekday() in {0, 2, 4}:
            additions.append(
                activity("read", "living_room_01", "evening", mandatory=False)
            )
        if value.weekday() in {1, 5}:
            additions.append(
                activity(
                    "evening_walk",
                    "neighborhood_park",
                    "evening",
                    mandatory=False,
                )
            )
        if value in mother_dates:
            additions.extend(
                [
                    activity(
                        "travel_to_mothers_home",
                        "mother_house_barcelona",
                        "afternoon",
                    ),
                    activity(
                        "visit_mother_and_have_dinner",
                        "mother_house_barcelona",
                        "evening",
                    ),
                    activity(
                        "travel_home",
                        "living_room_01",
                        "evening",
                    ),
                ]
            )
        daily = daily.model_copy(
            update={
                "activities": [
                    *daily.activities[:-2],
                    *additions,
                    *daily.activities[-2:],
                ]
            }
        )
        result.append(daily)
    return result


def replace_habit_band(
    proposal: DailyProposal,
    intent: str,
    band: TimeBand,
) -> DailyProposal:
    return proposal.model_copy(
        update={
            "activities": [
                item.model_copy(update={"time_band": band})
                if item.intent == intent
                else item
                for item in proposal.activities
            ]
        }
    )
```

Import `timedelta`, `ProposedActivity`, and the `proposal`/`activity` helpers at the
top of the test module. The fixture intentionally contains no medication refill.

- [ ] **Step 4: Implement accumulated metrics**

For each date, determine day type from `weekday()`. Aggregate daily-life and semantic
violations. For each habit:

```python
expected = sum(
    effective_habit_cadence(habit, proposal.date).typical_occurrences
    / effective_habit_cadence(habit, proposal.date).period_days
    for proposal in ordered
    if not habit.applicable_day_types
    or day_type(proposal.date) in habit.applicable_day_types
)
lower = math.floor(expected)
upper = math.ceil(expected)
observed = len(matched)
temporal = matching_preferred_bands / observed if observed else 1.0
location = matching_locations / observed if observed else 1.0
```

Append reasons when:

```python
observed < lower or observed > upper
temporal < 1.0
location < 1.0
```

Use these exact reason codes:

- `DAILY_LIFE_VIOLATIONS`
- `SEMANTIC_VIOLATIONS`
- `HABIT_FREQUENCY_DEVIATION`
- `HABIT_TEMPORAL_DEVIATION`
- `HABIT_LOCATION_DEVIATION`

Retain existing diversity reason codes.

- [ ] **Step 5: Update orchestrator fixtures**

Make `FakeChunkGenerator` use the deterministic dates from
`guarded_month_fixture()` that intersect the chunk planning window. Preserve the incoming
ledger update and existing resume/failure behavior. This ensures orchestrator tests pass
the same quality gate as production instead of bypassing it.

- [ ] **Step 6: Verify and commit Task 4**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_habit_gates.py tests/test_longitudinal_hybrid_planning.py -q
.\.venv\Scripts\python.exe -m ruff check `
  src/smart_home_sim/hybrid_planning/habit_gates.py `
  src/smart_home_sim/hybrid_planning/longitudinal_models.py `
  src/smart_home_sim/hybrid_planning/longitudinal_quality.py `
  tests/test_longitudinal_hybrid_planning.py
git add src/smart_home_sim/hybrid_planning/habit_gates.py `
  src/smart_home_sim/hybrid_planning/longitudinal_models.py `
  src/smart_home_sim/hybrid_planning/longitudinal_quality.py `
  tests/test_longitudinal_hybrid_planning.py
git commit -m "feat: measure longitudinal habit fidelity"
```

---

### Task 5: Add reusable A/B month comparison

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/longitudinal_analysis.py`
- Create: `tests/test_longitudinal_analysis.py`
- Modify: `src/smart_home_sim/hybrid_planning/longitudinal.py`
- Modify: `src/smart_home_sim/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `load_accepted_proposals(output_dir, records) -> list[DailyProposal]`
  - `summarize_proposals(profile, proposals) -> dict[str, object]`
  - `summarize_longitudinal_run(run_dir) -> dict[str, object]`
  - `compare_longitudinal_runs(before_dir, after_dir, baseline_path=None) -> dict[str, object]`
  - CLI command `compare-hybrid-months`.

- [ ] **Step 1: Make accepted-proposal loading reusable**

Rename `_load_accepted_proposals` to `load_accepted_proposals` in
`longitudinal.py` and update its internal call. Add a test that tampers with an
accepted-proposals file and asserts the existing digest mismatch remains enforced.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_hybrid_planning.py::test_accepted_proposal_digest_is_verified -q
```

Expected before adding the test implementation: test collection or assertion failure.

- [ ] **Step 2: Write failing summary tests**

Start `tests/test_longitudinal_analysis.py` with:

```python
from datetime import date, timedelta

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import proposal

from smart_home_sim.hybrid_planning.longitudinal_analysis import (
    compare_summaries,
    summarize_proposals,
)
```

Then add:

```python
def test_proposal_summary_measures_density_variety_and_daily_life() -> None:
    start = date(2026, 8, 10)
    intents = [
        "clean_kitchen",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
        "clean_kitchen",
    ]
    proposals = [
        proposal(start + timedelta(days=offset), intent)
        for offset, intent in enumerate(intents)
    ]

    summary = summarize_proposals(valid_profile(), proposals)
    assert summary["dayCount"] == 5
    assert summary["activityCount"] == sum(len(item.activities) for item in proposals)
    assert summary["dailyLife"]["nourishmentCoverage"] == 1.0
    assert summary["dailyLife"]["hygieneCoverage"] == 1.0
    assert summary["variety"]["distinctSignatures"] >= 4
    assert summary["habits"]["take_morning_medication"]["observed"] == 5
```

Run and verify the missing-module failure.

- [ ] **Step 3: Implement proposal summaries**

`summarize_proposals` must compute:

- dates and day count;
- total, mean, minimum, and maximum activities;
- distinct ordered signatures;
- Shannon and normalized signature entropy;
- mean consecutive Jaccard similarity;
- nourishment and hygiene day coverage;
- one entry per profile habit with observed occurrences, temporal adherence, and
  location adherence.

Use ordinary dictionaries containing JSON-compatible values. Return zero for entropy
and consecutive similarity when fewer than two days exist.

- [ ] **Step 4: Write and implement run comparison**

Test:

```python
report = compare_summaries(before, after)
assert report["delta"]["meanDailyActivities"] == pytest.approx(
    after["density"]["mean"] - before["density"]["mean"]
)
assert report["delta"]["nourishmentCoverage"] == pytest.approx(
    after["dailyLife"]["nourishmentCoverage"]
    - before["dailyLife"]["nourishmentCoverage"]
)
```

Implement `compare_longitudinal_runs` by loading each run's checkpoint and frozen
profile, verifying proposal digests through `load_accepted_proposals`, summarizing both,
and returning:

```python
{
    "documentType": "hybrid_longitudinal_comparison",
    "before": before_summary,
    "after": after_summary,
    "delta": compare_summaries(before_summary, after_summary),
    "baseline": baseline_summary_or_none,
}
```

When `baseline_path` is supplied, parse the bundle's `scenario.days` and compare only
dates shared with the guarded run. Never pass this data to generation or LM Studio.

- [ ] **Step 5: Add the CLI command test**

Monkeypatch `compare_longitudinal_runs` and assert:

```python
result = runner.invoke(
    app,
    [
        "compare-hybrid-months",
        str(before),
        str(after),
        "--output",
        str(output),
        "--baseline",
        str(baseline),
    ],
)
assert result.exit_code == 0
assert json.loads(output.read_text(encoding="utf-8"))["documentType"] == (
    "hybrid_longitudinal_comparison"
)
```

- [ ] **Step 6: Implement `compare-hybrid-months`**

Add:

```python
@app.command("compare-hybrid-months")
def compare_hybrid_months_command(
    before_dir: Path,
    after_dir: Path,
    output: Annotated[Path, typer.Option("--output")],
    baseline: Annotated[Path | None, typer.Option("--baseline")] = None,
) -> None:
    """Compare two accepted hybrid months without executing either plan."""
    try:
        report = compare_longitudinal_runs(
            before_dir,
            after_dir,
            baseline_path=baseline,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (HybridPlanningError, OSError, ValueError) as error:
        typer.echo(f"Hybrid month comparison failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Comparison written to: {output.resolve()}")
```

- [ ] **Step 7: Verify and commit Task 5**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_analysis.py `
  tests/test_longitudinal_hybrid_planning.py tests/test_cli.py -q
.\.venv\Scripts\python.exe -m ruff check `
  src/smart_home_sim/hybrid_planning/longitudinal_analysis.py `
  src/smart_home_sim/hybrid_planning/longitudinal.py `
  src/smart_home_sim/cli.py tests/test_longitudinal_analysis.py tests/test_cli.py
git add src/smart_home_sim/hybrid_planning/longitudinal_analysis.py `
  src/smart_home_sim/hybrid_planning/longitudinal.py `
  src/smart_home_sim/cli.py tests/test_longitudinal_analysis.py tests/test_cli.py
git commit -m "feat: compare guarded hybrid months"
```

---

### Task 6: Document, verify, regenerate, and compare

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Runtime create, ignored:
  `generated/hybrid-planning/tommaso-one-month-guarded-20260723/`
- Runtime create, ignored:
  `generated/hybrid-planning/tommaso-one-month-guarded-20260723/ab-comparison.json`

**Interfaces:**
- Consumes all prior tasks and the existing LM Studio endpoint.
- Produces a completed guarded month and machine-readable A/B report.

- [ ] **Step 1: Update documentation**

Document:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
.\.venv\Scripts\python.exe -m smart_home_sim.cli generate-hybrid-month `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --behavioral-profile generated/hybrid-planning/tommaso-behavioral-profile-20260722-attempt-7/behavioral-profile.json `
  --output-dir generated/hybrid-planning/tommaso-one-month-guarded-20260723 `
  --model qwen2.5-coder-7b-instruct `
  --chunk-days 7

.\.venv\Scripts\python.exe -m smart_home_sim.cli compare-hybrid-months `
  generated/hybrid-planning/tommaso-one-month-20260723 `
  generated/hybrid-planning/tommaso-one-month-guarded-20260723 `
  --baseline generated/tommaso_bianchi/tommaso_bianchi.json `
  --output generated/hybrid-planning/tommaso-one-month-guarded-20260723/ab-comparison.json
```

State explicitly that neither command executes a simulation and the baseline is read only
by the comparison command after generation.

- [ ] **Step 2: Run focused and full verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_habit_gates.py tests/test_hybrid_guardrails.py `
  tests/test_hybrid_planning.py tests/test_longitudinal_hybrid_planning.py `
  tests/test_longitudinal_analysis.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: every test and Ruff pass. If the monolithic suite exceeds the command timeout,
run the same complete four-group split previously used and sum the passing tests.

- [ ] **Step 3: Commit documentation**

```powershell
git add README.md ROADMAP.md
git commit -m "docs: describe guarded hybrid month evaluation"
```

- [ ] **Step 4: Confirm LM Studio model state**

Read `http://127.0.0.1:1234/api/v1/models`. Continue only when
`qwen2.5-coder-7b-instruct` is loaded. Do not load, eject, or retain a second model.

- [ ] **Step 5: Generate the guarded month**

Run the documented source-module command in a hidden background process with stdout and
stderr redirected to timestamped `.tmp` files. Poll under 60 seconds.

Expected final `run.json`:

```json
{
  "status": "completed",
  "executionPerformed": false,
  "baselineExposedToModel": false,
  "acceptedChunks": 5,
  "dayCount": 31
}
```

On any failure, inspect stored attempts, add a failing regression test, implement the
minimal fix, verify, commit, and resume the same guarded output. Never edit accepted
runtime artifacts by hand.

- [ ] **Step 6: Produce and inspect the A/B comparison**

Run the comparison command. Assert from `ab-comparison.json`:

- guarded nourishment coverage is `1.0`;
- guarded hygiene coverage is `1.0`;
- every habit temporal and location adherence is `1.0`;
- observed weekly habits match their accumulated target envelope;
- semantic violations are zero;
- distinct signatures remain at least 80% of accepted days;
- mean daily activities exceed the first hybrid month;
- `baselineExposedToModel` remains false.

- [ ] **Step 7: Final repository check**

```powershell
git status --short --branch
git check-ignore -v `
  generated/hybrid-planning/tommaso-one-month-guarded-20260723/run.json
```

Expected: clean tracked working tree, branch ahead of origin, guarded artifacts ignored,
and no merge.
