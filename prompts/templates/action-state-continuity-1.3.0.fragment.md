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

{{ACTION_STATE_CONTRACT}}

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
3. Every `put_item(role)` is preceded on every incoming path by a `take_item` with the exact
   same role. `take_item` is the only action in this catalog that grants a carrying fact, so a
   `put_item` whose role was never taken is always deterministically false. Do not take
   `ingredients` and put `prepared_meal`.
4. A component whose required sequence begins with `put_item` — `store_food`,
   `store_purchases`, `discard_recycling` — needs an explicit `take_item` of that same role
   inserted before the required sequence whenever the ledger does not already carry it.
5. `open(target)` and `close(target)` are balanced on the same target inside the same model, and
   so are `activate(target)` and `deactivate(target)`. A container left open at the end of one
   activity makes the next `open` of that same container deterministically false, on every
   later day.
   **Anything stored inside something is reached by opening it.** Wrap the `take_item` or
   `put_item` in `open(container) -> ... -> close(container)` whenever the role names one of these:

{{CONTAINER_ROLES}}

   This is what a contact sensor observes, and it is the difference between a home that reports its
   cupboards and one that does not. In one generated eight-month horizon every `open` and `close` in
   the whole log had a single target — the fridge — because the cleaning products, the medication
   and the clothes were taken straight out of closed furniture. The flat ended up with **two**
   contact sensors where a comparable real deployment has four to six, and the cabinets it did
   contain were invisible for eight months.
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
