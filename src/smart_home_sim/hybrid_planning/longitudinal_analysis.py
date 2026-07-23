from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, time
from pathlib import Path

from smart_home_sim.hybrid_planning.behavioral_models import BehavioralProfile
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.guardrails import (
    HYGIENE_INTENTS,
    NOURISHMENT_INTENTS,
)
from smart_home_sim.hybrid_planning.habit_gates import (
    effective_habit_time_bands,
)
from smart_home_sim.hybrid_planning.longitudinal import load_accepted_proposals
from smart_home_sim.hybrid_planning.longitudinal_models import LongitudinalCheckpoint
from smart_home_sim.hybrid_planning.metrics import day_signature
from smart_home_sim.hybrid_planning.models import DailyProposal, TimeBand
from smart_home_sim.hybrid_planning.service import HybridPlanningError


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _signature_entropy(signatures: list[str]) -> tuple[float, float]:
    if len(signatures) < 2:
        return 0.0, 0.0
    counts = Counter(signatures)
    entropy = -sum(
        (count / len(signatures)) * math.log2(count / len(signatures))
        for count in counts.values()
    )
    maximum = math.log2(len(signatures))
    return entropy, entropy / maximum if maximum else 0.0


def summarize_proposals(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> dict[str, object]:
    ordered = sorted(proposals, key=lambda item: item.date)
    counts = [len(item.activities) for item in ordered]
    signatures = [day_signature(item) for item in ordered]
    entropy, normalized_entropy = _signature_entropy(signatures)
    consecutive_similarities = [
        _jaccard(
            (item.intent for item in left.activities),
            (item.intent for item in right.activities),
        )
        for left, right in zip(ordered, ordered[1:], strict=False)
    ]
    nourishment_days = sum(
        bool(
            NOURISHMENT_INTENTS.intersection(
                item.intent for item in proposal.activities
            )
        )
        for proposal in ordered
    )
    hygiene_days = sum(
        bool(
            HYGIENE_INTENTS.intersection(
                item.intent for item in proposal.activities
            )
        )
        for proposal in ordered
    )
    habits: dict[str, object] = {}
    for habit in profile.habits:
        matched = [
            (proposal, activity)
            for proposal in ordered
            for activity in proposal.activities
            if activity.intent == habit.intent
        ]
        observed = len(matched)
        temporal_matches = sum(
            activity.time_band
            in effective_habit_time_bands(habit, proposal.date)
            for proposal, activity in matched
        )
        location_matches = sum(
            activity.location_id in habit.location_ids
            for _proposal, activity in matched
        )
        habits[habit.intent] = {
            "habitId": habit.habit_id,
            "observed": observed,
            "temporalAdherence": (
                temporal_matches / observed if observed else 1.0
            ),
            "locationAdherence": (
                location_matches / observed if observed else 1.0
            ),
        }
    day_count = len(ordered)
    return {
        "startDate": ordered[0].date.isoformat() if ordered else None,
        "endDate": ordered[-1].date.isoformat() if ordered else None,
        "dayCount": day_count,
        "activityCount": sum(counts),
        "density": {
            "mean": sum(counts) / day_count if day_count else 0.0,
            "minimum": min(counts, default=0),
            "maximum": max(counts, default=0),
        },
        "variety": {
            "distinctSignatures": len(set(signatures)),
            "signatureEntropy": entropy,
            "normalizedSignatureEntropy": normalized_entropy,
            "meanConsecutiveJaccard": (
                sum(consecutive_similarities) / len(consecutive_similarities)
                if consecutive_similarities
                else 0.0
            ),
        },
        "dailyLife": {
            "nourishmentCoverage": nourishment_days / day_count if day_count else 0.0,
            "hygieneCoverage": hygiene_days / day_count if day_count else 0.0,
        },
        "habits": habits,
    }


def compare_summaries(
    before: dict[str, object],
    after: dict[str, object],
) -> dict[str, object]:
    before_density = before["density"]
    after_density = after["density"]
    before_daily_life = before["dailyLife"]
    after_daily_life = after["dailyLife"]
    before_variety = before["variety"]
    after_variety = after["variety"]
    assert isinstance(before_density, dict)
    assert isinstance(after_density, dict)
    assert isinstance(before_daily_life, dict)
    assert isinstance(after_daily_life, dict)
    assert isinstance(before_variety, dict)
    assert isinstance(after_variety, dict)
    return {
        "meanDailyActivities": after_density["mean"] - before_density["mean"],
        "nourishmentCoverage": (
            after_daily_life["nourishmentCoverage"]
            - before_daily_life["nourishmentCoverage"]
        ),
        "hygieneCoverage": (
            after_daily_life["hygieneCoverage"]
            - before_daily_life["hygieneCoverage"]
        ),
        "distinctSignatures": (
            after_variety["distinctSignatures"]
            - before_variety["distinctSignatures"]
        ),
        "normalizedSignatureEntropy": (
            after_variety["normalizedSignatureEntropy"]
            - before_variety["normalizedSignatureEntropy"]
        ),
        "meanConsecutiveJaccard": (
            after_variety["meanConsecutiveJaccard"]
            - before_variety["meanConsecutiveJaccard"]
        ),
    }


def _load_longitudinal_run(
    run_dir: Path,
) -> tuple[BehavioralProfile, list[DailyProposal]]:
    try:
        checkpoint = LongitudinalCheckpoint.model_validate_json(
            (run_dir / "checkpoint.json").read_text(encoding="utf-8")
        )
        profile = BehavioralProfile.model_validate_json(
            (run_dir / "behavioral-profile-snapshot.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise HybridPlanningError(
            f"cannot load longitudinal run {run_dir}: {error}"
        ) from error
    if behavioral_profile_digest(profile) != checkpoint.profile_digest:
        raise HybridPlanningError(
            f"behavioral profile digest mismatch in longitudinal run: {run_dir}"
        )
    proposals = load_accepted_proposals(run_dir, checkpoint.chunks)
    return profile, proposals


def summarize_longitudinal_run(run_dir: Path) -> dict[str, object]:
    profile, proposals = _load_longitudinal_run(run_dir)
    return summarize_proposals(profile, proposals)


def _time_band_at(value: str) -> TimeBand:
    local_time = datetime.fromisoformat(value).timetz().replace(tzinfo=None)
    boundaries = [
        (time(21, 30), TimeBand.night),
        (time(18, 0), TimeBand.evening),
        (time(14, 0), TimeBand.afternoon),
        (time(12, 0), TimeBand.midday),
        (time(8, 0), TimeBand.morning),
    ]
    return next(
        (band for boundary, band in boundaries if local_time >= boundary),
        TimeBand.early_morning,
    )


def _summarize_baseline(
    baseline_path: Path,
    profile: BehavioralProfile,
    shared_dates: set[date],
) -> dict[str, object]:
    try:
        bundle = json.loads(baseline_path.read_text(encoding="utf-8"))
        days = bundle["scenario"]["days"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise HybridPlanningError(f"cannot load baseline scenario: {error}") from error
    if not isinstance(days, list):
        raise HybridPlanningError("baseline scenario days must be a list")
    selected: list[tuple[date, list[dict[str, object]]]] = []
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("activities"), list):
            raise HybridPlanningError("baseline scenario contains an invalid day")
        try:
            day_date = date.fromisoformat(str(day["date"]))
        except (KeyError, ValueError) as error:
            raise HybridPlanningError("baseline scenario contains an invalid date") from error
        if day_date in shared_dates:
            selected.append((day_date, day["activities"]))
    selected.sort(key=lambda item: item[0])
    intent_days = [
        [str(activity.get("intent", "")) for activity in activities]
        for _value, activities in selected
    ]
    signatures = ["|".join(intents) for intents in intent_days]
    entropy, normalized_entropy = _signature_entropy(signatures)
    counts = [len(activities) for _value, activities in selected]
    consecutive_similarities = [
        _jaccard(left, right)
        for left, right in zip(intent_days, intent_days[1:], strict=False)
    ]
    day_count = len(selected)
    habits: dict[str, object] = {}
    for habit in profile.habits:
        matched: list[tuple[date, dict[str, object]]] = [
            (day_date, activity)
            for day_date, activities in selected
            for activity in activities
            if activity.get("intent") == habit.intent
        ]
        temporal_matches = 0
        location_matches = 0
        for day_date, activity in matched:
            start_window = activity.get("startWindow")
            preferred = (
                start_window.get("preferred")
                if isinstance(start_window, dict)
                else None
            )
            if isinstance(preferred, str) and _time_band_at(
                preferred
            ) in effective_habit_time_bands(habit, day_date):
                temporal_matches += 1
            locations = activity.get("locationIds")
            if isinstance(locations, list) and any(
                location in habit.location_ids for location in locations
            ):
                location_matches += 1
        observed = len(matched)
        habits[habit.intent] = {
            "habitId": habit.habit_id,
            "observed": observed,
            "temporalAdherence": (
                temporal_matches / observed if observed else 1.0
            ),
            "locationAdherence": (
                location_matches / observed if observed else 1.0
            ),
        }
    return {
        "startDate": selected[0][0].isoformat() if selected else None,
        "endDate": selected[-1][0].isoformat() if selected else None,
        "dayCount": day_count,
        "activityCount": sum(counts),
        "density": {
            "mean": sum(counts) / day_count if day_count else 0.0,
            "minimum": min(counts, default=0),
            "maximum": max(counts, default=0),
        },
        "variety": {
            "distinctSignatures": len(set(signatures)),
            "signatureEntropy": entropy,
            "normalizedSignatureEntropy": normalized_entropy,
            "meanConsecutiveJaccard": (
                sum(consecutive_similarities) / len(consecutive_similarities)
                if consecutive_similarities
                else 0.0
            ),
        },
        "dailyLife": {
            "nourishmentCoverage": (
                sum(bool(NOURISHMENT_INTENTS.intersection(intents)) for intents in intent_days)
                / day_count
                if day_count
                else 0.0
            ),
            "hygieneCoverage": (
                sum(bool(HYGIENE_INTENTS.intersection(intents)) for intents in intent_days)
                / day_count
                if day_count
                else 0.0
            ),
        },
        "habits": habits,
    }


def compare_longitudinal_runs(
    before_dir: Path,
    after_dir: Path,
    *,
    baseline_path: Path | None = None,
) -> dict[str, object]:
    before_profile, before_proposals = _load_longitudinal_run(before_dir)
    after_profile, after_proposals = _load_longitudinal_run(after_dir)
    if behavioral_profile_digest(before_profile) != behavioral_profile_digest(
        after_profile
    ):
        raise HybridPlanningError(
            "cannot compare longitudinal runs with different behavioral profiles"
        )
    before_summary = summarize_proposals(before_profile, before_proposals)
    after_summary = summarize_proposals(after_profile, after_proposals)
    baseline_summary = (
        _summarize_baseline(
            baseline_path,
            after_profile,
            {item.date for item in after_proposals},
        )
        if baseline_path is not None
        else None
    )
    return {
        "documentType": "hybrid_longitudinal_comparison",
        "before": before_summary,
        "after": after_summary,
        "delta": compare_summaries(before_summary, after_summary),
        "baseline": baseline_summary,
    }
