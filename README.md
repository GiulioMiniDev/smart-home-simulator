# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

Le **Milestone 1 e 2 sono completate e congelate alla versione contrattuale 1.0.0**. Il sistema valida lo scenario flessibile e lo compila in un piano canonico deterministico; il prossimo sviluppo previsto è la Milestone 3, dedicata all'authoring comportamentale e ai modelli di processo ADL personali che costituiranno un input completo del futuro simulatore.

Sono intenzionalmente assenti:

- motore di simulazione;
- SimPy;
- ambiente e planimetria 2D;
- microesecuzione;
- sensori;
- exporter dei dataset;
- integrazione LLM.

Queste feature verranno sviluppate separatamente solo dopo il completamento dei rispettivi criteri di ingresso descritti in [ROADMAP.md](ROADMAP.md).

## Comandi disponibili

```bash
make sync
make validate
make compile
make schema
```

Per validare un file specifico:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim validate percorso/scenario.json
UV_NO_EDITABLE=1 uv run smart-home-sim validate percorso/scenario.json --format json
UV_NO_EDITABLE=1 uv run smart-home-sim compile percorso/scenario.json --output piano.json --report-output compilazione.json
```

`UV_NO_EDITABLE=1` evita che le installazioni editable basate su `.pth` vengano ignorate dalle versioni recenti di Python quando macOS assegna a tali file il flag filesystem `hidden`.

Test e qualità:

```bash
make test
make lint
make check
```

`validate` non corregge né esegue lo scenario. `compile` risolve vincoli, attività opzionali e contingenze, ma non esegue ancora le attività.

Gli artefatti pubblici congelati sono:

- `schemas/scenario-1.0.0.schema.json`;
- `schemas/validation-report-1.0.0.schema.json`;
- `schemas/canonical-plan-1.0.0.schema.json`;
- `schemas/compilation-report-1.0.0.schema.json`;
- il registro degli 83 codici in `src/smart_home_sim/domain/codes.py`.

L'accettazione principale è una settimana completa di 173 attività in `examples/valid/mario_week.json`. L'esempio `examples/valid/minimal.json` è utile per imparare il contratto senza il rumore del caso completo.

La compilazione golden della settimana è in `examples/compiled/`: contiene 169 attività principali, 3 contingenze, 4 alternative e 3 rischedulazioni. Usa OR-Tools CP-SAT `9.15.6755`, tempo intero al microsecondo e una policy deterministica documentata.

## Documentazione

- [Roadmap e milestone](ROADMAP.md)
- [Confine del sistema](docs/spec/00-system-boundary.md)
- [Contratto dello scenario](docs/spec/01-scenario-contract.md)
- [Motore di validazione](docs/spec/02-validation-engine.md)
- [Contratti downstream](docs/spec/03-downstream-contracts.md)
- [Compilatore del piano](docs/spec/05-plan-compiler.md)
- [Blueprint del futuro motore di simulazione](docs/design/simulation-engine-blueprint.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
- [Freeze dei contratti 1.0.0](docs/decisions/ADR-002-freeze-scenario-contract-1.0.0.md)
- [Freeze del compilatore 1.0.0](docs/decisions/ADR-003-freeze-plan-compiler-1.0.0.md)
