# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

Le **Milestone 1, 2, 3 e 4 sono completate e congelate alla versione contrattuale 1.0.0**. Il sistema valida lo scenario flessibile, lo compila in un piano canonico deterministico, valida i modelli di processo ADL personali e lega ogni loro azione a una casa metrica eseguibile. Il prossimo sviluppo previsto è la Milestone 5, il motore di simulazione completo.

Sono intenzionalmente assenti:

- motore di simulazione;
- SimPy;
- microesecuzione;
- sensori;
- exporter dei dataset;
- applicazione UI completa, prevista nella Milestone 7 dopo simulazione e sensori;
- chiamate integrate a provider LLM.

Queste feature verranno sviluppate separatamente solo dopo il completamento dei rispettivi criteri di ingresso descritti in [ROADMAP.md](ROADMAP.md).

## Comandi disponibili

```bash
make sync
make validate
make validate-behavior
make validate-home
make compile
make bundle
make benchmark-environment
make schema
make behavior-artifacts
make authoring-artifacts
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

Per validare la casa eseguibile e costruire atomicamente il bundle completo:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim validate-home \
  examples/environment/mario_monteverde.home.json
UV_NO_EDITABLE=1 uv run smart-home-sim build-simulation-bundle \
  examples/valid/mario_week.json \
  examples/compiled/mario_week.plan.json \
  examples/behavior/mario_rossi_week_2026_10_12.behavior.json \
  examples/environment/mario_monteverde.home.json \
  --output examples/bundles/mario_week.simulation-bundle.json \
  --report-output examples/bundles/mario_week.environment-report.json
```

Il binder controlla geometria, ostacoli, topologia, accesso, risorse, cinematica e tutte
le rotte prima di risolvere le capacità. In caso di errore non pubblica alcun bundle.

Il golden environment M4 può essere ispezionato anche nel
[benchmark visuale di Casa Monteverde](examples/visualizations/mario_monteverde.m4-benchmark.html).
È un artefatto di accettazione interattivo, non la UI applicativa della Milestone 7:
mostra la planimetria reale, le sei porte locali, i quattro ingombri metrici, le nove
risorse fisiche con simboli dedicati, le sei entità logiche domestiche, gli anchor e le 49
rotte interne calcolate dal path planner. Viene rigenerato da home, scenario, bundle e
report con `make environment-visualization`; la generazione fallisce se un elemento è
stale, inventato, omesso o privo di rappresentazione.

La chiusura terminale della milestone, requisito per iniziare la M5, è documentata
nell'[audit M4](docs/audits/milestone-4-closure.md).

Il flusso di authoring consigliato usa un solo file:
`prompts/generate-simulation-inputs-1.2.0.md`. Il ricercatore sostituisce il marcatore
`PERSON_AND_CASE_DESCRIPTION` con una descrizione libera della persona, invia l'intero
prompt a un LLM esterno e salva il solo JSON restituito. Non deve allegare separatamente
schemi o cataloghi.

La risposta viene validata e trasformata atomicamente nei due input canonici con:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  risposta-llm.json \
  --output-dir generated/mario
```

La directory di destinazione non deve esistere. L'ingestione esegue validazione dello
scenario, compilazione completa e validazione ADL nello stesso passaggio. Se un gate
fallisce non viene prodotto alcun input parziale. Il piano può essere rigenerato con il
normale comando `compile`; dopo l'accettazione l'LLM non viene più utilizzato.

Se il bundle viene rifiutato, lo stesso passaggio può produrre una richiesta di
riparazione autosufficiente:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  risposta-llm.json \
  --output-dir generated/mario \
  --format json \
  --report-output generated/mario-ingestion-report.json \
  --repair-request-output generated/mario-repair-attempt-1.json \
  --repair-attempt 1
```

In caso di errore il comando termina con exit code `1`, non crea `generated/mario` e
scrive sia il report sia `mario-repair-attempt-1.json`. Quest'ultimo contiene il bundle
originale, il suo digest, tutti gli errori con i relativi percorsi JSON, le istruzioni di
correzione e gli schemi/cataloghi autorevoli. Il ricercatore allega questo unico file
all'LLM e salva il bundle JSON completo corretto; non deve richiedere una rigenerazione da
zero né gestire manualmente i singoli errori. Il nuovo bundle rientra nello stesso comando.
Se fallisce ancora, si ripete indicando `--repair-attempt 2`, e così via. Il simulatore non
applica patch e non accetta il risultato finché tutti i gate non passano.

Una richiesta può anche essere preparata separatamente:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim prepare-authoring-repair \
  risposta-llm.json \
  --output generated/mario-repair-attempt-1.json \
  --attempt 1
```

Il ciclo riguarda esclusivamente l'authoring esterno: non introduce chiamate LLM durante
compilazione o simulazione.

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
- `schemas/simulation-authoring-bundle-1.0.0.schema.json`;
- `schemas/authoring-ingestion-report-1.0.0.schema.json`;
- `schemas/authoring-ingestion-report-1.1.0.schema.json`;
- `schemas/authoring-repair-request-1.0.0.schema.json`;
- `schemas/home-model-1.0.0.schema.json`;
- `schemas/environment-validation-report-1.0.0.schema.json`;
- `schemas/simulation-bundle-1.0.0.schema.json`;
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
- [Authoring end-to-end tramite LLM esterno](docs/spec/07-end-to-end-llm-authoring.md)
- [Ambiente domestico eseguibile e binding](docs/spec/08-executable-home-and-binding.md)
- [Blueprint del futuro motore di simulazione](docs/design/simulation-engine-blueprint.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
- [Freeze dei contratti 1.0.0](docs/decisions/ADR-002-freeze-scenario-contract-1.0.0.md)
- [Freeze del compilatore 1.0.0](docs/decisions/ADR-003-freeze-plan-compiler-1.0.0.md)
- [Freeze dell'authoring comportamentale 1.0.0](docs/decisions/ADR-004-freeze-behavioral-authoring-1.0.0.md)
- [Envelope di authoring a prompt singolo 1.0.0](docs/decisions/ADR-005-single-prompt-authoring-envelope-1.0.0.md)
- [Authoring con gate del compilatore 1.1.0](docs/decisions/ADR-006-compilation-gated-authoring-1.1.0.md)
- [Prompt con riferimenti compatibili 1.2.0](docs/decisions/ADR-007-reference-compatible-authoring-prompt-1.2.0.md)
- [Ciclo esterno di riparazione dell'authoring 1.0.0](docs/decisions/ADR-008-external-authoring-repair-loop-1.0.0.md)
- [Freeze dell'ambiente eseguibile 1.0.0](docs/decisions/ADR-009-freeze-executable-environment-1.0.0.md)
