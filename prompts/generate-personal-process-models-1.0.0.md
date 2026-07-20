# Personal ADL process-model generation prompt 1.0.0

## System instruction

You generate the complete package describing how the residents of one accepted scenario
perform their activities. Return only one JSON object conforming exactly to
`schemas/personal-process-package-1.0.0.schema.json`. Do not emit Markdown, Mermaid,
comments, explanations, executable code, unknown properties or action labels written as
free text.

The process models are personal behavioral models, not execution traces. They describe
allowed control flow and typed actions. Actual branch choices, durations, timestamps and
world effects are decided later by the deterministic simulator from context and seed.

## Authoritative rules

1. Copy `sourceScenarioId` and `sourceScenarioVersion` from the supplied scenario.
2. Use exactly the three supplied catalog identifiers and versions.
3. Create process models only for residents declared by the scenario.
4. Every activity record in every day, including conditional and fallback activities,
   must resolve to exactly one applicable binding. A binding may reuse a process model
   when the actual action flow is identical.
5. Copy the ordered activity-catalog `components` into `implementedComponents` and
   implement every one of them in the graph. Matching only the intent name is invalid.
6. Every process model has exactly one `start` node, at least one `end` node and no dead
   nodes. Every node lies on a path from start to an end.
7. Use only action types and parameters declared in the action catalog.
8. Use structured `ValueExpression` objects. Do not hide multiple actions in a label or
   invent prose actions.
9. Give every action node a positive `durationWeight`; add a bounded `duration` only when
   personal evidence supports an absolute local range.
10. Choice nodes have at least two outgoing branches, exactly one default branch and a
   declared variable condition on every non-default branch.
11. Parallel splits have a matching join. Every cycle passes through an explicit `loop`
   node with a finite `maxIterations`.
12. Reference only variables declared by the variable catalog. Use context-specific
    bindings only when the person's behavior actually changes; use an explicit fallback
    binding for the ordinary behavior.
13. Models must be detailed to the granularity at which movement, posture, resource use,
    object interaction and later sensor activation can be derived. Do not replace an ADL
    with one equally abstract action.
14. Record the actual model name, prompt version, generation timestamp and review status
    in `provenance`. Do not claim human review unless it occurred.

## User template

Generate a personal process package from:

```json
{
  "scenario": {{VALIDATED_SCENARIO_JSON}},
  "residentHabitEvidence": {{RESIDENT_HABIT_EVIDENCE_JSON}},
  "availableHomeCapabilities": {{HOME_CAPABILITY_SUMMARY_JSON}},
  "generationConstraints": {{GENERATION_CONSTRAINTS_JSON}}
}
```

Authoritative supporting documents:

- `schemas/personal-process-package-1.0.0.schema.json`;
- `activity-catalog-1.0.0.json`;
- `variable-catalog-1.0.0.json`;
- `action-catalog-1.0.0.json`.

Before returning the JSON, verify internally that all scenario activities are covered,
catalog identifiers match, every graph terminates, all branches are complete and all
actions are catalog actions. Return the JSON object only. The package will be rejected by
a deterministic validator if any rule is violated.
