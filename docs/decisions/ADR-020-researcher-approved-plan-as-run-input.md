# ADR-020: The reviewed planimetry is an input to the run, not a byproduct of it

- Status: accepted and implemented
- Date: 2026-08-08
- Amends [ADR-015](ADR-015-scenario-first-environment-materialization.md), whose promise that
  "imported or manually designed homes and custom sensor models remain supported overrides" was
  true of the contracts and false of the application.

## Context

ADR-015 made the home a derived artifact: from an accepted scenario and process package, an
explicit policy materializes rooms, furniture, sensors and bindings, and the researcher reaches a
first simulation without drawing anything. That is the right default and it stays the default.

What it did not settle is what happens after the researcher looks at the result. The application
has had a plan editor since M7 — rooms, obstacles, providers, sensors, undo, publication as an
immutable revision — and every published revision was authoritative for validation, export and
display. It was not authoritative for the only thing that matters: **the run regenerated the home
from the policy every time**. `materialize_workspace` called `generate_home` and `deploy_sensors`
unconditionally; the generated-horizon run re-read the bundles produced during generation and
redeployed their sensor field. A researcher could move a PIR, publish it, press *Run simulation*
and get observations from the sensor they had just moved away from — with no error, because
nothing was wrong: the run had simply never been told.

This is worse than a missing feature. The plan and the sensor field determine walking distances,
reachability, coverage and therefore the observable log itself. An editor whose edits do not reach
the simulation is an invitation to draw the wrong conclusion from a dataset.

## Decision

**A home's plan is either a recommendation or a decision, and the run can tell the difference.**

Home and sensor revisions carry `provenance.approval`. Deterministic pipelines publish
`recommended`; the editor and the explicit confirmation publish `researcher`. `plan_approval`
is the single place that reads it.

**An approved model replaces its policy step; it never merely accompanies it.**

- `materialize_workspace` takes `approved_home` / `approved_sensors`. When present it skips
  `generate_home` / `deploy_sensors` and writes no generation report for what it did not generate.
- `simulate_horizon` rebinds each generated day's bundle onto the approved plan and installs the
  approved field instead of redeploying it.
- Both runs publish `plan-approval.json`, recording which of the two models the researcher
  supplied and the digest of each.

**Approval is not an exemption from the gates.** An approved home passes `validate_home_model`,
the M4 binding and route gates and the M6 sensor contract exactly as a generated one does. A new
`rebind_bundle_home` re-runs precisely the home-dependent gates on an already accepted bundle —
home validation, scenario compatibility, action bindings, kinematics, routes — and nothing else,
because the scenario, the canonical plan and the package are unchanged by moving a wardrobe.

**A rejected approved model fails the run.** There is no silent fallback to the policy: simulating
a home the researcher did not agree to, and labelling the result with their approval, is the one
outcome worse than stopping.

**Confirming changes nothing except who is answerable for it.** The researcher who accepts the
proposal untouched creates a new revision of the same artifact, so the home's history shows when it
stopped being a proposal, and the runs stop regenerating it.

## Consequences

- The plan editor becomes what it always looked like. Rooms, furniture, PIR positions and coverage
  can be dragged and resized directly on the planimetry, and what is published is what is executed.
- No contract version moves. `home_model`, `sensor_model` and the bundle stay 1.0.0; this is a
  decision about which instance of them a run consumes.
- Rebinding a horizon costs the home-dependent gates per day, not a recompilation: the canonical
  plan does not depend on the home, and re-proving its digest would cost one CP-SAT solve per day
  (see [ADR-019](ADR-019-canonicalization-cost-and-compilation-budget.md)).
- A run made from an approved plan is still fully reproducible: the plan is an immutable workspace
  artifact, its digest is in the run's own manifest, and replay verifies the published content.
- Homes that nobody has reviewed behave exactly as before, so no existing workspace changes
  meaning by upgrading.
- Left open: an approved plan is not automatically re-checked when a *new* scenario revision is
  imported. The gates still refuse a plan that cannot bind, so the failure is loud rather than
  silent, but the researcher is the one who decides whether to re-approve or regenerate.
