from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from itertools import combinations

from smart_home_sim.hybrid_planning.models import DailyProposal, DiversityMetrics


def day_signature(proposal: DailyProposal) -> str:
    return "|".join(item.intent for item in proposal.activities)


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def diversity_metrics(proposals: list[DailyProposal]) -> DiversityMetrics:
    signatures = [day_signature(item) for item in proposals]
    pairs = list(combinations(proposals, 2))
    similarities = [
        _jaccard(
            (item.intent for item in left.activities),
            (item.intent for item in right.activities),
        )
        for left, right in pairs
    ]
    repeated_pairs = sum(value * (value - 1) // 2 for value in Counter(signatures).values())
    distinct_required = max(1, round(len(proposals) * 0.7))
    mean_similarity = sum(similarities) / len(similarities) if similarities else 0.0
    maximum_similarity = max(similarities, default=0.0)
    reasons: list[str] = []
    if len(set(signatures)) < distinct_required:
        reasons.append(
            f"only {len(set(signatures))} distinct day sequences; require {distinct_required}"
        )
    if len(proposals) > 2 and mean_similarity > 0.75:
        reasons.append(f"mean daily intent similarity is {mean_similarity:.3f}; maximum is 0.750")
    if repeated_pairs > 1:
        reasons.append(f"found {repeated_pairs} exactly repeated day pairs; maximum is 1")
    return DiversityMetrics(
        day_count=len(proposals),
        distinct_day_signatures=len(set(signatures)),
        mean_pairwise_jaccard=round(mean_similarity, 6),
        maximum_pairwise_jaccard=round(maximum_similarity, 6),
        exact_repeated_day_pairs=repeated_pairs,
        passes_gate=not reasons,
        reasons=reasons,
    )


def most_repetitive_day_index(proposals: list[DailyProposal]) -> int:
    if len(proposals) < 2:
        return 0
    scores: list[float] = []
    for index, proposal in enumerate(proposals):
        others = [item for other_index, item in enumerate(proposals) if other_index != index]
        score = sum(
            _jaccard(
                (item.intent for item in proposal.activities),
                (item.intent for item in other.activities),
            )
            for other in others
        ) / len(others)
        scores.append(score)
    return max(range(len(scores)), key=lambda index: (scores[index], index))
