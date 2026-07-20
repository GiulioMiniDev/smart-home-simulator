# End-to-end simulation input generation prompt 1.0.0

## Instruction to the external LLM

Generate one complete smart-home simulation authoring bundle for the person or people
described in the final section of this document. The researcher description is the
authoritative case specification. It may be short, informal and written in any language.
Preserve every stated fact and constraint. Where information required by the contract is
missing, make conservative, internally consistent choices suitable for a plausible
synthetic case; record the material inferred choices in
`scenario.provenance.parameters.authoringAssumptions`. Never present an inference as an
observed fact.

Return exactly one JSON object and nothing else. Do not return Markdown, code fences,
Mermaid, comments, explanations, ellipses, placeholders, multiple alternative answers or
truncated arrays. The top-level object must conform exactly to the embedded
`simulation-authoring-bundle` schema. It contains two independently authoritative
documents:

1. `scenario`, describing the intended life, calendar, state, activities and runtime
   uncertainty of the supplied residents;
2. `personalProcessPackage`, describing how those same residents perform every activity
   in that exact scenario through typed personal ADL process models.

Construct the scenario first internally, then construct the process package against the
finished scenario, and finally check both documents together before answering. Do not
emit execution outcomes, trajectories, sensor events or claims about what actually
happened. Actual branch choices, durations, timestamps and effects are decided later by
the deterministic simulator from context and seed.

## Scenario authoring rules

1. Use schema version `1.0.0` and document type `life_scenario`.
2. Use only activity `intent` identifiers declared by the embedded activity catalog. The
   project activity identifiers are authoritative; external taxonomies are metadata only.
3. Create one `DayPlan` for every local date intersecting the simulation window. If the
   researcher does not specify an interval, generate seven consecutive complete local
   days and record the chosen dates as an authoring assumption.
4. If no seed is specified, use `1`. Use an IANA time-zone identifier and timezone-aware
   timestamps everywhere.
5. Represent uncertainty through windows, duration ranges, conditions, optional
   activities, fallbacks and runtime-event candidates. Do not resolve uncertainty by
   inventing executed results.
6. Residents contain all personal facts needed by the embedded variable catalog. Initial
   state is authoritative at `simulationWindow.start`.
7. Declare every referenced resident, external person, location and resource. Keep
   simulated residents distinct from social participants who are not simulated.
8. When the description does not define a house, declare a conservative logical set of
   locations and resources sufficient for the activities, and use a clearly synthetic
   `homeModel.referenceId`. Concrete geometry and capability binding occur later.
9. Mandatory fixed activities must not overlap for the same resident. Every activity has
   a duration or end window, and every reference and dependency resolves.
10. Set provenance truthfully: `authorType` is `external_llm`, identify the actual model,
    set `promptTemplateVersion` to `generate-simulation-inputs-1.0.0`, include an aware
    generation timestamp and keep `humanReviewed` false unless review really occurred.

## Personal ADL process-model rules

1. Copy `sourceScenarioId` and `sourceScenarioVersion` from the generated scenario.
2. Reference exactly the three embedded catalog identifiers and versions.
3. Create process models only for residents declared by the generated scenario.
4. Every activity in every day, including conditional and fallback activities, resolves
   to exactly one applicable binding. Reuse a process model only when its actual action
   flow is identical.
5. For each intent, copy the ordered activity-catalog `components` into
   `implementedComponents` and realize every component in the same order through the
   component's required action types. Matching only the intent name is invalid.
6. Every model has exactly one `start`, at least one `end`, no dead nodes, and every node
   lies on a path from the start to an end.
7. Use only embedded action types and declared parameters. Use structured
   `ValueExpression` objects; never hide multiple actions in a label or invent prose
   actions.
8. Every action has a positive `durationWeight`. Add an absolute bounded `duration` only
   when the researcher description supports that personal timing.
9. Choice nodes have at least two outgoing branches, exactly one default, and a declared
   variable condition on each non-default branch.
10. Parallel splits have a matching join. Every cycle passes through an explicit `loop`
    node with finite `maxIterations`.
11. Use only embedded variables. Add contextual bindings only when behavior changes with
    that context and always provide an unambiguous ordinary fallback.
12. Model movement, posture, resource use and object interaction at the granularity from
    which later execution and sensor activation can be derived. Do not replace an ADL
    with an equally abstract single action.
13. Set provenance truthfully as required for the scenario and use the same actual model,
    prompt version and generation timestamp. Do not claim human review.

## Required final consistency checks

Before answering, verify internally that:

- the top-level response has exactly `schemaVersion`, `documentType`, `scenario` and
  `personalProcessPackage`;
- both nested documents satisfy their embedded structural contracts without unknown
  properties;
- all scenario references, timestamps, dates, dependencies and mandatory schedules are
  valid;
- the process package targets the exact generated scenario and exact embedded catalogs;
- every scenario activity has exactly one applicable binding;
- every declared component is implemented by an ordered compatible action sequence;
- every graph terminates, all branches are complete and every action and variable exists;
- output provenance is truthful and the JSON is complete.

The deterministic project validators reject the whole bundle and publish no simulator
inputs if either nested document fails.

## Authoritative output schema

The following JSON Schema Draft 2020-12 is complete and self-contained:

```json
{{BUNDLE_SCHEMA_JSON}}
```

## Authoritative activity catalog

```json
{{ACTIVITY_CATALOG_JSON}}
```

## Authoritative variable catalog

```json
{{VARIABLE_CATALOG_JSON}}
```

## Authoritative action catalog

```json
{{ACTION_CATALOG_JSON}}
```

## Researcher-supplied person and case description

Replace the marker below with the free-form description of the person or people to
simulate, their habits, relevant constraints and any desired dates, home facts or research
objective. No additional structured authoring file is required.

<PERSON_AND_CASE_DESCRIPTION>
{{PERSON_AND_CASE_DESCRIPTION}}
</PERSON_AND_CASE_DESCRIPTION>
