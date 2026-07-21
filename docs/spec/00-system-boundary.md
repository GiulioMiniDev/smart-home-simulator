# System boundary

## Authoritative artifacts

```text
external authoring
    -> scenario JSON + personal ADL process package
    -> validation reports + canonical plan
    -> resolved simulation bundle
    -> execution trace
    -> observable sensor log
    -> exports and reports
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
| Execution trace | simulator | what happened in the virtual world | Yes |
| Sensor model | researcher | device placement, timing and error semantics | No |
| Observable log | sensor models | what devices measured | No |
| Oracle ground truth | trace projector | semantic and causal truth | Yes |
| Sensor projection report | trace projector | projection counts, losses, noise and provenance | No |

## Stable boundary

The scenario and personal process package are stable, independently versioned authoring
contracts. No LLM controls the world or produces sensor measurements directly. Validators
are read-only: they accept or reject data and never repair it silently. A repair request
only packages feedback for a new external authoring pass; it does not edit or accept the
source. The process package describes possible behavior; only the simulator may turn it
into an executed trace.

## Fundamental invariants

1. Every reference resolves to an entity in the same scenario or an explicitly versioned external catalog.
2. A resident cannot be assigned two incompatible mandatory activities at the same fixed time.
3. Scenario validation does not imply behavioural realism.
4. The same accepted scenario can be executed without access to its original author or LLM.
5. Observable records never acquire oracle identifiers merely because they exist internally.
