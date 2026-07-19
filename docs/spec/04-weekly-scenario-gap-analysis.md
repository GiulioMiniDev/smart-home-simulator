# Weekly scenario gap analysis

The illustrative Mario week contains 173 activity records and exercises requirements that were not representable by the initial `0.1.0` draft. Every item below is resolved in the frozen contract `1.0.0`.

| Requirement found in the week | Decision for `1.0.0` |
|---|---|
| Activities scheduled only through predecessors | Start windows become optional when a dependency or fallback supplies placement |
| `after` and `afterAny` | Versioned dependency groups with `all` and `any` modes |
| Conditional replacements | Explicit fallback activation referencing the replaced activity |
| Activities spanning multiple rooms | `locationIds` replaces a single destination |
| Work and sleep expressed by an end | Optional end window in addition to duration |
| Fixed work and social commitments | First-class commitments with participants and interval |
| Initial fatigue, inventory and pending tasks | Structured resident initial states with extensible facts |
| Calendar and weather | Typed day context with extensible facts |
| Supermarket queues and interruptions | Seeded runtime event candidates with trigger and typed operation |
| External LLM provenance | Generator, model, prompt and review metadata |
| Friends and relatives taking part in activities | External people, distinct from simulated residents |
| Daily revalidation | Explicit materialization policy |
| Catalog and model versions | Versioned external model references |
| Output requests | Declarative output selection, without implementing exporters |

## Explicitly deferred

- room connectivity and path finding;
- coordinates, polygons and obstacles;
- sensor placement, coverage and noise;
- activity execution templates;
- schedule resolution;
- runtime state transitions.

The `1.0.0` validator may verify identifiers and definite contradictions. It must not perform work assigned to the plan compiler or simulator.

The migrated acceptance document is `examples/valid/mario_week.json`; `tools/migrate_legacy_week.py` makes the transformation reproducible from the original research note.

During Milestone 2 the compiler proved that the original 08:00 weekday commitments were infeasible: the earliest valid morning chain and minimum commute arrive at 08:08. The acceptance fixture now uses the already-declared latest work start, 08:15. This is a correction to example data, not a change to scenario contract `1.0.0`; the compiler retains a regression test showing that the former value fails with `MAIN_PLAN_INFEASIBLE`.
