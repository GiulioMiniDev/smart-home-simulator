# ADR-025: The house a persona lives in

- Status: accepted and implemented
- Date: 2026-08-29
- Completes [ADR-009](ADR-009-freeze-executable-environment-1.0.0.md), which froze the executable
  environment, and the procedural generation design in
  [docs/plans/2026-07-22-procedural-environment-generation-design.md](../plans/2026-07-22-procedural-environment-generation-design.md),
  which tiled rooms and gave furniture a footprint but stopped short of deciding what house a
  resident lives in or how the furniture stands in it.

## Context

Three things about the generated home were wrong in the same direction: it was the *same* home,
arranged the way nobody arranges a home, drawn so you could not see what was in it.

**One flat for everybody.** `hybrid_planning/world.py` declared five rooms and seventeen objects as
module constants and handed them to every persona ever generated. Its own note called that
deliberate and asked for the swap to a per-persona world to be kept open. A dataset whose
distinctiveness lives entirely in the days, with the same 60 m² flat under all of them, teaches a
recogniser the flat.

**Furniture was stored, not arranged.** `floorplan.place_furniture` walked the four walls in order
and pushed each piece flush against the first free span. The result was geometrically valid and
architecturally absurd: every object with its back to a wall, the middle of every room a void, the
television facing a blank wall while the sofa faced another one, and four dining chairs in a row
along the skirting board with the table two metres away.

**The drawing could not be read.** Every glyph was authored in one square 48×48 box and drawn into
its obstacle with `preserveAspectRatio="meet"`. A bed is 1.60 by 2.00, so the drawing shrank to the
narrow side and left a third of the footprint as bare hatching; a television, 1.10 by 0.35, became
a stamp adrift in a long thin box. And nothing was ever turned: the placer could stand a piece
against any of the four walls, so half the flat was drawn facing the wrong way.

## Decision

**A dwelling is designed for the persona.** `hybrid_planning/dwelling.py` picks an archetype —
studio, small flat, two-bedroom, family flat, maisonette, townhouse, bungalow — with weights taken
from what the persona says about itself, then its rooms, their storey, and their furniture. Two
things are guaranteed and are not subject to the dice: the five rooms `INTENT_CATALOG` places
intents in, which `expander._check_locations` requires, and the seventeen objects the reference
process models bind by role. Variety is added around that core and never taken out of it. Somebody
with a mobility note is never given a staircase — that is the one hard rule in the table.

**A storey is a block of the same plane.** `layout_rooms` tiles each storey separately and offsets
it, so a two-storey house is two tilings side by side in one coordinate system. Every geometric
rule in the system then keeps working untouched: regions still may not overlap, an obstacle still
lives inside one region, routing inside a room is still a plane problem. `HomeRegion.level` carries
the fact that the second block is upstairs, and a new `ConnectionKind.stairway` — walked, but
declaring its own length, because the gap between blocks is a drawing convention and not a distance
— carries the fact that a staircase rather than a corridor joins them. The staircase is a real
obstacle at both ends, standing on floor the arrangement has to work round.

**Furniture is placed by pose, not by cursor.** `materialization/furnishing.py` proposes candidate
poses for each piece — along every wall at a fine step, out in the open floor on a grid, or at an
exact offset from a piece already standing — scores them for the things that make a layout read as
designed, and takes the best that survives the hard checks. The hard checks are the ones the path
planner depends on and are unchanged in substance. What the scoring adds is arrangement: a bed on
the wall furthest from the door with its nightstand beside it, a coffee table in front of the sofa
and the television on the surface the sofa looks at, a dining table in open floor with its chairs
round it, a kitchen whose sink, hob and worktop form one run.

**Orientation is published rather than guessed.** `HomeObstacle.orientationDegrees` records which
way a piece is turned. It cannot be recovered from the geometry — a square hob is square whichever
way it faces — nor from the interaction point, which is wherever there was floor to stand on: a
dining chair is reached from behind, because its front is against the table.

**One SVG unit is one centimetre.** Each symbol's viewBox is exactly the footprint the generator
gives that kind of furniture, authored with the wall at the top and the usable front at the bottom.
The glyph then fills its obstacle instead of floating inside it, a stroke width of 2 means two
centimetres at any zoom, and one component turns the drawing by the obstacle's own bearing.

## Consequences

`HomeModel` gains two optional fields with defaults, so every home written before this reads
unchanged and simply draws unturned on one floor. It is still a schema change: the contract's digest
moves, which means the example bundles, traces, sensor logs and materialization goldens in the
repository were rebuilt, and any bundle held outside it has to be rebuilt from its own inputs before
it will load again. Execution traces and sensor logs already exported are files and are unaffected.

Generated flats now hold thirty to sixty objects rather than seventeen, and every added type
declares its capabilities. That is not decoration: a type absent from `ENTITY_TYPE_CAPABILITIES` is
permissive — it offers every capability there is — so an unlisted bookcase would answer to
`food_preparation`, sort before the sofa on the letter b, and quietly become the object the resident
does everything at. Even with narrow capabilities, a fuller flat is a flat with more candidates, so
which object a role binds to can differ from an earlier generation of the same persona. That is the
point of the change rather than a side effect of it, and the core objects still answer the roles the
reference models name.

The activity catalog still decides which rooms must exist, so a house cannot yet be generated
without a balcony, and a study is a room the resident has rather than a room an intent is placed in.
Letting an intent resolve its location against the dwelling it is in is the next thing here, and it
is a change to the expander rather than to the generator.

`tools/build_environment_visualization.py` keeps its own frozen copy of the old square glyphs. It is
a standalone M4 acceptance artifact for one hand-authored home and was deliberately left alone.
