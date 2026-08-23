# Replay frame performance evidence

**Date:** 2026-08-23
**Scope:** immutable annual replay frame reconstruction

The replay index remains owned by a `ReplayService` instance and is built only from immutable,
verified run artifacts. No module-level frame cache or cross-workspace state was introduced.

## Index design

The index retains the existing bounded event and sensor timelines, and adds compact binary-search
timelines for state-transition fields, completed and active movements, per-resident held-resource
state, and resource availability. A frame looks up the latest relevant delta for each live field
instead of folding all preceding transitions, movements, and resource events. Observable and Oracle
projection remains after reconstruction, so the index cannot disclose Oracle identity by itself.

## Equivalence evidence

The replay backend compares indexed reconstruction with the trusted full trace fold across 48
deterministic random timestamps in shuffled order, plus both trace boundaries. Existing tests keep
right-continuous duplicate-waypoint behavior and final-state verification. A benchmark regression
test counts applied transition deltas on a late 28-day seek and requires fewer than 100.

## Canonical benchmark

`reports/task8-frame-performance-current.json` contains the machine-readable capture. The annual
fixture is the canonical 364-day, full-density fixture with 1,635,816 events (including 312 daily
summaries) and 1,487,824 observations. It measured:

| Measure | Result |
| --- | ---: |
| Index construction | 54,578.166 ms |
| Median annual frame (100 deterministic seeks) | **1.392 ms** |
| Median annual bounded window | 4.945 ms |
| Annual state transitions | 65,104 |
| Annual resource events | 26,520 |
| Peak observed process working set during construction | about 2.53 GiB |

The annual median is below the <100 ms acceptance target with substantial margin. The extra
timeline metadata stores references and timestamps only; it does not materialize one world snapshot
per event or retain state outside the owning service.

## Daily-summary trace-family checkpoint

`dailySummaries` now appears as the `daily_summary` replay family. Each source summary has a stable
`daily_summary:<local-date>` identifier, its four authoritative activity-status counts, and a
`completed` status. Its availability timestamp is the next local midnight in the scenario timezone
(or the trace's aware offset for legacy runs without a scenario), clamped to `trace_end`; no
`final_state` replay event is synthesized. The bounded benchmark query
filters this family directly and asserts a non-zero canonical count. Observable projection keeps
the generic `Daily Summary event` label and the same aggregate counts while omitting actor,
activity, action, and causal identity; Oracle retains the same counts.
