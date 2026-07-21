# Milestone 6 closure audit

- **Status:** complete and frozen
- **Contract version:** `1.0.0`
- **Closure date:** 2026-07-21
- **Decision record:** `ADR-014`

## Acceptance evidence

| Requirement | Evidence |
| --- | --- |
| Supported devices | Five geometric PIRs, an action-driven entrance contact, a fact-driven object contact and a temperature sensor execute their full nominal semantics |
| Event-driven projection | Analytic trajectory crossings, action executions and state transitions are projected without a global sensor tick |
| Authoritative floor plan | Projection requires the exact source bundle and validates sensor catalogs, positions and coverage against its embedded researcher-provided home model |
| PIR semantics | Required coverage, segment intersection, ON/OFF hold pulses and grouped suppression are tested |
| Contact semantics | Both fact transitions and door-action OPEN/CLOSED pulses are present in the golden corpus |
| Temperature semantics | Delay, rise, decay and sampling produce a bounded response curve from and back to baseline |
| Timing and failures | Latency, jitter, cooldown and bounded failure windows are applied per device |
| Error model | Golden totals exercise 21 dropouts, 10 false negatives, 32 cooldown suppressions, 2 failure suppressions, 6 false positives and 119 noisy observations |
| Random isolation | Trace/model seed equality is enforced; each sensor and error concern owns a SHA-256-derived named stream |
| Oracle separation | Public records contain no resident, activity, action, trace or causal identifier |
| Causal traceability | Every public observation has exactly one separate oracle link |
| Tamper resistance | Bundle identity/digest/seed mismatch, invalid M5 semantic digests and inconsistent public content-addressed IDs stop publication |
| Publication safety | The three outputs are staged together and the hash-bearing success report is the last commit marker; injected staging failure leaves no partial data artifacts and emits a failed report |
| Accounting | All 1,173 nominal candidates are partitioned exactly among observations and the four loss causes; noise subsets are validated |
| Public contracts | Four Draft 2020-12 schemas have checksum sidecars and golden validation |
| Acceptance corpus | Eight sensors produce 1,108 public records and 1,108 oracle links for the golden week |
| Performance | Weekly projection remains below the 5-second acceptance target |
| Quality | Full test suite, lint, exact coverage gate, CLI and benchmark pass |

The acceptance model is `examples/sensors/mario_monteverde.sensor-model.json`. Golden
observable, oracle and report artifacts are generated from the frozen M5 trace by
`tools/build_sensor_artifacts.py`; regeneration is deterministic.

The terminal `make check` run on 2026-07-21 passed all 406 tests in 77.01 seconds with
95.26% total coverage, the enforced 95% threshold, Ruff lint and format checks, every
upstream validation/compile/simulate/replay command and all benchmarks. The M6 weekly
projection completed in 0.293 seconds against the 5-second acceptance ceiling.

## Requirement-to-test matrix

| Contract property | Executable evidence |
| --- | --- |
| Determinism, privacy and one-to-one oracle links | `test_acceptance_projection_is_deterministic_and_separates_oracle` |
| Per-sensor random isolation | `test_each_sensor_has_an_independent_random_stream` |
| Coverage, cooldown and analytic crossing | `test_pir_coverage_polygon_and_cooldown`, `test_pir_detects_segment_crossing_without_a_waypoint_inside` |
| Loss, failure and false-positive accounting | `test_dropout_false_negative_failure_and_false_positive_counters` |
| Contact latency/jitter, door pulses and thermal curve | `test_contact_and_temperature_semantics` |
| Bundle, seed and trace integrity | `test_projection_rejects_mismatched_or_tampered_trace` |
| Home-bound placement and wall containment | `test_sensor_placement_is_validated_against_source_home` |
| Model reference and contract invariants | `test_sensor_model_rejects_unknown_references`, `test_sensor_contract_validators` |
| No partial CLI success | `test_projection_failure_does_not_publish_partial_artifacts`, `test_project_sensors_does_not_publish_partial_success_on_output_failure` |
| Content-addressed public artifacts | `test_public_artifact_contracts_reject_inconsistent_content` |
| Frozen schemas, checksums and golden conformance | `test_sensor_schemas_match_models_and_golden_artifacts`, `test_frozen_schema_checksums_match` |
