from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_behavioral_profile import valid_profile
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.hybrid_planning.behavioral_models import HabitLedger
from smart_home_sim.hybrid_planning.behavioral_validation import behavioral_profile_digest
from smart_home_sim.hybrid_planning.comparison import compare_scenarios
from smart_home_sim.hybrid_planning.habit_gates import derive_habit_budget, initial_habit_ledger
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioError, LMStudioExchange
from smart_home_sim.hybrid_planning.materialization import materialize_scenario
from smart_home_sim.hybrid_planning.metrics import diversity_metrics, most_repetitive_day_index
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DurationClass,
    HybridPlanningConfig,
    PlanningCase,
    PlanningMemory,
    ProposedActivity,
    TimeBand,
    WeeklyBrief,
    WeeklyDayBrief,
)
from smart_home_sim.hybrid_planning.prompts import structural_repair_prompt
from smart_home_sim.hybrid_planning.service import (
    HybridPlanningError,
    _canonicalize_daily_anchors,
    _canonicalize_weekly_goals,
    _read_models,
    _reserve_future_weekly_goals,
    _updated_memory,
    _validate_daily_proposal,
    _weekly_schema,
    generate_hybrid_plan,
)

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"
BASELINE = ROOT / "generated/tommaso_bianchi/tommaso_bianchi.json"
runner = CliRunner()


def activity(
    intent: str,
    location: str,
    band: str,
    duration: str = "short",
    *,
    mandatory: bool = True,
) -> ProposedActivity:
    return ProposedActivity(
        intent=intent,
        location_id=location,
        time_band=TimeBand(band),
        duration_class=DurationClass(duration),
        mandatory=mandatory,
        priority=80 if mandatory else 30,
        rationale=f"Plausible {intent}",
    )


def test_overflow_repair_prompt_gives_capacity_instructions() -> None:
    planning_case, catalog = _read_models(CASE)
    brief = weekly_brief()
    rejected = proposal(date(2026, 8, 10), "read")

    prompt = structural_repair_prompt(
        planning_case,
        catalog,
        brief,
        rejected,
        "activities overflow day 2026-08-10",
    )

    assert "remove or defer optional activities" in prompt
    assert "at most four evening activities" in prompt


def test_weekly_schema_excludes_zero_target_habits() -> None:
    planning_case, catalog = _read_models(CASE)
    profile = valid_profile()
    digest = behavioral_profile_digest(profile)
    ledger = initial_habit_ledger(digest, profile)
    dates = planning_case.dates()
    budget = derive_habit_budget(
        profile,
        ledger,
        dates,
        {value: planning_case.calendar_day(value).day_type for value in dates},
    )

    schema = _weekly_schema(catalog, budget)
    intents = schema["$defs"]["WeeklyDayBrief"]["properties"]["goalIntents"]["items"][
        "enum"
    ]

    assert "visit_mother_and_have_dinner" not in intents
    assert "watch_documentary" in intents


def test_daily_anchor_canonicalization_adds_sleep_and_removes_weekend_work() -> None:
    planning_case, _catalog = _read_models(CASE)
    profile = valid_profile()
    monday = proposal(date(2026, 8, 10), "read")
    monday = monday.model_copy(
        update={"activities": [item for item in monday.activities if item.intent != "sleep"]}
    )

    normalized_monday, monday_changes = _canonicalize_daily_anchors(
        planning_case, profile, monday
    )
    sunday = proposal(date(2026, 8, 16), "read")
    sunday = sunday.model_copy(
        update={
            "activities": [
                *sunday.activities,
                activity("work_shift", "garden_workplace", "morning", "long"),
            ]
        }
    )
    normalized_sunday, sunday_changes = _canonicalize_daily_anchors(
        planning_case, profile, sunday
    )

    assert [item.intent for item in normalized_monday.activities].count("sleep") == 1
    sleep_first = normalized_monday.model_copy(
        update={
            "activities": [
                normalized_monday.activities[-1],
                *normalized_monday.activities[:-1],
            ]
        }
    )
    sleep_last, sleep_changes = _canonicalize_daily_anchors(
        planning_case, profile, sleep_first
    )
    assert sleep_last.activities[-1].intent == "sleep"
    assert any(item["reason"] == "sleep_must_be_last" for item in sleep_changes)
    assert "work_shift" not in [item.intent for item in normalized_sunday.activities]
    assert any(item["action"] == "insert" and item["intent"] == "sleep" for item in monday_changes)
    assert any(item["action"] == "remove" for item in sunday_changes)


def test_weekly_goal_canonicalization_respects_targets_and_preserves_solo_days() -> None:
    planning_case, _catalog = _read_models(CASE)
    profile = valid_profile()
    digest = behavioral_profile_digest(profile)
    ledger = initial_habit_ledger(digest, profile)
    dates = planning_case.dates()
    budget = derive_habit_budget(
        profile,
        ledger,
        dates,
        {value: planning_case.calendar_day(value).day_type for value in dates},
    )
    brief = weekly_brief()
    brief = brief.model_copy(
        update={
            "days": [
                day.model_copy(
                    update={
                        "goal_intents": (
                            ["work_shift", "read"]
                            if day.day_type == "workday"
                            else ["read"]
                        )
                    }
                )
                for day in brief.days
            ]
        }
    )

    normalized, changes = _canonicalize_weekly_goals(profile, budget, brief)
    read_target = next(item.target_occurrences for item in budget.items if item.intent == "read")
    read_days = [day for day in normalized.days if "read" in day.goal_intents]

    assert len(read_days) == read_target
    assert all(day.goal_intents for day in normalized.days)
    assert {date(2026, 8, 15), date(2026, 8, 16)} <= {day.date for day in read_days}
    assert changes


def proposal(value: date, distinctive_intent: str) -> DailyProposal:
    distinctive_locations = {
        "read": "living_room_01",
        "evening_walk": "neighborhood_park",
        "clean_kitchen": "kitchen_01",
        "buy_groceries": "supermarket_barcelona",
        "watch_documentary": "living_room_01",
        "start_laundry": "bathroom_01",
        "weekly_meal_preparation": "kitchen_01",
    }
    activities = [
        activity("wake_up", "bedroom_01", "early_morning", "brief"),
        activity("take_morning_medication", "bedroom_01", "early_morning", "brief"),
        activity("morning_toilet_and_shower", "bathroom_01", "early_morning"),
        activity("prepare_and_eat_breakfast", "kitchen_01", "morning", "medium"),
    ]
    if value.weekday() < 5:
        activities.append(activity("work_shift", "garden_workplace", "morning", "extended"))
    activities.extend(
        [
            activity(
                distinctive_intent,
                distinctive_locations[distinctive_intent],
                "evening" if value.weekday() < 5 else "afternoon",
                "medium",
                mandatory=False,
            ),
            activity("evening_hygiene", "bathroom_01", "night", "brief"),
            activity("sleep", "bedroom_01", "night", "extended"),
        ]
    )
    return DailyProposal(
        date=value,
        narrative_intent=f"A distinct plan for {value.isoformat()}",
        activities=activities,
    )


def weekly_brief() -> WeeklyBrief:
    start = date(2026, 8, 10)
    return WeeklyBrief(
        week_theme="A balanced summer week",
        variety_strategy=["vary evening leisure", "reserve domestic tasks for the weekend"],
        days=[
            WeeklyDayBrief(
                date=start.fromordinal(start.toordinal() + index),
                day_type="workday" if index < 5 else "weekend",
                narrative_intent=f"Day {index + 1}",
                distinctive_goals=[f"Distinct goal {index + 1}"],
            )
            for index in range(7)
        ],
    )


def profile_aware_week() -> tuple[WeeklyBrief, list[DailyProposal], list[DailyProposal]]:
    distinct = [
        "read",
        "evening_walk",
        "clean_kitchen",
        "buy_groceries",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    base = weekly_brief()
    brief = base.model_copy(
        update={
            "days": [
                item.model_copy(update={"goal_intents": [intent]})
                for item, intent in zip(base.days, distinct, strict=True)
            ]
        }
    )
    accepted = [
        proposal(item.date, intent)
        for item, intent in zip(brief.days, distinct, strict=True)
    ]
    broken = list(accepted)
    for index in (5, 6):
        current = broken[index]
        chain = [
            activity(
                "travel_to_mothers_home",
                "mother_house_barcelona",
                "afternoon",
                "short",
            ),
            activity(
                "visit_mother_and_have_dinner",
                "mother_house_barcelona",
                "evening",
                "medium",
            ),
            activity("travel_home", "living_room_01", "evening", "short"),
        ]
        broken[index] = current.model_copy(
            update={"activities": [*current.activities[:-2], *chain, *current.activities[-2:]]}
        )
    return brief, broken, accepted


class FakeClient:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def complete_json(self, **kwargs: Any) -> tuple[Any, LMStudioExchange]:
        self.prompts.append(kwargs["user_prompt"])
        value = self.outputs.pop(0)
        content = value.model_dump_json(by_alias=True)
        return value, LMStudioExchange(
            request={"messages": [{"content": kwargs["user_prompt"]}]},
            api_response={"choices": [{"message": {"content": content}}]},
            raw_content=content,
        )


def test_planning_memory_keeps_only_thirty_day_signatures() -> None:
    memory = PlanningMemory(day_signatures=[f"signature-{index}" for index in range(30)])

    updated = _updated_memory(
        memory,
        proposal(date(2026, 8, 10), "read"),
    )

    assert len(updated.day_signatures) == 30
    assert updated.day_signatures[0] == "signature-1"


def test_daily_proposal_must_realize_goals_assigned_to_its_date() -> None:
    planning_case, catalog = _read_models(CASE)
    daily = proposal(date(2026, 8, 10), "read")

    with pytest.raises(HybridPlanningError, match="short_evening_walk"):
        _validate_daily_proposal(
            planning_case,
            catalog,
            daily.date,
            daily,
            required_intents={"short_evening_walk"},
        )


def test_future_weekly_habit_goal_is_reserved_from_earlier_extra() -> None:
    profile = valid_profile()
    brief = weekly_brief()
    reserved_date = date(2026, 8, 11)
    brief = brief.model_copy(
        update={
            "days": [
                item.model_copy(
                    update={
                        "goal_intents": (
                            ["evening_walk"] if item.date == reserved_date else ["read"]
                        )
                    }
                )
                for item in brief.days
            ]
        }
    )
    earlier = proposal(date(2026, 8, 10), "evening_walk")

    normalized, changes = _reserve_future_weekly_goals(profile, brief, earlier)

    assert "evening_walk" not in {item.intent for item in normalized.activities}
    assert changes == [
        {
            "date": "2026-08-10",
            "habitId": "evening_walk",
            "intent": "evening_walk",
            "reason": "future_weekly_goal_reserved",
            "reservedFor": "2026-08-11",
        }
    ]


def test_daily_habit_is_not_reserved_for_a_future_weekly_goal() -> None:
    profile = valid_profile()
    brief = weekly_brief()
    reserved_date = date(2026, 8, 15)
    brief = brief.model_copy(
        update={
            "days": [
                item.model_copy(
                    update={
                        "goal_intents": ["sleep"] if item.date == reserved_date else ["read"]
                    }
                )
                for item in brief.days
            ]
        }
    )
    earlier = proposal(date(2026, 8, 10), "read")

    normalized, changes = _reserve_future_weekly_goals(profile, brief, earlier)

    assert "sleep" in {item.intent for item in normalized.activities}
    assert changes == []


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


def test_hybrid_plan_generates_compiles_and_compares_without_exposing_baseline(
    tmp_path: Path,
) -> None:
    distinct = [
        "read",
        "evening_walk",
        "clean_kitchen",
        "buy_groceries",
        "watch_documentary",
        "start_laundry",
        "weekly_meal_preparation",
    ]
    brief = weekly_brief()
    daily = [proposal(item.date, intent) for item, intent in zip(brief.days, distinct, strict=True)]
    invalid_activity = daily[0].activities[0].model_copy(update={"intent": "invented_intent"})
    invalid_first_day = daily[0].model_copy(
        update={"activities": [invalid_activity, *daily[0].activities[1:]]}
    )
    client = FakeClient([brief, invalid_first_day, *daily])
    output = tmp_path / "hybrid"

    result = generate_hybrid_plan(
        CASE,
        output,
        HybridPlanningConfig(model="fake-model", max_diversity_repairs=0),
        baseline_path=BASELINE,
        client=client,
    )

    assert result.plan.days and result.diversity.passes_gate
    assert result.comparison is not None and result.comparison["comparable"] is True
    assert json.loads((output / "run.json").read_text())["executionPerformed"] is False
    assert json.loads((output / "validation-report.json").read_text())["valid"] is True
    assert json.loads((output / "compilation-report.json").read_text())["success"] is True
    assert (output / "memory-checkpoint.json").is_file()
    assert (output / "days/2026-08-10/attempt-1/proposal.json").is_file()
    assert (output / "days/2026-08-10/attempt-2/proposal.json").is_file()
    assert "invented_intent" in client.prompts[2]
    all_prompts = "\n".join(client.prompts)
    assert "act_10_01" not in all_prompts
    assert "gemini-2.5-flash" not in all_prompts
    assert "barcelona_tommaso_gardener_week" not in all_prompts


def test_diversity_gate_repairs_the_most_repetitive_day(tmp_path: Path) -> None:
    brief = weekly_brief()
    repeated = [proposal(item.date, "read") for item in brief.days]
    first_index = most_repetitive_day_index(repeated)
    repaired_one = proposal(brief.days[first_index].date, "evening_walk")
    after_first = list(repeated)
    after_first[first_index] = repaired_one
    second_index = most_repetitive_day_index(after_first)
    repaired_two = proposal(brief.days[second_index].date, "clean_kitchen")
    client = FakeClient([brief, *repeated, repaired_one, repaired_two])

    with pytest.raises(HybridPlanningError, match="diversity gate"):
        generate_hybrid_plan(
            CASE,
            tmp_path / "repaired",
            HybridPlanningConfig(model="fake", max_diversity_repairs=2),
            client=client,
        )

    report = json.loads((tmp_path / "repaired/diversity-report.json").read_text())
    assert report["passesGate"] is False
    assert len(client.prompts) == 10


def test_materializer_rejects_unknown_location_and_date_gap() -> None:
    planning_case, _ = _read_models(CASE)
    config = HybridPlanningConfig(model="fake")
    brief = weekly_brief()
    proposals = [proposal(item.date, "read") for item in brief.days]
    proposals[0].activities[0] = proposals[0].activities[0].model_copy(
        update={"location_id": "missing"}
    )
    with pytest.raises(ValueError, match="unknown proposed location"):
        materialize_scenario(
            planning_case,
            proposals,
            config,
            datetime(2026, 7, 22, tzinfo=ZoneInfo("Europe/Madrid")),
        )
    with pytest.raises(ValueError, match="cover the planning window"):
        materialize_scenario(
            planning_case,
            proposals[:-1],
            config,
            datetime(2026, 7, 22, tzinfo=ZoneInfo("Europe/Madrid")),
        )


def test_metrics_identify_repetition() -> None:
    days = [proposal(date(2026, 8, 10 + index), "read") for index in range(7)]
    metrics = diversity_metrics(days)
    assert not metrics.passes_gate
    assert metrics.distinct_day_signatures == 2
    assert most_repetitive_day_index(days) == 4
    assert most_repetitive_day_index(days[:1]) == 0


def test_comparison_rejects_non_scenario_and_detects_mismatch() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = json.loads(json.dumps(baseline["scenario"]))
    changed["residents"][0]["residentId"] = "someone_else"
    report = compare_scenarios(changed, baseline)
    assert report["sameResidents"] is False
    assert report["comparable"] is False
    with pytest.raises(ValueError, match="life scenario"):
        compare_scenarios({}, baseline)
    with pytest.raises(ValueError, match="JSON object"):
        compare_scenarios([], baseline)


def test_planning_case_rejects_inconsistent_boundaries_and_calendar() -> None:
    raw = json.loads(CASE.read_text(encoding="utf-8"))

    invalid = json.loads(json.dumps(raw))
    invalid["routineRequirements"][0]["minimumOccurrences"] = 2
    with pytest.raises(ValidationError, match="maximumOccurrences"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["initialState"]["at"] = "2026-08-10T01:00:00+02:00"
    with pytest.raises(ValidationError, match="initialState.at"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["planningWindow"]["start"] = "2026-08-10T01:00:00+02:00"
    invalid["initialState"]["at"] = invalid["planningWindow"]["start"]
    with pytest.raises(ValidationError, match="start must be local midnight"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["planningWindow"]["end"] = "2026-08-17T01:00:00+02:00"
    with pytest.raises(ValidationError, match="end must be local midnight"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["calendar"] = [
        {"date": "2026-08-10", "dayType": "holiday"},
        {"date": "2026-08-10", "dayType": "workday"},
    ]
    with pytest.raises(ValidationError, match="calendar dates must be unique"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["calendar"] = [{"date": "2026-08-17", "dayType": "holiday"}]
    with pytest.raises(ValidationError, match="inside the planning window"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    invalid = json.loads(json.dumps(raw))
    invalid["initialState"]["residents"][0]["residentId"] = "someone_else"
    with pytest.raises(ValidationError, match="planning resident"):
        PlanningCase.model_validate_json(json.dumps(invalid))

    explicit = json.loads(json.dumps(raw))
    explicit["calendar"] = [{"date": "2026-08-15", "dayType": "holiday"}]
    planning_case = PlanningCase.model_validate_json(json.dumps(explicit))
    assert planning_case.calendar_day(date(2026, 8, 15)).day_type == "holiday"


def test_lmstudio_client_parses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    value = weekly_brief()

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            body = {"choices": [{"message": {"content": value.model_dump_json(by_alias=True)}}]}
            return json.dumps(body).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    client = LMStudioClient(HybridPlanningConfig(model="local"))
    parsed, exchange = client.complete_json(
        schema_name="weekly",
        output_model=WeeklyBrief,
        system_prompt="system",
        user_prompt="user",
        seed=1,
        schema_override={"type": "object"},
    )
    assert parsed == value
    assert exchange.request["response_format"]["type"] == "json_schema"
    assert exchange.request["response_format"]["json_schema"]["schema"] == {
        "type": "object"
    }


def test_lmstudio_client_wraps_transport_and_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    client = LMStudioClient(HybridPlanningConfig(model="local"))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(LMStudioError, match="unavailable"):
        client.complete_json(
            schema_name="weekly",
            output_model=WeeklyBrief,
            system_prompt="system",
            user_prompt="user",
            seed=1,
        )

    class InvalidResponse:
        def __enter__(self) -> InvalidResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"not-json"}}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: InvalidResponse())
    with pytest.raises(LMStudioError, match="invalid structured response"):
        client.complete_json(
            schema_name="weekly",
            output_model=WeeklyBrief,
            system_prompt="system",
            user_prompt="user",
            seed=1,
        )


def test_existing_output_directory_is_not_touched(tmp_path: Path) -> None:
    output = tmp_path / "exists"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(HybridPlanningError, match="already exists"):
        generate_hybrid_plan(CASE, output, HybridPlanningConfig(model="fake"))
    assert marker.read_text() == "keep"


def test_profile_aware_plan_repairs_frequency_and_writes_ground_truth(tmp_path: Path) -> None:
    brief, broken, _ = profile_aware_week()
    profile_path = tmp_path / "behavioral-profile.json"
    profile_path.write_text(valid_profile().model_dump_json(by_alias=True), encoding="utf-8")
    client = FakeClient([brief, *broken])
    output = tmp_path / "habit-aware"

    result = generate_hybrid_plan(
        CASE,
        output,
        HybridPlanningConfig(model="fake", max_diversity_repairs=0),
        behavioral_profile_path=profile_path,
        client=client,
    )

    assert result.habit_gate is not None and result.habit_gate.valid
    assert (output / "habit-budget.json").is_file()
    assert (output / "habit-gate-report.json").is_file()
    assert (output / "planned-habit-trace.json").is_file()
    assert (output / "habit-ledger.json").is_file()
    normalization_path = (
        output / "days/2026-08-16/attempt-1/habit-limit-normalizations.json"
    )
    assert normalization_path.is_file()
    normalizations = json.loads(normalization_path.read_text())["changes"]
    assert any(item["intent"] == "visit_mother_and_have_dinner" for item in normalizations)
    assert json.loads((output / "run.json").read_text())["executionPerformed"] is False
    assert "barcelona_tommaso_gardener_week" not in "\n".join(client.prompts)


def test_profile_aware_plan_rejects_ledger_digest_before_calling_llm(tmp_path: Path) -> None:
    profile_path = tmp_path / "behavioral-profile.json"
    profile_path.write_text(valid_profile().model_dump_json(by_alias=True), encoding="utf-8")
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        HabitLedger(profile_digest="0" * 64, entries=[]).model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    client = FakeClient([])
    output = tmp_path / "digest-mismatch"

    with pytest.raises(HybridPlanningError, match="digest"):
        generate_hybrid_plan(
            CASE,
            output,
            HybridPlanningConfig(model="fake"),
            behavioral_profile_path=profile_path,
            ledger_path=ledger_path,
            client=client,
        )

    assert client.prompts == []
    assert not (output / "weekly-brief").exists()


def test_profile_aware_plan_fails_after_exhausting_daily_goal_repairs(
    tmp_path: Path,
) -> None:
    brief, broken, _ = profile_aware_week()
    broken[-1] = broken[-1].model_copy(
        update={
            "activities": [
                item
                for item in broken[-1].activities
                if item.intent != "weekly_meal_preparation"
            ]
        }
    )
    profile_path = tmp_path / "behavioral-profile.json"
    profile_path.write_text(valid_profile().model_dump_json(by_alias=True), encoding="utf-8")
    client = FakeClient([brief, *broken, broken[-1], broken[-1]])
    output = tmp_path / "habit-failure"

    with pytest.raises(HybridPlanningError, match="assigned goal intents"):
        generate_hybrid_plan(
            CASE,
            output,
            HybridPlanningConfig(model="fake", max_diversity_repairs=0),
            behavioral_profile_path=profile_path,
            client=client,
        )

    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert len(client.prompts) == 10
    assert not (output / "scenario.json").exists()


def test_behavioral_profile_cli_reports_frozen_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "profile"
    profile = valid_profile()

    def fake_generate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            output_dir=output,
            profile=profile,
            profile_digest="a" * 64,
        )

    monkeypatch.setattr("smart_home_sim.cli.generate_behavioral_profile", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate-behavioral-profile",
            str(CASE),
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert str((output / "behavioral-profile.json").resolve()) in result.stdout
    assert str((output / "profile.sha256").resolve()) in result.stdout
    assert "8 intended habits frozen" in result.stdout


def test_hybrid_plan_cli_reports_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "run"
    profile_path = tmp_path / "behavioral-profile.json"
    ledger_path = tmp_path / "habit-ledger.json"
    diversity = SimpleNamespace(distinct_day_signatures=7, day_count=7)
    received: dict[str, object] = {}

    def fake_generate(*_args: object, **kwargs: object) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(
            output_dir=output,
            diversity=diversity,
            comparison={},
            habit_gate=SimpleNamespace(valid=True),
        )

    monkeypatch.setattr("smart_home_sim.cli.generate_hybrid_plan", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate-hybrid-plan",
            str(CASE),
            "--output-dir",
            str(output),
            "--behavioral-profile",
            str(profile_path),
            "--habit-ledger",
            str(ledger_path),
            "--model",
            "local-model",
            "--compare-with",
            str(BASELINE),
        ],
    )
    assert result.exit_code == 0
    assert "Hybrid canonical plan written" in result.stdout
    assert "7/7 distinct" in result.stdout
    assert "Habit gate passed" in result.stdout
    assert str((output / "habit-ledger.json").resolve()) in result.stdout
    assert "Comparison written" in result.stdout
    assert received["behavioral_profile_path"] == profile_path
    assert received["ledger_path"] == ledger_path


def test_hybrid_plan_cli_reports_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise HybridPlanningError("offline")

    monkeypatch.setattr("smart_home_sim.cli.generate_hybrid_plan", fail)
    result = runner.invoke(
        app,
        [
            "generate-hybrid-plan",
            str(CASE),
            "--output-dir",
            str(tmp_path / "run"),
            "--behavioral-profile",
            str(tmp_path / "behavioral-profile.json"),
        ],
    )
    assert result.exit_code == 1
    assert "offline" in result.stderr


def test_hybrid_plan_cli_requires_behavioral_profile(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate-hybrid-plan", str(CASE), "--output-dir", str(tmp_path / "run")],
    )

    assert result.exit_code == 2
    assert "--behavioral-profile" in result.output
