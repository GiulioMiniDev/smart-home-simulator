from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any

from smart_home_sim.compiler import compile_payload


def _scenario_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("comparison input must be a JSON object")
    scenario = value.get("scenario", value)
    if not isinstance(scenario, dict) or scenario.get("documentType") != "life_scenario":
        raise ValueError("comparison input does not contain a life scenario")
    return scenario


def _sequences(scenario: dict[str, Any]) -> list[list[str]]:
    return [
        [str(activity["intent"]) for activity in day.get("activities", [])]
        for day in scenario.get("days", [])
    ]


def _jaccard(left: list[str], right: list[str]) -> float:
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 1.0


def _plan_summary(scenario: dict[str, Any]) -> dict[str, Any]:
    sequences = _sequences(scenario)
    similarities = [_jaccard(left, right) for left, right in combinations(sequences, 2)]
    counts = Counter(intent for sequence in sequences for intent in sequence)
    signatures = ["|".join(sequence) for sequence in sequences]
    compilation = compile_payload(scenario)
    return {
        "scenarioId": scenario.get("scenarioId"),
        "activityCount": sum(len(item) for item in sequences),
        "distinctIntentCount": len(counts),
        "distinctDaySequenceCount": len(set(signatures)),
        "meanPairwiseDayJaccard": round(
            sum(similarities) / len(similarities) if similarities else 0.0, 6
        ),
        "maximumPairwiseDayJaccard": round(max(similarities, default=0.0), 6),
        "intentFrequency": dict(sorted(counts.items())),
        "compilationSucceeded": compilation.plan is not None,
        "compilationIssueCodes": [item.code for item in compilation.report.issues],
    }


def compare_scenarios(generated_value: Any, baseline_value: Any) -> dict[str, Any]:
    generated = _scenario_payload(generated_value)
    baseline = _scenario_payload(baseline_value)
    generated_sequences = _sequences(generated)
    baseline_sequences = _sequences(baseline)
    generated_residents = [item.get("residentId") for item in generated.get("residents", [])]
    baseline_residents = [item.get("residentId") for item in baseline.get("residents", [])]
    same_window = generated.get("simulationWindow") == baseline.get("simulationWindow")
    same_residents = generated_residents == baseline_residents
    corresponding = [
        {
            "date": generated["days"][index]["date"],
            "intentJaccard": round(_jaccard(left, right), 6),
            "sequenceSimilarity": round(SequenceMatcher(None, left, right).ratio(), 6),
        }
        for index, (left, right) in enumerate(
            zip(generated_sequences, baseline_sequences, strict=False)
        )
    ]
    return {
        "documentType": "hybrid_plan_comparison",
        "comparisonVersion": "0.1.0",
        "sameResidents": same_residents,
        "sameSimulationWindow": same_window,
        "comparable": same_residents and same_window,
        "generated": _plan_summary(generated),
        "baseline": _plan_summary(baseline),
        "correspondingDays": corresponding,
    }
