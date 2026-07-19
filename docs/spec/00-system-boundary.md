# System boundary

## Authoritative artifacts

```text
scenario JSON
    -> validation report
    -> canonical plan
    -> execution trace
    -> observable sensor log
    -> exports and reports
```

| Artifact | Producer | Authority | May contain oracle data? |
|---|---|---|---|
| Scenario | human, rule generator or external LLM | intended life | No |
| Validation report | validator | admissibility of the scenario | No |
| Canonical plan | compiler | planned activities for execution | No |
| Execution trace | simulator | what happened in the virtual world | Yes |
| Observable log | sensor models | what devices measured | No |
| Oracle ground truth | trace projector | semantic and causal truth | Yes |

## Stable boundary

The scenario is the stable input contract. No LLM controls the world or produces sensor measurements directly. The validator is read-only: it accepts or rejects data and never repairs it silently.

## Fundamental invariants

1. Every reference resolves to an entity in the same scenario or an explicitly versioned external catalog.
2. A resident cannot be assigned two incompatible mandatory activities at the same fixed time.
3. Scenario validation does not imply behavioural realism.
4. The same accepted scenario can be executed without access to its original author or LLM.
5. Observable records never acquire oracle identifiers merely because they exist internally.

