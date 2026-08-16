# ADR-023: Where the files live is a setting, and moving them belongs to the next start

- Status: accepted and implemented
- Date: 2026-08-16
- Extends [ADR-016](ADR-016-local-application-and-sqlite-workspace.md), which fixed the workspace
  under `~/.smart-home-simulator/`, and complements
  [ADR-021](ADR-021-workspace-reconciliation-and-deletion.md), which made a workspace shrinkable
  from inside the application but not movable.

## Context

A workspace only grows. Every run writes an execution trace, an observable log and an oracle
mapping; every export writes a further projection of one of those, and the export is kept because
rebuilding it costs a run. On this project's own machine, nine months of experiments reached 8.8 GB
— 6.2 GB of exports, 2.6 GB of runs — inside a home directory on a system drive with 13 GB left,
while a second drive sat 317 GB empty.

ADR-016 chose that home directory deliberately: outside the repository, outside Git, the same path
on every machine. What it did not anticipate is that the choice is not the application's to keep
making. Filling the system drive is not a degraded simulator, it is a degraded computer, and the
researcher is the only one who knows which drive has room. `--workspace` and
`SMART_HOME_SIM_DATA_DIR` already existed but neither is a decision the application remembers: they
have to be retyped at every launch, and the bootstrap script passed `--workspace` unconditionally,
so a saved preference would have been overridden even if there had been somewhere to save one.

The obvious alternative — let the exports directory be configured separately, since it is the bulk
— was rejected. Every artifact is catalogued by a path relative to the workspace root, and integrity
checking, repair, deletion and archiving all compare the catalogue against that one tree. Splitting
a branch of it onto another volume would put the digests and the files they vouch for under
different roots, which is precisely the state ADR-021 defines as broken.

## Decision

**The location is one setting, applied to the whole workspace.** A configuration file records the
workspace directory, the application directory, the port and whether to open a browser. It lives at
`~/.smart-home-simulator/configuration.json` — outside the workspace, because it is the thing that
says where the workspace is, and a file cannot describe the location of the folder containing it.
`SMART_HOME_SIM_HOME` relocates the anchor itself, which is what the test suite uses to stay off the
real installation.

**Precedence is explicit and stated in the interface.** Command line, then environment variable,
then configuration file, then default. The settings page reports which of the four decided the
folder currently in use, so a session launched with `--workspace` says so rather than appearing to
ignore what was saved — and, because a restart re-runs the same launch options, it is not offered a
restart that would change nothing.

**A move is agreed in the application and performed by the next start.** Nothing is copied while the
workspace is open: the SQLite catalogue has handles on it and a worker may be writing into `runs/`,
and a tree half-moved out from under either is not a workspace. The pending move is recorded, and
the launcher performs it before anything opens the database. Within one volume it is a rename and
finishes instantly. Across volumes the tree is copied first and the source deleted only once every
byte has arrived, so a failed copy leaves the original untouched and the partial destination is
removed. If the copy succeeds and only the deletion fails — a log file held open, an antivirus
scanner — the setting follows the data to the destination and the leftovers are reported for the
researcher to remove, because by then the workspace really is in the new place.

**The bootstrap script owns the restart.** The server exits with a distinct code to ask for one, and
`./start` repeats its whole configure-and-launch cycle rather than only respawning the process, so a
changed application directory has its Python environment built in the new place before anything is
started from it. A server started without that supervisor is told to say so instead of offering a
restart it cannot perform.

## Consequences

- The system drive stops being the only answer, and the settings page states the cost of the choice:
  what the workspace weighs by part, and how much room each volume has left.
- One move is agreed and takes effect at the next start, rather than being available instantly. That
  is the price of never having a workspace open while it is being moved, and it is the right price.
- Exports and runs cannot be split across volumes. Keeping a workspace to a size a drive can hold
  remains ADR-021's job — deleting exports, which are reproducible — and the settings page links to
  it with the number that makes the case.
- Two paths now read the configuration: the package, and the bootstrap script, which cannot import
  the package because it decides where to build the environment containing it. The file's field
  names are the shared contract, and it is read tolerantly on both sides so that a file written by a
  later version cannot stop an earlier one from starting.
