# System boundary

## Authoritative artifacts

```text
external authoring
    -> scenario JSON + personal ADL process package
    -> validation reports + canonical plan
    -> generated or imported home model
    -> resolved simulation bundle
    -> generated or imported sensor model
    -> execution trace
    -> observable sensor log
    -> synthetic workspace manifest, exports and reports
```

| Artifact | Producer | Authority | May contain oracle data? |
|---|---|---|---|
| Scenario | human, rule generator or external LLM | intended life | No |
| Personal ADL process package | human, rule generator or external LLM | possible resident-specific action flow | No |
| Simulation authoring bundle | external LLM | transport envelope containing scenario and personal process package | No |
| Authoring ingestion report | deterministic ingestor | whole-response validity and canonical artifact digests | No |
| Authoring repair request | deterministic ingestor | rejected source, diagnostics and immutable repair context | No |
| Behavior validation report | behavior validator | structural, graph and scenario compatibility | No |
| Validation report | validator | admissibility of the scenario | No |
| Canonical plan | compiler | planned activities for execution | No |
| Home generation policy/report | researcher + deterministic generator | reproducible layout controls and generation provenance | No |
| Home model | researcher or deterministic generator | executable metric environment and scenario bindings | No |
| Execution trace | simulator | what happened in the virtual world | Yes |
| Sensor deployment policy/report | researcher + deterministic deployer | reproducible deployment controls and provenance | No |
| Sensor model | researcher or deterministic deployer | device placement, timing and error semantics | No |
| Observable log | sensor models | what devices measured | No |
| Oracle ground truth | trace projector | semantic and causal truth | Yes |
| Sensor projection report | trace projector | projection counts, losses, noise and provenance | No |
| Synthetic workspace manifest | scenario-first orchestrator | roles, paths and canonical digests of a completed M3–M6 run | No |

## Stable boundary

The scenario and personal process package are stable, independently versioned authoring
contracts. No LLM controls the world or produces sensor measurements directly. Validators
are read-only: they accept or reject data and never repair it silently. A repair request
only packages feedback for a new external authoring pass; it does not edit or accept the
source. The process package describes possible behavior; only the simulator may turn it
into an executed trace.

The scenario-first generator is optional deterministic materialization, not an authoring
authority: it does not infer a real dwelling or repair scenario/process semantics. Its
home and sensor outputs have the same frozen contracts and pass the same M4/M6 gates as
researcher-authored alternatives. A workspace becomes visible only after every M2–M6
stage succeeds.

## Fundamental invariants

1. Every reference resolves to an entity in the same scenario or an explicitly versioned external catalog.
2. A resident cannot be assigned two incompatible mandatory activities at the same fixed time.
3. Scenario validation does not imply behavioural realism.
4. The same accepted scenario can be executed without access to its original author or LLM.
5. Observable records never acquire oracle identifiers merely because they exist internally.
