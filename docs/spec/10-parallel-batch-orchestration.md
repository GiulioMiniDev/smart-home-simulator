# Parallel simulation batches

## Input and identity

A batch manifest contains an experiment ID and one or more uniquely identified runs. A
run references a simulation bundle relative to the manifest or by absolute path and may
declare an effective seed. Run IDs are restricted to filesystem-safe ASCII identifiers.

The manifest is configuration, not hidden simulation state. Before execution, each worker
materializes the complete effective bundle in its run directory. Seed overrides therefore
change the canonical bundle hash recorded by M5 and remain replayable from that snapshot.

## Isolation and scheduling

The orchestrator uses the multiprocessing `spawn` context. Every worker creates a fresh
M5 engine, SimPy environment, world state, resource coordinator and named PRNG streams.
No runtime object crosses run boundaries. A one-worker batch executes in the coordinator
process to avoid unnecessary process startup; this does not alter simulation semantics.

Completed futures are collected in arbitrary wall-clock order, but the public report is
always ordered like the manifest. A worker failure becomes a failed run result and never
cancels sibling futures.

## Artifacts and commit protocol

Each run owns:

```text
<runId>/simulation-bundle.json
<runId>/execution-trace.json
<runId>/simulation-report.json
```

Files are flushed, fsynced and atomically renamed from unique sibling temporaries. The
experiment root is protected by a non-blocking process lock: `fcntl.flock` on macOS and
Linux, and a one-byte `msvcrt.locking` range on Windows. Platform modules are loaded only
by their matching backend. The aggregate `batch-report.json` is written last.

## Resume

Resume is enabled by default. A successful run is reused only when:

- its input bundle still validates;
- the effective bundle equals the current input plus the declared seed;
- report and trace parse against their frozen contracts;
- source bundle hashes match;
- trace hash and semantic digest match the simulation report.

Incomplete or previously failed runs execute again. A successful-looking but inconsistent
artifact set fails with `RESUME_INVALID` instead of being silently overwritten.

## Parallelism boundary

M5.1 parallelizes independent worlds. It does not split one SimPy event queue across
threads or processes. The intended deployment rule is one active simulation per worker,
with worker count bounded by available CPU and memory.

## Supported platforms

Python 3.12 on Windows, macOS and Linux is the acceptance matrix. Each platform must pass
the complete test suite and the real multi-process batch benchmark; a unit-level fake of
the Windows API additionally verifies byte offset, range length and error translation on
every development host. Lock semantics on shared network filesystems are not claimed by
this local-process orchestration contract.
