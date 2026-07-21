# Milestone 5.1 closure audit

- **Status:** complete and frozen
- **Contract version:** `1.0.0`
- **Closure date:** 2026-07-21
- **Decision records:** `ADR-012`, `ADR-013`
- **Portability amendment:** M5.1.1 (no public contract change; first green three-OS CI
  run required as external verification evidence)

## Acceptance evidence

| Requirement | Evidence |
| --- | --- |
| Real parallelism | Four seed variants execute in four observed worker processes |
| Isolation | Every run owns its effective bundle, engine, trace and report |
| Determinism | Per-run semantic digests match between one and four workers |
| Replay | Each trace replays against the materialized effective bundle |
| Failure isolation | A missing or failing bundle does not cancel valid siblings |
| Resume | Only hash- and digest-consistent completed runs are reused |
| Publication safety | Unique atomic temporaries and a non-blocking output lock prevent collisions |
| Platform gate | Lazy POSIX/Windows lock backends plus a mandatory Python 3.12 CI matrix for Linux, macOS and Windows |
| Public contracts | Manifest and report schemas are Draft 2020-12 with checksum sidecars |
| Performance | The four-run parallel benchmark remains below its 30-second target |
| Quality | Full tests, lint, exact coverage gate and end-to-end benchmark pass |

## Reference manifest

`examples/batch/mario_week.seed-sweep.json` defines four independent executions of the
M5 acceptance bundle with seeds 101, 202, 303 and 404. Batch outputs are intentionally
generated in temporary or researcher-selected experiment directories rather than frozen
as duplicate multi-megabyte repository artifacts.
