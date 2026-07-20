# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

Le **Milestone 1, 2 e 3 sono completate e congelate alla versione contrattuale 1.0.0**. Il sistema valida lo scenario flessibile, lo compila in un piano canonico deterministico e valida i modelli di processo ADL personali che descrivono come ogni residente svolge le proprie attività. Il prossimo sviluppo previsto è la Milestone 4, l'ambiente domestico eseguibile e il binding completo delle azioni.

Sono intenzionalmente assenti:

- motore di simulazione;
- SimPy;
- ambiente e planimetria 2D;
- microesecuzione;
- sensori;
- exporter dei dataset;
- chiamate integrate a provider LLM.

Queste feature verranno sviluppate separatamente solo dopo il completamento dei rispettivi criteri di ingresso descritti in [ROADMAP.md](ROADMAP.md).

## Comandi disponibili

```bash
make sync
make validate
make validate-behavior
make compile
make schema
make behavior-artifacts
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

Per validare un pacchetto personale di process model contro il relativo scenario:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim validate-behavior \
  examples/behavior/mario_rossi_week_2026_10_12.behavior.json \
  examples/valid/mario_week.json
```

Il comando usa i cataloghi `1.0.0` distribuiti con il pacchetto. I prompt in `prompts/`
permettono a un ricercatore di produrre scenario e process model tramite un LLM esterno;
il runtime non invoca alcun provider.

Gli artefatti pubblici congelati sono:

- `schemas/scenario-1.0.0.schema.json`;
- `schemas/validation-report-1.0.0.schema.json`;
- `schemas/canonical-plan-1.0.0.schema.json`;
- `schemas/compilation-report-1.0.0.schema.json`;
- `schemas/activity-catalog-1.0.0.schema.json`;
- `schemas/variable-catalog-1.0.0.schema.json`;
- `schemas/action-catalog-1.0.0.schema.json`;
- `schemas/personal-process-package-1.0.0.schema.json`;
- `schemas/behavior-validation-report-1.0.0.schema.json`;
- i tre cataloghi versionati in `src/smart_home_sim/catalogs/`;
- i prompt ufficiali versionati in `prompts/`;
- il registro degli 83 codici in `src/smart_home_sim/domain/codes.py`;
- il registro dei codici comportamentali in
  `src/smart_home_sim/domain/behavior_report.py`.

L'accettazione principale è una settimana completa di 173 attività in `examples/valid/mario_week.json`. L'esempio `examples/valid/minimal.json` è utile per imparare il contratto senza il rumore del caso completo.

La compilazione golden della settimana è in `examples/compiled/`: contiene 169 attività principali, 3 contingenze, 4 alternative e 3 rischedulazioni. Usa OR-Tools CP-SAT `9.15.6755`, tempo intero al microsecondo e una policy deterministica documentata.

## Documentazione

- [Roadmap e milestone](ROADMAP.md)
- [Confine del sistema](docs/spec/00-system-boundary.md)
- [Contratto dello scenario](docs/spec/01-scenario-contract.md)
- [Motore di validazione](docs/spec/02-validation-engine.md)
- [Contratti downstream](docs/spec/03-downstream-contracts.md)
- [Compilatore del piano](docs/spec/05-plan-compiler.md)
- [Authoring comportamentale e process model ADL](docs/spec/06-behavioral-authoring.md)
- [Blueprint del futuro motore di simulazione](docs/design/simulation-engine-blueprint.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
- [Freeze dei contratti 1.0.0](docs/decisions/ADR-002-freeze-scenario-contract-1.0.0.md)
- [Freeze del compilatore 1.0.0](docs/decisions/ADR-003-freeze-plan-compiler-1.0.0.md)
- [Freeze dell'authoring comportamentale 1.0.0](docs/decisions/ADR-004-freeze-behavioral-authoring-1.0.0.md)
