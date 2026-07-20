# End-to-end external-LLM authoring

## Purpose

The researcher receives one generic, self-contained prompt and enriches its final section
with a free-form description of the person or people to simulate. The description is not
a project JSON contract: it may be brief, detailed and written in natural language. An
external LLM turns it into the two structured inputs already defined by Milestones 1 and
3.

```text
generic prompt + free-form person description
                    -> external LLM
                    -> simulation authoring bundle
                    -> deterministic ingestion
                    -> scenario.json + personal-process-package.json
```

The simulator and its validators never call an LLM. Provider selection, authentication,
conversation state and retries remain outside the runtime boundary.

## Single distributed prompt

`prompts/generate-simulation-inputs-1.2.0.md` embeds:

- the complete authoring-bundle JSON Schema;
- the complete project activity catalog;
- the complete variable catalog;
- the complete typed action catalog;
- scenario, personal ADL and cross-document generation rules;
- the mandatory compatibility matrix between value-expression sources and action-parameter
  reference kinds;
- a marked `PERSON_AND_CASE_DESCRIPTION` section for the researcher.

It is generated deterministically from its template and the distributed contracts by
`tools/build_authoring_artifacts.py`. The generated prompt is the file supplied to the
chatbot; the separate source schemas and catalogs are not attachments. Regeneration is
part of `make check`, preventing the prompt from drifting from the validators.

The prompt instructs the LLM to preserve supplied facts, make conservative synthetic
choices where mandatory fields are absent, record material assumptions in provenance and
return only one complete JSON object. Mermaid is neither requested nor parsed.

## Transport envelope

The LLM response conforms to
`schemas/simulation-authoring-bundle-1.0.0.schema.json`:

```json
{
  "schemaVersion": "1.0.0",
  "documentType": "simulation_authoring_bundle",
  "scenario": {},
  "personalProcessPackage": {}
}
```

This envelope is a transport contract, not a third behavioral representation. Its nested
`scenario` is exactly `Scenario 1.0.0`; its nested `personalProcessPackage` is exactly
`PersonalProcessPackage 1.0.0`. Their frozen standalone schemas and semantics are not
changed. The envelope exists because a single pure-JSON response is portable across
chatbots and does not depend on a provider's ability to create downloadable files.

## Deterministic ingestion

The response is saved verbatim and ingested with:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  response.json \
  --output-dir generated/persona
```

The ingestor performs, in order:

1. bounded UTF-8 and JSON parsing with duplicate-key, non-finite-number and nesting
   rejection;
2. exact envelope validation;
3. the complete Milestone 1 scenario validation;
4. the complete Milestone 2 deterministic compilation gate;
5. the complete Milestone 3 package, catalog, graph and scenario-compatibility validation;
6. strict model/schema parity validation;
7. normalization and digest calculation;
8. atomic publication as `scenario.json` and `personal-process-package.json`.

The destination directory must not already exist. Files are written in a temporary
sibling directory and published through one rename. On any validation or filesystem
failure, neither canonical artifact is exposed and temporary files are removed. Existing
user data is never overwritten.

The versioned machine-readable result is
`schemas/authoring-ingestion-report-1.1.0.schema.json`. It preserves every nested
validator issue with a prefixed path and identifies whether it arose from the envelope,
scenario, compilation, behavior package or output publication. A successful report also
records the digest of the canonical plan proven by the compilation gate.

## External repair cycle

A rejected bounded UTF-8 response can be converted into one self-contained repair request
without changing the source bundle:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  response.json \
  --output-dir generated/persona \
  --format json \
  --report-output generated/persona-report.json \
  --repair-request-output generated/persona-repair-attempt-1.json \
  --repair-attempt 1
```

The failure exit code remains `1` and no canonical input is published. The repair artifact
conforms to `schemas/authoring-repair-request-1.0.0.schema.json` and contains:

- the rejected source text and its SHA-256 digest;
- the complete `AuthoringIngestionReport 1.1.0` with stable codes and JSON paths;
- explicit preservation, minimum-change and full-response policies;
- the authoritative bundle schema and all three catalogs;
- a positive attempt number and deterministic request identifier.

The source text is explicitly data, not an instruction channel. The external LLM must
resolve every error, preserve unrelated valid content and return exactly one complete
`simulation_authoring_bundle` JSON object. JSON Patch, partial fragments, explanations and
Markdown fences are forbidden because only the complete bundle can be checked across all
cross-document invariants.

The returned bundle enters the ordinary ingestion command again. If it still fails, a new
request is generated from that exact output with the next attempt number. No previous
request or inferred patch is trusted. A valid result is published only by the existing
atomic ingestion path. `prepare-authoring-repair` exposes the request-generation step as a
standalone command for workflows that already saved the validation report.

Already-valid bundles, unreadable files, non-UTF-8 data and inputs above the normal size
limit do not produce a repair request. Output-publication failures are local filesystem
problems and are not presented to the LLM as content defects.

This is an authoring-time feedback loop, not a runtime LLM dependency. Provider API keys,
conversations, uploads, retry limits and model selection remain under researcher control.

## Provenance and trust

The LLM output remains synthetic authoring material. The prompt requires the actual model,
prompt version, generation time, parameters and review status. Inferred details are not
treated as observations, and `humanReviewed` remains false until a human review actually
occurs. Passing ingestion proves contract validity and internal consistency, not empirical
fidelity to a real person; calibration remains Milestone 9.

## Relationship to later milestones

After ingestion, the existing compiler consumes `scenario.json`. Milestone 4 will bind the
accepted process package to one concrete executable home. Milestone 5 will execute the
result. No later stage requires the original prompt, chatbot conversation or LLM provider.
