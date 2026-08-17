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

Author at least 8 recurring activities, with at least these counts per kind (the portfolio gate rejects an unbalanced profile):

- `anchor`: 3
- `contextual`: 2
- `optional`: 2
- `rare`: 1


### Every recurring activity, event and commitment declares its intent

Every `intent` must be one of the canonical intents below, spelled exactly. The room given is where the activity catalog places it. These two lists are exhaustive: an identifier outside them does not exist, however reasonable it looks.

**Inside the home:**

- `buy_groceries` — outdoors
- `clean_kitchen` — kitchen
- `eat_breakfast` — kitchen
- `eat_dinner` — kitchen
- `eat_lunch` — kitchen
- `evening_hygiene` — bathroom
- `evening_walk` — outdoors
- `hang_laundry` — balcony
- `indoor_light_exercise` — living_room
- `morning_toilet_and_shower` — bathroom
- `morning_toilet_and_wash` — bathroom
- `phone_call` — living_room
- `prepare_and_drink_hot_drink` — kitchen
- `prepare_light_dinner` — kitchen
- `prepare_simple_lunch` — kitchen
- `put_groceries_away` — kitchen
- `read_and_rest` — living_room
- `rest_or_nap` — bedroom
- `sleep` — bedroom
- `start_laundry` — bathroom
- `take_morning_medication` — kitchen
- `tidy_living_room_and_hallway` — living_room
- `use_toilet` — bathroom
- `wake_up` — bedroom
- `watch_television` — living_room
- `weekly_meal_preparation` — kitchen
- `work_from_home` — living_room

**Away from home** — the only intents an absence may carry, whether it is a fixed commitment, a recurring activity or an event:

- `collect_belongings_and_leave_home` — outdoors
- `commute_home` — outdoors
- `commute_to_work` — outdoors
- `go_to_neighborhood_market` — outdoors
- `leave_home` — outdoors
- `return_home_and_store_purchases` — outdoors
- `social_drink_out` — outdoors
- `take_recycling_out` — outdoors
- `travel_home` — outdoors
- `travel_to_neighborhood_bar` — outdoors
- `travel_to_pharmacy` — outdoors
- `travel_to_relatives_home` — outdoors
- `travel_to_supermarket` — outdoors
- `visit_relative_and_have_dinner` — outdoors
- `work_shift` — outdoors


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

`world.locations` must declare every room the activity catalog places an intent in, under exactly these identifiers: `balcony`, `bathroom`, `bedroom`, `kitchen`, `living_room`, `outdoors`. A missing one is rejected before any day is built.


Declare any further rooms the case needs, plus external locations, and a composite location
grouping the indoor rooms. Every resource sits in a declared location. `startLocationId` is where
the resident is at the first instant of the horizon and must be a primitive room, never a
composite.

`homeModel` is a synthetic versioned reference; the executable home is materialised later from
these declared locations.

### Furnish every room the resident works in

`world.resources` declares the objects the home contains. Use these `resourceType` values, spelled exactly: they are the only ones that bind to anything, and the roles beside each are what that piece of furniture can be used for.

- `bed` — sleeping_area
- `chair` — consumption_area, dining_seat
- `moka_coffee_maker` — coffee_equipment
- `radio` — media
- `refrigerator` — coffee_and_breakfast_storage, food_storage, ingredients, prepared_food_portions, prepared_meal
- `shower` — personal_care_fixture, shower_water
- `sink` — drinking_water_source, food_preparation_area, sink_faucet, washing_area
- `sofa` — rest_area, seating
- `storage_cabinet` — cleaning_product_storage, cleaning_products, household_storage, household_supplies, medication, medication_cabinet, medication_storage
- `stove` — cooking_appliance, food_preparation_area
- `table` — consumption_area, dining_area
- `television` — media
- `toilet` — personal_care_fixture
- `wardrobe` — clothes, clothing_storage, laundry_collection, laundry_storage, used_clothing
- `washbasin` — personal_care_fixture, washing_area
- `washing_machine` — laundry, laundry_equipment


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

The drive layer places these on its own — a wake and a night every day, plus a nap, a nocturnal bathroom trip or an unplanned reach-out when the resident's state calls for one:

- `morning_toilet_and_wash` — morning wash
- `phone_call` — phone a relative or friend
- `rest_or_nap` — nap
- `sleep` — sleep
- `wake_up` — wake up


You do not declare these as recurring activities — the rhythm decides when they happen — but the
days will contain them, so `personalProcessPackage` must implement every one of them alongside the
intents your outline does declare. A package written only against the declared activities leaves
those days pointing at behaviour nobody authored: on the first eight-month case this produced 628
rejections for five missing models.

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
7. Every process model without exception contains at least one explicit movement action:
   `move_to`, `move_to_capability` or `travel_to`. This also applies to `wake_up`,
   `wake_up_without_alarm`, sleep, rest, calls and other apparently stationary ADLs. For a
   wake-up model, represent leaving the sleeping position or approaching the room-exit or
   next-transition capability after the posture change. Do not return a wake-up model
   containing only `change_posture`.
8. Use only embedded action types and declared parameters. Use structured
   `ValueExpression` objects; never hide multiple actions in a label or invent prose
   actions.
9. Every action has a positive `durationWeight`. Add an absolute bounded `duration` only
   when the researcher description supports that personal timing.
10. Choice nodes have at least two outgoing branches, exactly one default, and a declared
    variable condition on each non-default branch.
11. Parallel splits have a matching join. Every cycle passes through an explicit `loop`
    node with finite `maxIterations`.
12. Use only embedded variables. Add contextual bindings only when behavior changes with
    that context and always provide an unambiguous ordinary fallback.
13. Model movement, posture, resource use and object interaction at the granularity from
    which later execution and sensor activation can be derived. Do not replace an ADL
    with an equally abstract single action.

## Mandatory ValueExpression and reference-kind compatibility

`referenceKind` belongs to each action parameter definition in the embedded action
catalog. It is not a property to copy into a `ValueExpression`. Choose the expression's
`source` according to the parameter's `referenceKind` using this mandatory matrix:

| Expression `source` | Required expression fields | Compatible parameter `referenceKind` |
|---|---|---|
| `activity_location` | `index` | `location` or `none` |
| `activity_resource` | `index` | `resource` or `none` |
| `actor` | no other fields | `resident` or `none` |
| `activity_intent` | no other fields | normally `none` |
| `literal` | `value` | every kind, subject to the rules below |
| `variable` | `variableId` | only when the variable and parameter value types are compatible |

Apply these additional rules:

1. For a literal parameter with `referenceKind = location`, `resource`, `resident` or
   `external_person`, the value must be the identifier of an entity declared in the
   generated scenario.
2. For `referenceKind = capability` or `environment_entity`, use a meaningful symbolic
   literal role that Milestone 4 can bind, such as `coffee_preparation_item`,
   `cooking_appliance`, `medication_storage`, `laundry_appliance` or `cleaning_tool`.
   Do not use `activity_resource` for these parameters.
3. Use `activity_resource` only when the action parameter itself declares
   `referenceKind = resource` or `none`. A scenario resource is not automatically a
   capability or environment-entity role.
4. Use `activity_location` only when the action parameter declares
   `referenceKind = location` or `none`, and always supply a valid zero-based `index` into
   the activity's `locationIds`.
5. Use `actor` only for `resident` or `none` parameters.
6. Literal values must still match `valueType` and any `allowedValues` in the catalog.
7. Use stable semantic roles consistently across take/use/put or
   open/activate/deactivate/close actions that concern the same object. Do not generate
   meaningless placeholders such as `item_1`, `generic_target` or `unknown_role`.

Examples:

Valid movement to the activity's first declared location:

```json
{
  "actionType": "move_to",
  "arguments": {
    "destination": {"source": "activity_location", "index": 0}
  }
}
```

Valid symbolic item role for `take_item`, whose `itemRole` parameter has
`referenceKind = capability`:

```json
{
  "actionType": "take_item",
  "arguments": {
    "itemRole": {"source": "literal", "value": "coffee_preparation_item"}
  }
}
```

Valid symbolic appliance role for `activate`, whose `target` parameter has
`referenceKind = environment_entity`:

```json
{
  "actionType": "activate",
  "arguments": {
    "target": {"source": "literal", "value": "cooking_appliance"}
  }
}
```

Invalid — `activity_resource` resolves a concrete scenario resource and is incompatible
with the capability parameter `take_item.itemRole`:

```json
{
  "actionType": "take_item",
  "arguments": {
    "itemRole": {"source": "activity_resource", "index": 0}
  }
}
```

Before returning the bundle, inspect every action argument against the corresponding
parameter definition. There must be zero `ACTION_ARGUMENT_TYPE_MISMATCH` possibilities.

## Mandatory action state continuity

Structural validity is not sufficient. After behavior validation succeeds, the deterministic
ingestion replays every activity of every day, ordered by scheduled start, through one
persistent per-resident state. Each executed action asserts its catalog preconditions against
that state and then applies its catalog effects. A precondition the replay can prove false
rejects the whole bundle with `DETERMINISTIC_PRECONDITION_FAILED`, even when every model is
individually well formed and every component sequence is complete.

The state is not reset between activities and not reset between days. An action performed in
the morning still constrains an action performed three days later.

These are the preconditions and effects the replay applies. They come from the embedded action
catalog and are restated here because the failures they cause are invisible in a single model:

```text
Preconditions
activate            requires entity.{target}.active eq false
close               requires entity.{target}.open eq true
consume             requires capability.{itemRole}.available eq true
deactivate          requires entity.{target}.active eq true
enter_home          requires resident.at_home eq false
leave_home          requires resident.at_home eq true
open                requires entity.{target}.open eq false
put_item            requires resident.carrying.{itemRole} eq true
take_item           requires capability.{itemRole}.available eq true

Effects
activate            set       entity.{target}.active = true
change_posture      set       resident.posture = "{posture}"
close               set       entity.{target}.open = false
consume             increment capability.{itemRole}.consumed = 1
deactivate          set       entity.{target}.active = false
dress               set       resident.carrying.used_clothing = true
enter_home          set       resident.at_home = true
leave_home          set       resident.at_home = false
move_to             set       resident.location = "{destination}"
move_to_capability  set       resident.location = "{targetRole}"
open                set       entity.{target}.open = true
prepare_food        set       resident.carrying.{outputRole} = true
put_item            set       resident.carrying.{itemRole} = false
shop                set       resident.carrying.purchases = true
take_item           set       resident.carrying.{itemRole} = true
travel_to           set       resident.location = "{destination}"
```

Facts named `entity.<target>.*` and `capability.<role>.*` start unknown, so their preconditions
can only fail after one of your own actions has set them. Facts named `resident.*` start from
`scenario.initialState`, so their preconditions can fail from the very first activity.

Before emitting the bundle, build a private chronological ledger for each resident: sort every
activity of every day by `startWindow.preferred`, walk the action sequence of the bound process
model, and track at least `resident.at_home`, `resident.location`, `resident.carrying.<role>`,
`entity.<target>.open` and `entity.<target>.active`. Do not return the ledger. Apply these
construction rules while walking it:

1. Declare `at_home` explicitly in `initialState.residents[].facts`: `true` when the resident
   starts at home, `false` otherwise. Do not leave it implicit.
2. `leave_home` and `enter_home` strictly alternate. Never emit two consecutive `leave_home`
   actions and never emit two consecutive `enter_home` actions across the whole ledger.
   **An away activity is a round trip inside one model.** A model bound to an away intent leaves
   the home and comes back before its `end` node: `leave_home -> travel_to -> ... -> enter_home`.
   Split across two models it is not a round trip but a wager on ordering, and the two failures
   this produces are the most common defects in authored packages:
   - **Leaving without returning.** `resident.at_home` stays false for the rest of the horizon, so
     *every later outing* fails a precondition that is now deterministically false. The rejection
     is reported against those later activities, weeks away, and never names the model at fault.
   - **Never leaving at all.** A `work_shift` implemented as `move_to -> change_posture ->
     perform_work` describes working at a desk at home. It passes every gate and the resident then
     spends the whole horizon indoors: one eight-month run produced zero `leave_home` actions and
     74 door events, where a real home records several a day. If the intent says the resident is
     out, the model must take her out.
3. Every `put_item(role)` is preceded on every incoming path by an action that grants that exact
   role. A `put_item` whose role was never granted is always deterministically false, and the role
   has to match: taking `ingredients` and putting `prepared_meal` grants one fact and asserts
   another.
   `take_item` grants the role it names, and so do these: `dress` grants `used_clothing`,
   `prepare_food` grants `{outputRole}`, `shop` grants `purchases`. Any one of them satisfies a
   later `put_item` of that same role, with no `take_item` in between.
4. A component whose required sequence begins with `put_item` — `store_food`,
   `store_purchases`, `discard_recycling` — needs an explicit `take_item` of that same role
   inserted before the required sequence whenever the ledger does not already carry it.
5. `open(target)` and `close(target)` are balanced on the same target inside the same model, and
   so are `activate(target)` and `deactivate(target)`. A container left open at the end of one
   activity makes the next `open` of that same container deterministically false, on every
   later day.
   **Anything stored inside something is reached by opening it.** Wrap *every* action that reaches
   inside a container in `open(container) -> ... -> close(container)` whenever the role names one of
   these. `take_item` and `put_item` are the obvious ones, but they are not the only ones:
   `laundry_step(collect)` empties a laundry basket, `laundry_step(load)` fills a washing machine,
   and both reach inside exactly as a `take_item` would.

   - `refrigerator` — `coffee_and_breakfast_storage`, `food_storage`, `ingredients`, `prepared_food_portions`, `prepared_meal`
   - `storage_cabinet` — `cleaning_product_storage`, `cleaning_products`, `household_storage`, `household_supplies`, `medication`, `medication_cabinet`, `medication_storage`
   - `wardrobe` — `clothes`, `clothing_storage`, `laundry_collection`, `laundry_storage`, `used_clothing`
   - `washing_machine` — `laundry`, `laundry_equipment`

   This is what a contact sensor observes, and it is the difference between a home that reports its
   cupboards and one that does not. In one generated eight-month horizon every `open` and `close` in
   the whole log had a single target — the fridge — because the cleaning products, the medication
   and the clothes were taken straight out of closed furniture. The flat ended up with **two**
   contact sensors where a comparable real deployment has four to six, and the cabinets it did
   contain were invisible for eight months.

   Keying this rule on `take_item`/`put_item` alone is what produced the next such horizon: a
   resident who ran the washing machine 104 times over a year and opened it never, because her
   laundry model used `laundry_step` and the rule, read literally, did not apply to it. Both her
   washing machine and her wardrobe published a year of pure noise.
6. Do not change the target or the role between the two halves of a `take_item`/`put_item`,
   `open`/`close` or `activate`/`deactivate` pair.

### Mandatory bridge for a `travel` component performed away from home

The frozen `travel` component requires `leave_home -> travel_to`, and the catalog binds it to
return intents as well: `commute_home`, `travel_home` and `return_home_and_store_purchases`
declare `travel` followed by `enter_home`. When one of these runs, the resident is normally
already outside, so the required `leave_home` is deterministically false and the bundle is
rejected. Removing `leave_home` is not a repair: it produces `PROCESS_COMPONENT_MISMATCH`
instead.

Whenever the ledger says the resident is away from home at the moment a `travel` component
starts, insert this explicit bridge immediately before the required sequence:

```text
move_to_capability(home_entrance) -> enter_home [bridge] -> leave_home [required by travel]
    -> travel_to(destination) -> enter_home [required by the enter_home component]
```

The first `enter_home` is a technical adaptation to the frozen catalog, not an additional
component. Keep `implementedComponents` exactly as the activity catalog declares them. The same
bridge applies to a second outbound `travel` intent chained after an earlier one without an
intervening return home.


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

{"$defs":{"ActivityCadence":{"additionalProperties":false,"description":"How often a recurring activity happens, and inside which hours.\n\n`times_per_period` means different things per period, and both readings are the natural one.\nOver a week or a month it counts *days*: three runs a week are three days on which a run\nhappens. Over a day it counts *occurrences inside that day*, which is what a working day split\ninto blocks, a course of medication taken twice, or a dog walked morning and evening actually\nis. The daily reading used to be discarded — `_due_times` scheduled exactly one occurrence per\nday whatever the field said — so an author writing `period: day, timesPerPeriod: 4` got one\nactivity and no warning.","properties":{"everyNPeriods":{"default":1,"minimum":1,"title":"Everynperiods","type":"integer"},"jitterMinutes":{"default":30,"minimum":0,"title":"Jitterminutes","type":"integer"},"period":{"$ref":"#/$defs/CadencePeriod"},"timesPerPeriod":{"minimum":1,"title":"Timesperperiod","type":"integer"},"weekdays":{"items":{"$ref":"#/$defs/Weekday"},"title":"Weekdays","type":"array"},"windowEnd":{"title":"Windowend","type":"string"},"windowStart":{"title":"Windowstart","type":"string"}},"required":["period","timesPerPeriod","windowStart","windowEnd"],"title":"ActivityCadence","type":"object"},"ActivityDisplacement":{"additionalProperties":false,"description":"One habit the event pushes off its day, and what happens to that occurrence.\n\nThe policy is carried per habit rather than per event because a single event routinely wants\nboth. A week of flu postpones the shopping and simply cancels the runs; forcing one answer for\nthe whole event would misdescribe half of it, and expressing the mixture as two overlapping\nevents would be a workaround rather than a model.","properties":{"policy":{"$ref":"#/$defs/Displacement","default":"skip"},"recurringActivityId":{"minLength":1,"title":"Recurringactivityid","type":"string"}},"required":["recurringActivityId"],"title":"ActivityDisplacement","type":"object"},"ActivityOverride":{"additionalProperties":false,"description":"What a phase does to one habit while it is active.\n\nEither the habit stops occurring, or it occurs on a different cadence. Both at once is\ncontradictory and rejected: a suspended habit has no cadence to replace.","properties":{"cadence":{"anyOf":[{"$ref":"#/$defs/ActivityCadence"},{"type":"null"}],"default":null},"recurringActivityId":{"minLength":1,"title":"Recurringactivityid","type":"string"},"suspended":{"default":false,"title":"Suspended","type":"boolean"}},"required":["recurringActivityId"],"title":"ActivityOverride","type":"object"},"AuthorType":{"enum":["human","external_llm","rule_generator","import"],"title":"AuthorType","type":"string"},"BehaviorCatalogReferences":{"additionalProperties":false,"properties":{"actionCatalog":{"$ref":"#/$defs/CatalogReference"},"activityCatalog":{"$ref":"#/$defs/CatalogReference"},"variableCatalog":{"$ref":"#/$defs/CatalogReference"}},"required":["activityCatalog","variableCatalog","actionCatalog"],"title":"BehaviorCatalogReferences","type":"object"},"BehavioralProfile":{"additionalProperties":false,"properties":{"documentType":{"const":"behavioral_profile","default":"behavioral_profile","title":"Documenttype","type":"string"},"personaId":{"minLength":1,"title":"Personaid","type":"string"},"profileId":{"minLength":1,"title":"Profileid","type":"string"},"provenance":{"$ref":"#/$defs/Provenance"},"recurringActivities":{"items":{"$ref":"#/$defs/RecurringActivity"},"minItems":8,"title":"Recurringactivities","type":"array"},"schemaVersion":{"const":"1.0.0","default":"1.0.0","title":"Schemaversion","type":"string"}},"required":["profileId","personaId","recurringActivities","provenance"],"title":"BehavioralProfile","type":"object"},"CadencePeriod":{"enum":["day","week","month"],"title":"CadencePeriod","type":"string"},"CatalogReference":{"additionalProperties":false,"properties":{"catalogId":{"minLength":1,"title":"Catalogid","type":"string"},"version":{"minLength":1,"title":"Version","type":"string"}},"required":["catalogId","version"],"title":"CatalogReference","type":"object"},"ConditionOperator":{"enum":["truthy","falsy","exists","not_exists","eq","ne","gt","gte","lt","lte","in","not_in"],"title":"ConditionOperator","type":"string"},"Displacement":{"description":"What becomes of a activity occurrence the event pushed off its day.","enum":["skip","reschedule"],"title":"Displacement","type":"string"},"DurationRange":{"additionalProperties":false,"properties":{"maximumMinutes":{"exclusiveMinimum":0,"title":"Maximumminutes","type":"number"},"minimumMinutes":{"exclusiveMinimum":0,"title":"Minimumminutes","type":"number"},"preferredMinutes":{"exclusiveMinimum":0,"title":"Preferredminutes","type":"number"}},"required":["minimumMinutes","preferredMinutes","maximumMinutes"],"title":"DurationRange","type":"object"},"EffectOperation":{"enum":["set","increment","decrement","append","remove"],"title":"EffectOperation","type":"string"},"ExternalPerson":{"additionalProperties":false,"properties":{"attributes":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Attributes","type":"object"},"displayName":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Displayname"},"externalPersonId":{"minLength":1,"title":"Externalpersonid","type":"string"},"relationshipToResidents":{"additionalProperties":{"type":"string"},"title":"Relationshiptoresidents","type":"object"}},"required":["externalPersonId"],"title":"ExternalPerson","type":"object"},"FixedCommitment":{"additionalProperties":false,"description":"The one place absolute clock times are legitimate.\n\nWorking hours and appointments are fixed by someone other than the resident, so pinning them\nis a fact about the world rather than a schedule the model invented. Everything else in this\ncontract is a window.","properties":{"commitmentId":{"minLength":1,"title":"Commitmentid","type":"string"},"endDate":{"anyOf":[{"format":"date","type":"string"},{"type":"null"}],"default":null,"title":"Enddate"},"endTime":{"title":"Endtime","type":"string"},"intent":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Intent"},"label":{"minLength":1,"title":"Label","type":"string"},"note":{"default":"","title":"Note","type":"string"},"startDate":{"anyOf":[{"format":"date","type":"string"},{"type":"null"}],"default":null,"title":"Startdate"},"startTime":{"title":"Starttime","type":"string"},"weekdays":{"items":{"$ref":"#/$defs/Weekday"},"minItems":1,"title":"Weekdays","type":"array"}},"required":["commitmentId","label","weekdays","startTime","endTime"],"title":"FixedCommitment","type":"object"},"HabitSegment":{"additionalProperties":false,"description":"A habit in the sense the smart-home literature uses the word.\n\nLeotta, Mecella and Sora define a habit as \"a sequence or interleaving of activities that\nhappen in specific contextual conditions\", the focus being the routine rather than the goal —\nwhat the resident does each morning between 08:00 and 10:00. The habit-segmentation work makes\nthe same point operationally: it discretises the timestamp axis, and each bin is a time range\nin which a clearly identifiable process runs. In their Aruba results the bin `05:15-07:00` is\nabout 80% the *sleeping activity*, with `bed_to_toilet` and `meal_preparation` making up most\nof the rest.\n\nSo a habit is a band of the day, and activities live inside it. That is why this contract\nseparates the two: `RecurringActivity` says what recurs and how often, and this says how the\nday is carved up. A researcher's segmentation algorithm is trying to recover exactly these\nbands from a sensor log, which is why the expander publishes them as ground truth.\n\nThe night band is the one that legitimately wraps: `window_start` after `window_end` means the\nsegment crosses midnight.\n\nA band may also be scoped to particular days. Working hours are already weekday-scoped —\n`FixedCommitment.weekdays` is mandatory — so a single band covering 08:30-17:30 every day of\nthe week has to hold both the working day and the domestic Saturday, and a segmentation\nalgorithm asked to recover it is being asked to find one boundary for two behaviours. Measured\non a generated year: the same band was `work_shift` at 96% across 260 weekdays and, across 105\nweekend days, a mixture whose largest component was `buy_groceries` at 23%. The band that\nproduced those numbers had been named \"Fascia diurna e weekend domestico\" by its author, who\ncould see the problem and had no field in which to say it.","properties":{"habitId":{"minLength":1,"title":"Habitid","type":"string"},"label":{"minLength":1,"title":"Label","type":"string"},"note":{"default":"","title":"Note","type":"string"},"recurringActivityIds":{"items":{"type":"string"},"title":"Recurringactivityids","type":"array"},"weekdays":{"items":{"$ref":"#/$defs/Weekday"},"title":"Weekdays","type":"array"},"windowEnd":{"title":"Windowend","type":"string"},"windowStart":{"title":"Windowstart","type":"string"}},"required":["habitId","label","windowStart","windowEnd"],"title":"HabitSegment","type":"object"},"HorizonOutline":{"additionalProperties":false,"description":"One brief, one confirmed outline, any horizon length.\n\nNothing here grows with the number of days: a year and eight months differ in the event list,\nnot in the structure. The confirmed outline is also the habit ground truth the external\nauthoring path has never produced, `mining_difficulty` included.","properties":{"documentType":{"const":"horizon_outline","default":"horizon_outline","title":"Documenttype","type":"string"},"events":{"items":{"$ref":"#/$defs/OutlineEvent"},"title":"Events","type":"array"},"fixedCommitments":{"items":{"$ref":"#/$defs/FixedCommitment"},"title":"Fixedcommitments","type":"array"},"habits":{"items":{"$ref":"#/$defs/HabitSegment"},"title":"Habits","type":"array"},"months":{"minimum":1,"title":"Months","type":"integer"},"note":{"default":"","title":"Note","type":"string"},"outlineId":{"minLength":1,"title":"Outlineid","type":"string"},"phases":{"items":{"$ref":"#/$defs/OutlinePhase"},"title":"Phases","type":"array"},"profile":{"$ref":"#/$defs/BehavioralProfile"},"provenance":{"$ref":"#/$defs/Provenance"},"residentId":{"minLength":1,"title":"Residentid","type":"string"},"rhythm":{"$ref":"#/$defs/OutlineRhythm"},"schemaVersion":{"const":"1.0.0","default":"1.0.0","title":"Schemaversion","type":"string"},"startDate":{"format":"date","title":"Startdate","type":"string"},"timeZone":{"minLength":1,"title":"Timezone","type":"string"},"title":{"minLength":1,"title":"Title","type":"string"},"world":{"$ref":"#/$defs/OutlineWorld"}},"required":["outlineId","title","residentId","timeZone","startDate","months","world","profile","provenance"],"title":"Smart Home Horizon Outline 1.0.0","type":"object"},"JsonValue":{},"Location":{"additionalProperties":false,"properties":{"attributes":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Attributes","type":"object"},"kind":{"$ref":"#/$defs/LocationKind"},"locationId":{"minLength":1,"title":"Locationid","type":"string"},"memberLocationIds":{"items":{"type":"string"},"title":"Memberlocationids","type":"array"}},"required":["locationId","kind"],"title":"Location","type":"object"},"LocationKind":{"enum":["room","external","transit","composite"],"title":"LocationKind","type":"string"},"OutlineEvent":{"additionalProperties":false,"description":"Something that happens a bounded number of times inside a date window.\n\nThe window is the point. `earliest_date == latest_date` pins the day when the day genuinely is\nfixed; anything wider hands the placement to the expander, which owns the calendar and the\ndrive state and can put the event where the resident could plausibly absorb it.","properties":{"displaces":{"items":{"$ref":"#/$defs/ActivityDisplacement"},"title":"Displaces","type":"array"},"earliestDate":{"format":"date","title":"Earliestdate","type":"string"},"eventId":{"minLength":1,"title":"Eventid","type":"string"},"intent":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Intent"},"label":{"minLength":1,"title":"Label","type":"string"},"latestDate":{"format":"date","title":"Latestdate","type":"string"},"maximumMinutes":{"default":120,"minimum":1,"title":"Maximumminutes","type":"integer"},"minimumMinutes":{"default":30,"minimum":1,"title":"Minimumminutes","type":"integer"},"note":{"default":"","title":"Note","type":"string"},"occurrences":{"default":1,"minimum":1,"title":"Occurrences","type":"integer"},"weekdays":{"items":{"$ref":"#/$defs/Weekday"},"title":"Weekdays","type":"array"},"windowEnd":{"default":"22:00","title":"Windowend","type":"string"},"windowStart":{"default":"08:00","title":"Windowstart","type":"string"}},"required":["eventId","label","earliestDate","latestDate"],"title":"OutlineEvent","type":"object"},"OutlinePhase":{"additionalProperties":false,"description":"A stretch of the horizon over which the routine is not the baseline routine.\n\nA phase is what makes eight months more than one month repeated eight times: a course that\noccupies Tuesday evenings from October, a fortnight away, a winter in which the walk stops.\nIt carries dates, never instants, and reshapes recurring_activities only through explicit\noverrides.","properties":{"activityOverrides":{"items":{"$ref":"#/$defs/ActivityOverride"},"title":"Activityoverrides","type":"array"},"endDate":{"format":"date","title":"Enddate","type":"string"},"label":{"minLength":1,"title":"Label","type":"string"},"note":{"default":"","title":"Note","type":"string"},"phaseId":{"minLength":1,"title":"Phaseid","type":"string"},"startDate":{"format":"date","title":"Startdate","type":"string"}},"required":["phaseId","label","startDate","endDate"],"title":"OutlinePhase","type":"object"},"OutlineRhythm":{"additionalProperties":false,"description":"The persona-level constants the drive dynamics need, and nothing more.\n\nAge sets the nightly sleep need and the nocturia baseline; declared conditions move the same\ntwo dials. Everything downstream of these — the actual bedtimes, the debt, the naps — is\ncomputed, which is why an author declares who the resident is rather than when she sleeps.","properties":{"age":{"default":45,"maximum":120,"minimum":1,"title":"Age","type":"integer"},"chronotypeBedtime":{"default":"22:30","title":"Chronotypebedtime","type":"string"},"health":{"items":{"type":"string"},"title":"Health","type":"array"}},"title":"OutlineRhythm","type":"object"},"OutlineWorld":{"additionalProperties":false,"description":"Where the routine happens, declared once for the whole horizon.\n\nADR-015 materializes the executable home from the scenario's declared locations, so those\ndeclarations have to come from the author rather than from a generator that never read the\nbrief. Like everything else here, this is O(1) in the horizon.","properties":{"environmentFacts":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Environmentfacts","type":"object"},"externalPeople":{"items":{"$ref":"#/$defs/ExternalPerson"},"title":"Externalpeople","type":"array"},"homeModel":{"$ref":"#/$defs/VersionedReference"},"locations":{"items":{"$ref":"#/$defs/Location"},"minItems":1,"title":"Locations","type":"array"},"residentFacts":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Residentfacts","type":"object"},"resourceFacts":{"additionalProperties":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"type":"object"},"title":"Resourcefacts","type":"object"},"resources":{"items":{"$ref":"#/$defs/Resource"},"title":"Resources","type":"array"},"startLocationId":{"minLength":1,"title":"Startlocationid","type":"string"}},"required":["homeModel","locations","startLocationId"],"title":"OutlineWorld","type":"object"},"PersonalProcessPackage":{"additionalProperties":false,"properties":{"bindings":{"items":{"$ref":"#/$defs/ProcessBinding"},"minItems":1,"title":"Bindings","type":"array"},"catalogs":{"$ref":"#/$defs/BehaviorCatalogReferences"},"documentType":{"const":"personal_process_package","default":"personal_process_package","title":"Documenttype","type":"string"},"language":{"minLength":2,"title":"Language","type":"string"},"packageId":{"minLength":1,"title":"Packageid","type":"string"},"packageVersion":{"minLength":1,"title":"Packageversion","type":"string"},"processModels":{"items":{"$ref":"#/$defs/ProcessModel"},"minItems":1,"title":"Processmodels","type":"array"},"provenance":{"$ref":"#/$defs/Provenance"},"schemaVersion":{"const":"1.0.0","default":"1.0.0","title":"Schemaversion","type":"string"},"sourceScenarioId":{"minLength":1,"title":"Sourcescenarioid","type":"string"},"sourceScenarioVersion":{"minLength":1,"title":"Sourcescenarioversion","type":"string"}},"required":["packageId","packageVersion","sourceScenarioId","sourceScenarioVersion","language","provenance","catalogs","processModels","bindings"],"title":"Smart Home Personal Process Package 1.0.0","type":"object"},"ProcessBinding":{"additionalProperties":false,"properties":{"applicability":{"items":{"$ref":"#/$defs/VariableCondition"},"title":"Applicability","type":"array"},"bindingId":{"minLength":1,"title":"Bindingid","type":"string"},"fallback":{"default":false,"title":"Fallback","type":"boolean"},"intent":{"minLength":1,"title":"Intent","type":"string"},"processModelId":{"minLength":1,"title":"Processmodelid","type":"string"},"residentId":{"minLength":1,"title":"Residentid","type":"string"}},"required":["bindingId","residentId","intent","processModelId"],"title":"ProcessBinding","type":"object"},"ProcessEdge":{"additionalProperties":false,"properties":{"condition":{"anyOf":[{"$ref":"#/$defs/VariableCondition"},{"type":"null"}],"default":null},"isDefault":{"default":false,"title":"Isdefault","type":"boolean"},"sourceNodeId":{"minLength":1,"title":"Sourcenodeid","type":"string"},"targetNodeId":{"minLength":1,"title":"Targetnodeid","type":"string"}},"required":["sourceNodeId","targetNodeId"],"title":"ProcessEdge","type":"object"},"ProcessModel":{"additionalProperties":false,"properties":{"description":{"minLength":1,"title":"Description","type":"string"},"edges":{"items":{"$ref":"#/$defs/ProcessEdge"},"minItems":1,"title":"Edges","type":"array"},"implementedComponents":{"items":{"type":"string"},"minItems":1,"title":"Implementedcomponents","type":"array"},"nodes":{"items":{"$ref":"#/$defs/ProcessNode"},"minItems":2,"title":"Nodes","type":"array"},"processModelId":{"minLength":1,"title":"Processmodelid","type":"string"},"processModelVersion":{"minLength":1,"title":"Processmodelversion","type":"string"},"residentId":{"minLength":1,"title":"Residentid","type":"string"},"title":{"minLength":1,"title":"Title","type":"string"}},"required":["processModelId","processModelVersion","residentId","title","description","implementedComponents","nodes","edges"],"title":"ProcessModel","type":"object"},"ProcessNode":{"additionalProperties":false,"properties":{"actionType":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Actiontype"},"arguments":{"additionalProperties":{"$ref":"#/$defs/ValueExpression"},"title":"Arguments","type":"object"},"duration":{"anyOf":[{"$ref":"#/$defs/DurationRange"},{"type":"null"}],"default":null},"durationWeight":{"anyOf":[{"exclusiveMinimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Durationweight"},"effects":{"items":{"$ref":"#/$defs/StateEffect"},"title":"Effects","type":"array"},"kind":{"$ref":"#/$defs/ProcessNodeKind"},"maxIterations":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Maxiterations"},"nodeId":{"minLength":1,"title":"Nodeid","type":"string"},"preconditions":{"items":{"$ref":"#/$defs/VariableCondition"},"title":"Preconditions","type":"array"}},"required":["nodeId","kind"],"title":"ProcessNode","type":"object"},"ProcessNodeKind":{"enum":["start","end","action","choice","parallel_split","parallel_join","loop"],"title":"ProcessNodeKind","type":"string"},"Provenance":{"additionalProperties":false,"properties":{"authorType":{"$ref":"#/$defs/AuthorType"},"generatedAt":{"anyOf":[{"format":"date-time","type":"string"},{"type":"null"}],"default":null,"title":"Generatedat"},"generatorName":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Generatorname"},"generatorVersion":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Generatorversion"},"humanReviewed":{"default":false,"title":"Humanreviewed","type":"boolean"},"modelName":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Modelname"},"parameters":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Parameters","type":"object"},"promptTemplateVersion":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Prompttemplateversion"}},"required":["authorType"],"title":"Provenance","type":"object"},"RecurringActivity":{"additionalProperties":false,"properties":{"cadence":{"$ref":"#/$defs/ActivityCadence"},"intent":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Intent"},"kind":{"$ref":"#/$defs/RecurringActivityKind"},"label":{"minLength":1,"title":"Label","type":"string"},"miningDifficulty":{"default":"medium","enum":["easy","medium","hard"],"title":"Miningdifficulty","type":"string"},"note":{"default":"","title":"Note","type":"string"},"recurringActivityId":{"minLength":1,"title":"Recurringactivityid","type":"string"}},"required":["recurringActivityId","label","kind","cadence"],"title":"RecurringActivity","type":"object"},"RecurringActivityKind":{"enum":["anchor","contextual","optional","rare"],"title":"RecurringActivityKind","type":"string"},"Resource":{"additionalProperties":false,"properties":{"attributes":{"additionalProperties":{"$ref":"#/$defs/JsonValue"},"title":"Attributes","type":"object"},"capacity":{"default":1,"minimum":1,"title":"Capacity","type":"integer"},"locationId":{"minLength":1,"title":"Locationid","type":"string"},"resourceId":{"minLength":1,"title":"Resourceid","type":"string"},"resourceType":{"minLength":1,"title":"Resourcetype","type":"string"}},"required":["resourceId","resourceType","locationId"],"title":"Resource","type":"object"},"StateEffect":{"additionalProperties":false,"properties":{"fact":{"minLength":1,"title":"Fact","type":"string"},"operation":{"$ref":"#/$defs/EffectOperation"},"value":{"$ref":"#/$defs/JsonValue"}},"required":["fact","operation","value"],"title":"StateEffect","type":"object"},"ValueExpression":{"additionalProperties":false,"properties":{"index":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Index"},"source":{"$ref":"#/$defs/ValueSource"},"value":{"anyOf":[{"$ref":"#/$defs/JsonValue"},{"type":"null"}],"default":null},"variableId":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Variableid"}},"required":["source"],"title":"ValueExpression","type":"object"},"ValueSource":{"enum":["literal","variable","activity_location","activity_resource","activity_intent","actor"],"title":"ValueSource","type":"string"},"VariableCondition":{"additionalProperties":false,"properties":{"operator":{"$ref":"#/$defs/ConditionOperator","default":"truthy"},"value":{"anyOf":[{"$ref":"#/$defs/JsonValue"},{"type":"null"}],"default":null},"variableId":{"minLength":1,"title":"Variableid","type":"string"}},"required":["variableId"],"title":"VariableCondition","type":"object"},"VersionedReference":{"additionalProperties":false,"properties":{"referenceId":{"minLength":1,"title":"Referenceid","type":"string"},"version":{"minLength":1,"title":"Version","type":"string"}},"required":["referenceId","version"],"title":"VersionedReference","type":"object"},"Weekday":{"enum":["monday","tuesday","wednesday","thursday","friday","saturday","sunday"],"title":"Weekday","type":"string"}},"$id":"urn:smart-home-simulator:schema:horizon-authoring-bundle:1.0.0","$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"description":"Transport envelope for outline-first authoring: the arc, and how its actions are performed.\n\nKept apart for the same reason `SimulationAuthoringBundle` keeps scenario and package apart:\nthe two halves answer to different reviewers. A human confirms the outline, because whether\neight months are plausible is not a machine question. The process package is already gated by\nbehavior validation and the deterministic replay, so nobody needs to read its twenty-four\ngraphs by hand.\n\nNeither half grows with the horizon. The package is per-intent, which is why moving the days\nout of the model's output removes the entire horizon-proportional part of the response.","properties":{"documentType":{"const":"horizon_authoring_bundle","default":"horizon_authoring_bundle","title":"Documenttype","type":"string"},"outline":{"$ref":"#/$defs/HorizonOutline"},"personalProcessPackage":{"$ref":"#/$defs/PersonalProcessPackage"},"schemaVersion":{"const":"1.0.0","default":"1.0.0","title":"Schemaversion","type":"string"}},"required":["outline","personalProcessPackage"],"title":"Smart Home Horizon Authoring Bundle 1.0.0","type":"object"}

## Authoritative activity catalog

{"activities":[{"category":"errand","components":["shop","carry_purchases"],"description":"Project-specific activity intent 'buy_fresh_food_and_household_supplies'. Acquire goods, medication, or household supplies outside the home.","displayName":"Buy Fresh Food And Household Supplies","externalMappings":{},"intent":"buy_fresh_food_and_household_supplies","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.food_inventory","resident.mobility_profile"]},{"category":"errand","components":["shop","carry_purchases"],"description":"Project-specific activity intent 'buy_groceries'. Acquire goods, medication, or household supplies outside the home.","displayName":"Buy Groceries","externalMappings":{},"intent":"buy_groceries","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.food_inventory","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes"],"description":"Project-specific activity intent 'change_clothes'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Change Clothes","externalMappings":{},"intent":"change_clothes","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes","consume_snack"],"description":"Project-specific activity intent 'change_clothes_and_eat_snack'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Change Clothes And Eat Snack","externalMappings":{},"intent":"change_clothes_and_eat_snack","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes","consume_drink"],"description":"Project-specific activity intent 'change_clothes_and_have_coffee'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Change Clothes And Have Coffee","externalMappings":{},"intent":"change_clothes_and_have_coffee","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes","consume_snack"],"description":"Project-specific activity intent 'change_clothes_and_have_snack'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Change Clothes And Have Snack","externalMappings":{},"intent":"change_clothes_and_have_snack","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"leisure","components":["check_calendar","inspect_supplies"],"description":"Project-specific activity intent 'check_calendar_and_household_supplies'. Rest, read, watch media, or perform another leisure activity.","displayName":"Check Calendar And Household Supplies","externalMappings":{"casas_aruba":"Relax"},"intent":"check_calendar_and_household_supplies","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"housekeeping","components":["clean_surface"],"description":"Project-specific activity intent 'clean_bathroom'. Clean, tidy, maintain, or organize the home.","displayName":"Clean Bathroom","externalMappings":{"casas_aruba":"Housekeeping"},"intent":"clean_bathroom","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"housekeeping","components":["clean_surface"],"description":"Project-specific activity intent 'clean_kitchen'. Clean, tidy, maintain, or organize the home.","displayName":"Clean Kitchen","externalMappings":{"casas_aruba":"Housekeeping"},"intent":"clean_kitchen","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"travel","components":["collect_belongings","leave_home"],"description":"Project-specific activity intent 'collect_belongings_and_leave_home'. Enter, leave, or travel between declared locations.","displayName":"Collect Belongings And Leave Home","externalMappings":{"casas_aruba":"Leave_Home"},"intent":"collect_belongings_and_leave_home","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"medication","components":["collect_medication"],"description":"Project-specific activity intent 'collect_medication_refill'. Take, collect, or manage medication.","displayName":"Collect Medication Refill","externalMappings":{},"intent":"collect_medication_refill","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.medication_available_doses","resident.mobility_profile"]},{"category":"travel","components":["travel","enter_home"],"description":"Project-specific activity intent 'commute_home'. Enter, leave, or travel between declared locations.","displayName":"Commute Home","externalMappings":{},"intent":"commute_home","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'commute_to_work'. Enter, leave, or travel between declared locations.","displayName":"Commute To Work","externalMappings":{},"intent":"commute_to_work","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"housekeeping","components":["wash_dishes"],"description":"Project-specific activity intent 'complete_pending_dishwashing'. Clean, tidy, maintain, or organize the home.","displayName":"Complete Pending Dishwashing","externalMappings":{"casas_aruba":"Wash_Dishes"},"intent":"complete_pending_dishwashing","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'cook_chicken_and_vegetables'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Cook Chicken And Vegetables","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"cook_chicken_and_vegetables","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'cook_dinner'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Cook Dinner","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"cook_dinner","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes"],"description":"Project-specific activity intent 'dress_for_work'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Dress For Work","externalMappings":{},"intent":"dress_for_work","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"eating","components":["consume_snack"],"description":"Project-specific activity intent 'eat_afternoon_snack'. Consume a meal, snack, or drink.","displayName":"Eat Afternoon Snack","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_afternoon_snack","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal"],"description":"Project-specific activity intent 'eat_breakfast'. Consume a meal, snack, or drink.","displayName":"Eat Breakfast","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_breakfast","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal","listen_radio"],"description":"Project-specific activity intent 'eat_breakfast_and_listen_to_radio'. Consume a meal, snack, or drink.","displayName":"Eat Breakfast And Listen To Radio","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_breakfast_and_listen_to_radio","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal","read_news"],"description":"Project-specific activity intent 'eat_breakfast_and_read_news'. Consume a meal, snack, or drink.","displayName":"Eat Breakfast And Read News","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_breakfast_and_read_news","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal","listen_radio"],"description":"Project-specific activity intent 'eat_breakfast_with_radio_news'. Consume a meal, snack, or drink.","displayName":"Eat Breakfast With Radio News","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_breakfast_with_radio_news","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal"],"description":"Project-specific activity intent 'eat_dinner'. Consume a meal, snack, or drink.","displayName":"Eat Dinner","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_dinner","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal"],"description":"Project-specific activity intent 'eat_light_dinner'. Consume a meal, snack, or drink.","displayName":"Eat Light Dinner","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_light_dinner","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"eating","components":["consume_meal"],"description":"Project-specific activity intent 'eat_lunch'. Consume a meal, snack, or drink.","displayName":"Eat Lunch","externalMappings":{"casas_aruba":"Eating"},"intent":"eat_lunch","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"hygiene","components":["personal_hygiene"],"description":"Project-specific activity intent 'evening_hygiene'. Perform personal hygiene or bathroom care.","displayName":"Evening Hygiene","externalMappings":{},"intent":"evening_hygiene","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"exercise","components":["walk"],"description":"Project-specific activity intent 'evening_walk'. Perform intentional physical exercise or walking.","displayName":"Evening Walk","externalMappings":{},"intent":"evening_walk","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'go_to_neighborhood_market'. Enter, leave, or travel between declared locations.","displayName":"Go To Neighborhood Market","externalMappings":{},"intent":"go_to_neighborhood_market","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"laundry","components":["hang_laundry"],"description":"Project-specific activity intent 'hang_bed_linen'. Wash, dry, hang, or iron clothing and household textiles.","displayName":"Hang Bed Linen","externalMappings":{},"intent":"hang_bed_linen","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile"]},{"category":"laundry","components":["hang_laundry"],"description":"Project-specific activity intent 'hang_laundry'. Wash, dry, hang, or iron clothing and household textiles.","displayName":"Hang Laundry","externalMappings":{},"intent":"hang_laundry","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile"]},{"category":"exercise","components":["exercise"],"description":"Project-specific activity intent 'indoor_light_exercise'. Perform intentional physical exercise or walking.","displayName":"Indoor Light Exercise","externalMappings":{},"intent":"indoor_light_exercise","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"laundry","components":["iron_laundry"],"description":"Project-specific activity intent 'iron_work_shirts'. Wash, dry, hang, or iron clothing and household textiles.","displayName":"Iron Work Shirts","externalMappings":{},"intent":"iron_work_shirts","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile"]},{"category":"travel","components":["leave_home"],"description":"Project-specific activity intent 'leave_home'. Enter, leave, or travel between declared locations.","displayName":"Leave Home","externalMappings":{"casas_aruba":"Leave_Home"},"intent":"leave_home","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"exercise","components":["walk"],"description":"Project-specific activity intent 'long_sunday_walk'. Perform intentional physical exercise or walking.","displayName":"Long Sunday Walk","externalMappings":{},"intent":"long_sunday_walk","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"hygiene","components":["use_toilet","shower"],"description":"Project-specific activity intent 'morning_toilet_and_shower'. Perform personal hygiene or bathroom care.","displayName":"Morning Toilet And Shower","externalMappings":{},"intent":"morning_toilet_and_shower","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"hygiene","components":["use_toilet","wash_face"],"description":"Project-specific activity intent 'morning_toilet_and_wash'. Perform personal hygiene or bathroom care.","displayName":"Morning Toilet And Wash","externalMappings":{},"intent":"morning_toilet_and_wash","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"communication","components":["phone_call"],"description":"Project-specific activity intent 'phone_call'. Communicate or maintain a social relationship.","displayName":"Phone call","externalMappings":{},"intent":"phone_call","relevantVariableIds":["calendar.season","day.type","resident.age","resident.mobility_profile","resident.social_need","resident.stress"]},{"category":"meal_preparation","components":["portion_food","store_food"],"description":"Project-specific activity intent 'portion_and_store_prepared_food'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Portion And Store Prepared Food","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"portion_and_store_prepared_food","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"hygiene","components":["shower"],"description":"Project-specific activity intent 'post_walk_shower'. Perform personal hygiene or bathroom care.","displayName":"Post Walk Shower","externalMappings":{},"intent":"post_walk_shower","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_drink","consume_drink"],"description":"Project-specific activity intent 'prepare_and_drink_hot_drink'. Make a coffee or tea and drink it: the short trip to the kitchen that breaks up a stretch of work or an afternoon.","displayName":"Make A Hot Drink","externalMappings":{},"intent":"prepare_and_drink_hot_drink","relevantVariableIds":["calendar.season","day.type","resident.age","resident.mobility_profile","resident.preferred_breakfast_drink"]},{"category":"meal_preparation","components":["prepare_food","consume_meal"],"description":"Project-specific activity intent 'prepare_and_eat_breakfast'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare And Eat Breakfast","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_and_eat_breakfast","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_breakfast'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Breakfast","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_breakfast","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_drink","consume_drink"],"description":"Project-specific activity intent 'prepare_coffee_and_drink_on_balcony'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Coffee And Drink On Balcony","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_coffee_and_drink_on_balcony","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile","resident.preferred_breakfast_drink"]},{"category":"dressing","components":["organize_clothes","organize_bag"],"description":"Project-specific activity intent 'prepare_friday_clothes_and_bag'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Prepare Friday Clothes And Bag","externalMappings":{},"intent":"prepare_friday_clothes_and_bag","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_light_dinner'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Light Dinner","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_light_dinner","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"dressing","components":["organize_clothes","organize_bag","organize_documents"],"description":"Project-specific activity intent 'prepare_monday_clothes_bag_and_documents'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Prepare Monday Clothes Bag And Documents","externalMappings":{},"intent":"prepare_monday_clothes_bag_and_documents","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"dressing","components":["organize_clothes","organize_bag"],"description":"Project-specific activity intent 'prepare_next_workday'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Prepare Next Workday","externalMappings":{},"intent":"prepare_next_workday","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"dressing","components":["organize_clothes","organize_bag"],"description":"Project-specific activity intent 'prepare_next_workday_clothes_and_bag'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Prepare Next Workday Clothes And Bag","externalMappings":{},"intent":"prepare_next_workday_clothes_and_bag","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food","prepare_salad"],"description":"Project-specific activity intent 'prepare_quick_pasta_and_salad'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Quick Pasta And Salad","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_quick_pasta_and_salad","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_rice_and_vegetables'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Rice And Vegetables","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_rice_and_vegetables","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_simple_lunch'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Simple Lunch","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_simple_lunch","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_sunday_lunch'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Sunday Lunch","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_sunday_lunch","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"dressing","components":["change_clothes","collect_belongings"],"description":"Project-specific activity intent 'prepare_to_visit_relative'. Dress, change clothes, or prepare clothing and personal belongings.","displayName":"Prepare to visit relative","externalMappings":{},"intent":"prepare_to_visit_relative","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"meal_preparation","components":["prepare_food"],"description":"Project-specific activity intent 'prepare_weekend_breakfast'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Prepare Weekend Breakfast","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"prepare_weekend_breakfast","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"errand","components":["store_purchases"],"description":"Project-specific activity intent 'put_groceries_away'. Acquire goods, medication, or household supplies outside the home.","displayName":"Put Groceries Away","externalMappings":{},"intent":"put_groceries_away","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.food_inventory","resident.mobility_profile"]},{"category":"leisure","components":["read"],"description":"Project-specific activity intent 'read'. Rest, read, watch media, or perform another leisure activity.","displayName":"Read","externalMappings":{"casas_aruba":"Relax"},"intent":"read","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["read","rest"],"description":"Project-specific activity intent 'read_and_rest'. Rest, read, watch media, or perform another leisure activity.","displayName":"Read And Rest","externalMappings":{"casas_aruba":"Relax"},"intent":"read_and_rest","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"sleep","components":["read_in_bed"],"description":"Project-specific activity intent 'read_in_bed'. Enter, leave, or maintain a sleeping state.","displayName":"Read In Bed","externalMappings":{"casas_aruba":"Sleeping"},"intent":"read_in_bed","relevantVariableIds":["calendar.season","day.type","resident.age","resident.chronotype","resident.fatigue","resident.mobility_profile"]},{"category":"meal_preparation","components":["reheat_food","prepare_salad"],"description":"Project-specific activity intent 'reheat_leftover_dinner_and_prepare_salad'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Reheat Leftover Dinner And Prepare Salad","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"reheat_leftover_dinner_and_prepare_salad","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"leisure","components":["rest"],"description":"Project-specific activity intent 'rest'. Rest, read, watch media, or perform another leisure activity.","displayName":"Rest","externalMappings":{"casas_aruba":"Relax"},"intent":"rest","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["rest","read"],"description":"Project-specific activity intent 'rest_and_read'. Rest, read, watch media, or perform another leisure activity.","displayName":"Rest And Read","externalMappings":{"casas_aruba":"Relax"},"intent":"rest_and_read","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["rest","nap"],"description":"Project-specific activity intent 'rest_or_nap'. Rest, read, watch media, or perform another leisure activity.","displayName":"Rest Or Nap","externalMappings":{"casas_aruba":"Relax"},"intent":"rest_or_nap","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"travel","components":["travel","enter_home","store_purchases"],"description":"Project-specific activity intent 'return_home_and_store_purchases'. Enter, leave, or travel between declared locations.","displayName":"Return Home And Store Purchases","externalMappings":{"casas_aruba":"Enter_Home"},"intent":"return_home_and_store_purchases","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"exercise","components":["walk"],"description":"Project-specific activity intent 'short_evening_walk'. Perform intentional physical exercise or walking.","displayName":"Short Evening Walk","externalMappings":{},"intent":"short_evening_walk","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"hygiene","components":["shower","change_clothes"],"description":"Project-specific activity intent 'shower_and_get_ready_to_go_out'. Perform personal hygiene or bathroom care.","displayName":"Shower And Get Ready To Go Out","externalMappings":{},"intent":"shower_and_get_ready_to_go_out","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"sleep","components":["sleep"],"description":"Project-specific activity intent 'sleep'. Enter, leave, or maintain a sleeping state.","displayName":"Sleep","externalMappings":{"casas_aruba":"Sleeping"},"intent":"sleep","relevantVariableIds":["calendar.season","day.type","resident.age","resident.chronotype","resident.fatigue","resident.mobility_profile"]},{"category":"social_visit","components":["socialize_in_person","consume_drink"],"description":"Project-specific activity intent 'social_drink_out'. Travel for or participate in an in-person social visit.","displayName":"Social drink out","externalMappings":{},"intent":"social_drink_out","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.social_need"]},{"category":"laundry","components":["collect_laundry","load_laundry","start_laundry"],"description":"Project-specific activity intent 'start_bed_linen_laundry'. Wash, dry, hang, or iron clothing and household textiles.","displayName":"Start Bed Linen Laundry","externalMappings":{},"intent":"start_bed_linen_laundry","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile"]},{"category":"laundry","components":["collect_laundry","load_laundry","start_laundry"],"description":"Project-specific activity intent 'start_laundry'. Wash, dry, hang, or iron clothing and household textiles.","displayName":"Start Laundry","externalMappings":{},"intent":"start_laundry","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile"]},{"category":"medication","components":["take_medication"],"description":"Project-specific activity intent 'take_morning_medication'. Take, collect, or manage medication.","displayName":"Take Morning Medication","externalMappings":{},"intent":"take_morning_medication","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.medication_available_doses","resident.mobility_profile"]},{"category":"travel","components":["carry_recycling","leave_home","discard_recycling"],"description":"Project-specific activity intent 'take_recycling_out'. Enter, leave, or travel between declared locations.","displayName":"Take Recycling Out","externalMappings":{},"intent":"take_recycling_out","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"housekeeping","components":["tidy_area"],"description":"Project-specific activity intent 'tidy_living_room_and_hallway'. Clean, tidy, maintain, or organize the home.","displayName":"Tidy Living Room And Hallway","externalMappings":{"casas_aruba":"Housekeeping"},"intent":"tidy_living_room_and_hallway","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"travel","components":["travel","enter_home"],"description":"Project-specific activity intent 'travel_home'. Enter, leave, or travel between declared locations.","displayName":"Travel Home","externalMappings":{},"intent":"travel_home","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'travel_to_neighborhood_bar'. Enter, leave, or travel between declared locations.","displayName":"Travel To Neighborhood Bar","externalMappings":{},"intent":"travel_to_neighborhood_bar","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'travel_to_pharmacy'. Enter, leave, or travel between declared locations.","displayName":"Travel To Pharmacy","externalMappings":{},"intent":"travel_to_pharmacy","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'travel_to_relatives_home'. Enter, leave, or travel between declared locations.","displayName":"Travel to relative's home","externalMappings":{},"intent":"travel_to_relatives_home","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"travel","components":["travel"],"description":"Project-specific activity intent 'travel_to_supermarket'. Enter, leave, or travel between declared locations.","displayName":"Travel To Supermarket","externalMappings":{},"intent":"travel_to_supermarket","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.walking_speed"]},{"category":"hygiene","components":["use_toilet"],"description":"Project-specific activity intent 'use_toilet'. A short visit to the bathroom on its own, outside the morning and evening hygiene routines.","displayName":"Use The Toilet","externalMappings":{"casas_aruba":"Bed_to_Toilet"},"intent":"use_toilet","relevantVariableIds":["calendar.season","day.type","resident.age","resident.mobility_profile","resident.health_conditions"]},{"category":"housekeeping","components":["vacuum","dust"],"description":"Project-specific activity intent 'vacuum_and_dust_apartment'. Clean, tidy, maintain, or organize the home.","displayName":"Vacuum And Dust Apartment","externalMappings":{"casas_aruba":"Housekeeping"},"intent":"vacuum_and_dust_apartment","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"social_visit","components":["socialize_in_person","consume_meal"],"description":"Project-specific activity intent 'visit_relative_and_have_dinner'. Travel for or participate in an in-person social visit.","displayName":"Visit relative and have dinner","externalMappings":{},"intent":"visit_relative_and_have_dinner","relevantVariableIds":["calendar.season","day.type","day.weather","resident.age","resident.mobility_profile","resident.social_need"]},{"category":"sleep","components":["wake_up"],"description":"Project-specific activity intent 'wake_up'. Enter, leave, or maintain a sleeping state.","displayName":"Wake Up","externalMappings":{"casas_aruba":"Sleeping"},"intent":"wake_up","relevantVariableIds":["calendar.season","day.type","resident.age","resident.chronotype","resident.fatigue","resident.mobility_profile"]},{"category":"sleep","components":["wake_up"],"description":"Project-specific activity intent 'wake_up_without_alarm'. Enter, leave, or maintain a sleeping state.","displayName":"Wake Up Without Alarm","externalMappings":{"casas_aruba":"Sleeping"},"intent":"wake_up_without_alarm","relevantVariableIds":["calendar.season","day.type","resident.age","resident.chronotype","resident.fatigue","resident.mobility_profile"]},{"category":"housekeeping","components":["wash_dishes"],"description":"Project-specific activity intent 'wash_breakfast_dishes'. Clean, tidy, maintain, or organize the home.","displayName":"Wash Breakfast Dishes","externalMappings":{"casas_aruba":"Wash_Dishes"},"intent":"wash_breakfast_dishes","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile"]},{"category":"hygiene","components":["wash_face","change_clothes"],"description":"Project-specific activity intent 'wash_face_and_change_shirt'. Perform personal hygiene or bathroom care.","displayName":"Wash Face And Change Shirt","externalMappings":{},"intent":"wash_face_and_change_shirt","relevantVariableIds":["calendar.season","day.type","resident.age","resident.health_conditions","resident.mobility_profile"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_documentary'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Documentary","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_documentary","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_evening_television'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Evening Television","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_evening_television","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_football_highlights'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Football Highlights","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_football_highlights","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_late_news'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Late News","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_late_news","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_sunday_program'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Sunday Program","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_sunday_program","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"leisure","components":["watch_media"],"description":"Project-specific activity intent 'watch_television'. Rest, read, watch media, or perform another leisure activity.","displayName":"Watch Television","externalMappings":{"casas_aruba":"Relax"},"intent":"watch_television","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"meal_preparation","components":["prepare_food","portion_food","store_food"],"description":"Project-specific activity intent 'weekly_meal_preparation'. Prepare, cook, reheat, portion, or store food and drinks.","displayName":"Weekly Meal Preparation","externalMappings":{"casas_aruba":"Meal_Preparation"},"intent":"weekly_meal_preparation","relevantVariableIds":["calendar.season","day.type","resident.age","resident.food_inventory","resident.hunger","resident.mobility_profile"]},{"category":"home_work","components":["work"],"description":"Project-specific activity intent 'work_from_home'. Perform paid work inside the dwelling, at the resident's own desk or table, in one block of a working day that is split into several.","displayName":"Work From Home","externalMappings":{"casas_aruba":"Work"},"intent":"work_from_home","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]},{"category":"work","components":["work"],"description":"Project-specific activity intent 'work_shift'. Perform paid work or prepare directly for a work commitment.","displayName":"Work Shift","externalMappings":{"casas_aruba":"Work"},"intent":"work_shift","relevantVariableIds":["calendar.season","day.type","resident.age","resident.fatigue","resident.mobility_profile","resident.stress"]}],"catalogId":"smart_home_activity_catalog","catalogVersion":"1.3.0","components":[{"componentId":"carry_purchases","description":"Semantic component 'carry_purchases' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item"]},{"componentId":"carry_recycling","description":"Semantic component 'carry_recycling' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item"]},{"componentId":"change_clothes","description":"Semantic component 'change_clothes' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","dress","put_item"]},{"componentId":"check_calendar","description":"Semantic component 'check_calendar' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["inspect"]},{"componentId":"clean_surface","description":"Semantic component 'clean_surface' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","clean","put_item"]},{"componentId":"collect_belongings","description":"Semantic component 'collect_belongings' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item"]},{"componentId":"collect_laundry","description":"Semantic component 'collect_laundry' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["laundry_step"]},{"componentId":"collect_medication","description":"Semantic component 'collect_medication' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["manage_medication","take_item"]},{"componentId":"consume_drink","description":"Semantic component 'consume_drink' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["consume"]},{"componentId":"consume_meal","description":"Semantic component 'consume_meal' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","consume","change_posture"]},{"componentId":"consume_snack","description":"Semantic component 'consume_snack' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["consume"]},{"componentId":"discard_recycling","description":"Semantic component 'discard_recycling' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["put_item"]},{"componentId":"dust","description":"Semantic component 'dust' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","clean","put_item"]},{"componentId":"enter_home","description":"Semantic component 'enter_home' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["enter_home"]},{"componentId":"exercise","description":"Semantic component 'exercise' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["exercise"]},{"componentId":"hang_laundry","description":"Semantic component 'hang_laundry' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["laundry_step"]},{"componentId":"inspect_supplies","description":"Semantic component 'inspect_supplies' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["open","inspect","close"]},{"componentId":"iron_laundry","description":"Semantic component 'iron_laundry' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["laundry_step"]},{"componentId":"leave_home","description":"Semantic component 'leave_home' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["leave_home"]},{"componentId":"listen_radio","description":"Semantic component 'listen_radio' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["leisure"]},{"componentId":"load_laundry","description":"Semantic component 'load_laundry' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["laundry_step"]},{"componentId":"nap","description":"Semantic component 'nap' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","wait"]},{"componentId":"organize_bag","description":"Semantic component 'organize_bag' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["organize"]},{"componentId":"organize_clothes","description":"Semantic component 'organize_clothes' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["organize"]},{"componentId":"organize_documents","description":"Semantic component 'organize_documents' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["organize"]},{"componentId":"personal_hygiene","description":"Semantic component 'personal_hygiene' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["personal_care"]},{"componentId":"phone_call","description":"Semantic component 'phone_call' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","communicate","change_posture"]},{"componentId":"portion_food","description":"Semantic component 'portion_food' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["organize"]},{"componentId":"prepare_drink","description":"Semantic component 'prepare_drink' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","activate","prepare_food","deactivate"]},{"componentId":"prepare_food","description":"Semantic component 'prepare_food' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["open","take_item","close","activate","prepare_food","deactivate","put_item"]},{"componentId":"prepare_salad","description":"Semantic component 'prepare_salad' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","prepare_food","put_item"]},{"componentId":"read","description":"Semantic component 'read' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","leisure"]},{"componentId":"read_in_bed","description":"Semantic component 'read_in_bed' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","leisure"]},{"componentId":"read_news","description":"Semantic component 'read_news' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["leisure"]},{"componentId":"reheat_food","description":"Semantic component 'reheat_food' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","activate","prepare_food","deactivate"]},{"componentId":"rest","description":"Semantic component 'rest' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","wait"]},{"componentId":"shop","description":"Semantic component 'shop' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["shop"]},{"componentId":"shower","description":"Semantic component 'shower' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["activate","personal_care","deactivate"]},{"componentId":"sleep","description":"Semantic component 'sleep' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","wait"]},{"componentId":"socialize_in_person","description":"Semantic component 'socialize_in_person' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["communicate"]},{"componentId":"start_laundry","description":"Semantic component 'start_laundry' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["laundry_step"]},{"componentId":"store_food","description":"Semantic component 'store_food' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["open","put_item","close"]},{"componentId":"store_purchases","description":"Semantic component 'store_purchases' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["open","put_item","close"]},{"componentId":"take_medication","description":"Semantic component 'take_medication' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","manage_medication","put_item"]},{"componentId":"tidy_area","description":"Semantic component 'tidy_area' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["organize"]},{"componentId":"travel","description":"Movement between locations. Crossing the home boundary is modeled separately by leave_home and enter_home actions when applicable.","requiredActionTypes":["travel_to"]},{"componentId":"use_toilet","description":"Semantic component 'use_toilet' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["personal_care"]},{"componentId":"vacuum","description":"Semantic component 'vacuum' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["take_item","activate","clean","deactivate","put_item"]},{"componentId":"wake_up","description":"Semantic component 'wake_up' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture"]},{"componentId":"walk","description":"Semantic component 'walk' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["exercise"]},{"componentId":"wash_dishes","description":"Semantic component 'wash_dishes' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["activate","clean","deactivate"]},{"componentId":"wash_face","description":"Semantic component 'wash_face' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["activate","personal_care","deactivate"]},{"componentId":"watch_media","description":"Semantic component 'watch_media' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","activate","leisure","deactivate"]},{"componentId":"work","description":"Semantic component 'work' implemented at the project trace granularity by its ordered required actions.","requiredActionTypes":["change_posture","perform_work"]}],"documentType":"activity_catalog","schemaVersion":"1.0.0"}

## Authoritative variable catalog

{"catalogId":"smart_home_variable_catalog","catalogVersion":"1.0.0","documentType":"variable_catalog","schemaVersion":"1.0.0","variables":[{"allowedValues":[],"description":"Authoritative behavioral variable: age.","displayName":"Age","required":false,"scope":"resident","sourcePath":"age","valueType":"integer","variableId":"resident.age"},{"allowedValues":[],"description":"Authoritative behavioral variable: household composition.","displayName":"Household composition","required":false,"scope":"resident","sourcePath":"household","valueType":"string","variableId":"resident.household"},{"allowedValues":[],"description":"Authoritative behavioral variable: health conditions.","displayName":"Health conditions","required":false,"scope":"resident","sourcePath":"health.conditions","valueType":"array","variableId":"resident.health_conditions"},{"allowedValues":[],"description":"Authoritative behavioral variable: mobility profile.","displayName":"Mobility profile","required":false,"scope":"resident","sourcePath":"mobility.profile","valueType":"string","variableId":"resident.mobility_profile"},{"allowedValues":[],"description":"Authoritative behavioral variable: walking speed.","displayName":"Walking speed","required":false,"scope":"resident","sourcePath":"mobility.walkingSpeedMetersPerSecond","valueType":"number","variableId":"resident.walking_speed"},{"allowedValues":[],"description":"Authoritative behavioral variable: chronotype.","displayName":"Chronotype","required":false,"scope":"resident","sourcePath":"preferences.chronotype","valueType":"string","variableId":"resident.chronotype"},{"allowedValues":["coffee","tea","cold_drink"],"description":"Authoritative behavioral variable: preferred breakfast drink.","displayName":"Preferred breakfast drink","required":false,"scope":"resident","sourcePath":"preferences.breakfastDrink","valueType":"string","variableId":"resident.preferred_breakfast_drink"},{"allowedValues":[],"description":"Authoritative behavioral variable: fatigue.","displayName":"Fatigue","required":false,"scope":"initial_state","sourcePath":"fatigue","valueType":"number","variableId":"resident.fatigue"},{"allowedValues":[],"description":"Authoritative behavioral variable: hunger.","displayName":"Hunger","required":false,"scope":"initial_state","sourcePath":"hunger","valueType":"number","variableId":"resident.hunger"},{"allowedValues":[],"description":"Authoritative behavioral variable: stress.","displayName":"Stress","required":false,"scope":"initial_state","sourcePath":"stress","valueType":"number","variableId":"resident.stress"},{"allowedValues":[],"description":"Authoritative behavioral variable: social need.","displayName":"Social need","required":false,"scope":"initial_state","sourcePath":"socialNeed","valueType":"number","variableId":"resident.social_need"},{"allowedValues":[],"description":"Authoritative behavioral variable: food inventory.","displayName":"Food inventory","required":false,"scope":"initial_state","sourcePath":"foodInventory","valueType":"object","variableId":"resident.food_inventory"},{"allowedValues":[],"description":"Authoritative behavioral variable: medication available doses.","displayName":"Medication available doses","required":false,"scope":"initial_state","sourcePath":"medicationAvailableDoses","valueType":"integer","variableId":"resident.medication_available_doses"},{"allowedValues":[],"description":"Authoritative behavioral variable: day type.","displayName":"Day type","required":true,"scope":"day","sourcePath":"dayType","valueType":"string","variableId":"day.type"},{"allowedValues":[],"description":"Authoritative behavioral variable: weather.","displayName":"Weather","required":false,"scope":"day","sourcePath":"facts.weather","valueType":"string","variableId":"day.weather"},{"allowedValues":[],"description":"Authoritative behavioral variable: public holiday.","displayName":"Public holiday","required":false,"scope":"day","sourcePath":"facts.publicHoliday","valueType":"boolean","variableId":"day.public_holiday"},{"allowedValues":[0,1,2,3,4,5,6],"description":"Authoritative behavioral variable: weekday.","displayName":"Weekday","required":true,"scope":"derived_calendar","sourcePath":"weekday","valueType":"integer","variableId":"calendar.weekday"},{"allowedValues":["winter","spring","summer","autumn"],"description":"Authoritative behavioral variable: season.","displayName":"Season","required":true,"scope":"derived_calendar","sourcePath":"season","valueType":"string","variableId":"calendar.season"}]}

## Authoritative action catalog

{"actions":[{"actionType":"move_to","description":"Execute the typed atomic action 'move_to'.","effects":[{"factTemplate":"resident.location","operation":"set","value":"{destination}"}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'destination'.","parameterName":"destination","referenceKind":"location","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"reachable","parameterName":"destination","role":"destination"}]},{"actionType":"move_to_capability","description":"Execute the typed atomic action 'move_to_capability'.","effects":[{"factTemplate":"resident.location","operation":"set","value":"{targetRole}"}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'targetRole'.","parameterName":"targetRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"interaction_point","parameterName":"targetRole","role":"target"}]},{"actionType":"change_posture","description":"Execute the typed atomic action 'change_posture'.","effects":[{"factTemplate":"resident.posture","operation":"set","value":"{posture}"}],"parameters":[{"allowedValues":["standing","walking","sitting","lying"],"description":"Typed parameter 'posture'.","parameterName":"posture","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"posture_control","role":"resident"}]},{"actionType":"open","description":"Execute the typed atomic action 'open'.","effects":[{"factTemplate":"entity.{target}.open","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'target'.","parameterName":"target","referenceKind":"environment_entity","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"entity.{target}.open","operator":"eq","value":false}],"requiredCapabilities":[{"capability":"openable","parameterName":"target","role":"target"}]},{"actionType":"close","description":"Execute the typed atomic action 'close'.","effects":[{"factTemplate":"entity.{target}.open","operation":"set","value":false}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'target'.","parameterName":"target","referenceKind":"environment_entity","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"entity.{target}.open","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"openable","parameterName":"target","role":"target"}]},{"actionType":"take_item","description":"Execute the typed atomic action 'take_item'.","effects":[{"factTemplate":"resident.carrying.{itemRole}","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'itemRole'.","parameterName":"itemRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"capability.{itemRole}.available","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"graspable","parameterName":"itemRole","role":"item"}]},{"actionType":"put_item","description":"Execute the typed atomic action 'put_item'.","effects":[{"factTemplate":"resident.carrying.{itemRole}","operation":"set","value":false}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'itemRole'.","parameterName":"itemRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"resident.carrying.{itemRole}","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"storable","parameterName":"itemRole","role":"item"}]},{"actionType":"activate","description":"Execute the typed atomic action 'activate'.","effects":[{"factTemplate":"entity.{target}.active","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'target'.","parameterName":"target","referenceKind":"environment_entity","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"entity.{target}.active","operator":"eq","value":false}],"requiredCapabilities":[{"capability":"switchable","parameterName":"target","role":"target"}]},{"actionType":"deactivate","description":"Execute the typed atomic action 'deactivate'.","effects":[{"factTemplate":"entity.{target}.active","operation":"set","value":false}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'target'.","parameterName":"target","referenceKind":"environment_entity","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"entity.{target}.active","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"switchable","parameterName":"target","role":"target"}]},{"actionType":"wait","description":"Execute the typed atomic action 'wait'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'purpose'.","parameterName":"purpose","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[]},{"actionType":"inspect","description":"Execute the typed atomic action 'inspect'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'targetRole'.","parameterName":"targetRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"inspectable","parameterName":"targetRole","role":"target"}]},{"actionType":"consume","description":"Execute the typed atomic action 'consume'.","effects":[{"factTemplate":"capability.{itemRole}.consumed","operation":"increment","value":1}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'itemRole'.","parameterName":"itemRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[{"factTemplate":"capability.{itemRole}.available","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"consumable","parameterName":"itemRole","role":"item"}]},{"actionType":"personal_care","description":"Execute the typed atomic action 'personal_care'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'procedure'.","parameterName":"procedure","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"personal_care_support","role":"fixture"}]},{"actionType":"clean","description":"Execute the typed atomic action 'clean'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'targetRole'.","parameterName":"targetRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"cleanable","parameterName":"targetRole","role":"target"}]},{"actionType":"laundry_step","description":"Execute the typed atomic action 'laundry_step'.","effects":[],"parameters":[{"allowedValues":["collect","load","start","unload","hang","iron"],"description":"Typed parameter 'operation'.","parameterName":"operation","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"laundry_support","role":"equipment"}]},{"actionType":"organize","description":"Execute the typed atomic action 'organize'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'targetRole'.","parameterName":"targetRole","referenceKind":"capability","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"storage_support","parameterName":"targetRole","role":"target"}]},{"actionType":"dress","description":"Execute the typed atomic action 'dress'.","effects":[{"factTemplate":"resident.carrying.used_clothing","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'purpose'.","parameterName":"purpose","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"wearable","role":"item"}]},{"actionType":"manage_medication","description":"Execute the typed atomic action 'manage_medication'.","effects":[],"parameters":[{"allowedValues":["take","refill","store"],"description":"Typed parameter 'operation'.","parameterName":"operation","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"medication_support","role":"item"}]},{"actionType":"leave_home","description":"Execute the typed atomic action 'leave_home'.","effects":[{"factTemplate":"resident.at_home","operation":"set","value":false}],"parameters":[],"preconditions":[{"factTemplate":"resident.at_home","operator":"eq","value":true}],"requiredCapabilities":[{"capability":"home_egress","role":"access"}]},{"actionType":"enter_home","description":"Execute the typed atomic action 'enter_home'.","effects":[{"factTemplate":"resident.at_home","operation":"set","value":true}],"parameters":[],"preconditions":[{"factTemplate":"resident.at_home","operator":"eq","value":false}],"requiredCapabilities":[{"capability":"home_ingress","role":"access"}]},{"actionType":"travel_to","description":"Execute the typed atomic action 'travel_to'.","effects":[{"factTemplate":"resident.location","operation":"set","value":"{destination}"}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'destination'.","parameterName":"destination","referenceKind":"location","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"transport_reachable","parameterName":"destination","role":"destination"}]},{"actionType":"shop","description":"Execute the typed atomic action 'shop'.","effects":[{"factTemplate":"resident.carrying.purchases","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'purpose'.","parameterName":"purpose","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"retail_service","role":"place"}]},{"actionType":"communicate","description":"Execute the typed atomic action 'communicate'.","effects":[],"parameters":[{"allowedValues":["phone","in_person"],"description":"Typed parameter 'channel'.","parameterName":"channel","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"communication","parameterName":"channel","role":"channel"}]},{"actionType":"perform_work","description":"Execute the typed atomic action 'perform_work'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'mode'.","parameterName":"mode","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"work_support","role":"place"}]},{"actionType":"exercise","description":"Execute the typed atomic action 'exercise'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'kind'.","parameterName":"kind","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"exercise_support","role":"place"}]},{"actionType":"leisure","description":"Execute the typed atomic action 'leisure'.","effects":[],"parameters":[{"allowedValues":[],"description":"Typed parameter 'kind'.","parameterName":"kind","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"leisure_support","role":"medium"}]},{"actionType":"prepare_food","description":"Execute the typed atomic action 'prepare_food'.","effects":[{"factTemplate":"resident.carrying.{outputRole}","operation":"set","value":true}],"parameters":[{"allowedValues":[],"description":"Typed parameter 'mealKind'.","parameterName":"mealKind","referenceKind":"none","required":true,"valueType":"string"},{"allowedValues":["drink","prepared_food_portions","prepared_meal","prepared_salad"],"description":"Role of the prepared item made available to subsequent actions.","parameterName":"outputRole","referenceKind":"none","required":true,"valueType":"string"}],"preconditions":[],"requiredCapabilities":[{"capability":"food_preparation","role":"equipment"}]}],"catalogId":"smart_home_action_catalog","catalogVersion":"1.1.0","documentType":"action_catalog","schemaVersion":"1.0.0"}

## Researcher-supplied person and case description

<PERSON_AND_CASE_DESCRIPTION>
{{PERSON_AND_CASE_DESCRIPTION}}
</PERSON_AND_CASE_DESCRIPTION>
