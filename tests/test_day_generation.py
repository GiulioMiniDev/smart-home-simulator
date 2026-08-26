from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import ActivityOccurrence, CadenceCalendar, CalendarDay
from smart_home_sim.hybrid_planning.day_generation import (
    DEFAULT_INTENT,
    build_day_plan,
    build_day_scenario,
    build_day_scenarios,
    label_to_intent,
)
from smart_home_sim.hybrid_planning.intents import intent_ids, intent_spec
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.recurring_activities import RecurringActivityKind, Weekday
from smart_home_sim.hybrid_planning.world import build_planning_world

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _world():
    persona = Persona(
        persona_id="luigi_bianchi",
        name="Luigi Bianchi",
        age=72,
        sex="M",
        occupation="retired",
        household="lives alone",
        health=["arthritis"],
        city="Bologna",
        timezone="Europe/Rome",
        notes="quiet",
        routine_anchors=["morning walk", "evening tea"],
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )
    return build_planning_world(persona, now=_NOW)


def _occ(
    label: str, target: str, kind: RecurringActivityKind = RecurringActivityKind.anchor
) -> ActivityOccurrence:
    return ActivityOccurrence(
        recurring_activity_id=label.replace(" ", "_"),
        label=label,
        kind=kind,
        target_time=target,
        window_start="06:00",
        window_end="22:00",
    )


def _day(date_str: str, weekday: Weekday, occurrences: list[ActivityOccurrence]) -> CalendarDay:
    return CalendarDay(date=date_str, weekday=weekday, occurrences=occurrences)


def _calendar(days: list[CalendarDay]) -> CadenceCalendar:
    return CadenceCalendar(
        calendar_id="cal",
        persona_id="luigi_bianchi",
        profile_id="luigi_bianchi_profile",
        start_date=days[0].date,
        end_date=days[-1].date,
        months=1,
        seed=1,
        timezone="Europe/Rome",
        days=days,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def test_habit_to_intent_keyword_matches() -> None:
    assert label_to_intent("morning coffee") == "eat_breakfast"
    assert label_to_intent("blood-pressure pill") == "take_morning_medication"
    assert label_to_intent("evening walk") == "evening_walk"
    assert label_to_intent("weekly groceries") == "buy_groceries"
    assert label_to_intent("watch the news") == "watch_television"
    assert label_to_intent("something idiosyncratic") == DEFAULT_INTENT


def test_specific_habit_labels_are_not_swallowed_by_generic_keywords() -> None:
    """With first-match-wins the generic word won and the habit was recorded as another activity:
    "wash up the dishes" became morning hygiene and `evening_hygiene` was unreachable outright."""
    assert label_to_intent("wash up the dishes") == "clean_kitchen"
    assert label_to_intent("do the dishes") == "clean_kitchen"
    assert label_to_intent("evening hygiene") == "evening_hygiene"
    assert label_to_intent("morning wash") == "morning_toilet_and_wash"
    assert label_to_intent("hang the laundry") == "hang_laundry"
    assert label_to_intent("start the laundry") == "start_laundry"
    # Every intent the table names must stay reachable through at least one of its own keywords.
    from smart_home_sim.hybrid_planning.day_generation import _INTENT_KEYWORDS

    for intent_id, keywords in _INTENT_KEYWORDS:
        assert any(label_to_intent(keyword) == intent_id for keyword in keywords), (
            f"{intent_id} is shadowed by another entry and can never be selected"
        )


def test_build_day_plan_scaffolds_wake_and_sleep() -> None:
    day = _day(
        "2026-08-03",
        Weekday.monday,
        [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
    )
    plan = build_day_plan(day, timezone="Europe/Rome", actor_id="luigi_bianchi")
    intents = [activity.intent for activity in plan.activities]
    assert intents[0] == "wake_up"
    assert intents[-1] == "sleep"
    assert intents[1:3] == ["eat_breakfast", "take_morning_medication"]
    assert len(plan.activities) == 4
    sleep = plan.activities[-1]
    assert sleep.allow_boundary_truncation and not sleep.mandatory
    assert plan.activities[1].location_ids == [intent_spec("eat_breakfast").default_location]
    assert plan.activities[1].labels == ["activity:morning_coffee"]


def test_a_break_is_not_given_the_length_of_its_category() -> None:
    """A category is a coarse grouping, and for these two it is the wrong number outright.

    `hygiene` holds a twenty-minute shower and a two-minute visit to the toilet; `cooking` holds a
    Sunday roast and the ninety seconds it takes to put the moka on. Drawn from their categories a
    bathroom break would run eighteen minutes and a coffee half an hour, which is not a break.
    """
    day = _day(
        "2026-08-03",
        Weekday.monday,
        [_occ("toilet break", "11:20"), _occ("coffee break", "16:05")],
    )

    plan = build_day_plan(day, timezone="Europe/Rome", actor_id="luigi_bianchi", seed=4)

    durations = {
        activity.intent: activity.duration
        for activity in plan.activities
        if activity.duration is not None
    }
    assert durations["use_toilet"].maximum_minutes == 15
    assert durations["prepare_and_drink_hot_drink"].maximum_minutes == 35
    # The categories they belong to would have allowed 45 and 80.
    assert durations["use_toilet"].preferred_minutes <= 15
    assert durations["prepare_and_drink_hot_drink"].preferred_minutes <= 35


def test_a_daytime_bathroom_visit_is_not_the_morning_routine() -> None:
    """The intent id *is* the label the dataset publishes, so reusing the morning one for an
    afternoon trip would put `morning_toilet_and_wash` in the ground truth at 15:30."""
    assert label_to_intent("bathroom break") == "use_toilet"
    assert label_to_intent("morning wash") == "morning_toilet_and_wash"
    assert intent_spec("use_toilet").default_location == "bathroom"


def test_build_day_scenario_uses_vocabulary_intents() -> None:
    day = _day(
        "2026-08-03", Weekday.monday, [_occ("groceries", "10:30", RecurringActivityKind.contextual)]
    )
    scenario = build_day_scenario(_world(), day)
    assert scenario.scenario_id == "luigi_bianchi_scenario"
    assert len(scenario.days) == 1
    vocabulary = set(intent_ids())
    assert all(activity.intent in vocabulary for activity in scenario.days[0].activities)


def test_build_day_scenarios_slice_and_empty() -> None:
    calendar = _calendar(
        [
            _day("2026-08-03", Weekday.monday, [_occ("coffee", "07:10")]),
            _day("2026-08-04", Weekday.tuesday, [_occ("lunch", "12:30")]),
        ]
    )
    scenarios = build_day_scenarios(_world(), calendar)
    assert len(scenarios) == 2
    one = build_day_scenarios(_world(), calendar, start_index=0, days=1)
    assert one[0].days[0].date.isoformat() == "2026-08-03"
    with pytest.raises(ValueError):
        build_day_scenarios(_world(), calendar, start_index=5)


def test_generated_day_compiles() -> None:
    day = _day(
        "2026-08-03",
        Weekday.monday,
        [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00"), _occ("walk", "17:00")],
    )
    scenario = build_day_scenario(_world(), day)
    result = compile_scenario(scenario)
    assert result.plan is not None, [i.message for i in result.report.issues]


def test_cli_generate_days_writes_scenarios(tmp_path) -> None:
    calendar = _calendar(
        [
            _day("2026-08-03", Weekday.monday, [_occ("coffee", "07:10")]),
            _day("2026-08-04", Weekday.tuesday, [_occ("dinner", "19:30")]),
        ]
    )
    world_path = tmp_path / "world.json"
    calendar_path = tmp_path / "calendar.json"
    world_path.write_text(_world().model_dump_json(by_alias=True), encoding="utf-8")
    calendar_path.write_text(calendar.model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "days"
    result = runner.invoke(
        cli.app,
        ["generate-days", str(world_path), str(calendar_path), "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    written = sorted(p.name for p in out.glob("*.scenario.json"))
    assert written == ["day-2026-08-03.scenario.json", "day-2026-08-04.scenario.json"]
    scenario = json.loads((out / written[0]).read_text(encoding="utf-8"))
    assert scenario["documentType"] == "life_scenario"


def test_cli_generate_days_rejects_bad_input(tmp_path) -> None:
    world_path = tmp_path / "world.json"
    world_path.write_text("{broken}", encoding="utf-8")
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["generate-days", str(world_path), str(calendar_path), "-o", str(tmp_path / "days")],
    )
    assert result.exit_code == 2
    assert "Cannot load inputs" in result.output


def _rhythm_horizon(days: int = 60, **profile_overrides: object):
    from datetime import date, timedelta

    from smart_home_sim.hybrid_planning.drives import RhythmProfile, plan_rhythms

    profile = RhythmProfile(persona_id="luigi_bianchi", **profile_overrides)  # type: ignore[arg-type]
    horizon = [date(2026, 8, 3) + timedelta(days=index) for index in range(days)]
    return profile, horizon, plan_rhythms(profile, horizon, seed=1)


def _plans_over_horizon(days: int = 60, **profile_overrides: object):
    from datetime import timedelta

    _, horizon, rhythms = _rhythm_horizon(days, **profile_overrides)
    plans = []
    for day in horizon:
        calendar_day = _day(
            day.isoformat(),
            Weekday.monday,
            [_occ("morning coffee", "07:10"), _occ("lunch", "12:30")],
        )
        plans.append(
            build_day_plan(
                calendar_day,
                timezone="Europe/Rome",
                actor_id="luigi_bianchi",
                rhythm=rhythms[day.isoformat()],
                # A night that runs past midnight is emitted on the day it happens on, so a plan
                # built without yesterday's rhythm is missing whichever night that was.
                previous_rhythm=rhythms.get((day - timedelta(days=1)).isoformat()),
                seed=1,
            )
        )
    return plans


def test_day_plan_without_a_rhythm_keeps_the_frozen_scaffold() -> None:
    day = _day("2026-08-03", Weekday.monday, [_occ("morning coffee", "07:10")])
    plan = build_day_plan(day, timezone="Europe/Rome", actor_id="luigi_bianchi")
    wake = next(item for item in plan.activities if item.intent == "wake_up")
    assert wake.start_window.preferred.strftime("%H:%M") == "06:00"
    breakfast = next(item for item in plan.activities if item.intent == "eat_breakfast")
    assert breakfast.duration.preferred_minutes == 30


def test_rhythm_moves_wake_and_bedtime_off_the_fixed_scaffold() -> None:
    plans = _plans_over_horizon()
    wake_times = {
        next(
            item for item in plan.activities if item.intent == "wake_up"
        ).start_window.preferred.strftime("%H:%M")
        for plan in plans
    }
    assert len(wake_times) > 25
    assert wake_times != {"06:00"}


def test_rhythm_lays_night_visits_before_the_wake() -> None:
    plans = _plans_over_horizon(nocturia_base_probability=0.8)
    nights = 0
    for plan in plans:
        wake = next(item for item in plan.activities if item.intent == "wake_up")
        visits = [item for item in plan.activities if "night_visit" in item.labels]
        nights += bool(visits)
        for visit in visits:
            assert visit.start_window.preferred < wake.start_window.preferred
            # Its own intent since catalog 1.4.0, and it declares two rooms: the bathroom it
            # happens in and the bedroom it ends in. Both matter. The intent is the ground-truth
            # label a dataset publishes, and it used to say `morning_toilet_and_wash` at two in the
            # morning; the second room is what lets the process put the resident back to bed
            # instead of leaving her at the washbasin until the next activity comes for her.
            assert visit.intent == "night_toilet_visit"
            assert visit.location_ids == ["bathroom", "bedroom"]
            assert intent_spec("night_toilet_visit").return_location == "bedroom"
    assert nights > 15


def test_an_unmet_need_for_company_produces_a_labelled_unplanned_call() -> None:
    """The social counterpart of the debt nap, placed against the schedule that actually exists."""
    from datetime import date, timedelta

    from smart_home_sim.hybrid_planning.drives import RhythmProfile, plan_rhythms

    profile = RhythmProfile(persona_id="luigi_bianchi")
    horizon = [date(2026, 8, 3) + timedelta(days=index) for index in range(60)]
    # Meals are scheduled, company never is: exactly the case that should make the resident call.
    rhythms = plan_rhythms(
        profile,
        horizon,
        seed=1,
        meals_by_day={day: 3 for day in horizon},
        social_by_day={day: 0 for day in horizon},
    )

    calls = 0
    for day in horizon:
        calendar_day = _day(
            day.isoformat(),
            Weekday.monday,
            [_occ("morning coffee", "07:10"), _occ("lunch", "12:30")],
        )
        plan = build_day_plan(
            calendar_day,
            timezone="Europe/Rome",
            actor_id="luigi_bianchi",
            rhythm=rhythms[day.isoformat()],
            seed=1,
        )
        for activity in plan.activities:
            if "social_need_contact" not in activity.labels:
                continue
            calls += 1
            assert activity.intent == "phone_call"
            # The key invariant: it happened, but nobody planned it, so it is not a habit.
            assert not any(label.startswith("activity:") for label in activity.labels)
    assert calls > 10


def test_sampled_durations_are_right_skewed_instead_of_hugging_a_ceiling() -> None:
    """The frozen table pinned every occurrence to preferredMinutes, so the observed maximum was
    the planned value and the variance was near zero."""
    import statistics

    # Long enough to resolve the skew. The gap between mean and median is about a minute and a
    # half against a nine-minute spread, so sixty lunches cannot tell it from noise: the sample
    # this ran on before happened to land the wrong side of it, and said so only when an unrelated
    # change reshuffled the draw.
    plans = _plans_over_horizon(days=240)
    lunches = [
        item.duration.preferred_minutes
        for plan in plans
        for item in plan.activities
        if item.intent == "eat_lunch"
    ]
    assert statistics.pstdev(lunches) > 4
    assert max(lunches) > statistics.mean(lunches) + 10
    # A right tail, not a symmetric band clipped at the top.
    assert statistics.mean(lunches) > statistics.median(lunches)


def test_night_lengths_vary_across_the_horizon() -> None:
    plans = _plans_over_horizon()
    nights = {
        item.duration.preferred_minutes
        for plan in plans
        for item in plan.activities
        if item.intent == "sleep"
    }
    assert len(nights) > 20


def test_a_night_past_midnight_is_planned_on_the_day_it_happens_on() -> None:
    """The horizon has exactly one night per evening, wherever the clock puts its start.

    Lights-out used to be capped at 23:50 so that it could not leave its own calendar day. Lifting
    the cap moves a late night onto the following day's plan, which is the list its wall-clock time
    belongs to — so the count that has to stay right is one night per *evening*, not one per plan.
    A day may legitimately hold two: the late night it inherited, and its own.
    """
    plans = _plans_over_horizon(days=90, bedtime_sigma_minutes=90.0)
    nights = [
        item.start_window.preferred
        for plan in plans
        for item in plan.activities
        if item.intent == "sleep"
    ]
    small_hours = [moment for moment in nights if moment.hour < 4]

    assert small_hours, "a wide bedtime draw has to produce nights that start after midnight"
    for plan in plans:
        on_this_day = [item for item in plan.activities if item.intent == "sleep"]
        assert len(on_this_day) <= 2
        for item in on_this_day:
            assert item.start_window.preferred.date() == plan.date
    # Every night still sits before the wake it leads to.
    for plan in plans:
        wake = next(item for item in plan.activities if item.intent == "wake_up")
        for item in plan.activities:
            if item.intent == "sleep" and item.start_window.preferred.hour < 4:
                assert item.start_window.preferred < wake.start_window.preferred


def test_a_disturbed_night_survives_compilation() -> None:
    """A bathroom trip happens *inside* the night, so it must not compete with it for the hours.

    The compiler keeps one actor in one place at a time, and the night is the only activity in the
    day marked optional. So a trip and the night that contains it were two claims on the same hours
    and the solver resolved them the only way it could: by dropping the night. On a year of Giulia
    that was 64 nights with no sleep at all, every one of them a night the drive model had given
    trips to, and not one undisturbed night among them.
    """
    _, horizon, rhythms = _rhythm_horizon(days=8, nocturia_base_probability=0.95)
    disturbed = 0
    for day in horizon:
        rhythm = rhythms[day.isoformat()]
        calendar_day = _day(
            day.isoformat(),
            Weekday.monday,
            [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
        )
        scenario = build_day_scenario(_world(), calendar_day, rhythm=rhythm, seed=1)
        visits = [
            item
            for item in scenario.days[0].activities
            if "night_visit" in item.labels and item.start_window is not None
        ]
        disturbed += bool(visits)
        for visit in visits:
            assert visit.can_overlap_for_actor
        result = compile_scenario(scenario)
        assert result.plan is not None, [i.message for i in result.report.issues]
        omitted = [
            entry.source_activity_id
            for planned in result.plan.days
            for entry in planned.omitted_activities
        ]
        assert omitted == [], omitted

    assert disturbed, "a 0.95 nocturia probability has to produce disturbed nights"


def test_rhythm_days_still_compile() -> None:
    _, horizon, rhythms = _rhythm_horizon(days=6, nocturia_base_probability=0.9)
    for day in horizon:
        calendar_day = _day(
            day.isoformat(),
            Weekday.monday,
            [_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
        )
        scenario = build_day_scenario(
            _world(), calendar_day, rhythm=rhythms[day.isoformat()], seed=1
        )
        result = compile_scenario(scenario)
        assert result.plan is not None, [i.message for i in result.report.issues]
