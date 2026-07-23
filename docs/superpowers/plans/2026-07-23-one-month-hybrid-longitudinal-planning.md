# One-Month Hybrid Longitudinal Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate, validate, compile and resume one month of weekly hybrid plans for one frozen behavioral profile without executing a simulation or exposing the comparison baseline to LM Studio.

**Architecture:** Add a plan-only longitudinal orchestrator above the existing seven-day hybrid planner. It slices one month into immutable chunks, carries bounded planning memory and the habit ledger between chunks, rejects cross-chunk repetition or causal errors, and atomically advances a checkpoint only after a chunk passes every gate.

**Tech Stack:** Python 3.13, Pydantic 2, Typer, pytest, Ruff, existing LM Studio OpenAI-compatible adapter.

## Global Constraints

- The first implementation accepts exactly one month; three- and six-month live generation remain gated by review of the one-month report.
- The frozen behavioral profile is generated once and reused unchanged in every chunk.
- The hidden baseline is never passed to the longitudinal orchestrator, prompts, repairs or planning memory.
- The feature stops after validation and compilation; it must not import or call simulation execution, environment or sensor services.
- Every chunk contains at most seven local calendar dates.
- The LLM proposes semantic activities; deterministic code owns exact timing, feasibility, quality gates and acceptance.
- Failed attempts remain diagnosable but never advance the checkpoint.
- Runtime artifacts remain under the Git-ignored `generated/hybrid-planning/` directory.
- Unit and integration tests use fake clients and temporary directories; the normal test suite never requires LM Studio.
- Coverage for the new modules is at least 95%, and repository-wide Ruff must pass.

## File map

- Modify `src/smart_home_sim/hybrid_planning/behavioral_validation.py`: allow one frozen profile to validate for later chunks of the same case.
- Modify `src/smart_home_sim/hybrid_planning/models.py`: bound planning memory and expose the contracts needed to carry it.
- Modify `src/smart_home_sim/hybrid_planning/prompts.py`: give the weekly call the bounded prior memory.
- Modify `src/smart_home_sim/hybrid_planning/service.py`: accept prior memory and return final proposals, memory and ledger.
- Create `src/smart_home_sim/hybrid_planning/longitudinal_models.py`: checkpoint, chunk record and longitudinal quality contracts.
- Create `src/smart_home_sim/hybrid_planning/longitudinal_quality.py`: cross-chunk habit-shell diversity and causal checks.
- Create `src/smart_home_sim/hybrid_planning/longitudinal.py`: month slicing, atomic checkpointing, resume validation and orchestration.
- Modify `src/smart_home_sim/hybrid_planning/__init__.py`: export the public longitudinal service.
- Modify `src/smart_home_sim/cli.py`: add the headless one-month command.
- Create `tests/test_longitudinal_hybrid_planning.py`: focused unit and service tests.
- Modify `tests/test_hybrid_planning.py`: verify memory handoff through the existing chunk planner.
- Modify `tests/test_cli.py`: verify command arguments, success and explicit failure.
- Modify `README.md`: document the plan-only command and milestone boundary.

---

### Task 1: Reuse one frozen behavioral profile across later chunks

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/behavioral_validation.py:54-76`
- Test: `tests/test_behavioral_profile.py`

**Interfaces:**
- Consumes: `PlanningCase.dates()` and `BehavioralProfile.effective_from`.
- Produces: `validate_behavioral_profile(...)` accepting `effective_from <= chunk_start` for the same `case_id`, resident and immutable facts.

- [ ] **Step 1: Write the failing later-chunk validation test**

Append this test to `tests/test_behavioral_profile.py`:

```python
def test_frozen_profile_is_valid_for_later_chunk_of_same_case() -> None:
    planning_case, catalog = _read_models(CASE)
    later_start = planning_case.planning_window.start.replace(day=17)
    later_end = planning_case.planning_window.end.replace(day=24)
    later_case = planning_case.model_copy(
        update={
            "planning_window": planning_case.planning_window.model_copy(
                update={"start": later_start, "end": later_end}
            ),
            "initial_state": planning_case.initial_state.model_copy(
                update={"at": later_start}
            ),
            "calendar": [],
        }
    )

    report = validate_behavioral_profile(later_case, catalog, valid_profile())

    assert report.valid
    assert "PROFILE_EFFECTIVE_DATE_MISMATCH" not in {
        issue.code for issue in report.issues
    }
```

Add these imports if they are not already present:

```python
from smart_home_sim.hybrid_planning.service import _read_models
```

- [ ] **Step 2: Run the test and verify the current exact-date rule fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py::test_frozen_profile_is_valid_for_later_chunk_of_same_case -v
```

Expected: `FAILED`, with `PROFILE_EFFECTIVE_DATE_MISMATCH` in the report.

- [ ] **Step 3: Relax only the effective-date comparison**

Replace the effective-date block in
`src/smart_home_sim/hybrid_planning/behavioral_validation.py` with:

```python
    chunk_start = planning_case.dates()[0]
    if profile.effective_from > chunk_start:
        issues.append(
            _issue(
                "PROFILE_EFFECTIVE_DATE_MISMATCH",
                "effectiveFrom must not be later than chunk start "
                f"{chunk_start.isoformat()}",
            )
        )
```

Do not relax `source_case_id`, resident, immutable facts, catalog or location checks.

- [ ] **Step 4: Run focused profile tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the profile reuse rule**

```powershell
git add src/smart_home_sim/hybrid_planning/behavioral_validation.py tests/test_behavioral_profile.py
git commit -m "feat: reuse frozen profile across planning chunks"
```

---

### Task 2: Carry bounded planning memory through the chunk planner

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/models.py:120-143`
- Modify: `src/smart_home_sim/hybrid_planning/prompts.py:173-230`
- Modify: `src/smart_home_sim/hybrid_planning/service.py:93-99,455-473,543-990`
- Test: `tests/test_hybrid_planning.py`

**Interfaces:**
- Consumes: `initial_memory: PlanningMemory | None` and the existing optional habit ledger.
- Produces: `HybridPlanningResult.proposals`, `.memory`, and `.habit_ledger`; `memory-checkpoint.json` includes prior history plus the accepted chunk.

- [ ] **Step 1: Write failing tests for prior memory and bounded signatures**

Add to `tests/test_hybrid_planning.py`:

```python
from smart_home_sim.hybrid_planning.models import PlanningMemory
from smart_home_sim.hybrid_planning.service import _updated_memory


def test_planning_memory_keeps_only_thirty_day_signatures() -> None:
    memory = PlanningMemory(day_signatures=[f"signature-{index}" for index in range(30)])

    updated = _updated_memory(
        memory,
        proposal(date(2026, 8, 10), "read"),
    )

    assert len(updated.day_signatures) == 30
    assert updated.day_signatures[0] == "signature-1"


def test_hybrid_plan_includes_prior_memory_in_weekly_and_daily_prompts(
    tmp_path: Path,
) -> None:
    brief, broken, _ = profile_aware_week()
    profile_path = tmp_path / "behavioral-profile.json"
    profile_path.write_text(
        valid_profile().model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    prior = PlanningMemory(
        through_date=date(2026, 8, 9),
        recent_days=[
            {
                "date": "2026-08-09",
                "narrativeIntent": "Quiet Sunday",
                "intents": ["read"],
            }
        ],
        intent_frequency={"read": 2},
        intent_last_seen={"read": date(2026, 8, 9)},
        day_signatures=["wake_up|read|sleep"],
    )
    client = FakeClient([brief, *broken])

    result = generate_hybrid_plan(
        CASE,
        tmp_path / "run",
        HybridPlanningConfig(model="fake", max_diversity_repairs=0),
        behavioral_profile_path=profile_path,
        initial_memory=prior,
        client=client,
    )

    assert "2026-08-09" in client.prompts[0]
    assert "2026-08-09" in client.prompts[1]
    assert [item.date for item in result.proposals] == [
        date.fromordinal(date(2026, 8, 10).toordinal() + offset)
        for offset in range(7)
    ]
    assert result.memory.through_date == date(2026, 8, 16)
    assert result.memory.intent_frequency["read"] >= 3
    assert result.habit_ledger is not None
```

- [ ] **Step 2: Run the two tests and verify missing interfaces**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_hybrid_planning.py::test_planning_memory_keeps_only_thirty_day_signatures tests/test_hybrid_planning.py::test_hybrid_plan_includes_prior_memory_in_weekly_and_daily_prompts -v
```

Expected: collection or call failure because `initial_memory` and result fields do not
exist, plus the signature-bound assertion fails after the interfaces are introduced but
before the cap is applied.

- [ ] **Step 3: Add memory handoff to prompts and service**

In `src/smart_home_sim/hybrid_planning/models.py`, bound the two rolling lists:

```python
class PlanningMemory(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    through_date: date | None = None
    recent_days: list[dict[str, object]] = Field(
        default_factory=list,
        max_length=14,
    )
    intent_frequency: dict[str, int] = Field(default_factory=dict)
    intent_last_seen: dict[str, date] = Field(default_factory=dict)
    day_signatures: list[str] = Field(default_factory=list, max_length=30)
```

In `src/smart_home_sim/hybrid_planning/prompts.py`, change `weekly_prompt` to:

```python
def weekly_prompt(
    planning_case: PlanningCase,
    _catalog: ActivityCatalog,
    profile: BehavioralProfile | None = None,
    budget: HabitBudget | None = None,
    memory: PlanningMemory | None = None,
) -> str:
    payload = {
        "case": _case_payload(planning_case),
        "planningMemory": (memory or PlanningMemory()).model_dump(
            mode="json",
            by_alias=True,
        ),
        **_behavioral_payload(profile, budget),
    }
    return f"""Design the narrative structure for this planning window.

Make workdays and weekends structurally different. Preserve recurring necessities, but vary
leisure, domestic, social and errand choices. Give every day at least one distinctive goal.
Use prior planning memory to avoid repeating the variable shell, while retaining profile
supported habits. Do not treat an available location or resource as evidence that an event
must happen. Do not invent named relationships that the case does not support.

The days array must contain exactly these dates in order:
{json.dumps([item.isoformat() for item in planning_case.dates()])}

Authoritative planning input:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""
```

In `src/smart_home_sim/hybrid_planning/service.py`, replace the result dataclass with:

```python
@dataclass(frozen=True, slots=True)
class HybridPlanningResult:
    output_dir: Path
    plan: CanonicalPlan
    diversity: DiversityMetrics
    comparison: dict[str, object] | None
    proposals: tuple[DailyProposal, ...]
    memory: PlanningMemory
    habit_gate: HabitGateReport | None = None
    habit_ledger: HabitLedger | None = None
```

Change `_updated_memory` so the last field is bounded:

```python
        day_signatures=[
            *memory.day_signatures,
            day_signature(proposal),
        ][-30:],
```

Change `_rebuild_memory` to:

```python
def _rebuild_memory(
    proposals: list[DailyProposal],
    initial: PlanningMemory | None = None,
) -> PlanningMemory:
    memory = initial or PlanningMemory()
    for proposal in proposals:
        memory = _updated_memory(memory, proposal)
    return memory
```

Add the keyword parameter:

```python
    initial_memory: PlanningMemory | None = None,
```

Initialize memory immediately before the weekly completion call:

```python
    memory = initial_memory or PlanningMemory()
```

Pass that `memory` to `weekly_prompt`, remove the existing reset to `PlanningMemory()` before
the daily loop, and rebuild the final memory from the initial value:

```python
            user_prompt=weekly_prompt(
                planning_case,
                catalog,
                behavioral_profile,
                budget,
                memory,
            ),

        final_memory = _rebuild_memory(proposals, initial_memory)
```

After all diversity and habit repairs, overwrite the final accepted proposal for each day:

```python
        for proposal in proposals:
            _write_json(
                output_dir / "days" / proposal.date.isoformat() / "accepted-proposal.json",
                proposal,
            )
```

Return with named arguments:

```python
        return HybridPlanningResult(
            output_dir=output_dir,
            plan=compilation.plan,
            diversity=diversity,
            comparison=comparison,
            proposals=tuple(proposals),
            memory=final_memory,
            habit_gate=habit_gate,
            habit_ledger=updated_ledger if behavioral_profile is not None else None,
        )
```

Initialize `updated_ledger: HabitLedger | None = None` beside `habit_gate` before the
`try` block.

- [ ] **Step 4: Run hybrid planner tests and Ruff**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_hybrid_planning.py tests/test_behavioral_profile.py -v
.\.venv\Scripts\python.exe -m ruff check src/smart_home_sim/hybrid_planning tests/test_hybrid_planning.py tests/test_behavioral_profile.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit bounded memory handoff**

```powershell
git add src/smart_home_sim/hybrid_planning/models.py src/smart_home_sim/hybrid_planning/prompts.py src/smart_home_sim/hybrid_planning/service.py tests/test_hybrid_planning.py
git commit -m "feat: carry bounded memory between hybrid chunks"
```

---

### Task 3: Define longitudinal contracts and deterministic month slicing

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/longitudinal_models.py`
- Create: `src/smart_home_sim/hybrid_planning/longitudinal.py`
- Create: `tests/test_longitudinal_hybrid_planning.py`

**Interfaces:**
- Produces: `LongitudinalCheckpoint`, `LongitudinalChunkRecord`,
  `LongitudinalQualityReport`, `one_month_end(...)`, and `slice_planning_case(...)`.
- Consumes: the existing `PlanningCase`, `PlanningMemory`, `HabitLedger` and
  `HybridPlanningConfig`.

- [ ] **Step 1: Write failing contract and slicing tests**

Create `tests/test_longitudinal_hybrid_planning.py` with:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path

from smart_home_sim.hybrid_planning.longitudinal import (
    one_month_end,
    slice_planning_case,
)
from smart_home_sim.hybrid_planning.service import _read_models

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"


def test_one_month_end_clamps_day_for_shorter_month() -> None:
    assert one_month_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert one_month_end(date(2028, 1, 31)) == date(2028, 2, 29)
    assert one_month_end(date(2026, 8, 10)) == date(2026, 9, 10)


def test_slice_planning_case_covers_month_without_gaps() -> None:
    planning_case, _ = _read_models(CASE)

    chunks = slice_planning_case(
        planning_case,
        end_exclusive=date(2026, 9, 10),
        chunk_days=7,
    )

    assert [len(item.dates()) for item in chunks] == [7, 7, 7, 7, 3]
    dates = [value for chunk in chunks for value in chunk.dates()]
    assert dates == [
        date.fromordinal(date(2026, 8, 10).toordinal() + offset)
        for offset in range(31)
    ]
    assert all(chunk.case_id == planning_case.case_id for chunk in chunks)
    assert all(chunk.initial_state.at == chunk.planning_window.start for chunk in chunks)
```

- [ ] **Step 2: Run slicing tests and verify imports fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -v
```

Expected: collection fails because the longitudinal modules do not exist.

- [ ] **Step 3: Add the longitudinal contracts**

Create `src/smart_home_sim/hybrid_planning/longitudinal_models.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.hybrid_planning.behavioral_models import HabitLedger
from smart_home_sim.hybrid_planning.models import PlanningMemory


class CausalViolation(ContractModel):
    code: str = Field(min_length=1)
    date: date
    intent: str = Field(min_length=1)
    message: str = Field(min_length=1)


class LongitudinalQualityReport(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["longitudinal_planning_quality"] = (
        "longitudinal_planning_quality"
    )
    valid: bool
    day_count: int = Field(ge=0)
    maximum_consecutive_identical_days: int = Field(ge=0)
    optional_windows_without_variation: list[date] = Field(default_factory=list)
    causal_violations: list[CausalViolation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class LongitudinalChunkRecord(ContractModel):
    index: int = Field(ge=1)
    start_date: date
    end_date_exclusive: date
    artifact_path: str = Field(min_length=1)
    canonical_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_proposals_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LongitudinalCheckpoint(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["hybrid_longitudinal_checkpoint"] = (
        "hybrid_longitudinal_checkpoint"
    )
    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_date: date
    end_date_exclusive: date
    next_date: date
    chunks: list[LongitudinalChunkRecord] = Field(default_factory=list)
    planning_memory: PlanningMemory
    habit_ledger: HabitLedger
```

- [ ] **Step 4: Add exact month and chunk slicing**

Create the initial `src/smart_home_sim/hybrid_planning/longitudinal.py`:

```python
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import SimulationWindow
from smart_home_sim.hybrid_planning.models import PlanningCase


def one_month_end(start: date) -> date:
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def slice_planning_case(
    base: PlanningCase,
    *,
    end_exclusive: date,
    chunk_days: int,
) -> list[PlanningCase]:
    if not 1 <= chunk_days <= 7:
        raise ValueError("chunk_days must be between 1 and 7")
    start = base.dates()[0]
    if end_exclusive <= start:
        raise ValueError("end_exclusive must be after planning start")
    zone = ZoneInfo(base.time_zone)
    chunks: list[PlanningCase] = []
    current = start
    while current < end_exclusive:
        chunk_end = min(current + timedelta(days=chunk_days), end_exclusive)
        start_at = datetime.combine(current, time.min, tzinfo=zone)
        end_at = datetime.combine(chunk_end, time.min, tzinfo=zone)
        calendar = [
            item for item in base.calendar if current <= item.date < chunk_end
        ]
        chunks.append(
            base.model_copy(
                update={
                    "planning_window": SimulationWindow(
                        start=start_at,
                        end=end_at,
                    ),
                    "initial_state": base.initial_state.model_copy(
                        update={"at": start_at}
                    ),
                    "calendar": calendar,
                }
            )
        )
        current = chunk_end
    return chunks
```

- [ ] **Step 5: Run tests, lint and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -v
.\.venv\Scripts\python.exe -m ruff check src/smart_home_sim/hybrid_planning/longitudinal.py src/smart_home_sim/hybrid_planning/longitudinal_models.py tests/test_longitudinal_hybrid_planning.py
```

Expected: all tests pass and Ruff reports no errors.

Commit:

```powershell
git add src/smart_home_sim/hybrid_planning/longitudinal.py src/smart_home_sim/hybrid_planning/longitudinal_models.py tests/test_longitudinal_hybrid_planning.py
git commit -m "feat: define one-month planning chunks"
```

---

### Task 4: Add cross-chunk behavioral and causal quality gates

**Files:**
- Create: `src/smart_home_sim/hybrid_planning/longitudinal_quality.py`
- Modify: `tests/test_longitudinal_hybrid_planning.py`

**Interfaces:**
- Consumes: a frozen `BehavioralProfile` and accepted `DailyProposal` values in date order.
- Produces: `evaluate_longitudinal_quality(...) -> LongitudinalQualityReport`.

- [ ] **Step 1: Write failing quality tests**

Append to `tests/test_longitudinal_hybrid_planning.py`:

```python
from test_behavioral_profile import valid_profile
from test_hybrid_planning import activity, proposal

from smart_home_sim.hybrid_planning.longitudinal_quality import (
    evaluate_longitudinal_quality,
)


def test_longitudinal_quality_rejects_four_identical_consecutive_days() -> None:
    days = [
        proposal(
            date.fromordinal(date(2026, 8, 10).toordinal() + offset),
            "read",
        )
        for offset in range(4)
    ]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert not report.valid
    assert report.maximum_consecutive_identical_days == 4
    assert "CONSECUTIVE_DUPLICATE_DAYS" in report.reasons


def test_longitudinal_quality_rejects_commute_without_work_shift() -> None:
    day = proposal(date(2026, 8, 16), "read")
    bad = day.model_copy(
        update={
            "activities": [
                *day.activities[:-2],
                activity(
                    "commute_to_work",
                    "garden_workplace",
                    "afternoon",
                    mandatory=False,
                ),
                *day.activities[-2:],
            ]
        }
    )

    report = evaluate_longitudinal_quality(valid_profile(), [bad])

    assert not report.valid
    assert {item.code for item in report.causal_violations} == {
        "WORK_TRAVEL_WITHOUT_SHIFT"
    }


def test_longitudinal_quality_accepts_habit_skeleton_with_variable_shell() -> None:
    intents = [
        "read",
        "evening_walk",
        "clean_kitchen",
        "buy_groceries",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    days = [
        proposal(
            date.fromordinal(date(2026, 8, 10).toordinal() + offset),
            intent,
        )
        for offset, intent in enumerate(intents)
    ]

    report = evaluate_longitudinal_quality(valid_profile(), days)

    assert report.valid
    assert report.optional_windows_without_variation == []
```

- [ ] **Step 2: Run quality tests and verify the module is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -k "longitudinal_quality" -v
```

Expected: collection fails because `longitudinal_quality` does not exist.

- [ ] **Step 3: Implement deterministic longitudinal quality**

Create `src/smart_home_sim/hybrid_planning/longitudinal_quality.py`:

```python
from __future__ import annotations

from datetime import date

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitKind,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    CausalViolation,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.metrics import day_signature
from smart_home_sim.hybrid_planning.models import DailyProposal

WORK_TRAVEL_INTENTS = {"commute_to_work", "travel_to_work"}


def _maximum_identical_run(proposals: list[DailyProposal]) -> int:
    maximum = 0
    current = 0
    previous: str | None = None
    for proposal in proposals:
        signature = day_signature(proposal)
        current = current + 1 if signature == previous else 1
        maximum = max(maximum, current)
        previous = signature
    return maximum


def _causal_violations(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> list[CausalViolation]:
    habits = {item.intent: item for item in profile.habits}
    violations: list[CausalViolation] = []
    for proposal in proposals:
        intents = [item.intent for item in proposal.activities]
        for position, intent in enumerate(intents):
            if intent in WORK_TRAVEL_INTENTS and "work_shift" not in intents[position + 1 :]:
                violations.append(
                    CausalViolation(
                        code="WORK_TRAVEL_WITHOUT_SHIFT",
                        date=proposal.date,
                        intent=intent,
                        message="outbound work travel requires a later work_shift",
                    )
                )
            habit = habits.get(intent)
            if habit is None:
                continue
            missing_predecessors = [
                required
                for required in habit.predecessor_intents
                if required not in intents[:position]
            ]
            missing_successors = [
                required
                for required in habit.successor_intents
                if required not in intents[position + 1 :]
            ]
            for required in missing_predecessors:
                violations.append(
                    CausalViolation(
                        code="MISSING_HABIT_PREDECESSOR",
                        date=proposal.date,
                        intent=intent,
                        message=f"{intent} requires earlier {required}",
                    )
                )
            for required in missing_successors:
                violations.append(
                    CausalViolation(
                        code="MISSING_HABIT_SUCCESSOR",
                        date=proposal.date,
                        intent=intent,
                        message=f"{intent} requires later {required}",
                    )
                )
    return violations


def _empty_variable_windows(
    proposals: list[DailyProposal],
    variable_intents: set[str],
) -> list[date]:
    empty: list[date] = []
    for start in range(0, len(proposals) - 6, 7):
        window = proposals[start : start + 7]
        has_variation = any(
            activity.intent in variable_intents
            for proposal in window
            for activity in proposal.activities
        )
        if not has_variation:
            empty.append(window[0].date)
    return empty


def evaluate_longitudinal_quality(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> LongitudinalQualityReport:
    ordered = sorted(proposals, key=lambda item: item.date)
    variable_intents = {
        item.intent
        for item in profile.habits
        if item.kind in {HabitKind.optional, HabitKind.rare}
    }
    empty_windows = _empty_variable_windows(ordered, variable_intents)
    maximum_run = _maximum_identical_run(ordered)
    causal = _causal_violations(profile, ordered)
    reasons: list[str] = []
    if maximum_run > 3:
        reasons.append("CONSECUTIVE_DUPLICATE_DAYS")
    if empty_windows:
        reasons.append("MISSING_WEEKLY_VARIABLE_SHELL")
    if causal:
        reasons.append("CAUSAL_VIOLATIONS")
    return LongitudinalQualityReport(
        valid=not reasons,
        day_count=len(ordered),
        maximum_consecutive_identical_days=maximum_run,
        optional_windows_without_variation=empty_windows,
        causal_violations=causal,
        reasons=reasons,
    )
```

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -k "longitudinal_quality" -v
.\.venv\Scripts\python.exe -m ruff check src/smart_home_sim/hybrid_planning/longitudinal_quality.py tests/test_longitudinal_hybrid_planning.py
```

Expected: three quality tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the cross-chunk gates**

```powershell
git add src/smart_home_sim/hybrid_planning/longitudinal_quality.py src/smart_home_sim/hybrid_planning/longitudinal_models.py tests/test_longitudinal_hybrid_planning.py
git commit -m "feat: gate longitudinal behavioral quality"
```

---

### Task 5: Implement atomic one-month orchestration and resume

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/longitudinal.py`
- Modify: `tests/test_longitudinal_hybrid_planning.py`

**Interfaces:**
- Produces:
  `generate_one_month_plan(case_path, profile_path, output_dir, config, resume=False, client=None) -> LongitudinalPlanningResult`.
- Calls: `generate_hybrid_plan(...)` once per unfinished chunk.
- Persists: `run.json`, `checkpoint.json`, `profile-snapshot.json`,
  `behavioral-profile-snapshot.json`, and immutable `chunks/<start>/attempt-NNN/`.

- [ ] **Step 1: Write failing atomicity and resume service tests**

Extend the imports in `tests/test_longitudinal_hybrid_planning.py` with:

```python
import json
from types import SimpleNamespace
from typing import Any

import pytest

from smart_home_sim.hybrid_planning.behavioral_models import HabitLedger
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.habit_gates import update_habit_ledger
from smart_home_sim.hybrid_planning.longitudinal import generate_one_month_plan
from smart_home_sim.hybrid_planning.longitudinal_models import (
    LongitudinalCheckpoint,
)
from smart_home_sim.hybrid_planning.models import (
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
)
from smart_home_sim.hybrid_planning.service import (
    HybridPlanningError,
    _rebuild_memory,
)
```

Add this complete fake chunk generator and fixture:

```python
VARIABLE_INTENTS = [
    "read",
    "evening_walk",
    "clean_kitchen",
    "buy_groceries",
    "watch_documentary",
    "start_laundry",
    "weekly_meal_preparation",
]


class FakeChunkGenerator:
    def __init__(self) -> None:
        self.call_count = 0
        self.fail_on_call: int | None = None
        self.repeat_every_day = False
        self.chunk_starts: list[date] = []

    def __call__(
        self,
        case_path: Path,
        output_dir: Path,
        _config: HybridPlanningConfig,
        *,
        behavioral_profile_path: Path,
        ledger_path: Path | None,
        initial_memory: PlanningMemory,
        client: Any,
    ) -> SimpleNamespace:
        del client
        self.call_count += 1
        planning_case = PlanningCase.model_validate_json(
            case_path.read_text(encoding="utf-8")
        )
        self.chunk_starts.append(planning_case.dates()[0])
        if self.call_count == self.fail_on_call:
            raise HybridPlanningError("synthetic chunk failure")
        profile = valid_profile()
        assert behavioral_profile_digest(profile) == behavioral_profile_digest(
            type(profile).model_validate_json(
                behavioral_profile_path.read_text(encoding="utf-8")
            )
        )
        if ledger_path is None:
            raise AssertionError("longitudinal chunks require a habit ledger")
        ledger = HabitLedger.model_validate_json(
            ledger_path.read_text(encoding="utf-8")
        )
        proposals = [
            proposal(
                value,
                "read"
                if self.repeat_every_day
                else VARIABLE_INTENTS[
                    (value.toordinal() - date(2026, 8, 10).toordinal())
                    % len(VARIABLE_INTENTS)
                ],
            )
            for value in planning_case.dates()
        ]
        output_dir.mkdir(parents=True)
        (output_dir / "canonical-plan.json").write_text(
            '{"documentType":"canonical_plan"}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            proposals=tuple(proposals),
            memory=_rebuild_memory(proposals, initial_memory),
            habit_ledger=update_habit_ledger(
                profile,
                behavioral_profile_digest(profile),
                ledger,
                proposals,
            ),
        )


@pytest.fixture
def fake_chunk_generator(tmp_path: Path) -> FakeChunkGenerator:
    (tmp_path / "profile.json").write_text(
        valid_profile().model_dump_json(indent=2, by_alias=True) + "\n",
        encoding="utf-8",
    )
    return FakeChunkGenerator()
```

Then add:

```python
def test_one_month_orchestrator_accepts_five_chunks_and_completes(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    result = generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        chunk_generator=fake_chunk_generator,
    )

    assert result.checkpoint.next_date == date(2026, 9, 10)
    assert len(result.checkpoint.chunks) == 5
    assert result.quality.valid
    manifest = json.loads((tmp_path / "month/run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["executionPerformed"] is False
    assert manifest["baselineExposedToModel"] is False


def test_resume_skips_accepted_chunks(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    fake_chunk_generator.fail_on_call = 3
    with pytest.raises(HybridPlanningError, match="synthetic chunk failure"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake"),
            chunk_generator=fake_chunk_generator,
        )
    assert len(
        LongitudinalCheckpoint.model_validate_json(
            (tmp_path / "month/checkpoint.json").read_text(encoding="utf-8")
        ).chunks
    ) == 2

    fake_chunk_generator.fail_on_call = None
    generate_one_month_plan(
        CASE,
        tmp_path / "profile.json",
        tmp_path / "month",
        HybridPlanningConfig(model="fake"),
        resume=True,
        chunk_generator=fake_chunk_generator,
    )

    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 10)) == 1
    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 17)) == 1
    assert fake_chunk_generator.chunk_starts.count(date(2026, 8, 24)) == 2


def test_failed_quality_does_not_advance_checkpoint(
    tmp_path: Path,
    fake_chunk_generator: FakeChunkGenerator,
) -> None:
    fake_chunk_generator.repeat_every_day = True

    with pytest.raises(HybridPlanningError, match="longitudinal quality"):
        generate_one_month_plan(
            CASE,
            tmp_path / "profile.json",
            tmp_path / "month",
            HybridPlanningConfig(model="fake"),
            chunk_generator=fake_chunk_generator,
        )

    checkpoint = LongitudinalCheckpoint.model_validate_json(
        (tmp_path / "month/checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint.next_date < date(2026, 9, 10)
    assert len(checkpoint.chunks) < 5
```

- [ ] **Step 2: Run orchestration tests and verify the public service is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -k "orchestrator or resume or failed_quality" -v
```

Expected: collection or import failure because `generate_one_month_plan` and its result do
not exist.

- [ ] **Step 3: Add hashing, atomic writes and resume validation**

In `src/smart_home_sim/hybrid_planning/longitudinal.py`, add:

```python
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic_core import to_jsonable_python

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitLedger,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    LongitudinalCheckpoint,
    LongitudinalChunkRecord,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.longitudinal_quality import (
    evaluate_longitudinal_quality,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    HybridPlanningConfig,
    PlanningMemory,
)
from smart_home_sim.hybrid_planning.service import (
    CompletionClient,
    HybridPlanningError,
    HybridPlanningResult,
    _read_models,
    generate_hybrid_plan,
)


class ChunkGenerator(Protocol):
    def __call__(
        self,
        case_path: Path,
        output_dir: Path,
        config: HybridPlanningConfig,
        *,
        behavioral_profile_path: Path,
        ledger_path: Path | None,
        initial_memory: PlanningMemory,
        client: CompletionClient | None,
    ) -> HybridPlanningResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class LongitudinalPlanningResult:
    output_dir: Path
    checkpoint: LongitudinalCheckpoint
    quality: LongitudinalQualityReport


def _canonical_json(value: object) -> str:
    return json.dumps(
        to_jsonable_python(value, by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            to_jsonable_python(value, by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)
```

The configuration fingerprint must be:

```python
def _configuration_digest(
    case_id: str,
    resident_id: str,
    profile_digest: str,
    start_date: date,
    end_date: date,
    chunk_days: int,
    config: HybridPlanningConfig,
) -> str:
    return _digest(
        {
            "caseId": case_id,
            "residentId": resident_id,
            "profileDigest": profile_digest,
            "startDate": start_date.isoformat(),
            "endDateExclusive": end_date.isoformat(),
            "chunkDays": chunk_days,
            "llm": config.model_dump(mode="json", by_alias=True),
        }
    )
```

On resume, parse `checkpoint.json` and reject mismatched `configuration_digest`,
`profile_digest`, case or resident before creating a new chunk attempt.

- [ ] **Step 4: Implement the one-month loop**

Add `generate_one_month_plan` with this exact control flow:

```python
def generate_one_month_plan(
    case_path: Path,
    behavioral_profile_path: Path,
    output_dir: Path,
    config: HybridPlanningConfig,
    *,
    chunk_days: int = 7,
    resume: bool = False,
    client: CompletionClient | None = None,
    chunk_generator: ChunkGenerator = generate_hybrid_plan,
) -> LongitudinalPlanningResult:
    base, _ = _read_models(case_path)
    profile = BehavioralProfile.model_validate_json(
        behavioral_profile_path.read_text(encoding="utf-8")
    )
    profile_digest = behavioral_profile_digest(profile)
    start = base.dates()[0]
    end = one_month_end(start)
    chunks = slice_planning_case(base, end_exclusive=end, chunk_days=chunk_days)
    configuration_digest = _configuration_digest(
        base.case_id,
        base.resident.resident_id,
        profile_digest,
        start,
        end,
        chunk_days,
        config,
    )
    checkpoint_path = output_dir / "checkpoint.json"
    if resume:
        if not checkpoint_path.is_file():
            raise HybridPlanningError("resume requires checkpoint.json")
        checkpoint = LongitudinalCheckpoint.model_validate_json(
            checkpoint_path.read_text(encoding="utf-8")
        )
        identity = (
            checkpoint.configuration_digest,
            checkpoint.profile_digest,
            checkpoint.case_id,
            checkpoint.resident_id,
        )
        expected = (
            configuration_digest,
            profile_digest,
            base.case_id,
            base.resident.resident_id,
        )
        if identity != expected:
            raise HybridPlanningError("resume checkpoint identity mismatch")
    else:
        if output_dir.exists():
            raise HybridPlanningError(f"output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True)
        (output_dir / "profile-snapshot.json").write_text(
            base.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        snapshot = output_dir / "behavioral-profile-snapshot.json"
        snapshot.write_text(
            profile.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        initial_ledger = initial_habit_ledger(profile_digest, profile)
        checkpoint = LongitudinalCheckpoint(
            run_id=output_dir.name,
            case_id=base.case_id,
            resident_id=base.resident.resident_id,
            profile_digest=profile_digest,
            configuration_digest=configuration_digest,
            start_date=start,
            end_date_exclusive=end,
            next_date=start,
            planning_memory=PlanningMemory(),
            habit_ledger=initial_ledger,
        )
        _atomic_json(checkpoint_path, checkpoint)

    manifest = {
        "documentType": "hybrid_longitudinal_run",
        "runVersion": "0.1.0",
        "status": "running",
        "caseId": base.case_id,
        "residentId": base.resident.resident_id,
        "profileDigest": profile_digest,
        "startDate": start.isoformat(),
        "endDateExclusive": end.isoformat(),
        "chunkDays": chunk_days,
        "executionPerformed": False,
        "baselineExposedToModel": False,
    }
    _atomic_json(output_dir / "run.json", manifest)
    accepted = _load_accepted_proposals(output_dir, checkpoint.chunks)
    try:
        for index, chunk in enumerate(chunks, start=1):
            chunk_start = chunk.dates()[0]
            if chunk_start < checkpoint.next_date:
                continue
            chunk_root = output_dir / "chunks" / chunk_start.isoformat()
            attempt_number = len(list(chunk_root.glob("attempt-*"))) + 1
            attempt = chunk_root / f"attempt-{attempt_number:03d}"
            attempt.mkdir(parents=True)
            chunk_case_path = attempt / "planning-case.json"
            chunk_case_path.write_text(
                chunk.model_dump_json(indent=2, by_alias=True) + "\n",
                encoding="utf-8",
            )
            ledger_path = attempt / "habit-ledger-input.json"
            ledger_path.write_text(
                checkpoint.habit_ledger.model_dump_json(indent=2, by_alias=True)
                + "\n",
                encoding="utf-8",
            )
            result = chunk_generator(
                chunk_case_path,
                attempt / "planning",
                config,
                behavioral_profile_path=behavioral_profile_path,
                ledger_path=ledger_path,
                initial_memory=checkpoint.planning_memory,
                client=client,
            )
            candidate = [*accepted, *result.proposals]
            quality = evaluate_longitudinal_quality(profile, candidate)
            _atomic_json(attempt / "longitudinal-quality.json", quality)
            if not quality.valid:
                raise HybridPlanningError(
                    "longitudinal quality gate failed: "
                    + ", ".join(quality.reasons)
                )
            proposals_path = attempt / "accepted-proposals.json"
            _atomic_json(proposals_path, list(result.proposals))
            relative = attempt.relative_to(output_dir).as_posix()
            record = LongitudinalChunkRecord(
                index=index,
                start_date=chunk_start,
                end_date_exclusive=chunk.dates()[-1] + timedelta(days=1),
                artifact_path=relative,
                canonical_plan_sha256=_file_digest(
                    attempt / "planning" / "canonical-plan.json"
                ),
                accepted_proposals_sha256=_file_digest(proposals_path),
            )
            if result.habit_ledger is None:
                raise HybridPlanningError("accepted chunk did not return a habit ledger")
            checkpoint = checkpoint.model_copy(
                update={
                    "next_date": record.end_date_exclusive,
                    "chunks": [*checkpoint.chunks, record],
                    "planning_memory": result.memory,
                    "habit_ledger": result.habit_ledger,
                }
            )
            _atomic_json(checkpoint_path, checkpoint)
            accepted = candidate
        quality = evaluate_longitudinal_quality(profile, accepted)
        if checkpoint.next_date != end or not quality.valid:
            raise HybridPlanningError("one-month plan is incomplete or failed quality")
        _atomic_json(output_dir / "quality-report.json", quality)
        manifest["status"] = "completed"
        manifest["acceptedChunks"] = len(checkpoint.chunks)
        manifest["dayCount"] = quality.day_count
        _atomic_json(output_dir / "run.json", manifest)
        return LongitudinalPlanningResult(output_dir, checkpoint, quality)
    except (OSError, ValueError, HybridPlanningError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        _atomic_json(output_dir / "run.json", manifest)
        if isinstance(error, HybridPlanningError):
            raise
        raise HybridPlanningError(str(error)) from error
```

Also import:

```python
from pydantic import TypeAdapter, ValidationError

from smart_home_sim.hybrid_planning.habit_gates import initial_habit_ledger
```

Add the loader:

```python
PROPOSAL_LIST = TypeAdapter(list[DailyProposal])


def _load_accepted_proposals(
    output_dir: Path,
    records: list[LongitudinalChunkRecord],
) -> list[DailyProposal]:
    proposals: list[DailyProposal] = []
    try:
        for record in records:
            path = (
                output_dir
                / record.artifact_path
                / "accepted-proposals.json"
            )
            if _file_digest(path) != record.accepted_proposals_sha256:
                raise HybridPlanningError(
                    f"accepted proposal digest mismatch: {path}"
                )
            proposals.extend(
                PROPOSAL_LIST.validate_json(path.read_text(encoding="utf-8"))
            )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise HybridPlanningError(
            f"cannot restore accepted proposals: {error}"
        ) from error
    proposals.sort(key=lambda item: item.date)
    dates = [item.date for item in proposals]
    if len(dates) != len(set(dates)):
        raise HybridPlanningError("accepted proposals contain duplicate dates")
    if dates and dates != [
        date.fromordinal(dates[0].toordinal() + offset)
        for offset in range(len(dates))
    ]:
        raise HybridPlanningError("accepted proposals contain a date gap")
    return proposals
```

- [ ] **Step 5: Run service tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_longitudinal_hybrid_planning.py -v
.\.venv\Scripts\python.exe -m ruff check src/smart_home_sim/hybrid_planning tests/test_longitudinal_hybrid_planning.py
```

Expected: all longitudinal tests pass and Ruff reports no errors.

Commit:

```powershell
git add src/smart_home_sim/hybrid_planning/longitudinal.py tests/test_longitudinal_hybrid_planning.py
git commit -m "feat: orchestrate resumable one-month plans"
```

---

### Task 6: Expose the one-month planner through the CLI

**Files:**
- Modify: `src/smart_home_sim/hybrid_planning/__init__.py`
- Modify: `src/smart_home_sim/cli.py:65-70,135-205`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces command:
  `smart-home-sim generate-hybrid-month CASE --behavioral-profile PROFILE --output-dir DIR`.
- Options: `--model`, `--base-url`, `--temperature`, `--chunk-days`, `--resume`.

- [ ] **Step 1: Write failing CLI success and failure tests**

Append to `tests/test_cli.py`:

```python
def test_generate_hybrid_month_reports_completed_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "month"
    checkpoint = SimpleNamespace(chunks=[object()] * 5)
    quality = SimpleNamespace(day_count=31)
    received: dict[str, object] = {}

    def fake_generate(*args: object, **kwargs: object) -> SimpleNamespace:
        received["args"] = args
        received.update(kwargs)
        return SimpleNamespace(
            output_dir=output,
            checkpoint=checkpoint,
            quality=quality,
        )

    monkeypatch.setattr(
        "smart_home_sim.cli.generate_one_month_plan",
        fake_generate,
    )
    result = runner.invoke(
        app,
        [
            "generate-hybrid-month",
            "case.json",
            "--behavioral-profile",
            "profile.json",
            "--output-dir",
            str(output),
            "--model",
            "local-model",
            "--chunk-days",
            "7",
        ],
    )

    assert result.exit_code == 0
    assert "31 days accepted in 5 chunks" in result.stdout
    assert "simulation was not executed" in result.stdout
    assert received["chunk_days"] == 7


def test_generate_hybrid_month_reports_explicit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise HybridPlanningError("checkpoint identity mismatch")

    monkeypatch.setattr("smart_home_sim.cli.generate_one_month_plan", fail)
    result = runner.invoke(
        app,
        [
            "generate-hybrid-month",
            "case.json",
            "--behavioral-profile",
            "profile.json",
            "--output-dir",
            str(tmp_path / "month"),
        ],
    )

    assert result.exit_code == 1
    assert "checkpoint identity mismatch" in result.stderr
```

- [ ] **Step 2: Run CLI tests and verify the command is absent**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_cli.py -k "generate_hybrid_month" -v
```

Expected: both tests fail because the command and imported function do not exist.

- [ ] **Step 3: Export the service and add the command**

In `src/smart_home_sim/hybrid_planning/__init__.py`, import and export:

```python
from smart_home_sim.hybrid_planning.longitudinal import (
    LongitudinalPlanningResult,
    generate_one_month_plan,
)
```

Replace `__all__` with:

```python
__all__ = [
    "BehavioralProfileResult",
    "HybridPlanningError",
    "HybridPlanningResult",
    "LongitudinalPlanningResult",
    "generate_behavioral_profile",
    "generate_hybrid_plan",
    "generate_one_month_plan",
]
```

In `src/smart_home_sim/cli.py`, import `generate_one_month_plan` from
`smart_home_sim.hybrid_planning` and add:

```python
@app.command("generate-hybrid-month")
def generate_hybrid_month_command(
    case_path: Path,
    output_dir: Annotated[Path, typer.Option("--output-dir")],
    behavioral_profile: Annotated[Path, typer.Option("--behavioral-profile")],
    model: Annotated[str, typer.Option("--model")] = "qwen2.5-coder-7b-instruct",
    base_url: Annotated[str, typer.Option("--base-url")] = "http://127.0.0.1:1234",
    temperature: Annotated[float, typer.Option("--temperature")] = 0.65,
    chunk_days: Annotated[int, typer.Option("--chunk-days", min=1, max=7)] = 7,
    resume: Annotated[bool, typer.Option("--resume")] = False,
) -> None:
    """Generate one month of validated plans without simulation execution."""
    try:
        result = generate_one_month_plan(
            case_path,
            behavioral_profile,
            output_dir,
            HybridPlanningConfig(
                model=model,
                base_url=base_url,
                temperature=temperature,
            ),
            chunk_days=chunk_days,
            resume=resume,
        )
    except (HybridPlanningError, ValueError) as error:
        typer.echo(f"Hybrid month generation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        f"{result.quality.day_count} days accepted in "
        f"{len(result.checkpoint.chunks)} chunks"
    )
    typer.echo(f"Longitudinal plan written to: {result.output_dir.resolve()}")
    typer.echo("Planning and compilation completed; simulation was not executed")
```

- [ ] **Step 4: Run CLI and hybrid tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_cli.py tests/test_hybrid_planning.py tests/test_longitudinal_hybrid_planning.py -v
.\.venv\Scripts\python.exe -m ruff check src/smart_home_sim/cli.py src/smart_home_sim/hybrid_planning tests/test_cli.py tests/test_longitudinal_hybrid_planning.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the command**

```powershell
git add src/smart_home_sim/hybrid_planning/__init__.py src/smart_home_sim/cli.py tests/test_cli.py
git commit -m "feat: expose one-month hybrid planning command"
```

---

### Task 7: Document, verify and prepare the live one-month gate

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `docs/plans/2026-07-23-hybrid-longitudinal-milestones-design.md` only if implementation details differ from the approved design.

**Interfaces:**
- Documents the exact local command, output hierarchy, resume behavior and plan-only
  boundary.
- Produces no generated runtime artifact in Git.

- [ ] **Step 1: Add the command and output contract to README**

Add a “One-month hybrid planning” subsection showing:

```powershell
.\.venv\Scripts\smart-home-sim.exe generate-hybrid-month `
  examples/hybrid/tommaso_bianchi_week.planning-case.json `
  --behavioral-profile generated/hybrid-planning/tommaso-behavioral-profile-20260722-attempt-7/behavioral-profile.json `
  --output-dir generated/hybrid-planning/tommaso-one-month-20260723 `
  --model qwen2.5-coder-7b-instruct `
  --chunk-days 7
```

Document resume with the identical arguments plus `--resume`. State explicitly that:

- the command writes plans, validation reports, compilation reports and checkpoints;
- it does not execute simulation or generate sensor data;
- `generated/hybrid-planning/` is intentionally ignored by Git;
- the Tommaso baseline is not an input to this command.

- [ ] **Step 2: Update the roadmap status without declaring Milestone 8.1 complete**

Change the Milestone 8.1 status row from `Pianificata` to
`In corso — prototipo settimanale accettato, pilot mensile da validare`.

Under Milestone 8.1, add a short progress note listing:

- accepted seven-day vertical slice;
- frozen detailed behavioral profile;
- one-month resumable gate implemented;
- three- and six-month gates still blocked on the monthly evaluation.

- [ ] **Step 3: Run the complete automated verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: 491 existing tests plus the new tests pass, with no failures, and Ruff reports no
errors. If the monolithic test command exceeds the local ten-minute process limit, run the
same established test chunks used for the branch verification and record each passing
count in the milestone report.

- [ ] **Step 4: Measure focused coverage**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_behavioral_profile.py tests/test_hybrid_planning.py tests/test_longitudinal_hybrid_planning.py tests/test_cli.py --cov=src/smart_home_sim/hybrid_planning --cov-report=term-missing --cov-fail-under=95
```

Expected: selected tests pass and hybrid-planning coverage is at least 95%.

- [ ] **Step 5: Commit documentation and stop before live generation**

```powershell
git add README.md ROADMAP.md docs/plans/2026-07-23-hybrid-longitudinal-milestones-design.md
git commit -m "docs: prepare one-month hybrid planning pilot"
```

Do not start LM Studio generation in this task. Review automated results and the exact
one-month input/calendar first. The live pilot is a separately approved operation because
it can consume substantial local compute time.

---

## Self-review

- **Spec coverage:** Profile reuse is Task 1; bounded context is Task 2; chunking and
  contracts are Task 3; behavioral originality and causal coherence are Task 4; atomic
  resume and failure isolation are Task 5; headless operation is Task 6; documentation,
  coverage and the live-run gate are Task 7.
- **Boundary coverage:** No task imports simulation execution, environment or sensor
  services. The baseline is absent from every public longitudinal interface.
- **Milestone discipline:** The implementation stops at one month. Three and six months
  remain design milestones and require separate plans after empirical review.
- **Artifact discipline:** Tests use temporary paths, and live outputs remain below the
  Git-ignored `generated/hybrid-planning/` directory.
- **Type consistency:** `PlanningMemory`, `HabitLedger`, `LongitudinalCheckpoint`,
  `LongitudinalQualityReport` and `HybridPlanningResult` use the same field names in
  producers and consumers throughout the tasks.
