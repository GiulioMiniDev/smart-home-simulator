# ADR-026: The household as the subject of an outline

- Status: accepted and implemented
- Date: 2026-09-12
- Supersedes the single-resident half of
  [ADR-018](ADR-018-outline-first-external-authoring.md), which moved the concrete days out of the
  model's response and, in doing so, fixed the subject of an outline as one person.
- Settles the design in
  [docs/plans/2026-09-09-orizzonte-multi-residente-design.md](../plans/2026-09-09-orizzonte-multi-residente-design.md),
  whose four open questions were closed before any code was written.

## Context

`HorizonOutline` 1.0.0 had `residentId: str`, one `profile` and one `rhythm`. Every layer beneath
it was already plural — `Scenario.residents` is a list, the compiler builds one no-overlap chain
per resident through `occupied_residents()`, `_MotionPulse.resident_ids` is a tuple, berths exist
precisely for two bodies on one sofa, `HabitGroundTruth` carries `resident_id`, and the published
profile iterates `profile.residents`. The hole was entirely in authoring and expansion, and it had
two coordinates: the contract above, and `actor_id = world.residents[0].resident_id` in
`day_generation.py`, which is where the code decided there was one person.

That asymmetry is the reason this is mostly a contract change. Almost nothing here had to be
*solved* better; it had to be *declared* better.

Two strategies were rejected before this one.

**Sequential generation** — write the first resident, expand her, and ask the model for the second
against her concrete days — puts back into the prompt exactly what ADR-018 took out. Eight months
of concrete days do not fit in a context window and do not compress; that growth is what took the
ratio of distinct daily signatures from 1.00 at a week to 0.03 at eight months. It also makes the
coupling asymmetric, producing a primary resident and a satellite rather than a cohabitation, and
it breaks "one horizon, one solve": regenerating B invalidates A with no fingerprint able to say
so.

**"Write the family's routine"** in the naive sense fails in two predictable ways. A language model
over-synchronises, pinning dinner at 19:30 for both and narrowing the band exactly where the
placement engine needs slack; and it duplicates rather than shares, writing "dinner" twice with two
similar bands that the solver has no reason to align, so the dataset ends up with two dinners where
the house had one.

## Decision

**The outline's subject is a household.** `HorizonOutline` 2.0.0 replaces `residentId` + `profile`
+ `rhythm` with `residents[]`, each carrying its own profile, rhythm, habits, commitments, phases
and events, and adds a `household` level for what is true of a pair rather than of anyone. A
one-person outline is `len(residents) == 1`: there is no `if` anywhere below this line, and the
household of one is the same document with an empty household.

**The LLM declares the propensity to share; the expander decides which occurrences are shared.**
This is the ADR-018 principle extended rather than amended. The author writes "dinner is a shared
activity when both are in", never "on Tuesday the 14th they eat together" — who is even in the
house that Tuesday is known only after the commitments are placed and the events have landed.

**A shared activity is declared once**, in `household.jointActivities`, with explicit
`participantIds` and one band. There is no "both" field anywhere in the contract: in a household of
four the dinner has four participants and the school run has two.

**Sharing has four modes, not two.** `joint`, `optional_joint`, `independent` and `exclusive`,
because "together or not" hides two different questions — whether an occurrence is one interval or
two, and whether the other may be in the room at all. Collapsing them loses the bathroom.

**Privacy, not capacity.** A room's co-presence rule is a norm between two named people, directional
and specific to the activity; capacity counts bodies, and no room has a true one — two people fit
in a shower cabin. It compiles to a pairwise non-overlap rather than a cumulative constraint, which
costs more constraints and is the only one of the two a preflight can put into a sentence a
researcher reads. What stays on `Resource.capacity` is what it always was: simultaneous *uses*, so
a shower taken by two is one use and two independent showers at one instant are refused.

**Restrictive defaults.** Undeclared, two residents are `independent`, and a room with a single
sanitary fixture is private. The two mistakes do not cost the same: a wrong permissive default is
two people in one shower cabin, physically impossible and silently false downstream, while a wrong
restrictive default is a formal cohabitation a reader can see. `household.sharedLocationIds` is the
one line that opts a room out.

**The propensity is a number indexed by class of day**, not a predicate language, with a minimum
overlap beside it. A single average scatters shared dinners at random through the working week and
fabricates a weekly pattern in the ground truth — in exactly the distinction `day_types` exists to
preserve. A predicate language is the surface on which small models invent, which the authoring
prompt already shouts about for intents, and it would need an evaluation order and a tie-break
where a bug is silent.

**One dataset per dwelling**: one shared observable log, N per-resident `HabitGroundTruth` (1.3.0)
and one `HouseholdGroundTruth` (1.0.0). A dataset per resident would duplicate the same log N times
and lose the only thing that makes the case interesting.

**The PIR stays ambiguous, and the oracle does not.** Two bodies crossing one cone inside the
retrigger window are one observation, because that is what the hardware does; the reconciled
record's oracle link names every resident, cause, activity and action that held the sensor on. That
asymmetry — the log does not know who moved, the answer sheet does — is the scientific content of a
shared dataset, and it is the same lesson this projector learned once already when independent
per-sensor pulse draws gave 5.1% co-activation against Aruba's 29.5%.

**The habit ground truth is measured on the run, and is exact for it.** The bands are the outline's
declaration and true by definition. Everything measured inside them — composition, the unaccounted
remainder, where the dominant activity really runs, ambiguity, co-presence, shared episodes — is
measured on the execution trace when a run is exported (`hybrid_planning/habits.py`), with actual
times and the rooms the bodies were in. The scenario carries only the declaration
(`declaredHabits`). The same arithmetic runs on the expanded plan for the authoring warnings, and
every document says which it was measured on (`measuredOn`). This replaced a ground truth measured
on the expanded plan before compilation — preferred times, candidates the engine could still turn
down counted as having happened, nothing the compiler or the run changed — which three contract
versions had published as the answer to a sensor log. The two readings are checked against each
other: the published composition matches an independent reading of the trace.

**Every participant is executed.** The compiler had always occupied every participant of an
activity; the engine executed the actor's process model and nothing else, so at a shared dinner
the second resident's body stayed where it was, in the trace, the sensor log and the replay alike.
A participant now walks to the room the actor's providers are in, takes a seat of her own (a piece
already full is not the nearest seat) and holds the posture the actor's model is spent in, all as
ordinary actions under the shared execution. `ActivityExecution` gained `participantIds`, taking
the trace to 1.1.0; an empty list hashes like the absent field, so every 1.0.0 trace still verifies
against its own digest.

**The ambiguity share is a field of `HabitObservation`**, beside `unaccounted_share`: the fraction
of a band's minutes another resident spent in the same room. It is the second axis of difficulty,
and without it an algorithm failing on a crowded band and one failing on a noisy band report the
same number and mean different things.

## Consequences

- **`HorizonOutline` 1.0.0 documents are lifted, not refused.** `upgrade_outline_payload` moves the
  single-resident fields into a roster of one and touches no value, so the horizons already
  authored still expand. It sits in front of both doors — the CLI and the application import — and
  returns a 2.0.0 document unchanged, so no caller has to know which version it holds.
- **`HorizonAuthoringBundle` goes to 2.0.0 with it.** The envelope is unchanged; it is versioned
  with the document it transports, because validating a bundle is validating the outline inside it.
- **The acceptance criterion is the compiled plan, not the bytes.** A migrated outline must expand
  to the same plan, verified by compiling the whole horizon rather than reading the first few days:
  a plan that looks right can still be unsolvable further on. Verified on an existing case,
  Filippo's five-month bundle: expanded and compiled over all 153 days by the committed 1.0.0 code
  and by this one after the lift, the 4 392 scheduled activities have the same start and end, with
  device uses written into 2 436 of them. (The reference Meredith outline could not serve: it is
  infeasible on 2026-10-15 under both, a full-day shift and a mandatory event on one date.)
- **Activity identifiers are unique across the document.** Every resident's day is merged into one
  scenario, so two people who had each named an activity `morning_coffee` would arrive there as one
  activity performed twice. Identifiers within a day are allocated from a running offset, so a
  one-resident horizon keeps the numbering it has always produced.
- **Compilation cost is measured, not estimated.** One month of the household test couple, compiled
  whole, one run at a time: one resident 728 activities in 36 s (230 probes); the couple 1 635
  activities in 135 s (1 583 probes); the couple with an exclusive bathroom in 168 s (1 573); the
  couple without device uses in 130 s. `exclusive` enlarges the model as expected. The probes did
  not explode where the design guessed — a narrow band on an `exclusive` activity — but in two
  structural places, both fixed. The window split was triggered by a day count calibrated on one
  resident, so a couple's month was one solve whose first probes exhausted their budget
  (`SOLVER_NOT_OPTIMAL` after twelve minutes); it is now triggered by resident-days, which for one
  resident is the day count and changes nothing. And a degradable activity was canonicalised arm
  by arm, so the arm that loses was a guaranteed rejection found by bisection every day; the choice
  is now one lock per group on the most valuable arm. What is left is ordinary evening contention
  between waking, the shared television, hygiene and sleep. The per-day partition does survive:
  residents live inside the same day, so the coupling never crosses the frontier that makes it
  valid. The separate arm's priority is sized by the number of participants, since three dinners at
  forty outweighed one shared at ninety and a family would never have eaten together.
- **Degradation is on by default.** `degradeToIndependent` compiles into two mutually exclusive
  arms and lets the solver take the one that fits — the only layer that knows the slack. The shared
  arm cannot be shorter than `minimumSharedMinutes`: without that floor the solver never chose, and
  served a couple a shared dinner squeezed to its catalogue minimum with degradation on or off. It
  was first shipped off by default, because the ground truth was then measured on the plan and a
  degraded day would have published a shared meal that never happened; measured on the run, the
  answer sheet describes whatever the compiler chose.
- **A household package is checked per resident.** A binding belongs to a resident, so the
  expander refuses a package that implements an intent for one participant and not another, instead
  of letting behaviour validation report one missing binding per activity.
- **Every activity names the objects it holds.** The paragraph on capacity above was true of the
  compiler and of the engine and was not true of any plan: nothing wrote `required_resources`, so
  two morning washes at one basin were placed on top of each other and the second `activate` of the
  tap failed its precondition and stopped the run. The expander now writes one use of each object
  an activity's process switches on or uses as a sanitary fixture (`switchable`,
  `personal_care_support`), chosen the way the environment binder chooses it, and a test checks the
  two agree on a real run. The compiler serialises the uses with `add_cumulative`, and the engine's
  resource coordinator makes a second body wait where execution slips. The rest of a room — chairs,
  shelves, a refrigerator door open for three seconds — is used in turn inside the same hour and is
  deliberately not serialised. The toilet trips and fillers the engine may turn down carry their
  uses but are left out of the compiler's resource model, like they are left out of their
  resident's no-overlap chain: they interrupt a block rather than compete with it for the hour.
  Serialised, the solver kept those optional candidates and moved the author's habits out of their
  way — on the five-month case 66 activities, a mandatory toilet visit by three and a half hours.
  They are arbitrated live instead: a candidate that finds its object in use is dropped
  (`object_in_use`), neither queued behind it nor pre-empting it. Two limits remain: an activity holds its objects for its whole interval,
  not for the minutes of the step that uses them; and the engine's priority pre-emption (ADR-011)
  can still suspend a lower-priority use when a higher-priority one arrives late.
- **A shared activity starts soon after the last participant is home.** No-overlap only kept a
  shared lunch out of the hours somebody was still at work; nothing stopped it beginning three
  hours after she walked in. It now depends on the latest mandatory absence of any participant
  that ends inside its window, with a maximum lag of twenty minutes (the design's figure), and only
  where that absence cannot end outside the window whatever the compiler does with it.
- **Everyone sleeps in her own bed.** A resident's start location is her bedroom for every night,
  nap and return to bed, where the room holds a bed; before, only the first midnight read it, and
  two housemates spent every other night in one bed. Declared `housemates` or `other` sharing a
  bedroom are refused unless the household lists the room as shared. The dwelling designer derives
  the number of bedrooms from a roster (`Household.from_roster`) and treats it as a hard constraint.
- **Declared propensity is published beside the realised share.** `HouseholdGroundTruth.sharing`,
  per shared activity and class of day, measured on the run; exported as `household_sharing`.
- **A table has its places.** A table the outline furnished with one chair got none added, so a
  person living alone had a single chair at her own table. The generator now brings every dining
  surface to two to four places, fixed by the table's id and never fewer than the residents, and
  takes back any it supplied that did not fit round the table — a small kitchen with its table
  against the counters seats two, not two plus a row of chairs along the far wall.

## Out of scope, and said so

Physical collision between bodies in a corridor (already a deliberate roadmap exclusion); mutual
sleep disturbance, so a partner coming to bed at 01:00 does not wake the one who went at 23:30;
conversation, negotiation, and any change of plan induced by the other resident other than through
a declared constraint; and the automatic fusion of two existing single-resident scenarios into a
shared house, which stays what the roadmap says it is — the multi-resident case is authored, not
assembled afterwards.
