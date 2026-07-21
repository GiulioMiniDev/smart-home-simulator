# Review del prompt semplificato 1.2.0 per LLM locali

> **Nota storica:** questo documento descrive il primo trial rifiutato del commit `6dc5d1b`.
> La successiva prova settimanale valida e i suoi limiti qualitativi sono documentati in
> [`esperimento_simulazione_7giorni_mario_rossi.md`](esperimento_simulazione_7giorni_mario_rossi.md).

- Data della review: 2026-07-21
- Commit esaminato: `6dc5d1b` (`Simplified prompt + local llm model generation (qwen 7b)`)
- Prompt esaminato: `prompts/generate-simulation-inputs-1.2.0-simplified.md`
- Risposta esaminata:
  `generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/failed-trials/marco-2024-invalid.authoring-bundle.json`
- Modello dichiarato nella risposta: `qwen2.5-coder`
- Stato complessivo: **non accettato; la simulazione non può ancora partire da questa risposta**

## Decisione di scope: si modifica soltanto il prompt

Questa iterazione è un'attività di **prompt engineering**, non una modifica del simulatore.
Il simulatore, i suoi contratti e i suoi gate deterministici sono il riferimento autorevole
contro cui valutare l'output dell'LLM.

Per correggere gli errori descritti in questo documento è autorizzata esclusivamente la
modifica di:

- `prompts/generate-simulation-inputs-1.2.0-simplified.md`, oppure di una sua nuova versione
  esplicitamente identificata, per esempio
  `prompts/generate-simulation-inputs-1.2.1-local-small.md`.

La documentazione di valutazione e gli output sperimentali possono essere aggiornati o
rigenerati per registrare nuove prove, ma non costituiscono una correzione del simulatore.

### Codice e contratti che non devono essere modificati

Non devono essere modificati per fare accettare l'output del piccolo LLM:

- `src/smart_home_sim/**`;
- `src/smart_home_sim/domain/**` e i relativi modelli Pydantic;
- `src/smart_home_sim/authoring/**` e il gate di ingestion;
- `src/smart_home_sim/validation/**`;
- `src/smart_home_sim/compiler/**`;
- `src/smart_home_sim/behavior/**`;
- `src/smart_home_sim/environment/**`;
- `src/smart_home_sim/materialization/**`;
- `src/smart_home_sim/simulation/**`;
- `src/smart_home_sim/sensors/**`;
- `src/smart_home_sim/cli.py`;
- `schemas/**` e i relativi checksum;
- `src/smart_home_sim/catalogs/**`;
- i test esistenti in `tests/**`;
- il prompt completo di riferimento `prompts/generate-simulation-inputs-1.2.0.md`.

In particolare, non bisogna:

- allentare la validazione comportamentale;
- aggiungere action type inventati dall'LLM ai cataloghi;
- rendere opzionali i nodi finali o il movimento nei process model;
- indebolire il controllo fra componenti semantici e sequenze di azioni;
- disabilitare errori, trasformarli in warning o modificare i test per farli passare;
- correggere manualmente il bundle Marco rifiutato in `failed-trials/` e presentarlo come nuova
  generazione del modello.

L'output deve adattarsi al contratto congelato, non il contratto all'output del modello.

## Gate che una generazione deve superare

Il solo parsing JSON o il solo caricamento Pydantic non dimostrano che la simulazione possa
partire. Una risposta è accettata soltanto se supera, nell'ordine, tutti i gate seguenti.

### Gate 0 — Formato della risposta

- La risposta contiene un solo oggetto JSON.
- Non contiene Markdown, commenti o testo esterno al JSON.
- Il JSON è sintatticamente valido e completo, senza troncamenti.

### Gate 1 — Contratto `SimulationAuthoringBundle`

- Il documento ha esattamente l'envelope previsto.
- `scenario` e `personalProcessPackage` rispettano i modelli Pydantic e gli schemi congelati.
- Non sono presenti proprietà sconosciute.
- Versioni, document type, riferimenti e provenance sono coerenti e veritieri.

### Gate 2 — Validazione dello scenario

- Residenti, location, risorse e riferimenti esistono.
- Date e timestamp appartengono alla simulation window e usano la timezone corretta.
- Ogni attività usa un intent del catalogo.
- Finestre temporali, durate, dipendenze, fallback, capacità e sovrapposizioni sono valide.
- Tutti i giorni richiesti sono coperti.

### Gate 3 — Compilazione del piano

- Il solver trova un piano temporale completo.
- Non esistono conflitti temporali o dipendenze impossibili.
- Non vengono perse attività obbligatorie.
- Il canonical plan viene prodotto senza errori.

### Gate 4 — Validazione comportamentale

- Ogni attività dello scenario risolve a **esattamente un binding** applicabile.
- `implementedComponents` coincide, nello stesso ordine, con i componenti dell'intent.
- Ogni componente è realizzato tramite la sequenza di action type richiesta dal catalogo.
- Ogni action type appartiene al catalogo delle azioni.
- Ogni azione contiene tutti e soli gli argomenti richiesti.
- Ogni argomento usa una `ValueExpression` compatibile con tipo e `referenceKind`.
- Ogni process model ha esattamente uno `start` e almeno un `end`.
- Non esistono nodi morti; ogni nodo appartiene a un percorso da `start` a `end`.
- Gradi dei nodi, choice, loop e archi sono validi.
- Ogni process model contiene almeno un'azione esplicita di movimento fra `move_to`,
  `move_to_capability` e `travel_to`.
- Ogni nodo action ha un `durationWeight` positivo.

### Gate 5 — Ingestion atomica

Il comando autorevole è:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  generated/risposta-llm.authoring-bundle.json \
  --output-dir generated/risposta-llm_ingested \
  --format json \
  --report-output generated/risposta-llm.ingestion-report.json
```

Condizioni di successo:

- exit code `0`;
- `valid: true`;
- `errorCount: 0`;
- zero errori scenario, compilation e behavior;
- pubblicazione atomica di `scenario.json` e `personal-process-package.json`.

Se il comando termina con exit code `1` o non pubblica i due artefatti, la risposta non è
eseguibile e non deve essere descritta come simulazione valida.

### Gate 6 — Materializzazione ed esecuzione end-to-end

Dopo l'ingestion, i due input devono completare:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim run-synthetic \
  generated/risposta-llm_ingested/scenario.json \
  generated/risposta-llm_ingested/personal-process-package.json \
  --output-dir generated/risposta-llm_simulation
```

Il gate finale richiede la pubblicazione del workspace completo: piano, casa, binding,
simulation bundle, execution trace, simulation report, sensori, observable sensor log,
oracle mapping e manifest verificato. Solo dopo questo passaggio è corretto affermare che
la simulazione è partita.

## Risultato effettivo della generazione Qwen

L'esecuzione del gate ufficiale sul bundle Marco rifiutato conservato in `failed-trials/` ha
prodotto:

| Controllo | Risultato |
|---|---:|
| Sintassi JSON | superato |
| Parsing Pydantic del bundle | superato |
| Errori scenario | 0 |
| Errori di compilazione | 0 |
| Errori comportamentali | 64 |
| Artefatti pubblicati | 0 |
| Simulazione avviabile | no |

Distribuzione dei 64 errori:

| Codice | Quantità |
|---|---:|
| `GRAPH_NODE_DEAD` | 18 |
| `UNKNOWN_ACTION_TYPE` | 9 |
| `PROCESS_MOVEMENT_MISSING` | 9 |
| `PROCESS_COMPONENT_MISMATCH` | 9 |
| `INVALID_GRAPH_DEGREE` | 9 |
| `GRAPH_END_INVALID` | 9 |
| `MISSING_PROCESS_BINDING` | 1 |

La guida `docs/llm_local_authoring_guide.md` non deve quindi dichiarare che questo bundle è
"100% valido e compilabile" o "pronto per essere eseguito". Il parsing strutturale è
passato, ma il contratto comportamentale e l'ingestion atomica sono falliti.

## Criticità del prompt semplificato

### 1. Assenza del mapping componenti → azioni

Il prompt elenca:

- gli intent e i rispettivi componenti;
- gli action type autorizzati.

Non fornisce però la relazione determinante fra ciascun componente e la sequenza ordinata
di azioni che lo realizza. Il modello ha quindi usato nomi astratti come `wake_up`,
`morning_toilet_and_shower`, `work_shift` ed `eat_dinner` direttamente come `actionType`.
Questi valori sono intent o componenti, non azioni primitive autorizzate.

Correzione richiesta nel solo prompt:

- includere una tabella compatta `componentId -> requiredActionTypes` derivata dal catalogo;
- dichiarare esplicitamente che intent, component e action type sono tre livelli diversi;
- includere almeno un esempio positivo e uno negativo.

### 2. Requisiti del grafo incompleti

L'interfaccia TypeScript ammette `start` ed `end`, ma non ordina al modello di costruire un
grafo terminante. Tutti i nove modelli generati hanno uno `start`, una action e nessun nodo
`end`.

Correzione richiesta nel solo prompt:

- esigere esattamente uno `start` e almeno un `end`;
- esigere che ogni action abbia archi in ingresso e uscita validi;
- vietare nodi morti;
- fornire lo scheletro minimo `start -> movement -> component actions -> end`.

### 3. Movimento obbligatorio omesso

Il validatore richiede movimento esplicito in ogni process model, comprese attività
apparentemente stazionarie come sveglia, sonno, lettura e chiamate. Questa regola è presente
nel prompt completo, ma non nel prompt semplificato.

Correzione richiesta nel solo prompt:

- rendere tassativa la presenza di `move_to`, `move_to_capability` o `travel_to`;
- mostrare un esempio che usa `activity_location` con indice valido.

### 4. Copertura dei binding non resa tassativa

L'attività `read_in_bed` del secondo giorno non ha alcun binding. Il prompt descrive la
struttura dei binding, ma non impone chiaramente la copertura completa di tutte le attività
di tutti i giorni.

Correzione richiesta nel solo prompt:

- aggiungere il controllo finale: insieme degli `(actorId, intent)` usati nelle attività
  completamente coperto dai binding;
- richiedere esattamente un binding applicabile per attività;
- ricordare di controllare anche attività condizionali e fallback.

### 5. Compatibilità degli argomenti troppo sintetica

Il prompt richiede correttamente oggetti `ValueExpression`, ma non conserva tutta la matrice
fra `source`, `referenceKind`, tipo, allowed values e riferimenti dichiarati. Questo rischia
di reintrodurre gli errori già osservati nelle prove del prompt 1.1.0.

Correzione richiesta nel solo prompt:

- includere la matrice compatta di compatibilità;
- vietare `activity_resource` per capability ed environment entity;
- imporre gli `allowedValues` del catalogo;
- richiedere ruoli simbolici stabili per lo stesso oggetto lungo take/use/put o
  open/activate/deactivate/close.

### 6. Self-check finale insufficiente

Le regole finali si concentrano su `durationWeight`, `startWindow`, `duration` e forma delle
ValueExpression, ma non chiedono al modello di verificare copertura, grafo, movimento e
sequenze dei componenti.

Correzione richiesta nel solo prompt:

- aggiungere una checklist breve ma completa corrispondente ai gate del validatore;
- ordinare al modello di correggere internamente ogni violazione prima di restituire il
  JSON;
- ribadire che il solo rispetto dell'interfaccia TypeScript non è sufficiente.

## Criticità qualitative dell'output generato

Anche dopo il superamento dei contratti formali, il contenuto deve essere valutato per
plausibilità e fedeltà al caso descritto.

Problemi osservati:

- il filename contiene `2026`, ma la simulation window è nel 2024;
- `generatedAt` è nel 2023, precedente sia allo scenario sia alla prova;
- il modello dichiarato non identifica variante, dimensione e quantizzazione effettive;
- entrambe le attività di sonno hanno durata preferita di 90 minuti;
- non è presente il pranzo in nessuna delle due giornate lavorative;
- cambio vestiti e snack precedono immediatamente preparazione e consumo della colazione;
- i process model sono astrazioni di una sola azione anziché sequenze osservabili;
- non è conservata la descrizione sorgente usata per generare Marco;
- non sono conservati temperatura, seed, context length, max tokens, quantizzazione e
  versione esatta del modello;
- senza la richiesta sorgente non è verificabile la fedeltà della risposta alle
  caratteristiche della persona.

Il prompt deve chiedere timestamp veritieri, coerenza fra date e identificatori, durate
umane plausibili e una routine completa. Non deve però codificare valori specifici per
Marco: la correzione deve restare generale e riutilizzabile.

## Criticità di documentazione e riproducibilità

### Script documentati ma assenti

`docs/llm_local_authoring_guide.md` dichiara come integrati:

- `tools/build_simplified_prompt.py`;
- `tools/auto_generate_and_repair.py`;
- `tools/batch_generate_year.py`.

I tre script non sono presenti nel commit esaminato. Non bisogna presentarli come tooling
disponibile né usare come risultato verificato tempi e capacità annuali che dipendono da
essi.

Questa criticità documentale non autorizza a introdurre nuovo codice durante la correzione
del prompt. La guida deve descrivere soltanto ciò che è realmente presente e testato.

### Percentuale di riduzione imprecisa

Le dimensioni effettive sono:

- prompt completo: 102.717 byte;
- prompt semplificato: 16.722 byte.

La riduzione per byte è circa `83,7%`, non `90%`. Un'eventuale riduzione in token deve
essere misurata dichiarando tokenizer e modello, non dedotta dalla dimensione in KB.

### Workflow non collegato al README e ai test

- Il README continua a raccomandare solo `generate-simulation-inputs-1.2.0.md`.
- Non esiste un test di consistenza per il prompt semplificato.
- Non esiste un target Makefile dedicato.
- Il test attuale del prompt 1.2.0 verifica esclusivamente la versione completa.

Poiché lo scope corrente consente solo modifiche al prompt, questi punti vanno registrati
come lavoro successivo e non risolti alterando codice o test in questa iterazione.

### Provenance ambigua

Il prompt semplificato continua a imporre:

```json
"promptTemplateVersion": "generate-simulation-inputs-1.2.0"
```

In questo modo non è possibile distinguere output prodotti dal prompt completo e dal prompt
semplificato. La nuova versione del prompt deve usare un identificatore univoco e coerente
nel filename, nella provenance, nella guida e negli output sperimentali.

## Organizzazione consigliata degli artefatti

Il prompt appartiene correttamente a `prompts/`. Il report della prova appartiene invece a
`docs/evaluation/`, insieme alle valutazioni 1.0.0 e 1.1.0.

Una struttura riproducibile per le prove future è:

```text
prompts/generate-simulation-inputs-1.2.1-local-small.md
docs/evaluation/authoring-prompt-1.2.1-local-qwen2.5-7b.md
generated/experiments/qwen2.5-coder-7b/marco/
  case-description.md
  response.authoring-bundle.json
  ingestion-report.json
  generation-metadata.json
```

Un output rifiutato non deve avere un nome che lo faccia sembrare un artefatto canonico.
Deve essere accompagnato dal relativo ingestion report e chiaramente marcato come trial
fallito.

## Criteri di accettazione della prossima versione del prompt

La revisione del prompt è conclusa soltanto quando una nuova risposta non modificata a mano:

1. è prodotta da un LLM locale 7B–8B usando il solo prompt distribuito e la descrizione del
   caso;
2. viene salvata integralmente insieme a richiesta e metadata di generazione;
3. passa JSON e contratto Pydantic;
4. produce zero errori di scenario;
5. produce zero errori di compilazione;
6. produce zero errori comportamentali;
7. pubblica atomicamente scenario e personal process package;
8. completa `run-synthetic` e pubblica il workspace verificato;
9. genera una routine temporalmente e semanticamente plausibile;
10. supera almeno più prove indipendenti, non un singolo caso fortunato.

Il target consigliato per dichiarare robusto il prompt è una piccola matrice di valutazione
con più persone, finestre temporali e seed, riportando per ogni prova first-pass success,
numero di repair attempt, categorie di errore e risultato end-to-end.

## Stato del repository al momento della review

Il controllo generale del progetto ha dato esito positivo:

- 416 test superati;
- coverage totale `95,12%`;
- lint e format check superati;
- validazioni, compilazioni, simulazione golden e benchmark superati.

Questo conferma che non esiste evidenza di un difetto nel simulatore da correggere. Il
fallimento è circoscritto alle istruzioni del prompt semplificato e alla risposta prodotta
dal modello locale. La prossima attività deve quindi intervenire esclusivamente sul prompt.
