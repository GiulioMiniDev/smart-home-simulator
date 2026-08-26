# Horizon outline authoring prompt 1.1.0

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
- `promptTemplateVersion`: `generate-horizon-outline-1.1.0`;
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
another. A commitment is an absence, so its intent is one of the away intents above.

**Never coin an intent.** The two lists above are the whole vocabulary; an identifier that is not
in them does not exist no matter how ordinary it sounds. Expansion stops on the first one with

> `declare an intent the activity catalog does not define: activity 'ra_cook_dinner' -> 'cook_dinner'`

and nothing is imported. The failures are always the same shape — a plausible compound the catalog
happens to spell differently, or a household task the catalog simply does not model:

- there is **no** generic cooking intent. A meal is `prepare_light_dinner`, `prepare_simple_lunch`
  or `weekly_meal_preparation`, and eating it is `eat_breakfast`, `eat_lunch` or `eat_dinner`;
- there is **no** bathroom-cleaning and **no** vacuuming intent. Housework inside the dwelling is
  `clean_kitchen` or `tidy_living_room_and_hallway`, and nothing else;
- washing is `morning_toilet_and_wash`, `morning_toilet_and_shower` or `evening_hygiene`.

When the case describes something the catalog has no intent for, do one of two things: carry it on
the **nearest listed intent** and say so in the activity's `note`, or leave it out of the outline
entirely. Both are correct. Inventing an identifier is not, and neither is inventing one in the
process package: a binding or process model for an intent the outline cannot declare is dead weight
the import rejects.

The catalog is deliberately **home-centred**: it describes what happens inside the dwelling. Time
spent away — a shift elsewhere, school, appointments, sport, an outing — is not modelled as detailed
activity, because none of it is observable by home sensors. What matters is only *that the resident
is out*. Do not invent intents for occupations, and do not build a detailed away-from-home routine:
where the persona's job happens matters, what the job consists of does not.

Declare each absence **exactly once**, choosing the form that fits:

- a **`fixedCommitment`** when the hours are set by someone else and repeat on given weekdays — a
  shift, a class, a standing appointment. It carries real clock times, its own validity dates, and
  an away `intent` like any other absence;
- a **recurring activity** with an away intent when the resident chooses when to go and it may drift — a gym
  session, a walk;
- an **event** for a bounded absence inside a date window — a trip, an appointment.

Do not describe the same absence twice. A `work_shift` recurring activity *and* a fixed commitment for the same
teaching hours put the resident at work twice over.

### Work done at home is not an absence

`work_from_home` is an ordinary in-home intent, in the first list above, placed in `living_room`.
Use it whenever the case has the resident working inside the dwelling — freelancing, remote days,
a home study — and **never** `work_shift`, which is an away intent and would send her out of the
front door for the whole working day.

This is the largest single stretch of a working-age resident's day, so leaving it undeclared is not
a small approximation. One authored horizon omitted it, recording the reason in its own notes
("freelance work itself is not declared because no canonical home-work intent exists"), and its
09:30-17:30 band then contained a single lunch on 260 weekdays: seven waking hours in which the
ground truth says nothing happens.

**Author the working day as several blocks, not as one.** A day at home is not a shift: the person
gets up, makes coffee, starts a wash, takes a call, comes back. Declare the work with a **daily**
cadence and `timesPerPeriod` set to the number of blocks — three or four across a wide band is
typical — and the expander spreads them through the window, one per equal sub-band, each wobbled by
the jitter you declare.

**Then declare the breaks.** They are not decoration: they are the entire sensor signature of home
work. Four blocks with nothing between them describe a person who does not move, which reads
exactly like an empty flat. Two intents exist for the short ones, and they earn their place by
moving the resident to a different room:

- `prepare_and_drink_hot_drink` — the trip to the kitchen for a coffee or a tea. Once or twice a
  working day, in the same band as the work;
- `use_toilet` — a visit to the bathroom on its own. Two or three times a day is ordinary, and it
  is *not* `morning_toilet_and_wash`: that one is the morning routine, and using it for an
  afternoon trip mislabels the ground truth the dataset publishes.

The longer breaks are ordinary home intents you already have: lunch, a stretch, a phone call, the
laundry going on mid-afternoon, a walk before the shops close. Interleave them with the blocks
rather than stacking them at the edges of the day.

An unbroken working day is still allowed, because some people do work that way. Write it as a
`fixedCommitment` with `work_from_home` as its intent — the hours are then pinned and the day holds
one long block. Expect a `HOME_WORK_IS_ONE_UNBROKEN_BLOCK` warning saying so; it is a warning
precisely because it may be what the case describes. What it will not let you do is arrive at eight
motionless hours by accident.

Two things do not change for a resident who works at home. She still has to **leave the house on a
recurring basis** — she is at home all day, which makes the errand and the evening walk more of her
door signal, not less. And a working day still ends: do not let the blocks run into the evening the
rhythm needs for its night.

**The resident must leave the house on a recurring basis, not only for events.** Declare at least
two *recurring* activities that happen outdoors — the weekly shop, a walk, an errand — with a
cadence that fits the person. An outline whose only outings are two or three events describes
someone who does not go out: one eight-month horizon produced sixteen door crossings in total,
against the several a day a real household records, and the front door is the single most
informative sensor in the home. Note that `buy_groceries` and `evening_walk` are outdoor intents
even though they appear in the home-centred list above: **what places an activity outside is its
room, `outdoors`, not the list it is printed in.** Every one of them takes the resident through the
door and back.

For each recurring activity:

- `cadence.period`, `timesPerPeriod` and `everyNPeriods` state how often it recurs; `weekdays`
  restricts it to particular days when the case says so, and is otherwise left empty. Over a
  `week` or a `month`, `timesPerPeriod` counts **days** — three runs a week are three days on
  which a run happens. Over a `day` it counts **occurrences inside that day**, which is how a
  working day split into blocks, a medication taken twice or a dog walked morning and evening is
  written. The window is then divided into that many equal sub-bands, one occurrence to each, so
  it must be wide enough for them: at least twenty minutes apiece;
- `cadence.windowStart` and `cadence.windowEnd` are the hours it may occupy. Make them as wide as
  the case honestly allows;
- `cadence.jitterMinutes` is how *irregular* this recurring activity is — how far a single occurrence wanders
  around its usual moment. A rigid anchor takes a small value, a loose optional one a large value.
  It is not the width of the band and must not duplicate it. Read it as the *typical* wander rather
  than the largest one: about two thirds of occurrences fall inside it, and a few land much further
  out, the way a real routine has its off days;
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

Three rules:

- **bands may not overlap on a day they share.** They divide the timestamp axis, and a moment
  belonging to two habits would not be a division. Gaps are allowed — time no band claims is
  simply unsegmented;
- **the night band may cross midnight.** For habits only, `windowStart` later than `windowEnd`
  means the band wraps, which is how a night from 22:30 to 06:15 is written;
- **a band may be scoped to particular days** with `weekdays`, listing the days it applies to.
  Leaving it out means every day, which is the right answer for the night and usually for the
  morning.

**Scope the band whenever the hours hold two different behaviours.** If the resident works
09:00-17:00 from Monday to Friday, those hours are a working day on five days and something else
entirely on the other two, and one band covering all seven has to describe both. Measured on a
generated year, exactly that band came out `work_shift` at 96% across its 260 weekdays and, across
its 105 weekend days, a mixture whose largest component reached 23% — one band, two behaviours,
and a segmentation algorithm asked to find a single boundary for them. Write two bands instead,
one scoped to the working days and one to the weekend; sharing the same hours is allowed precisely
because their days are disjoint.

The signal to watch for is your own label. If a band needs a name like "daytime and domestic
weekend" to be honest, it wants to be two bands.

**Splitting a band leaves you with two bands, and each of them has to stand up on its own.** This is
where authored horizons fail most often, because the split feels like the work and the filling feels
like bookkeeping. It is the other way round.

Measured on a generated year: the weekday band 09:00-18:00 had 451 of its 540 minutes accounted for
by declared activities, with `work_from_home` alone holding 344 of them. Its weekend twin, over the
same hours, had 172 minutes accounted for and its largest single activity was a 31-minute lunch. The
weekend band was not authored badly by accident — it was authored as the weekday band with the work
removed, and nothing was put in its place. Two thirds of every Saturday and Sunday between nine and
six, in a document whose whole purpose is to say what the resident was doing, said nothing.

Two rules follow, and a band must satisfy both:

- **every band names at least one recurring activity of `kind: anchor`.** The anchor is the thing
  that makes the band that band — sleeping in the night, working on a weekday, the long lunch on a
  Sunday. A band whose activities are all `optional` and `rare` is a list of errands, not a habit;
- **a band wider than about three hours needs an activity that occupies it in blocks**, declared
  with a `day` cadence and a `timesPerPeriod` above one, exactly as the working day is written
  above. Half a dozen half-hour errands cannot fill nine hours, and declaring them as though they
  did is what produced the weekend band above. The anchor rule alone does not catch this: that
  weekend band *had* an anchor — lunch — and lunch is thirty minutes long.

**Two bands that share a window must differ in what they contain, not only in `weekdays`.** In the
same generated year the two 09:00-18:00 bands listed seven recurring activities each and six of them
were the same six. If your two bands would name nearly the same activities, then either the days
really do hold the same behaviour — in which case write one band and no `weekdays` scope — or the
one you split off is missing its own anchor. Do not let the scope carry a difference the content
does not have.

None of this asks you to invent a life that is easy to recognise from sensors. If this person's
Saturday genuinely is her Tuesday without the work, say so, in one band or in two honest ones. What
is not allowed is a declared band with nothing declared inside it.

**The night band must open at least two hours before `rhythm.chronotypeBedtime`.** The chronotype is
where the resident *tends*, not where she is put: the drive layer moves each night's lights-out up
to 45 minutes earlier as sleep debt builds, and jitters it around that by a further half-hour or so.
A band opening at 23:00 under a 23:15 chronotype therefore spends much of the horizon with the night
starting before the band that is supposed to contain it — the sleep lands in the evening band, and
the habit ground truth says the resident was reading when she was asleep. Nothing rejects this,
which is exactly why it has to be authored correctly: give the night room on its early side, and end
the evening band where the night begins.

### How your bands will be scored

The confirmed outline is expanded into a habit ground truth, and each band is then measured against
the days it actually produced. Three of those numbers say whether you authored it well, and you can
predict all three while writing:

- **`unaccountedShare`** — the fraction of the band's minutes in which no declared activity was
  running. The bands above came out between 0.10 and 0.29; the abandoned weekend one came out
  **0.68**. Anything past about a third means the band is a window with things scattered in it
  rather than a stretch of the day with a shape;
- **`dominantIntent`** and its share — the largest single activity. `sleep` held 0.76 of the night
  and `work_from_home` 0.64 of the weekday; the weekend band's dominant intent was `eat_lunch` at
  **0.058**, which is not a description of a day. A band with no dominant activity is possible and
  sometimes right — a slow morning of four comparable routines is a real thing — but a *widest*
  component under a tenth means nothing anchors the band;
- **`effectiveShare`** — how much of the declared window the band's activities really occupy once
  they are placed.

You are not asked to compute these. You are asked to write bands that would survive them.

These bands are the answer sheet: a researcher's segmentation algorithm sees only a sensor log and
has to recover both where the day divides and what runs in each division. Declare them as the
person actually lives, not as a tidy grid.

## The arc of the period

A horizon longer than a few weeks that contains no phases and no events is a single week repeated,
and will be rejected in review. Use both.

The horizon itself is the **half-open** span `[startDate, startDate + months)`: the day exactly
`months` after `startDate` is the first day *past* the horizon, not its last day. With
`startDate: 2026-08-04` and `months: 8` the horizon runs 2026-08-04 through **2027-04-03**, and
2027-04-04 is out of range. Every date written anywhere in the outline — a phase's `startDate` and
`endDate`, an event's `earliestDate` and `latestDate`, a fixed commitment's `startDate` and
`endDate` — must fall inside that span. A commitment that runs to the end of the period ends on the
last day inside the horizon; do not write the boundary day itself.

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

**An absence displaces everything it covers, meals included.** Work out the hours the event can
occupy — its window plus its `minimumMinutes` — and name in `displaces` *every* recurring activity
whose band falls inside them. Chores are the easy half and the one everybody remembers; the meals
are the half that gets forgotten, and they are mandatory, so forgetting them does not produce an
odd day but an impossible one. A weekend trip of 480 to 840 minutes that displaced the shopping,
the batch cooking, the laundry and the tidying — but not lunch or dinner — required the resident to
be away for fourteen hours and to cook at home in the middle of them; the whole eight-month horizon
was rejected for that one Sunday.

## The world

`outline.world` declares where the routine happens. It is stated once for the whole horizon.

{{CATALOG_ROOMS}}

Declare any further rooms the case needs, plus external locations, and a composite location
grouping the indoor rooms. Every resource sits in a declared location. `startLocationId` is where
the resident is at the first instant of the horizon and must be a primitive room, never a
composite.

`homeModel` is a synthetic versioned reference; the executable home is materialised later from
these declared locations.

### Furnish every room the resident works in

{{FURNITURE_CATALOG}}

**A room is furnished when the objects its activities use are declared.** The materialiser builds
exactly what `world.resources` names and, for every role nothing provides, substitutes one
placeholder per room — an object with no footprint, no contact sensor and no position of its own.
Nothing about that substitution is visible in the output, so a thin inventory is not a small
omission that shows up later: it silently deletes the sensor evidence.

One generated eight-month horizon declared five objects for an entire flat — a bed, a washing
machine, a moka, a desk and a television. Its kitchen therefore had no stove, no sink, no fridge and
no table, so seven intents and 705 hours of cooking, eating and cleaning all executed at the same
placeholder point. Two consequences, both fatal to the dataset: that room's single motion sensor
carried **66.5% of the whole log**, and the home ended up with **one contact sensor** — the front
door — because contact sensors attach to objects that open, and there were none.

So, before writing `resources`, go through the recurring activities room by room and ask what each
one physically touches. Cooking needs a `stove`, a `sink` and a `refrigerator`; eating needs a
`table` and a `chair`; washing needs a `shower` or a `washbasin` and a `toilet`; dressing needs a
`wardrobe`; cleaning needs a `storage_cabinet`. **A kitchen with fewer than three objects is a
mistake, not a minimalist flat.** Give each one a `resourceId` of your choosing, a `resourceType`
from the list above, and the `locationId` of the room it stands in.

**Then read the list back the other way: every object you declared must have an activity that uses
it.** The rule above stops you furnishing too thinly; this one stops you furnishing a home nobody
lives in, and it is the failure that actually happens once the first rule has been learned.

A five-month horizon for a father of two declared a wardrobe, a washing machine and three storage
cabinets, and then gave him no laundry, no change of clothes and no cleaning — twenty recurring
activities, not one of which reaches into any of the five. The furniture was right and the life was
missing, so three contact sensors spent five months publishing nothing but their own false
positives, and the wardrobe opening at 07:00 that tells a segmentation algorithm the resident is
awake never happened once.

So for each declared object, name the recurring activity that touches it. A `wardrobe` wants
`change_clothes` or `dress`; a `washing_machine` wants `start_laundry` and `hang_laundry`; a
`storage_cabinet` wants `clean_kitchen`, `tidy_living_room_and_hallway` or the medication routine.
If no activity in your profile wants the object, you have two honest options and inventing neither
is one of them: add the activity, because a household of that description almost certainly does the
washing — or delete the object, and let the home be a home without one.

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

### What those rules mean on this path

The section above is shared with the prompt that authors days directly, where a scenario already
exists by the time the package is written. Here it does not: the expander builds the scenario from
your outline after you answer. Two of its rules therefore have a different answer, and these are
the ones that apply:

- `sourceScenarioId` is your **`outline.outlineId`**, and `sourceScenarioVersion` is `1.0.0`. There
  is no generated scenario to copy them from; the expander names the scenario after the outline,
  and a package that guesses anything else is rejected as targeting a different scenario.
- the catalog references are exactly the identifiers and versions of the three documents embedded
  in this prompt. Do not carry over versions from another prompt: a package pointing at a catalog
  that does not define an intent it binds is rejected, and so is one whose reference disagrees with
  the catalog actually loaded.

## Required final consistency checks

Before answering, verify all of the following:

- the top-level object validates against the embedded `horizon-authoring-bundle` schema;
- no value anywhere in `outline` is a date-and-time, except that `fixedCommitments` carry `HH:MM`
  clock times;
- the habit portfolio satisfies the stated minimum counts per kind;
- every `recurringActivityId` named by a phase override, an event displacement or a habit band
  exists in `outline.profile.recurringActivities`;
- `habits` declares between three and six bands for any given day of the week, no two of them
  overlapping on a day they share, and at most one of them crossing midnight;
- any band whose hours mean something different at the weekend carries a `weekdays` scope, and the
  days it does not claim are covered by another band;
- every band names at least one recurring activity of `kind: anchor`, and every band wider than
  three hours names one declared with a `day` cadence and a `timesPerPeriod` above one;
- no two bands sharing a window name nearly the same `recurringActivityIds`;
- the night band opens at least two hours before `rhythm.chronotypeBedtime`, and the evening band
  ends where it opens;
- no two overlapping phases override the same recurring activity;
- every phase, event and fixed-commitment date falls inside the half-open horizon, so no date is
  on or after `startDate + months`;
- `world.locations` declares every room listed above under the activity catalog;
- every room the recurring activities work in declares the objects those activities touch, with a
  `resourceType` from the furniture list — a kitchen with fewer than three is unfurnished;
- every resource's `locationId` and `startLocationId` resolve to declared locations, and
  `startLocationId` is not a composite;
- every recurring activity, event and fixed commitment declares an `intent` copied character for
  character from one of the two canonical lists, and every absence carries an away intent;
- the process package binds only intents that appear in the outline, and every intent the outline
  uses is bound;
- `personalProcessPackage.sourceScenarioId` equals `outline.outlineId`, and the three catalog
  references match the embedded documents exactly;
- every band has `windowStart` strictly before `windowEnd`, and every duration range has its
  minimum at or below its maximum;
- an event's `occurrences` does not exceed the number of eligible days in its window;
- every event displaces each recurring activity whose band falls inside the hours it can occupy,
  the meals included;
- the process package implements every intent the recurring activities, events and commitments
  imply, **and** the intents the rhythm adds by itself, listed above;
- every action reaching inside a container — `take_item`, `put_item`, `laundry_step` — opens and
  closes it, so the fridge is not the only object in the home a contact sensor ever observes;
- every object declared in `world.resources` is reached by at least one recurring activity, and any
  object no activity wants has been removed from the home;
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
