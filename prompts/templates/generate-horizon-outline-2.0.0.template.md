# Horizon outline authoring prompt 2.0.0

## Instruction to the external LLM

Generate one horizon outline and its personal process package for the **household** described
in the final section of this document — one person, or several sharing a home. The researcher description is the authoritative case
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

1. `outline`, describing the people who live there, the recurring activities each of them has,
   the habit bands those fall into, what they do together, the world they share, and the arc of
   the period;
2. `personalProcessPackage`, describing how the resident performs each activity through typed
   personal ADL process models.

Construct the household level first, then each resident's profile against it, then the process
package against both, then check the three together. This keeps the response O(1) in the length of
the horizon *and* in the number of residents: everything shared is written once.

## Mandatory provenance values

Use the following exact values in both nested provenance objects:

- `authorType`: `external_llm`;
- `generatorName`: `smart-home-simulator-external-llm-authoring`;
- `generatorVersion`: `1.4.0`;
- `promptTemplateVersion`: `generate-horizon-outline-2.0.0`;
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

## The household

`outline.residents` is a list, and everything the case says about *a person* — profile, rhythm,
habits, fixed commitments, phases, events — belongs to her entry in it. A case about one person is
a list of one and an empty `household`; nothing below changes shape for it.

What belongs to the **pair** rather than to anyone goes in `outline.household`. That level exists
because a language model asked for "the family's routine" reliably breaks two things at once, and
both are silent:

- it **over-synchronises**, pinning dinner at 19:30 for both and narrowing the band exactly where
  the placement engine needs slack;
- it **duplicates instead of sharing**, writing dinner twice with two similar bands. The solver has
  no reason to align them, they drift by forty minutes, and the dataset ends up with two dinners
  where the house had one.

### A shared activity is declared once

Anything the residents do *together* goes in `household.jointActivities`, once, with an explicit
`participantIds` and **one** band. Never also in an individual profile.

There is no "both" field anywhere in this contract, and that is deliberate: in a household of four
the dinner has four participants and the school run has two, so every shared thing names the people
it is about.

Each entry carries a `sharing`:

- `joint` — one activity, one interval, several participants. A couple's dinner; sleeping in the
  same bed. Given that the day has room for it, it happens;
- `optional_joint` — together *when it happens*, with a declared `propensity`. Watching television
  in the evening; the morning coffee.

The expander decides which concrete occurrences are shared. You declare the *propensity to share*;
which Tuesday they actually eat together is known only after the commitments are placed and the
drives are computed, and it is not yours to write.

### The propensity is a number, indexed by class of day

```json
"propensity": { "default": 0.25, "weekend": 0.85 },
"minimumSharedMinutes": 20
```

Write `default`, and `weekday` or `weekend` where the two regimes genuinely differ. A couple who
watch television together at the weekend and almost never during the week are not described by
`0.4`: a single average scatters shared evenings at random through the working week and fabricates
a weekly pattern in the ground truth, in exactly the distinction the evaluation cares about.

`minimumSharedMinutes` is the overlap below which the occurrence is not worth calling shared. A
breakfast squeezed into the twelve minutes two people have in common before one of them leaves is
an artefact of the arithmetic, not a shared breakfast.

Co-presence is always checked before the number is consulted, so a propensity can never conjure a
shared dinner on a day whose bands do not meet. A propensity above zero on an activity whose bands
*never* meet is refused before any day exists.

### Waiting is not something you write

If one of them gets home half an hour before the other and they usually eat together, that is a
`joint` activity with a wide band — not `optional_joint`. There is no coin to toss. The expander
places one interval that fits everybody, so it lands after the later arrival, and the twenty-five
minutes in front of it are the residue of that. Do not model the wait; do not invent an intent for
it.

### What the residents do separately

Two people doing the same thing at different times need no declaration: they are independent, they
contend only for the physical things the home has one of, and the compiler resolves that through
`world.resources` and their `capacity`. A shower taken by two is one use with two participants and
passes; two independent showers at the same instant are two uses of one jet and are refused.

Use `household.sharingPolicies` only to declare `exclusive`: this pair does not share the room while
one of them is doing this. Two friends splitting the rent do not walk in on each other in the
bathroom; a couple may. It is a fact about the relationship, so state the relationships too, in
`household.relations`, as pairs.

### Privacy is about rooms, and it is directional

`household.locationPrivacy` says who may **not** be in a room while its occupant is using it. It is
not a capacity: no room has a true one — two people fit in a shower cabin, and at the table one can
sit in the other's lap. What decides is a norm between two named people.

- `subjectId` is whose privacy it is;
- `excludedResidentIds`, left empty, means everybody else;
- `intents`, left empty, means the room is private whatever the subject is doing there;
- `symmetric` is `true` for the ordinary reciprocal case between adults, and `false` where it is
  not — a parent and a small child.

**Defaults are restrictive, and permissive settings are chosen rather than inherited.** Undeclared,
the residents are independent, and a room holding a single sanitary fixture is private. The two
mistakes do not cost the same: a wrong permissive default puts two people in one shower cabin,
which is physically impossible and silently false everywhere downstream, while a wrong restrictive
default is a slightly formal cohabitation a reader can see and correct. A household that genuinely
shares its bathroom says so in `household.sharedLocationIds`.

One thing privacy cannot be declared over: the room the night happens in. Two people each need
about eight hours of it and the day has twenty-four, so it is refused rather than compiled.

**Every resident sleeps where she starts the horizon.** A resident begins the horizon asleep, so her
`startLocationId` — or the household's, if she declares none — is her bedroom for every night, nap
and waking of it, provided the room holds a bed. Two friends splitting the rent do not share a bed:
residents related as `housemates` or `other` who would sleep in the same room are refused, so give
the second one a room of her own with a `single_bed` or `bed` in it and set her `startLocationId`
there. A couple, a parent with a small child and siblings may share one; any other pair that
genuinely does lists the room in `household.sharedLocationIds`.

### The portfolio gate applies to each resident

Every resident's own `profile` must satisfy the counts below on its own. A resident with two habits
of her own and everything else held in common is not a second person, she is a shadow of the first —
and a shadow contributes no second behaviour for a segmentation algorithm to confuse with the
first, which is the whole reason for generating a shared log.

Write the household level first, then each resident's profile *against* it, then check them
together.

### Every resident performs her own activities

The process package is personal *per resident*: every process model carries a `residentId`, and
every binding says which resident it is for. Write the models and bindings for **each** resident,
covering every intent that resident's own activities, commitments and events use, every shared
activity she takes part in, and the intents the rhythm adds by itself. A package that implements
dinner for one of two people has implemented it for one person, and the horizon is refused before
any day is written.

A shared activity is performed by one participant's model — who that is changes with the calendar —
while the others walk to where it happens and take their place. So every participant needs a binding
for it, exactly as she would if she did it alone.

### Identifiers are unique across the whole document

Every `recurringActivityId`, `habitId`, `phaseId`, `eventId` and `commitmentId` is unique across all
residents and the household, not merely within one resident. Every resident's day is merged into one
scenario, so two people who had each called an activity `morning_coffee` would arrive there as one
activity performed twice.

## Recurring activities

`residents[].profile.recurringActivities` is the behavioural ground truth of the case, and the
confirmed profile is what any downstream habit-mining evaluation is scored against. Author it
accordingly, once per resident. Activities the residents do *together* are not written here at all —
they belong to `household.jointActivities`, once.

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

- there is **no** generic cooking intent. Making a meal is `prepare_breakfast`,
  `prepare_simple_lunch`, `prepare_light_dinner` or `weekly_meal_preparation`, and eating it is
  `eat_breakfast`, `eat_lunch` or `eat_dinner`;
- there is **no** bathroom-cleaning and **no** vacuuming intent. Housework inside the dwelling is
  `clean_kitchen` or `tidy_living_room_and_hallway`, and nothing else;
- washing is `morning_toilet_and_wash`, `morning_toilet_and_shower` or `evening_hygiene`.

When the case describes something the catalog has no intent for, do one of three things: carry it on
the **nearest listed intent** and say so in the activity's `note`, leave it out of the outline
entirely, or — only when the nearest intent would misdescribe it — **propose** a new one in
`outline.vocabularyProposals.activities`. All three are correct. Inventing an identifier silently is
not, and neither is inventing one in the process package: a binding or process model for an intent
the outline cannot declare is dead weight the import rejects.

### Proposing an activity the vocabulary does not have

A proposal is a request to a researcher, not a way around the list. Use one when the case states
something recurring or memorable that no listed intent names — a guest for dinner is not a phone
call — and write nothing you could have carried on a listed intent. Each entry has:

- `intentId`: a new `lower_snake_case` identifier that is in neither list above;
- `label`: what a person would call it;
- `category`: one of the categories the activity catalog below uses;
- `defaultLocation`: a location `world.locations` declares, where it usually happens;
- `description`: one sentence on what the resident does;
- `rationale`: one sentence on why no listed intent describes it.

Use the proposed `intentId` wherever the case needs it, exactly as you would a listed one, and
implement it in the process package **with the actions of the embedded action catalog only** — a
proposal adds a word, never a movement the simulator cannot perform. Its process models declare
`implementedComponents` as `["authored__<intentId>"]`, and their first action is the one the
activity starts with.

Know what it costs: the import stops on an outline that uses a proposed intent until a researcher
has added it to the vocabulary, because a new intent is a new label in the dataset. Propose one
where the case genuinely needs it, and at most a few per outline.

**A meal eaten at home is made at home.** The three eating intents only put the resident in a
chair: nothing in them opens a cupboard or lights a hob, and what they consume is whatever the
preparation before them left. So declare the preparation next to the meal — `prepare_breakfast`
before `eat_breakfast`, `prepare_simple_lunch` before `eat_lunch`, `prepare_light_dinner` before
`eat_dinner` — and the compiler will keep the two in that order on every day it schedules both.
Give the preparation a `kind` at least as committed as the meal's: `anchor` and `contextual` are
both kept, and only those are ordered. A preparation you mark `optional` or `rare` may be dropped
on a crowded day, so it is deliberately left unordered — where the meal has to happen and the
cooking does not, an uncooked meal is what you asked for.
Omit it only where the case says the food came from somewhere else: a lunch eaten at the office, a
coffee and a pastry at the bar on the way to work. That is a real answer and the `note` is where
you say so. What is not an answer is a horizon in which the resident eats three meals a day for
five months and never once makes one.

{{ACTIVITY_LOCATION}}
The catalog is deliberately **home-centred**: it describes what happens inside the dwelling. Time
spent away — a shift elsewhere, school, appointments, sport, an outing — is not modelled as detailed
activity, because none of it is observable by home sensors. What matters is only *that the resident
is out*. Do not invent intents for occupations, and do not build a detailed away-from-home routine:
where the persona's job happens matters, what the job consists of does not.

Declare each absence **exactly once**, choosing the form that fits:

- a **`fixedCommitment`** when the hours are set by someone else and repeat on given weekdays — a
  shift, a class, a standing appointment. It carries real clock times, its own validity dates, and
  an away `intent` like any other absence. Its `startTime` is always earlier than its `endTime`:
  a commitment never crosses midnight, and `24:00` is not a clock time;
- a **recurring activity** with an away intent when the resident chooses when to go and it may drift — a gym
  session, a walk;
- an **event** for a bounded absence inside a date window — a trip, an appointment.

Do not describe the same absence twice. A `work_shift` recurring activity *and* a fixed commitment for the same
teaching hours put the resident at work twice over.

**A night shift is two commitments, not one.** A nurse out from 21:30 to 06:30 on Mondays,
Wednesdays and Fridays is written as the part before midnight and the part after it:

- `21:30`–`23:59` with `weekdays` Monday, Wednesday and Friday;
- `00:00`–`06:30` with `weekdays` Tuesday, Thursday and Saturday — the mornings those nights end
  on — and, when the shifts are dated, `startDate` and `endDate` each one day later than the first
  part's.

Both halves carry the same `intent` and label. Written as one commitment from `21:30` to `06:30`,
the shift is rejected before any day is built.

Do not declare the sleep that follows it. The rhythm recognises a night taken by commitments and
lays the main sleep in the morning after the shift — shorter than a night's, as a real one is — and
starts that day's waking hours after it: the breakfast and the rest of the morning slide into the
afternoon on their own. A recurring activity that tries to put the resident to bed at 07:00 would be
a second sleep over the first. The same holds for an event's `windowStart` and
`windowEnd`: an outing that runs past midnight ends at `23:59`.

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

The confirmed outline is expanded and simulated, and each band is measured against what the run
actually did — the activities that were executed, when, and in which room. That measurement is the
habit ground truth the dataset publishes. Before any run exists, the same numbers are computed on
the expanded plan and shown as warnings, so a band that holds nothing is caught straight after
import. Three of those numbers say whether you authored it well, and you can predict all three
while writing:

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

{{ROOM_PALETTE}}

Declare external locations too, and a composite location grouping the indoor rooms. Every resource
sits in a declared location. `startLocationId` is where the resident is at the first instant of the
horizon and must be a primitive room, never a composite.

### How big the home is, and how many storeys

{{DWELLING_SHAPE}}

### Furnish every room the resident works in

{{FURNITURE_PALETTE}}

**When the home needs an object no type above describes**, declare the resource with a new
`resourceType` of your own and propose that type in `outline.vocabularyProposals.furniture`:

- `entityType`: the `resourceType` you used, `lower_snake_case`;
- `displayName`: what the object is called;
- `capabilities`: what it can be used for, chosen **only** from the capabilities listed after the
  dashes above — a capability no action asks for binds nothing;
- `contactInstrumented`: `true` only if it has a door or a lid a contact sensor would be fitted to;
- `rationale`: one sentence on why no listed type would do.

A yoga mat for a resident who exercises in the living room is the typical case: no listed type
offers `exercise_support` there. Do not propose a type for an object a listed one already
describes under another name, and do not propose drawings — the researcher adds how it looks.

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

### What a model of the right granularity looks like

Rule 5 says to realize each component through its required action types, and read on its own it
licenses a model that is *only* those. `consume_meal` requires `change_posture, consume,
change_posture`, so `move_to -> change_posture(sitting) -> consume -> change_posture(standing)`
passes every rule above — and describes a resident who crosses the kitchen, sits down and eats a
meal she never picked up, in a kitchen whose cupboards nobody opened. Both horizons authored
against this prompt wrote exactly that, for all three meals. Measured on the export that followed,
the fridge was opened 0.81 times a day against the eight to fifteen of a real household, and the
contact sensors — half the instrumentation of the home — observed almost nothing.

The required action types are a floor, not a recipe. Below is the decomposition this project uses
for each intent: the same action types, the same roles and the same argument shapes you are asked
for, at the granularity the sensor layer is derived from. Take these as the shape and adapt the
detail to your persona — a moka rather than a machine, a wardrobe rather than a chest — rather than
writing a shorter model that validates.

{{REFERENCE_PROCESS_MODELS}}

Two habits in there are worth naming, because they are what a contact sensor in a kitchen mostly
sees. Every process **fetches what it uses from the storage it is kept in and closes it again**:
`move_to_capability(storage) -> open -> take_item -> close`, never a `take_item` on its own. And
every process **puts back or clears up** what it finished with — the ingredients into the fridge,
the plate to the washing area.

What a model forgets to put down, the simulator puts down for it. Most things go back as the
activity that took them ends — ingredients, the moka, a cleaning cloth — so a `put_item` of them in
a *later* activity finds nothing in her hands and is rejected. A few may be carried on into the
next activity: `drink`, `prepared_meal`, `prepared_salad` and `prepared_food_portions` for half an
hour or so, `purchases` for two hours, `used_clothing` for half an hour. They are set down when the
activity that consumed them ends, or when their time runs out. So a coffee made in the kitchen can
be drunk at the desk, and shopping carried home can be put away by the next activity — but write
the `put_item` wherever the resident really would put something back, because that is the gesture
a contact sensor sees.

## Required final consistency checks

Before answering, verify all of the following:

- the top-level object validates against the embedded `horizon-authoring-bundle` schema;
- no value anywhere in `outline` is a date-and-time, except that `fixedCommitments` carry `HH:MM`
  clock times;
- no fixed commitment, event window or recurring-activity cadence window crosses midnight: each
  starts earlier in the day than it ends, and a night shift is split into its two halves;
- every resident's habit portfolio satisfies the stated minimum counts per kind on its own;
- every `recurringActivityId` named by a phase override, an event displacement or a habit band
  exists in that resident's `profile.recurringActivities`, or in a `household.jointActivities`
  entry she takes part in;
- no identifier of any kind is used by two residents, and no shared activity is also declared
  inside an individual profile;
- every resident's `habits` declares between three and six bands for any given day of the week, no
  two of them overlapping on a day they share, and at most one of them crossing midnight;
- any band whose hours mean something different at the weekend carries a `weekdays` scope, and the
  days it does not claim are covered by another band;
- every band names at least one recurring activity of `kind: anchor`, and every band wider than
  three hours names one declared with a `day` cadence and a `timesPerPeriod` above one;
- no two bands sharing a window name nearly the same `recurringActivityIds`;
- the night band opens at least two hours before that resident's `rhythm.chronotypeBedtime`, and
  the evening band ends where it opens;
- every `household.jointActivities` entry names at least two participants, all of them residents,
  and carries a `propensity` if and only if its `sharing` is `optional_joint`;
- the process package holds models and bindings for every resident, each binding naming its
  resident, and every participant of a shared activity has a binding for its intent;
- every shared activity's band leaves its participants enough time in common on at least one class
  of day, once their fixed commitments are taken out of it;
- every `household.relations`, `sharingPolicies` and `locationPrivacy` entry names residents that
  exist and a room that `world.locations` declares, and no privacy rule covers the room the night
  happens in;
- no two overlapping phases override the same recurring activity;
- every phase, event and fixed-commitment date falls inside the half-open horizon, so no date is
  on or after `startDate + months`;
- `world.locations` declares every room listed above under the activity catalog;
- every room the recurring activities work in declares the objects those activities touch, with a
  `resourceType` from the furniture list — a kitchen with fewer than three is unfurnished;
- every resource's `locationId` and `startLocationId` resolve to declared locations, and
  `startLocationId` is not a composite; a resident who starts the horizon somewhere other than the
  household's start location declares her own, and it is a room;
- housemates sleep in rooms of their own: each has a bedroom with a bed in it as her start location,
  unless the room is listed in `household.sharedLocationIds`;
- every recurring activity, event and fixed commitment declares an `intent` copied character for
  character from one of the two canonical lists, from the workspace additions, or from
  `vocabularyProposals.activities` — and every absence carries an away intent;
- every `vocabularyProposals.furniture` entry names a `resourceType` some resource uses and only
  listed capabilities, every `vocabularyProposals.activities` entry names an `intentId` the outline
  uses and a declared location, and nothing is proposed that a listed entry already describes;
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

## What this workspace adds to the vocabulary

The lists above are the simulator's own. A researcher may have extended them in this workspace;
what they added is listed here, and it is as usable as anything above.

{{WORKSPACE_VOCABULARY}}

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
