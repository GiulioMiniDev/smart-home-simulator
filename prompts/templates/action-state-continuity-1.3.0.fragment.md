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
