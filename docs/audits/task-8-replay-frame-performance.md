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
fixture is the canonical 364-day, full-density fixture with 1,635,504 events and 1,487,824
observations. It measured:

| Measure | Result |
| --- | ---: |
| Index construction | 56,574.115 ms |
| Median annual frame (100 deterministic seeks) | **1.468 ms** |
| Median annual bounded window | 5.061 ms |
| Annual state transitions | 65,104 |
| Annual resource events | 26,520 |
| Peak observed process working set during construction | about 2.53 GiB |

The annual median is below the <100 ms acceptance target with substantial margin. The extra
timeline metadata stores references and timestamps only; it does not materialize one world snapshot
per event or retain state outside the owning service.
