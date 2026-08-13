# ADR-021: Workspace reconciliation and researcher-initiated deletion

- **Status:** accepted
- **Date:** 2026-08-12

## Context

ADR-016 made startup reconciliation refuse to accept a workspace whose files disagree with the
catalogue: any difference enabled diagnostic mode and blocked new publication. That rule treated
three unrelated situations as one failure.

A complete export of a long horizon is a third of a gigabyte, exports are built repeatedly, and the
application offered no way to remove one — the documented way to reclaim the space was to delete the
folder in the file manager, which `ExportService` explicitly supports by rebuilding the export on the
next request. Doing exactly that put the workspace into diagnostic mode at the next start: 271
catalogue rows described files the researcher had deliberately deleted, publication stopped, and
nothing in the application could undo it. Homes and runs could not be deleted at all, so a workspace
only ever grew.

## Decision

Distinguish the three cases and act on each according to what it actually means.

- **Missing** — a catalogued file is no longer in the folder. It is gone; no amount of caution
  brings it back, and keeping the row only blocks the workspace it was meant to protect. Startup
  forgets the row, clears every reference to it, closes exports whose folder was deleted, and
  reports what it changed on the dashboard.
- **Corrupt** — a file is present with content that contradicts the recorded digest, or its path
  escapes the workspace root. What a run executed can no longer be established, so this alone
  enables diagnostic mode. Repair never deletes such a row; it reports it.
- **Orphan** — a file no catalogue entry describes. It is never read, so it is reported as
  reclaimable and only deleted when the researcher asks. Unfinished staging directories, which this
  application itself writes under dot-prefixed names, are the exception: they are always removed.

Deletion becomes a first-class operation. A home takes its residents, revisions, validation issues,
runs, exports and stored inputs with it; a run takes its events, artifacts, generated days and
exports; an export takes its folder and archive. Deletion and repair remain available in diagnostic
mode, because they are recovery operations. Content-addressed objects are released rather than
deleted: two homes that published the same bytes share one row, so an object is only reclaimed once
nothing surviving still names it.

`reconcile()` keeps returning every disagreement as one strict list, and stays the check an
imported `.shw` archive has to pass — an archive is written in one operation, so anything missing or
unaccounted for in it is a damaged archive rather than a folder somebody tidied.

## Consequences

- Working in the workspace folder no longer disables the application, and what that cost is stated
  rather than applied silently.
- Diagnostic mode now means one specific thing, so it is worth acting on when it appears.
- A workspace can be kept at a working size without leaving the application.
- The catalogue can lose provenance the researcher chose to delete. That is the intended trade:
  the alternative was a permanently paused workspace describing files nobody has.
