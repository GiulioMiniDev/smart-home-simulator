"""How long a resident keeps something in her hands once the process model stops mentioning it.

`take_item`, `prepare_food`, `shop` and `dress` set `resident.carrying.<role>`; only `put_item`
clears it. A model that takes the ingredients and puts down only the dish, or drinks the coffee and
never sets the cup down, left the fact true for the rest of the horizon: on one generated month
every carrying fact of both residents was stuck after its first pick-up, and the replay showed two
people walking about with their hands full for thirty-one days.

Two kinds of thing, two rules, both applied by the engine and mirrored by the authoring preflight:

- Most things are handled and put back as the activity that took them ends — the ingredients, the
  moka, the cleaning cloth. Nobody carries the olive oil to the sofa.
- A few are carried on, into whatever the resident does next: the coffee taken to the desk, the
  plate brought to the table, the shopping carried home. Those are set down once they have been
  consumed, when the activity that consumed them ends, or after `PORTABLE_MINUTES` otherwise.

`consume` itself does not free the hands: the reference meal is `take_item(prepared_meal)`,
`consume`, `put_item(prepared_meal)`, the plate outliving the food on it.
"""

from __future__ import annotations

CARRYING_PREFIX = "carrying."

# Minutes a carried thing may outlive the activity that took it, counted from that activity's end.
# `purchases` is the longest because the shopping has to survive the walk home and the activity that
# puts it away (`resident_away_from_home_with_purchases` asks for it in between).
PORTABLE_MINUTES: dict[str, float] = {
    "drink": 45.0,
    "prepared_meal": 30.0,
    "prepared_salad": 30.0,
    "prepared_food_portions": 30.0,
    "purchases": 120.0,
    "used_clothing": 30.0,
}


def carried_role(fact: str) -> str | None:
    """`carrying.drink` -> `drink`; anything that is not a carrying fact -> None."""
    if not fact.startswith(CARRYING_PREFIX):
        return None
    return fact.removeprefix(CARRYING_PREFIX) or None


def portable_minutes(role: str) -> float | None:
    """How long this role may be carried on after its activity, or None if it is put back then."""
    return PORTABLE_MINUTES.get(role)
