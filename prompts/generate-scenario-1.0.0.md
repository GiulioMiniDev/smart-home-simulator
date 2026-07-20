# Scenario generation prompt 1.0.0

## System instruction

You generate one complete smart-home life scenario for the supplied residents and time
window. Return only one JSON object conforming exactly to
`schemas/scenario-1.0.0.schema.json`. Do not emit Markdown, comments, explanations,
non-finite numbers, unknown properties, executed timestamps, trajectories, sensor events,
or claims about what actually happened.

The scenario describes intended life before execution. Use only identifiers declared in
the document. Every date in the simulation window must be present. Activities must use an
`intent` contained in `activity-catalog-1.0.0.json`. Preserve uncertainty through windows,
duration ranges, conditions, optional activities, fallbacks and runtime event candidates;
do not resolve it by inventing execution outcomes.

## User template

Generate the scenario from the following authoritative inputs:

```json
{
  "researchObjective": {{RESEARCH_OBJECTIVE_JSON}},
  "simulationWindow": {{SIMULATION_WINDOW_JSON}},
  "timeZone": {{IANA_TIME_ZONE_JSON}},
  "seed": {{SEED_JSON}},
  "residents": {{RESIDENT_PROFILES_JSON}},
  "habitDescriptions": {{HABITS_JSON}},
  "calendar": {{CALENDAR_JSON}},
  "homeSummary": {{HOME_SUMMARY_JSON}},
  "externalPeople": {{EXTERNAL_PEOPLE_JSON}},
  "runtimeVariability": {{RUNTIME_VARIABILITY_JSON}}
}
```

Authoritative supporting documents:

- `schemas/scenario-1.0.0.schema.json`;
- `activity-catalog-1.0.0.json`;
- `variable-catalog-1.0.0.json`.

Before returning the JSON, verify internally that references resolve, timestamps use the
declared zone, required dates are present, mandatory fixed activities do not overlap and
each activity has a duration or end window. Return the JSON object only.
