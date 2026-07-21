# Milestone 5 closure audit

- **Status:** complete and frozen
- **Contract version:** `1.0.0`
- **Closure date:** 2026-07-21
- **Decision records:** `ADR-010`, `ADR-011`

## Acceptance evidence

| Requirement | Evidence |
| --- | --- |
| Complete weekly execution | 172 activity outcomes, 769 executed actions and zero failed activities |
| Complete vocabulary | All 27 action types execute through strict catalog handlers |
| Process semantics | Choice, bounded loop and three parallel models execute with typed branches |
| Spatial truth | 202 collision-free movement episodes and independently checked waypoints |
| State and causality | 1,139 state transitions with stable causes and final closed world state |
| Shared resources | Atomic acquisition, stable priority queues and real pre-emption are tested; every capacity event is traced and every resource returns to full availability |
| Runtime variability | Five candidates are sampled from independent named streams; two occur for the golden seed |
| Contingency behavior | Tuesday rain and unavailable leftovers produce three explicit dropped/replaced outcomes |
| Strict failure contract | The legacy M4 bundle fails on its first undeclared action precondition and publishes no trace |
| Reproducibility | Two executions and internal replay produce the same semantic digest |
| Public contracts | Three Draft 2020-12 schemas and checksum sidecars match the Pydantic models |
| Performance | Complete weekly simulation remains below the 15-second acceptance target |
| Quality | Full tests, schema generation, artifact regeneration, lint and coverage gate pass |

## Golden result

- corrected source scenario: `examples/valid/mario_week.runtime-1.1.0.json`;
- behavior package: `examples/behavior/mario_rossi_week_2026_10_12.behavior-1.1.0.json`;
- bundle: `examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json`;
- trace: `examples/execution/mario_week.execution-trace.json`;
- report: `examples/execution/mario_week.simulation-report.json`;
- replay report: `examples/execution/mario_week.replay-report.json`.

The golden seed executes 123 activities without deviation, 46 with an explicitly traced
deviation and three declared contingency outcomes. The final resident state is in the
bedroom, at home, idle and holds no resource. Medication inventory closes at 34 doses
after seven administrations and one refill.

## Final gate

```bash
make check
```

Any failure in upstream regeneration, strict execution, invariant checking, semantic
replay, schema checksums, lint, coverage or benchmark keeps the milestone closed.
