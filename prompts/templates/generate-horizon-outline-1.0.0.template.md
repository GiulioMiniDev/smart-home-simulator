# Horizon outline authoring prompt 1.0.0

## Instruction to the external LLM

Generate one horizon outline and its personal process package for the person described in the
final section of this document. The researcher description is the authoritative case
specification. It may be short, informal and written in any language. Preserve every stated fact
and constraint. Where information required by the contract is missing, make conservative,
internally consistent choices suitable for a plausible synthetic case, and record the material
inferred choices in `outline.provenance.parameters.authoringAssumptions`. Never present an
inference as an observed fact.

**Do not write the days of the horizon.** This is the difference between this prompt and every
earlier one. You describe the *structure* of the period — which recurring activities exist, how often they
recur, inside which hours, what changes over the months, what interrupts it — and a deterministic
expander turns that structure into every concrete day, computing sleep debt, hunger, social need
and fatigue as it goes. An outline for eight months and an outline for five years are the same
size.

This is not a stylistic preference. Single-response authoring of concrete days degrades with
horizon length: measured over this project's own generated cases, the ratio of distinct daily
signatures to days falls from 1.00 at a week to 0.74 at a month to 0.03 at eight months, where
244 days collapsed into seven templates repeated thirty-five times. The contract below removes the
possibility rather than asking you to avoid it.

Return exactly one JSON object and nothing else. No Markdown, no code fences, no comments, no
explanations, no ellipses, no placeholders, no alternative answers, no truncated arrays. The
top-level object must conform exactly to the embedded `horizon-authoring-bundle` schema and
contains two independently authoritative documents:

1. `outline`, describing the recurring activities, the habit bands they fall into, the world
   they happen in, and the arc of the period;
2. `personalProcessPackage`, describing how the resident performs each activity through typed
   personal ADL process models.

Construct the outline first, then the process package against it, then check both together.

## Mandatory provenance values

Use the following exact values in both nested provenance objects:

- `authorType`: `external_llm`;
- `generatorName`: `smart-home-simulator-external-llm-authoring`;
- `generatorVersion`: `1.4.0`;
- `promptTemplateVersion`: `generate-horizon-outline-1.0.0`;
- `humanReviewed`: `false`.

Set `modelName` to the actual model name exposed by the current interface and `generatedAt` to the
current timezone-aware timestamp. Do not use null, an empty string or an invented provider release
for any required provenance field.

## No absolute times

The outline carries **no timestamps**. The schema cannot express one, so an attempt to write a
date-and-time value is a validation failure rather than a stylistic lapse.

- a **date** (`YYYY-MM-DD`) selects a day: the span of a phase, the window an event may land in;
- a **band** (`HH:MM` to `HH:MM`) bounds the hours inside a day where something is acceptable;
- a **duration** is a range in minutes.

The single exception is `fixedCommitments`, where `startTime` and `endTime` are real clock times.
That is legitimate because those hours are fixed by someone other than the resident — a shift, a
class, an appointment. Everything the resident decides herself is a band.

Never narrow a band to force a particular moment. A band is your statement that anywhere inside it
is acceptable, and it is exactly the room the deterministic placement engine needs to resolve a
collision. A band of a few minutes on every recurring activity removes that room and makes the horizon
infeasible or unusably slow.

## Recurring activities

`outline.profile.recurringActivities` is the behavioural ground truth of the case, and the confirmed profile is
what any downstream habit-mining evaluation is scored against. Author it accordingly.

{{ACTIVITY_PORTFOLIO}}

### Every recurring activity, event and commitment declares its intent

{{CATALOG_INTENTS}}

`intent` is not free text and is not inferred from your label. Set it explicitly on **every
recurring activity, every event and every fixed commitment**, choosing the closest listed intent.
An unlisted value is rejected, and so is an omitted one whose label matches nothing — a silent
fallback would leave the scenario performing one activity while the process package implements
another. A commitment is an absence, so its intent is one of the away intents below.

The catalog is deliberately **home-centred**: it describes what happens inside the dwelling. Time
spent away — work, school, appointments, sport, an outing — is not modelled as detailed activity,
because none of it is observable by home sensors. What matters is only *that the resident is out*.
Do not invent intents for occupations, and do not build a detailed away-from-home routine: the
persona's job is useful context for shaping plausible activities at home, not something to simulate.

Declare each absence **exactly once**, choosing the form that fits:

- a **`fixedCommitment`** when the hours are set by someone else and repeat on given weekdays — a
  shift, a class, a standing appointment. It carries real clock times, its own validity dates, and
  an away `intent` like any other absence;
- a **recurring activity** with an away intent when the resident chooses when to go and it may drift — a gym
  session, a walk;
- an **event** for a bounded absence inside a date window — a trip, an appointment.

Do not describe the same absence twice. A `work_shift` recurring activity *and* a fixed commitment for the same
teaching hours put the resident at work twice over.

For each recurring activity:

- `cadence.period`, `timesPerPeriod` and `everyNPeriods` state how often it recurs; `weekdays`
  restricts it to particular days when the case says so, and is otherwise left empty;
- `cadence.windowStart` and `cadence.windowEnd` are the hours it may occupy. Make them as wide as
  the case honestly allows;
- `cadence.jitterMinutes` is how *irregular* this recurring activity is — how far a single occurrence wanders
  around its usual moment. A rigid anchor takes a small value, a loose optional one a large value.
  It is not the width of the band and must not duplicate it;
- `miningDifficulty` records how hard the activity should be to recover from sensor data: `easy` for
  a punctual daily anchor, `hard` for something sporadic or easily confused with another.

Do not give every recurring activity the same jitter or the same band. A profile in which everything is equally
regular describes a clock, not a person.

**Do not declare a recurring activity for waking or for the night.** The rhythm produces both — bedtime, the
length of each night, and the wake that follows — from the resident's chronotype and her
accumulated sleep debt. A `wake_up` or `sleep` activity would be scheduled a second time on the same
day and its band would argue with a night already placed. Describe the chronotype in `rhythm`
instead.

**A habitual nap, on the other hand, is a recurring activity.** A resident who dozes off on the sofa most
afternoons has a routine, and `rest_or_nap` states it like any other. It is not the same thing as
the nap the rhythm adds by itself when sleep debt has built up: that one is a response to a short
night, irregular by nature, and it is placed only if the afternoon still has room for it. Declare
the routine; leave the tiredness to the rhythm.

A band never crosses midnight: `windowStart` must be earlier in the day than `windowEnd`. Anything
that would need to wrap — a late evening running into the small hours — belongs to the night the
rhythm owns, not to a recurring activity.

## Habits: how the day divides

This is the word's technical sense in the smart-home literature, and it is **not** a synonym for a
recurring activity. A habit is *a sequence or interleaving of activities that happen in specific
contextual conditions* — what the resident does each morning between 08:00 and 10:00. It is a band
of the day; activities live inside it. In a published segmentation of a real home, the band
`05:15-07:00` turned out to be roughly 80% the sleeping activity, the rest being a bathroom trip
and the start of breakfast.

So there are three levels and you author two of them:

- an **action** is a sensor-level primitive; the simulator produces those, you do not;
- an **activity** is what the resident is doing, with a goal — `eat_breakfast`, `start_laundry`.
  You declare these as recurring activities, above;
- a **habit** is a band of the day in which a recognisable group of activities recurs. You declare
  these in `habits`.

Give the day between three and six bands: the night, the morning, whatever the middle of this
person's day looks like, the evening. Each has an id, a label a human would recognise, and its
`windowStart`/`windowEnd`. List in `recurringActivityIds` the activities you expect to populate it.

Two rules:

- **bands may not overlap.** They divide the timestamp axis, and a moment belonging to two habits
  would not be a division. Gaps are allowed — time no band claims is simply unsegmented;
- **the night band may cross midnight.** For habits only, `windowStart` later than `windowEnd`
  means the band wraps, which is how a night from 22:30 to 06:15 is written.

These bands are the answer sheet: a researcher's segmentation algorithm sees only a sensor log and
has to recover both where the day divides and what runs in each division. Declare them as the
person actually lives, not as a tidy grid.

## The arc of the period

A horizon longer than a few weeks that contains no phases and no events is a single week repeated,
and will be rejected in review. Use both.

`phases` are stretches over which the routine is not the baseline routine — a season, a course, a
period of illness, a change of job. A phase either **suspends** a recurring activity or **replaces its
cadence** for its own span, never both for the same one. Two phases that overlap in time may not
override the same activity: there would be no rule to choose between them.

`events` are things that happen a bounded number of times inside a date window. Set
`earliestDate` equal to `latestDate` only when the day is genuinely fixed; otherwise give a window
and let the expander place the event where the resident could plausibly absorb it. `occurrences`
may exceed one for something that spans several days.

An event that occupies the day names the recurring activities it pushes aside in `displaces`, and says for each
what becomes of that occurrence:

- `skip` — the occurrence simply does not happen. Use it when there is nothing to catch up on: a
  dinner at home during three days away is not made up later.
- `reschedule` — the occurrence moves to the nearest following day that is free of it. Use it for
  instrumental activities: shopping missed during a week of illness is done afterwards.

One event routinely needs both policies at once, which is why the choice is made per habit.

## The world

`outline.world` declares where the routine happens. It is stated once for the whole horizon.

{{CATALOG_ROOMS}}

Declare any further rooms the case needs, plus external locations, and a composite location
grouping the indoor rooms. Every resource sits in a declared location. `startLocationId` is where
the resident is at the first instant of the horizon and must be a primitive room, never a
composite.

`homeModel` is a synthetic versioned reference; the executable home is materialised later from
these declared locations.

## The rhythm

`outline.rhythm` gives the drive dynamics the few facts they need: `age`, any `health` conditions
that bear on sleep, and the `chronotypeBedtime` the resident tends towards. Everything downstream
of those — the actual bedtimes, the length of each night, sleep debt, naps, nocturnal waking — is
computed. Do not attempt to describe sleep patterns yourself; declare who the resident is.

### The package must also implement what the rhythm adds

{{RHYTHM_INTENTS}}

You do not declare these as recurring activities — the rhythm decides when they happen — but the
days will contain them, so `personalProcessPackage` must implement every one of them alongside the
intents your outline does declare. A package written only against the declared activities leaves
those days pointing at behaviour nobody authored: on the first eight-month case this produced 628
rejections for five missing models.

{{PROCESS_MODEL_SECTIONS}}

## Required final consistency checks

Before answering, verify all of the following:

- the top-level object validates against the embedded `horizon-authoring-bundle` schema;
- no value anywhere in `outline` is a date-and-time, except that `fixedCommitments` carry `HH:MM`
  clock times;
- the habit portfolio satisfies the stated minimum counts per kind;
- every `recurringActivityId` named by a phase override, an event displacement or a habit band
  exists in `outline.profile.recurringActivities`;
- `habits` declares between three and six bands, none of them overlapping, and at most one of them
  crossing midnight;
- no two overlapping phases override the same recurring activity;
- every phase and event date falls inside the horizon;
- `world.locations` declares every room listed above under the activity catalog;
- every resource's `locationId` and `startLocationId` resolve to declared locations, and
  `startLocationId` is not a composite;
- every recurring activity, event and fixed commitment declares an `intent` the catalog defines;
- every band has `windowStart` strictly before `windowEnd`, and every duration range has its
  minimum at or below its maximum;
- an event's `occurrences` does not exceed the number of eligible days in its window;
- the process package implements every intent the recurring activities, events and commitments
  imply, **and** the intents the rhythm adds by itself, listed above;
- the process package satisfies the
  action state continuity rules above.

## Authoritative output schema

The returned object must validate against this schema exactly.

{{OUTLINE_BUNDLE_SCHEMA_JSON}}

## Authoritative activity catalog

{{ACTIVITY_CATALOG_JSON}}

## Authoritative variable catalog

{{VARIABLE_CATALOG_JSON}}

## Authoritative action catalog

{{ACTION_CATALOG_JSON}}

## Researcher-supplied person and case description

<PERSON_AND_CASE_DESCRIPTION>
{{PERSON_AND_CASE_DESCRIPTION}}
</PERSON_AND_CASE_DESCRIPTION>
