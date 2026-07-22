# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

Le **Milestone 1–7 e l'estensione M5.1 sono completate e congelate alla versione
contrattuale 1.0.0**. Il
sistema valida e compila lo scenario, lega i process model personali a una casa metrica e
ne esegue integralmente attività, azioni, movimenti, risorse, eventi e stato tramite un
clock discreto deterministico. M5.1 orchestra run indipendenti in processi isolati con
seed, snapshot, resume e failure isolation. M6 proietta la traccia in osservazioni PIR,
contatto e temperatura mantenendo le etichette causali in un oracle mapping separato.
M6.1 genera deterministicamente casa e sensori dai due JSON M3. M7 espone l'intero flusso
in un'applicazione web locale: workspace SQLite persistente, editor 2D, worker durevoli,
diario della ground truth, vista observable/oracle, replay verificato ed export streaming
JSONL/CSV/XES.

Il runtime richiede Python 3.12 e supporta Windows, macOS e Linux. La CI impone su tutti e
tre i sistemi suite completa, lint e benchmark multiprocesso.

Restano intenzionalmente assenti:

- esecuzione longitudinale annuale e repliche Monte Carlo, assegnate a M8;
- calibrazione empirica, assegnata a M9;
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
make simulate
make replay
make project-sensors
make run-synthetic
make benchmark-environment
make benchmark-simulation
make benchmark-batch-simulation
make benchmark-sensors
make benchmark-materialization
make benchmark-application
make frontend-build
make frontend-test
make frontend-e2e
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

`validate` non corregge né esegue lo scenario. `compile` risolve vincoli, attività
opzionali e contingenze; `simulate` consuma esclusivamente un bundle M4 completo.

## Applicazione locale M7

Per configurare e avviare l'applicazione con un solo comando:

```bash
# macOS e Linux
./start

# Windows — Prompt dei comandi
start.cmd

# Windows — PowerShell
.\start.cmd
```

Il bootstrap rileva piattaforma e architettura, verifica `uv`, Node.js 20+ e npm, installa
le dipendenze soltanto quando mancano o il lockfile cambia, costruisce il frontend quando
le sorgenti cambiano e installa il backend in `~/.smart-home-simulator/venv`. Lo stato
applicativo resta in `~/.smart-home-simulator/workspace`, fuori dal repository. Alle
esecuzioni successive, se nulla è cambiato, passa direttamente all'avvio. `./start
--reconfigure` forza una configurazione completa; `./start --configure-only` prepara
l'ambiente senza avviare il server. Su Windows le stesse opzioni si passano a `start.cmd`.

I soli prerequisiti di sistema sono Python 3, [uv](https://docs.astral.sh/uv/) e
[Node.js](https://nodejs.org/) 20 o successivo. Se `uv` o Node.js non sono disponibili,
il bootstrap si ferma con un messaggio e il collegamento ufficiale, senza eseguire script
remoti o installazioni di sistema implicite.

Il launcher ascolta soltanto su loopback, apre il browser per default e crea o riapre il
workspace indicato. Se `--workspace` non viene specificato usa la directory locale
`~/.smart-home-simulator/workspace`, esterna al repository e non sincronizzata da Git.
Database, run, export, ambienti virtuali e build locali non devono essere versionati;
gli esperimenti da condividere vanno selezionati esplicitamente in `generated/` oppure
trasferiti come archivio `.shw`. `--no-browser` è disponibile per server di test. I metadati applicativi
sono in `workspace/workspace.sqlite3`; trace, log, oracle ed export restano file immutabili
con dimensione e SHA-256 catalogati. Non spostare singoli file a mano: usare **Archive
workspace** nella pagina Exports per produrre uno snapshot portabile `.shw` verificabile.

Il dettaglio di una run presenta tre viste distinte. **Diary** deriva direttamente dalla
execution trace e mostra attività, azioni e identificativi di provenienza. **Observable**
contiene soltanto campi esponibili dai dispositivi. **Oracle links** attraversa, su richiesta,
il mapping separato verso la causa simulata. **Replay** ricontrolla il digest semantico M5
prima di registrare la sessione. Le esportazioni mantengono la stessa separazione e includono
un manifest con seed, versioni, conteggi, relazioni, dimensioni e digest.

Se l'avvio trova un file mancante o corrotto, il workspace entra in modalità diagnostica:
consultazione e archivio restano disponibili, mentre nuove pubblicazioni e job vengono
bloccati. I job rimasti `running` dopo un arresto diventano `interrupted`; una cancellazione
rimuove lo staging e non presenta output parziali come validi. Architettura e invarianti sono
documentati in [ADR-016](docs/decisions/ADR-016-local-application-and-sqlite-workspace.md) e
nella [specifica M7](docs/spec/12-application-workspace-export-replay.md).

Per ottenere la prima simulazione dai due JSON pubblicati dall'ingestion, senza disegnare
la casa o collocare manualmente i sensori:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim run-synthetic \
  generated/mario_rossi_2026_10_30_ingested/scenario.json \
  generated/mario_rossi_2026_10_30_ingested/personal-process-package.json \
  --output-dir generated/mario_rossi_2026_10_30_simulation
```

Il comando usa per default le policy `compact-grid 1.1.0` e sensori `room_coverage
1.2.0` con profilo osservativo `realistic`, ma accetta file custom con `--home-policy` e
`--sensor-policy`. Il profilo realistico usa durate PIR e contatto distribuite, latenza,
jitter, dropout, falsi negativi e positivi, rumore e campionamento termico sfalsato. La
temperatura combina città e data dello scenario con inerzia e offset distinti per stanza;
se la città manca usa un profilo stagionale generico. `SensorDeploymentPolicy()` conserva
il profilo ideale 1.1.0 per replay e test legacy, mentre
`examples/policies/sensor-realistic-1.2.0.json` rende esplicito il nuovo default di ricerca.
La finestra dello scenario resta l'intervallo richiesto per pianificazione e analisi, ma
un'attività autorizzata con `allowBoundaryTruncation` può terminare oltre il confine finale:
il runtime la completa, estende `execution-trace.endedAt` e proietta anche la relativa coda
sensoriale. Il nome del campo è conservato per compatibilità con il contratto 1.0.0; nelle
valutazioni la coda va riportata separatamente dalla finestra principale, non tagliata.
Pubblica la
directory solo dopo il successo di compilazione, binding M4, simulazione M5 e proiezione
M6; se un gate fallisce rimuove lo staging. Il manifest finale verifica 17 artefatti con
digest canonici. I generatori possono essere usati separatamente con `generate-home` e
`deploy-sensors`; home e sensor model manuali restano supportati dai comandi originali.

Il layout generato è sintetico e controllato dalla policy: non ricostruisce una vera
planimetria. La policy sensoriale `1.1.0` aggiunge attività PIR intra-stanza, campionamento
termico periodico quantizzato e contatti sugli oggetti fisici effettivamente risolti. Il
confronto con CASAS Aruba è un controllo di plausibilità, non la calibrazione statistica
formale assegnata a M9. Questa scelta, insieme alle
questioni future sulla riusabilità della casa e sul multi-residente, è registrata in
[ADR-015](docs/decisions/ADR-015-scenario-first-environment-materialization.md).

Per eseguire e riprodurre deterministicamente il golden M5:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim simulate \
  examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json \
  --output examples/execution/mario_week.execution-trace.json \
  --report-output examples/execution/mario_week.simulation-report.json
UV_NO_EDITABLE=1 uv run smart-home-sim replay \
  examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json \
  examples/execution/mario_week.execution-trace.json
```

Il trace golden contiene 172 esiti di attività, 769 azioni, 202 movimenti geometrici e
1.139 transizioni di stato. Tutti i 27 action type sono eseguiti; nessun handler è un
no-op di compatibilità. La correzione semantica upstream `1.1.0` è parallela e lascia
immutati gli artefatti M1–M4 originali.

Per proiettare il trace M5 senza mescolare osservabile e ground truth:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim project-sensors \
  examples/execution/mario_week.execution-trace.json \
  examples/sensors/mario_monteverde.sensor-model.json \
  --bundle examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json \
  --output examples/sensors/mario_week.observable-sensor-log.json \
  --oracle-output examples/sensors/mario_week.oracle-mapping.json \
  --report-output examples/sensors/mario_week.sensor-projection-report.json
```

Il golden M6 usa otto sensori e produce 1.108 osservazioni e altrettanti link oracle. I
1.173 candidati includono evidenza non nulla per dropout, falsi negativi, cooldown,
guasti, falsi positivi e rumore. Il log pubblico contiene
soltanto campi misurabili dal dispositivo; persona, attività, azione e causa sono
accessibili esclusivamente attraverso l'oracle mapping. Tutto il rumore è derivato da
stream indipendenti per sensore e non modifica la traccia M5.

Il ricercatore colloca i dispositivi nel sensor model usando lo stesso sistema metrico
locale dell'home model: `position` per tutti i sensori, `regionIds` e poligono `coverage`
per i PIR, entità/stato o azioni per i contatti e regione/sorgenti per la temperatura. Il
bundle passato con `--bundle` incorpora la planimetria sintetica effettivamente usata dalla
simulazione; cataloghi, posizioni e coverage vengono controllati contro quella planimetria
prima di produrre qualsiasi record.

Per eseguire più simulazioni indipendenti in parallelo:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim simulate-batch \
  examples/batch/mario_week.seed-sweep.json \
  --output-dir runs/mario-week-seed-sweep \
  --workers 4
```

Ogni run materializza nella propria directory il bundle con il seed effettivo, la trace e
il simulation report. `batch-report.json` mantiene l'ordine del manifest e aggrega esiti,
tempi e provenance. `--resume` è attivo per default e riusa soltanto artefatti i cui hash
e digest sono ancora coerenti; run fallite o mancanti vengono eseguite senza interrompere
le altre. Due batch non possono scrivere contemporaneamente nella stessa directory. Il
lock usa il backend nativo del sistema (`msvcrt` su Windows, `fcntl` su macOS/Linux),
senza dipendenze esterne.

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
È un artefatto di accettazione interattivo M4 distinto dalla UI applicativa M7:
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

Per modelli locali è disponibile anche il prompt compatto corretto
`prompts/generate-simulation-inputs-1.2.2-simplified.md`. La guida integrata inserisce
automaticamente la descrizione del caso e il timestamp ISO di generazione; usando il file
manualmente occorre sostituire sia `[PERSON_AND_CASE_DESCRIPTION]` sia
`[GENERATION_TIMESTAMP]`. La versione 1.2.2 corregge riferimenti catalogo, intervallo
temporale end-exclusive, argomenti azione e precondizioni cronologiche. La precedente prova
Qwen 2.5 Coder 7B, eseguita con versioni compatte antecedenti e comprensiva di risposta,
ingestion report, workspace Windows/macOS e limiti qualitativi, è documentata nel
[report di authoring locale](docs/evaluation/esperimento_simulazione_7giorni_mario_rossi.md).
Il prompt completo resta il riferimento autorevole; zero errori di ingestion non sostituisce
la valutazione di plausibilità della routine generata.

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

### Prototipo di pianificazione ibrida locale

Il vertical slice della Milestone 8.1 usa LM Studio soltanto per proporre la struttura
semantica di una settimana. Il simulatore materializza gli orari, valida e compila il
piano, ma **non lo esegue**:

```bash
PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim generate-hybrid-plan \
  examples/hybrid/tommaso_bianchi_week.planning-case.json \
  --output-dir generated/hybrid-planning/tommaso-prova-1 \
  --model qwen2.5-coder-7b-instruct \
  --compare-with generated/tommaso_bianchi/tommaso_bianchi.json
```

La generazione effettua una chiamata di regia settimanale e sette chiamate giornaliere,
con memoria compatta progressiva e al massimo due revisioni esplicite per varietà
insufficiente. Il baseline passato con `--compare-with` viene letto soltanto dopo che
scenario e piano canonico sono stati accettati; non entra nei prompt o nella memoria.
Prompt, risposte, digest, checkpoint, report e confronto restano isolati nella directory
della run. LM Studio non è richiesto per validare, compilare, simulare o riprodurre
artefatti già esistenti.

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
- `schemas/execution-trace-1.0.0.schema.json`;
- `schemas/simulation-report-1.0.0.schema.json`;
- `schemas/replay-report-1.0.0.schema.json`;
- `schemas/simulation-batch-manifest-1.0.0.schema.json`;
- `schemas/simulation-batch-report-1.0.0.schema.json`;
- `schemas/sensor-model-1.0.0.schema.json`;
- `schemas/observable-sensor-log-1.0.0.schema.json`;
- `schemas/oracle-mapping-1.0.0.schema.json`;
- `schemas/sensor-projection-report-1.0.0.schema.json`;
- `schemas/home-generation-policy-1.0.0.schema.json`;
- `schemas/home-generation-report-1.0.0.schema.json`;
- `schemas/sensor-deployment-policy-1.0.0.schema.json`;
- `schemas/sensor-deployment-report-1.0.0.schema.json`;
- `schemas/synthetic-workspace-manifest-1.0.0.schema.json`;
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
- [Motore di simulazione completo](docs/spec/09-simulation-engine.md)
- [Orchestrazione dei batch paralleli](docs/spec/10-parallel-batch-orchestration.md)
- [Sensori e separazione oracle/observable](docs/spec/11-sensor-projection.md)
- [Blueprint architetturale del motore](docs/design/simulation-engine-blueprint.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
- [Freeze dei contratti 1.0.0](docs/decisions/ADR-002-freeze-scenario-contract-1.0.0.md)
- [Freeze del compilatore 1.0.0](docs/decisions/ADR-003-freeze-plan-compiler-1.0.0.md)
- [Freeze dell'authoring comportamentale 1.0.0](docs/decisions/ADR-004-freeze-behavioral-authoring-1.0.0.md)
- [Envelope di authoring a prompt singolo 1.0.0](docs/decisions/ADR-005-single-prompt-authoring-envelope-1.0.0.md)
- [Authoring con gate del compilatore 1.1.0](docs/decisions/ADR-006-compilation-gated-authoring-1.1.0.md)
- [Prompt con riferimenti compatibili 1.2.0](docs/decisions/ADR-007-reference-compatible-authoring-prompt-1.2.0.md)
- [Ciclo esterno di riparazione dell'authoring 1.0.0](docs/decisions/ADR-008-external-authoring-repair-loop-1.0.0.md)
- [Freeze dell'ambiente eseguibile 1.0.0](docs/decisions/ADR-009-freeze-executable-environment-1.0.0.md)
- [Correzione semantica runtime 1.1.0](docs/decisions/ADR-010-strict-runtime-semantics-1.1.0.md)
- [Freeze del motore di simulazione 1.0.0](docs/decisions/ADR-011-freeze-simulation-engine-1.0.0.md)
- [Orchestrazione batch parallela 1.0.0](docs/decisions/ADR-012-parallel-batch-orchestration-1.0.0.md)
- [Lock batch multipiattaforma](docs/decisions/ADR-013-cross-platform-batch-locking.md)
- [Freeze della proiezione sensoriale 1.0.0](docs/decisions/ADR-014-freeze-sensor-projection-1.0.0.md)
- [Materializzazione scenario-first di casa e sensori](docs/decisions/ADR-015-scenario-first-environment-materialization.md)
- [Audit di chiusura M5](docs/audits/milestone-5-closure.md)
- [Audit di chiusura M5.1](docs/audits/milestone-5.1-closure.md)
- [Audit di chiusura M6](docs/audits/milestone-6-closure.md)
- [Audit di chiusura M6.1](docs/audits/milestone-6.1-closure.md)
