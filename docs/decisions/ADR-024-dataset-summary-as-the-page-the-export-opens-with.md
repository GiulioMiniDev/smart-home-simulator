# ADR-024: The export opens with one page that says what the dataset is

- Status: accepted and implemented
- Date: 2026-08-19
- Completes [ADR-022](ADR-022-resident-profile-as-published-evidence.md), which published what the
  resident is like, and [ADR-018](ADR-018-outline-first-external-authoring.md), which published the
  bands she was given, by publishing the thing neither of them does: the house, and the reading of
  all three together.

## Context

An export is a folder of evidence. Every file in it answers a question the reader has to already
know to ask, and one thing a reader looks for first is not in there at all: the house.

The home model and the sensor model are run artifacts. No export role touches them. A researcher
holding `observable.jsonl` reads `pir_kitchen` and has no way to learn where that sensor is, what
it covers, how many rooms the flat has or which of them the resident actually crosses to get from
the bedroom to the kitchen. The only drawing of the flat lives in the editor canvas, which means
it requires a running application and a workspace — exactly what an export exists to travel
without.

The habit ground truth has the opposite problem. It *is* exported, as rows: `windowStart`,
`dominantIntent`, `effectiveShare`, a composition array. Every number a segmentation experiment
needs is there and none of it is a sentence, so the person who commissioned the dataset — who
wants to know what this resident's mornings look like — reads a CSV to find out.

And nothing ties the files together. `manifest.json` lists them with digests, which is an
integrity record, not an explanation.

## Decision

Publish a second computed role, `summary`: **one self-contained HTML page** per export.

1. **It draws the flat.** The plan is derived from the same geometry the path planner routes
   through — rooms as tiled, doors on the walls they actually cross, furniture at the extent the
   resident walks around — with the deployed sensors and their coverage over it. The derivation is
   the editor's, ported to Python, because an export cannot start a browser. Places the simulator
   keeps kilometres away are named but not drawn: at that distance they decide the viewport and
   leave the dwelling unreadable in a corner.

2. **It states the ground truth in words.** Each band gets a sentence: what holds it, how much of
   the band that activity accounts for, and where it *actually* runs as opposed to where the
   declared window allows it. A band whose activity holds no stretch on most days says so and
   claims no boundary, because inventing one would publish a target the run never produced.

3. **It is for the person who commissioned the dataset.** The answer sheet is in the open,
   deliberately. The blind view of the same run is the export beside it, whose observable log
   carries no labels; a summary that withheld the bands would be a summary of somebody else's
   problem.

4. **Rates, never labels.** Per-sensor reading counts, loss and false-positive rates are published;
   the per-reading `quality` field stays withheld exactly as it was. Declaring the noise conditions
   is what a dataset owes its reader. Labelling which rows are noisy hands over part of the answer.

5. **Everything it reads is optional.** Home model, sensor model, scenario and projection report
   are each absent from some run somewhere. Each missing one turns into a sentence saying so. A
   summary that refuses to build is a summary nobody can rely on.

6. **It records no identity of its own.** No clock reading, and no export identifier — that one is
   a fresh uuid per publication, and printing it would make two rebuilds of the same request differ
   by bytes. Rebuilding a deleted export byte for byte is the promise the export already makes.

## Consequences

`ExportRequest` gains one role. The manifest gains one `html` file, which 1.1.0 already admits, so
no contract version moves and no run artifact changes: the page applies retroactively to every run
already in a workspace.

The two computed roles now share one aggregation of the execution trace, built lazily and reused.
Requesting profile and summary together costs one pass over the trace rather than two, which on an
eight month run is the difference that matters. Both are built after the projected roles, because
the summary indexes them.

The declared persona reaches the page only for scenarios that carry one. Outline-first horizons
keep the persona in the outline, which the application never receives — the run holds the days the
persona produced, not the person who produced them. The page says that rather than showing a
resident with no traits. Carrying a résumé of the outline into the scenario the way
`habitGroundTruth` already travels would fix it, and is a change to the expander rather than to the
export.
