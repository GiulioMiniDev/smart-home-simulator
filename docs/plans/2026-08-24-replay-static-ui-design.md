# Replay static presentation UI design

## Scope

Improve only the replay presentation UI. The simulation clock, replay frame pipeline,
resident semantics, verification flow, and night behaviour remain unchanged.

## Interaction design

The plan remains authoritative but becomes passive inside replay. It is fitted and centred
using the existing default plan viewport, while pointer panning and wheel zoom are disabled.
The same `PlanCanvas` remains interactive everywhere else, especially in authoring/editor
screens.

The presentation transport stays below the evidence caption in document order for keyboard
and screen-reader users, but becomes sticky at the bottom of the visible page. Its background,
border, spacing, typography, and controls continue to use the simulator's existing design
tokens. A restrained shadow separates the controls from plan content while scrolling.

## Component boundary

`PlanCanvas` receives an explicit interaction mode with an interactive default. Replay passes
the passive mode; existing callers need no changes. CSS owns the sticky transport and compact
presentation sizing, while replay state and data fetching remain untouched.

## Verification

Component tests will prove that passive mode does not bind pan or wheel handlers and that the
default interactive mode still does. Replay workbench tests will prove that presentation mode
requests a passive canvas and retains the transport region. Focused frontend tests and the
frontend build will validate the change.
