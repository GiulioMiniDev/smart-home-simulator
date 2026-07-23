# Hybrid Planning Guardrails and A/B Regeneration Design

## Objective

Improve the accepted one-month hybrid plan without changing Tommaso Bianchi's
frozen behavioral profile, the LM Studio model, the date interval, or the
seven-day chunk size. Generate the same month into a separate output directory
and compare the original hybrid month, the guarded month, and the original
seven-day baseline without exposing the baseline to the model.

The guarded planner must preserve semantic variety while making planned habits
faithful enough for habit-mining experiments.

## Controlled A/B Conditions

The comparison keeps these inputs identical:

- planning case and resident identity;
- frozen behavioral-profile file and digest;
- `qwen2.5-coder-7b-instruct`;
- 2026-08-10 inclusive through 2026-09-10 exclusive;
- seven-day chunks;
- plan-only execution;
- baseline isolation from every LLM request.

Only planner guardrails, validation, and repair behavior change.

## Selected Approach

Keep the LLM responsible for narratives, optional activities, and meaningful
variation. Make the software authoritative for habit budgets, daily-life
completeness, preferred habit fields, semantic dependencies, and longitudinal
acceptance.

This avoids two undesirable extremes:

- exact fully deterministic day templates, which would damage variety;
- prompt-only guidance, which the first month showed is not reliable enough.

## Components

### Daily-life policy

Add a focused policy module that declares reusable intent groups and minimum
daily density:

- nourishment intents;
- hygiene intents;
- walking intents;
- work-travel and family-visit semantic chains;
- minimum six activities on workdays;
- minimum five activities on weekends;
- at least one nourishment and one hygiene activity every day.

The policy uses only the planning case and the activity catalog. It never reads
the baseline.

### Binding habit targets

`targetOccurrences` becomes the effective per-chunk cap for non-anchor profile
habits. The existing maximum remains a safety ceiling, while target zero
forbids an occurrence in that chunk.

The existing cadence carry remains responsible for moving fractional expected
support across chunks. Exact target realization therefore produces roughly
four or five occurrences for a weekly habit in a 31-day month and schedules a
yearly habit only when its accumulated cadence reaches an occurrence.

Weekly goal allocation continues to reserve target occurrences for their
assigned dates. Extra occurrences are removed deterministically and recorded.
The habit gate rejects both missing and excess target occurrences.

### Preferred-field normalization

For each activity mapped to a non-anchor profile habit:

- retain an already preferred time band;
- otherwise select the first preferred time band;
- retain an allowed location;
- otherwise select the first allowed location.

Every change is written to a normalization artifact. Materialization still
checks capacity and ordering after normalization.

### Semantic dependency validation

Introduce reusable rules independent of the frozen profile:

- `post_walk_shower` requires an earlier walking intent;
- `visit_mother_and_have_dinner` requires an earlier
  `travel_to_mothers_home` and a later `travel_home`;
- `work_shift` requires an earlier `commute_to_work` and a later
  `commute_home`;
- outbound or return work travel requires a work shift in the correct order.

Profile-declared predecessor and successor rules remain active. The software
rules fill gaps in the frozen profile without changing its identity or digest.

### Daily repair

The initial daily prompt receives the daily-life and semantic policy. After
anchor, budget, and preferred-field normalization, the daily validator checks:

1. identifiers and locations;
2. assigned weekly goals;
3. routine anchors;
4. binding habit targets;
5. daily-life categories and density;
6. semantic dependency order;
7. materialization feasibility.

A failure produces one precise structural-repair request for that day. The
model returns a complete replacement day. Exhausting the configured repair
count fails the chunk without advancing the checkpoint.

### Longitudinal quality

Extend the longitudinal report with:

- mean, minimum, and maximum daily activity counts;
- sparse-day violations;
- missing daily-life category violations;
- semantic dependency violations;
- one metric per profile habit containing expected support, observed support,
  temporal adherence, and target deviation.

A completed month is invalid when:

- any essential category is missing;
- any day is below its density floor;
- any semantic dependency is incomplete;
- a profile habit is outside the rounded typical-cadence envelope;
- temporal adherence is below 100%;
- existing duplicate-day or weekly-variable-shell gates fail.

Chunk-level binding targets remain the authoritative frequency gate; the
monthly envelope is an independent audit.

## Data Flow

For every chunk:

1. derive the budget from the frozen profile and incoming ledger;
2. generate and canonicalize the weekly brief;
3. generate a daily proposal with policy guidance;
4. canonicalize anchors;
5. reserve future weekly goals;
6. constrain non-anchor habits to binding targets;
7. normalize profile time bands and locations;
8. validate daily-life and semantic rules;
9. repair the day when necessary;
10. run diversity and exact habit-target gates;
11. compile and validate the scenario;
12. evaluate the accumulated longitudinal plan;
13. atomically advance the checkpoint only after every gate passes.

## Error Handling and Auditability

No invalid output is patched by hand or accepted through a bypass.

Artifacts record:

- target-limit removals;
- preferred-field normalizations;
- every LLM request and response;
- structural and diversity repairs;
- exact habit-gate violations;
- daily-life and semantic violations;
- accumulated longitudinal metrics.

Failed chunk attempts remain local audit artifacts. The new month uses a
separate ignored output directory so the first month remains immutable.

## Testing

Test-driven implementation covers:

- target-zero removal;
- removal above target but below maximum;
- exact target missing and exceeded violations;
- time-band and location normalization;
- nourishment, hygiene, and density failures;
- every semantic dependency and ordering rule;
- successful structural repair of a policy violation;
- extended longitudinal metrics and failure reasons;
- backward compatibility for ordinary non-hybrid simulation tests;
- a completed five-chunk fake month;
- live one-month regeneration through LM Studio.

## A/B Evaluation

After the guarded month completes, create a report comparing:

- accepted days and chunks;
- total and daily activity density;
- daily signature entropy and consecutive similarity;
- habit target versus actual support;
- temporal and location adherence;
- nourishment and hygiene coverage;
- semantic-chain completeness;
- repair counts;
- the guarded first week versus the isolated original baseline.

The guarded month is considered an improvement only if it keeps high variety
while eliminating the target, preferred-band, daily-life, and semantic defects
found in the first month.
