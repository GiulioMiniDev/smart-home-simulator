# Visual design memory

## Product character

The simulator is a precise spatial research instrument. Product surfaces should feel like
an inspectable technical workspace, not a generic analytics dashboard or a decorative
smart-home illustration. The primary visual object is always the home, simulation or
sensor field being inspected.

## M4 acceptance viewer

The M4 viewer is a standalone generated acceptance artifact, not the application UI. It
must expose contract truth without requiring a frontend runtime:

- the floor plan is the visual anchor;
- metric obstacles, physical scenario resources, logical environment entities,
  interaction anchors and planned routes are separate layers;
- every selectable item resolves to an ID present in the home, scenario or bundle;
- routing geometry and non-authoritative resource display coordinates are explicitly
  distinguished;
- domestic floor-plan space and external-service topology remain visually distinct.

## Visual language

- Warm off-white workspace, cool room tints and precise grey boundaries.
- Amber hatching is reserved for routing obstacles.
- Teal outlined floor-plan symbols identify physical resources.
- Indigo nodes identify logical capability providers and indigo dashed lines identify
  computed routes.
- Use one consistent, editable SVG symbol system with rounded strokes. No emoji, raster
  furniture, external icon CDN, generic rectangles standing in for named resources or
  decorative gradients.
- Prefer split panes, toolbars, inspector rows and object canvases. Cards are limited to
  genuine summaries; the floor plan must never be presented as a small dashboard card.

## Typography and density

Use a compact system/UI sans with tabular or monospace treatment for IDs, hashes and
metrics. Page titles stay at or below 32 px; inspector headings stay at or below 22 px.
Hierarchy comes from grouping and alignment rather than oversized type. Desktop density
is high; narrow screens stack the inspector below a horizontally inspectable plan.

## Interaction and motion

Selection updates one persistent inspector. Layer controls expose their pressed state,
native selects are keyboard accessible, and floor-plan objects support Enter/Space.
Route motion communicates direction only; all motion is short and stateful, with a
`prefers-reduced-motion` fallback. Future UI work should preserve object identity between
canvas selection, inspector details and simulation progress.

## Non-negotiable checks

- Never render an entity, resource or obstacle missing from authoritative input.
- Never silently omit a bound resource because its graphic is unavailable; fail artifact
  generation instead.
- Never imply that a visual resource coordinate affects routing unless it is represented
  by authoritative obstacle geometry.
- Verify desktop and narrow-screen renders, keyboard selection, route changes, layer
  states and browser console errors before accepting a visual milestone artifact.
