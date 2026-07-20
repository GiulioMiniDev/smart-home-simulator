# ADR-008: External authoring repair loop 1.0.0

- Status: accepted
- Date: 2026-07-20

## Context

External LLM responses can be structurally plausible while violating a small number of
cross-document or catalog constraints. Restarting generation discards valid personalized
content and can introduce unrelated regressions. The ingestion report already exposes
stable issue codes, stages, JSON paths, messages and structured details, but a researcher
would otherwise have to assemble that feedback and the authoritative contracts manually.

The simulator must remain deterministic and provider-independent. It must not silently
modify rejected authoring material or depend on an LLM during compilation or simulation.

## Decision

Introduce the frozen `AuthoringRepairRequest 1.0.0` contract and two equivalent CLI entry
points:

- `ingest-authoring-output --repair-request-output ... --repair-attempt N` creates the
  request as a side artifact of failed ingestion;
- `prepare-authoring-repair --output ... --attempt N` creates it independently.

The request embeds the rejected UTF-8 source verbatim, its SHA-256 digest, the complete
ingestion report, immutable repair policies, the bundle schema and all authoring catalogs.
Its deterministic identifier combines the source digest prefix and explicit positive
attempt number.

The source bundle is treated as data. The external LLM must make the smallest coherent
change, preserve unrelated valid content, resolve every error and return exactly one full
bundle. Partial fragments and JSON Patch are rejected as a workflow because they cannot be
validated independently against cross-document invariants. The returned full document
always re-enters validation, compilation and behavioral validation from the beginning.

Request creation supports malformed JSON if the original file remains bounded valid UTF-8.
It does not support unreadable, oversized or non-UTF-8 inputs. Already-valid inputs need no
repair. Filesystem publication errors are local operational failures rather than LLM
content errors.

## Consequences

- Valid personalized content can be retained across repair attempts.
- Every attempt is attributable to an exact source digest and validation report.
- The researcher sends one repair file instead of manually attaching schemas and catalogs.
- The LLM still runs only in the external authoring phase; provider integration, retry
  limits and credentials remain outside the simulator.
- No rejected bundle is edited in place and no canonical artifact is published early.
- The repair-request schema, checksum, CLI behavior and complete re-ingestion path are
  covered by regression tests.
