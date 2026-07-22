# Single-bundle authoring import design

**Status:** approved  
**Date:** 2026-07-22  
**Scope:** researcher-facing authoring import, advanced split import, and integrated guidance

## Goal

Restore the frozen M3 product boundary in the local application: a researcher gives an external
LLM one prompt, receives one `simulation_authoring_bundle` JSON document, and imports that single
file. The application validates and publishes the embedded scenario and personal process package
without requiring the researcher to understand internal canonical or runtime artifacts.

The existing two-file import remains available as an explicitly Advanced workflow for debugging,
migrations, and expert intervention.

## Selected approach

Add a dedicated bundle endpoint and make it the primary UI workflow. Keep the existing split
endpoint for backward compatibility, but make both routes call the same application-service
pipeline.

This is preferred over a polymorphic endpoint, whose request contract and errors would be
ambiguous, and over unpacking only in the frontend, which would leave the server's public
researcher-facing contract incorrect.

## Data flow and provenance

The primary flow is:

```text
external LLM
  -> simulation_authoring_bundle JSON
  -> POST /api/homes/{homeId}/authoring-bundle
  -> envelope, scenario, compilation, and behavior validation
  -> canonical bundle + scenario + personal process package artifacts
  -> immutable revisions and resident associations
```

The accepted bundle is stored as a canonical semantic JSON artifact and linked through revision
provenance to the two published canonical documents. It remains possible to identify exactly
which researcher input produced each revision. Formatting and insignificant whitespace from the
uploaded file are not scientific data and are not retained.

The Advanced route accepts scenario and personal process package documents separately, constructs
the same envelope server-side, and enters the identical validation and publication pipeline.

No catalog upgrade, repair, or Lucia-specific runtime migration is applied silently. The bundle is
the ground truth and its declared frozen contracts are authoritative.

## User interface and integrated guide

The empty resident context presents one prominent bundle file selector and one action that says
what will happen: validate the complete bundle and attach it to the home. Validation failures are
deduplicated and shown with code and JSON path where available.

An integrated guide makes the workflow self-contained. It contains:

- the exact steps from describing a study to importing the resulting JSON;
- a copyable complete/Advanced prompt, identified as the authoritative recommended path;
- a copyable simplified prompt, clearly identified as experimental rather than reliable for
  one-shot generation with small local models;
- explicit instructions to return pure JSON and import the whole response unchanged;
- an explanation of the bundle structure and the difference between source, canonical, and
  runtime artifacts;
- a compact troubleshooting section for malformed JSON and authoritative validation errors.

The prompt text is served from the repository's versioned prompt files so the UI cannot drift from
the documented authoring contract. The guide is reachable from both the import surface and the
application Help navigation. It works fully offline.

The Advanced import is a collapsed disclosure below the primary flow. It uses separate scenario
and personal-process-package selectors and clearly states that ordinary researchers should not
need it.

## Failure semantics

Envelope, scenario, compilation, catalog-reference, graph, binding, and argument validation finish
before publishable authoring revisions are created. A rejected input may persist normalized
validation issues for diagnosis, but it creates no authoring artifact, resident association, or
revision.

Invalid JSON is rejected client-side with the selected filename. Server-side validation remains
authoritative. Repeated issues with the same code, path, and message are displayed only once.

## Verification

Backend tests cover direct bundle import, invalid-bundle non-publication, the dedicated HTTP route,
source-artifact provenance, and parity with the Advanced split wrapper. Frontend tests cover the
primary single-file workflow, the collapsed Advanced workflow, prompt-guide navigation and copy
content, malformed JSON, deduplicated validation feedback, and accessible labels.

The real Lucia `authoring-bundle.json` is used for a local regression verification without adding
generated study data as a permanent test dependency. Python, TypeScript, lint, build, and browser
acceptance gates are run before handoff. No commit is created without explicit user permission.
