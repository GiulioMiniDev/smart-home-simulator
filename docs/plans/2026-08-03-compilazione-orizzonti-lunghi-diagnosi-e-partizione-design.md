# Compilazione di orizzonti lunghi — diagnosi del blocco e soluzioni valutate

- Data dell'analisi: 2026-08-03
- Commit del simulatore durante l'analisi: `6195c8f1e1b9a1e50f48e762392a73a38b29e1b8`
- Stato: **diagnosi conclusa e verificata; soluzione 1 misurata e scartata; soluzione 2
  implementata e verificata (§11)**
- Ambito: percorso di ingestione di un `SimulationAuthoringBundle`, fase di compilazione CP-SAT

Questo documento registra un difetto di scalabilità del compilatore e le soluzioni candidate
valutate. La soluzione 1 (§6) è stata scartata; resta documentata perché le misure che la
accompagnano restano valide. La soluzione 2 (§8) è quella adottata. La §10 registra un rilievo
separato, emerso durante l'analisi, sulla natura del bundle stesso.

---

## 1. Il caso che ha rivelato il problema

Il bundle di authoring che innesca il difetto:

| | |
|---|---|
| file | `generated/meredith_merrino_8_months_simulation_bundle_fixed.json` |
| SHA-256 | `ca7918fda318680e5e239611dfaa7f53021850ba06f972f9bdf07f17d680ce68` |
| dimensione | 3 220 006 byte |
| `scenarioId` | `meredith-merrino-long-island-8-months-2026-2027` |
| `title` | Meredith Merrino eight-month smart-home routine |
| `schemaVersion` / `documentType` | `1.0.0` / `simulation_authoring_bundle` |
| finestra | `2026-08-03T00:00:00-04:00` → `2027-04-03T23:59:59-04:00` |
| fuso / seed | `America/New_York` / `1` |
| giorni | 244 |
| attività | 3 870 (di cui 0 opzionali) |
| residenti | 1 (`meredith`) |

Ambiente delle misure: Windows 11 Home, Python `3.12.13`, OR-Tools `9.15.6755`, il venv del
progetto, singolo worker come da politica congelata.

**Sintomo osservato dall'operatore:** caricando il bundle nel simulatore l'interfaccia resta
appesa a tempo indeterminato. Nessun errore, nessun report di ingestione, nessun avanzamento.

---

## 2. Localizzazione del blocco

La catena percorsa dal file è:

```
POST /api/homes/{home_id}/authoring-bundle     web/app.py:254
  └─ validate_authoring_file                   authoring/service.py:252
       └─ validate_authoring_payload           authoring/service.py:369
            └─ compile_payload                 compiler/service.py:71
                 └─ compile_scenario           compiler/service.py:90
                      └─ ScheduleSolver.solve  compiler/solver.py:306
```

Validazione JSON, schemi e cataloghi completano in meno di un secondo. Il tempo è **interamente**
dentro `ScheduleSolver.solve`. Stack catturato con `faulthandler.dump_traceback_later(150)`:

```
File "...\ortools\sat\python\cp_model.py", line 1771 in solve
File "...\src\smart_home_sim\compiler\solver.py", line 378 in _try_lock_value
File "...\src\smart_home_sim\compiler\solver.py", line 306 in solve
File "...\src\smart_home_sim\compiler\service.py", line 90 in compile_scenario
File "...\src\smart_home_sim\compiler\service.py", line 71 in compile_payload
File "...\src\smart_home_sim\authoring\service.py", line 369 in validate_authoring_payload
File "...\src\smart_home_sim\authoring\service.py", line 252 in validate_authoring_file
```

Il processo non è bloccato: sta lavorando. È una questione di ordine di grandezza, non di deadlock.

---

## 3. Causa: il costo della canonicalizzazione è quadratico

### 3.1 Cosa il compilatore sta deliberatamente facendo

[ADR-003](../decisions/ADR-003-freeze-plan-compiler-1.0.0.md) richiede un piano **unico e
riproducibile**, non semplicemente ottimo: se milioni di soluzioni sono equivalenti, quale CP-SAT
restituisca dipenderebbe dai suoi interni. L'ADR è esplicito sul prezzo pagato:

> The meaning of `OPTIMAL` is precise: globally optimal optional selection plus proven-feasible
> deterministic preference locking, not global minimum deviation.

L'unicità è ottenuta in [`solver.py:215-311`](../../src/smart_home_sim/compiler/solver.py) fissando
i valori uno alla volta in ordine deterministico:

- **fase A** — due stadi lessicografici (`optional_priority`, poi `optional_count`), ciascun ottimo
  congelato come vincolo rigido;
- **fase B** — per ogni attività, in ordine `(day_index, activity_index)`, e per ciascun campo
  preferenziale (`duration`, `start`, `end`), una chiamata a `_try_lock_value`.

`_try_lock_value` ([`solver.py:361-383`](../../src/smart_home_sim/compiler/solver.py)) pone una
domanda per volta — *"questa attività può stare esattamente all'orario preferito senza rendere
infattibile il resto?"* — e ogni domanda è **una risoluzione CP-SAT completa dell'intero modello**:

```python
lock = self.model.new_bool_var(f"lock__{name}")
self.model.add(variable == target).only_enforce_if(enforcement)
self.model.add_assumption(lock)
solver = self._new_solver()
status = solver.solve(self.model)          # risoluzione completa
self.model.add(lock == (1 if status == cp_model.OPTIMAL else 0))
```

La procedura è corretta e indipendente dalle euristiche del solver. Il suo costo, però, è una
risoluzione per ogni coppia (attività, campo).

### 3.2 La misura

Il numero di domande cresce linearmente nelle attività; la dimensione del modello su cui ogni
domanda è posta cresce anch'essa linearmente. Il lavoro totale è **quadratico**.

| | `mario_rossi_2026_10_30` | `meredith_merrino_8_months` |
|---|---|---|
| giorni | 3 | 244 |
| attività | 57 | 3 870 |
| variabili CP-SAT | 486 | **34 835** |
| vincoli CP-SAT | 688 | **49 829** |
| chiamate a `_try_lock_value` | ~170 | **7 740** |
| tempo per chiamata | ~20 ms | **~6,2 s** |
| **totale compilazione** | **3,4 s** | **~13 h (stimato)** |

Le 7 740 chiamate sono `duration` + `startWindow` per ciascuna delle 3 870 attività; nel bundle
non esiste alcun `endWindow`. Il tempo per chiamata è la media misurata su 60 chiamate reali
(372,7 s complessivi, strumentando `_try_lock_value`); non decresce apprezzabilmente col
progredire dei lock.

### 3.3 Il tempo non va nella ricerca

Log interno di CP-SAT su una singola chiamata (`log_search_progress = True`):

```
status: OPTIMAL
conflicts: 0
branches: 9986
lp_iterations: 12001
walltime: 6.19137
deterministic_time: 0.891578
integers: 19467
booleans: 9983
Lp dimension: 10532 rows, 19278 columns, 35667 entries
Starting presolve at 0.16s
```

`conflicts: 0` è il dato decisivo: **il problema non è difficile.** CP-SAT dimostra la fattibilità
di ogni lock praticamente senza backtracking. I 6,2 secondi sono overhead fisso di avviamento,
ripagato da zero ad ogni chiamata:

- l'API Python di `cp_model` non ha risoluzione incrementale — il modello da 35 k variabili viene
  riserializzato e ritrasmesso al solver C++ ad ogni `solve()`;
- il presolve rigira l'intera pipeline (`PresolveToFixPoint`, `Probe`,
  `DetectDuplicateConstraints`, `FindBigVerticalLinearOverlap`, …) per circa 2 s;
- il rilassamento lineare viene ricostruito e risolto da capo: 12 001 iterazioni di simplesso su
  una LP da 10 532 × 19 278.

In sintesi: non si attende la soluzione di un problema difficile, si paga 7 740 volte il
caricamento di un problema facile.

---

## 4. Perché non compare né errore né timeout

Tre fattori indipendenti si sommano:

1. `MAX_DETERMINISTIC_TIME = 2.0` ([`solver.py:17`](../../src/smart_home_sim/compiler/solver.py))
   limita la **singola** risoluzione. Il deterministic time misurato è `0.891578`, sotto soglia:
   la valvola non scatta mai. Ogni risoluzione presa da sola è "veloce"; è il loro numero il
   problema, e nessuno lo sorveglia.
2. Non esiste alcun budget globale sulla compilazione, né un limite sul numero di giorni o di
   attività accettati in ingresso.
3. L'endpoint è un `def` sincrono: FastAPI lo esegue nel threadpool, il server resta reattivo, ma
   quella richiesta HTTP non ritorna mai. Non c'è eccezione da propagare né avanzamento da
   mostrare — dall'esterno è indistinguibile da un blocco.

Il difetto è quindi doppio: **un costo quadratico** e **l'assenza di qualunque diagnostica che lo
renda visibile**. Il secondo va corretto a prescindere dalla strada scelta per il primo.

---

## 5. Struttura di accoppiamento dello scenario

Misure sul bundle, necessarie a valutare qualunque strategia di partizionamento.

**Dipendenze fra giorni diversi: nessuna.**

```
riferimenti in dependencyGroups: 3 626
di cui verso un altro giorno:        0
```

**Timestamp dichiarati fuori dal proprio giorno: nessuno.**

```
attività totali:                                  3 870
timestamp di finestra fuori dal giorno di appartenenza: 0
attività prive di finestre:                            0
```

**Ma le attività sforano la mezzanotte attraverso la durata.**

```
sforano con start preferito + durata preferita:  243
sforano nel caso peggiore (latest + maximum):    244
   2026-08-03_16_sleep  22:45  +435 min  ->  2026-08-04 06:00
```

Il sonno di ogni notte termina alle 06:00 del giorno successivo. Giorni consecutivi sono quindi
**realmente accoppiati** dal `no_overlap` per residente
([`solver.py:656`](../../src/smart_home_sim/compiler/solver.py)).

> **Conseguenza da non dimenticare.** Una decomposizione *per singolo giorno* non è valida a
> priori: spezzerebbe l'accoppiamento sonno → mattina successiva su tutti i 243 confini. La prima
> versione di questa analisi lo aveva erroneamente escluso avendo controllato solo i timestamp
> dichiarati e non `start + duration`.

**Contesa effettiva: quasi assente.** Su 14 giorni compilati:

```
schedulate all'orario preferito: 218 / 222
spostate:                          4
   2026-08-08_12_eat_dinner               20:55 -> 20:50
   2026-08-08_13_watch_evening_television  21:10 -> 21:15
   2026-08-15_12_eat_dinner               20:55 -> 20:50
   2026-08-15_13_watch_evening_television  21:10 -> 21:15
```

Il 98 % delle attività ottiene esattamente l'orario preferito e le uniche quattro contese sono
interne alla stessa serata. Coerente con `conflicts: 0`: non c'è arbitraggio reale in corso.

---

## 6. Soluzione candidata 1 — partizione della compilazione per gruppi di giorni

**Stato: misurata, non implementata, SCARTATA.** Superata dalla soluzione 2 (§8), che raggiunge
un tempo migliore senza partizionare il problema e con un argomento di equivalenza dimostrativo
anziché campionario. La sezione è conservata per le misure che contiene.

### 6.1 Idea

Dentro `compile_scenario`, spezzare i `records` in gruppi di giorni consecutivi, risolvere un
`ScheduleSolver` per gruppo condividendo la stessa `TimeAxis` costruita sullo scenario **intero**,
e fondere i `values` in un unico `SolveOutcome`. A valle nulla cambia: un solo piano canonico da
244 giorni, un solo digest, un solo bundle, una sola simulazione.

### 6.2 Vincolo implementativo scoperto in misura

La `simulationWindow` **non va ristretta al chunk**. Restringerla rende infattibile il sonno
dell'ultima notte, che deve poter terminare oltre la mezzanotte:

```
7 giorni + finestra troncata a mezzanotte     0,05 s   MAIN_PLAN_INFEASIBLE
7 giorni + finestra originale (8 mesi)        8,61 s   piano prodotto
```

Si tagliano i giorni e si lascia la finestra intatta. L'asse temporale resta lungo otto mesi, ma
è un semplice intervallo di interi e non incide sul costo.

### 6.3 Costo misurato

Tutti i tempi con finestra originale intatta:

| chunk | tempo per chunk | n° chunk su 244 gg | totale proiettato |
|---|---|---|---|
| 1 giorno | 0,26 s | 244 | ~1 min |
| 7 giorni | 8,61 s | 35 | **~5 min** |
| 14 giorni | 34,04 s | 18 | ~10 min |
| 244 giorni (attuale) | — | 1 | ~13 h |

Lo scaling quadratico è visibile: da 7 a 14 giorni il tempo passa da 8,61 s a 34,04 s (2× i
giorni, 4× il tempo). Chunk più piccoli sono quindi strettamente più veloci.

### 6.4 Verifica di equivalenza dell'output

Ground truth: 14 giorni compilati in un modello unico. Confronto su `scheduled_start` e
`scheduled_end` di ogni attività:

```
ground truth (giorni 0-13, modello unico)   222 attività   34,04 s
  split naive   [0:7] + [7:14]              222/222 coperte   DIVERSE = 0   17,32 s
  split overlap [0:8]→0-6 + [7:15]→7-13     222/222 coperte   DIVERSE = 0   36,78 s
```

Su questo scenario lo split naive riproduce il piano monolitico **al microsecondo**, ed è anche
2× più veloce del monolitico sugli stessi giorni.

### 6.5 Perché combacia, e il limite della garanzia

L'equivalenza non è casuale: come mostrato in §5, il 98 % delle attività ottiene il proprio valore
preferito e le uniche contese sono intra-giornaliere. Il ciclo di locking arriva quindi alla stessa
risposta indipendentemente dalla presenza dei giorni vicini nel modello, perché al confine non c'è
competizione da arbitrare.

**È un risultato empirico su questo scenario, non un teorema.** Uno scenario con contesa forte a
cavallo della mezzanotte — per esempio una risorsa satura fra il sonno e la mattina seguente —
potrebbe divergere al confine dei chunk. La variante *overlap* (compilare `[k, k+D+1]` e
conservare solo `[k, k+D]`) ricostruisce esattamente l'accoppiamento, perché l'unica dipendenza
fisica cross-day misurata è di un solo giorno; costa circa il doppio e nelle prove dà anch'essa
zero differenze.

### 6.6 Perché la partizione va dentro il compilatore e non sui dati

Spezzare il **bundle** in 35 ingestioni separate produrrebbe 35 run distinti. Il simulatore
inizializza lo stato una sola volta da `scenario.initialState`
([`simulation/service.py:285`](../../src/smart_home_sim/simulation/service.py)) e lo fa evolvere in
continuità sull'intera traccia. Lo scenario dichiara:

```json
"authoritativeStateSource": "scenario_initial_then_previous_execution",
"facts": { "fatigue": 0.45, "hunger": 0.2, "stress": 0.3,
           "socialNeed": 0.4, "medicationAvailableDoses": 0 }
```

Con run separati, `fatigue`, `stress`, `socialNeed` e le dosi di farmaco si azzererebbero ai
valori iniziali ad ogni confine, introducendo discontinuità artificiali proprio nelle variabili
che un dataset a otto mesi serve a studiare. Il concatenamento manuale via `finalState` è
possibile ma fragile: `ResidentFinalState` espone `region_id` + `position` mentre
`ResidentInitialState` richiede `location_id`, e lo stato delle entità risiede nell'home model,
non nello scenario.

### 6.7 Implicazione formale

[ADR-003](../decisions/ADR-003-freeze-plan-compiler-1.0.0.md) stabilisce:

> A solver upgrade or changed tie-break policy requires an explicit compiler-version decision and
> regenerated golden plans.

La partizione non modifica la politica di tie-break, ma cambia l'insieme su cui viene applicata e
può quindi alterarne l'esito nei casi contesi al confine. La strada corretta sarebbe: bump
esplicito di `compilerVersion`, un ADR che documenti la partizione e la soglia di attivazione,
golden plan rigenerati. L'equivalenza al bit misurata in §6.4 è evidenza da riportare in
quell'ADR, non motivo per saltarlo.

---

## 7. Intervento indipendente dalla soluzione scelta

Serve un budget globale sulla compilazione — tetto sul numero complessivo di lock o sul tempo
totale — che produca un issue leggibile (per esempio `COMPILATION_BUDGET_EXCEEDED`) invece di
lasciare la richiesta HTTP appesa per ore. Va accompagnato da un avanzamento osservabile sulla
fase di compilazione. Questo va fatto **qualunque** sia la strategia adottata per il costo
quadratico: oggi l'unico sintomo di un carico fuori scala è il silenzio.

---

## 8. Soluzione 2 — parametri di fattibilità corretti e locking a lotti con nuclei di conflitto

**Stato: misurata, verificata, APPROVATA per l'implementazione.**

### 8.1 L'osservazione che la rende possibile

In [`_try_lock_value`](../../src/smart_home_sim/compiler/solver.py) il risultato delle 7 740
risoluzioni viene usato **solo** attraverso `status`:

```python
status = solver.solve(self.model)
self.model.clear_assumptions()
self.model.add(lock == (1 if status == cp_model.OPTIMAL else 0))
if presence is None and status == cp_model.INFEASIBLE:
    self.model.add(variable != target)
return status, solver
```

I valori trovati sono scartati: l'unica risoluzione che produce il piano è quella finale. Ne
segue che i **parametri del solver usati per le verifiche di fattibilità non entrano
nell'output** — SAT/UNSAT è un fatto matematico, non una scelta euristica. Possono essere
scelti liberamente.

### 8.2 Leva A — il rilassamento lineare è controproducente

Con `conflicts: 0` non c'è ricerca da guidare: la LP da 10 532 × 19 278 righe viene costruita e
risolta (12 001 iterazioni di simplesso) ad ogni chiamata senza essere mai sfruttata. Misure su
una singola verifica di lock del modello a 244 giorni:

| configurazione | esito | tempo | deterministic time |
|---|---|---|---|
| attuale (baseline) | **UNKNOWN** | 17,798 s | 2,000 (cap saturato) |
| `linearization_level=0` | OPTIMAL | 3,026 s | 0,467 |
| `linearization_level=0` + `cp_model_probing_level=0` | OPTIMAL | **2,202 s** | 0,466 |
| `cp_model_presolve=False` | UNKNOWN | 23,439 s | 2,003 |
| `linearization_level=0` + presolve off | OPTIMAL | 9,766 s | 0,022 |

> **Difetto latente rilevato qui.** Il baseline restituisce `UNKNOWN` saturando
> `max_deterministic_time`. In `solve()` uno stato diverso da `OPTIMAL` e `INFEASIBLE` fa
> abortire la compilazione con `not_optimal`: la compilazione monolitica può quindi **fallire**
> dopo ore, non soltanto essere lenta. La configurazione corretta risponde in modo conclusivo
> in 2,2 s.

La sola leva A porta da ~13 h a ~4,7 h: il costo si stabilizza a 2,17 s per lock e **non** cala
accumulando lock (misurato sui primi 200 lock del ciclo reale). Insufficiente da sola.

### 8.3 Leva B — una domanda per lotto invece di una per preferenza

Tutte le preferenze vengono imposte simultaneamente come assunzioni e si risolve una volta sola.

- **SAT** → tutte bloccabili. È dimostrabile che il ciclo sequenziale avrebbe prodotto lo stesso
  insieme: se l'insieme completo è fattibile, per induzione ogni passo del ciclo trova il proprio
  target fattibile a maggior ragione, avendo meno vincoli attivi.
- **UNSAT** → CP-SAT restituisce un nucleo di conflitto sufficiente. Se il nucleo è `{p}`, allora
  `base ∧ p` è insoddisfacibile: `p` è infattibile **di per sé**, dunque il ciclo sequenziale la
  respinge comunque, qualunque cosa sia bloccata quando vi arriva. La si scarta e si ripete.
  Nota: scartare una preferenza a nucleo unitario non altera i confronti successivi, perché la
  negazione di `p` era già implicata dal modello.
- **nucleo di dimensione > 1** → l'ordine di precedenza torna a contare e il lotto non può
  deciderlo. Si ricade sul ciclo sequenziale originale limitato alle preferenze ancora indecise,
  che è esatto per definizione.

### 8.4 Costo misurato — orizzonte completo, 244 giorni

```
setup 3.5s | preferenze 7740
iter   1: INFEASIBLE 2.18s core=1 scarta start__2026-08-08_12_eat_dinner
iter   2: INFEASIBLE 2.30s core=1 scarta start__2026-08-08_13_watch_evening_television
...
iter  70: INFEASIBLE 2.10s core=1 scarta start__2027-04-03_13_watch_evening_television
iter  71: SAT in 2.53s -> tutte le 7670 preferenze restanti bloccabili
solve finale: OPTIMAL in 0.72s
TOTALE 162.4s = 2.71 min | iterazioni 71 | respinte 70 | dimensioni core [1]
```

**Tutti i 70 nuclei sono unitari**: il ramo di riserva non è mai stato necessario e l'equivalenza
è garantita per dimostrazione su ogni singola decisione presa.

| | compilatore attuale | soluzione 2 |
|---|---|---|
| 244 giorni | ~13 h (stimato) | **162,4 s** |
| 14 giorni | 36,10 s (misurato) | **0,60 s** (misurato) |
| risoluzioni CP-SAT | 7 740 | **71** |

### 8.5 Verifica di equivalenza dell'output

Confronto su 14 giorni fra il compilatore attuale invariato e la soluzione 2, su
`scheduled_start` e `scheduled_end` di ogni attività:

```
compilo ground truth con il compilatore ATTUALE, invariato...
  222 attivita in 36.10s
attivita confrontate: 222/222   DIVERSE: 0
```

Anche l'insieme delle preferenze respinte coincide: `eat_dinner` e `watch_evening_television`
dell'8 e del 15 agosto, cioè esattamente le quattro attività che il compilatore attuale sposta.

### 8.6 Perché è preferibile alla soluzione 1

- **Non partiziona il problema**: un solo modello, un solo piano, una sola simulazione. Nessuna
  questione di continuità dello stato (§6.6), nessun confine artificiale.
- **L'equivalenza è dimostrativa, non campionaria.** La soluzione 1 poggiava su un confronto
  empirico su 14 giorni; qui ogni decisione è giustificata (ramo SAT per induzione, ramo a nucleo
  unitario per indipendenza dall'ordine) ed è **verificabile a runtime** con un controllo su
  `len(core) == 1`.
- **Impatto ADR-003 più lieve**: i parametri delle verifiche di fattibilità non entrano
  nell'output e la procedura a lotti produce lo stesso insieme di lock. Un bump esplicito di
  `compilerVersion` con golden plan rigenerati resta dovuto, ma può appoggiarsi a una
  dimostrazione anziché a un campione.

### 8.7 Note implementative

- Il **solve finale** resta sui parametri congelati di `_new_solver()`: è l'unico che determina i
  valori del piano. Nelle misure sopra usava i parametri modificati e l'output coincideva
  ugualmente, ma non c'è ragione di assumere quel rischio per 0,7 s.
- Anche gli **stadi lessicografici** restano sui parametri congelati: leggono
  `solver.value(variable)` e concorrono quindi all'output.
- I parametri modificati si applicano **solo** alle verifiche di fattibilità.

### 8.8 Sulla parallelizzazione, valutata e scartata

- Il ciclo di locking è **intrinsecamente sequenziale**: ogni lock modifica il modello su cui si
  pone la domanda successiva.
- `num_search_workers > 1` non aiuterebbe comunque: con `conflicts: 0` non c'è ricerca da
  distribuire e ogni worker ripeterebbe presolve e LP. ADR-003 congela inoltre le impostazioni
  deterministiche a singolo worker.
- La parallelizzazione per chunk richiederebbe i chunk, cioè la soluzione 1.

A 162 secondi la questione non si pone.

---

## 9. Riproduzione delle misure

Tutte le misure sono state ottenute da script temporanei sopra il venv del progetto, senza
modificare il codice sorgente:

- **localizzazione del blocco** — `faulthandler.dump_traceback_later(150, exit=True)` attorno a
  `validate_authoring_file` sul bundle;
- **dimensione del modello** — patch di `ScheduleSolver._try_lock_value` che alla prima chiamata
  legge `len(self.model.proto.variables)` e `len(self.model.proto.constraints)`;
- **costo per chiamata** — stessa patch, cronometrando le prime 60 chiamate;
- **profilo interno del solver** — ricostruzione della singola chiamata con
  `log_search_progress = True` e `log_callback`;
- **tempi per chunk ed equivalenza** — slicing di `scenario["days"]` con `simulationWindow`
  invariata, `compile_scenario` diretto, confronto di `(scheduled_start, scheduled_end)` per
  `source_activity_id` fra piano monolitico e piani partizionati.

Il bundle analizzato non è tracciato da git al momento dell'analisi (`?? generated/…`); il suo
SHA-256 è riportato in §1 per riferimento.

Per la soluzione 2 si aggiungono:

- **parametri** — ricostruzione di una singola verifica di lock sul modello a 244 giorni,
  variando `linearization_level`, `cp_model_probing_level`, `symmetry_level`,
  `cp_model_presolve`;
- **traiettoria del ciclo corretto** — sostituzione di `ScheduleSolver._new_solver` con la
  configurazione di fattibilità e cronometraggio dei primi 200 lock del ciclo reale;
- **algoritmo a lotti** — riproduzione fuori dal sorgente di `solve()` fino agli stadi
  lessicografici, poi ciclo assunzioni → `sufficient_assumptions_for_infeasibility()` → scarto,
  con registrazione di dimensione dei nuclei, iterazioni e tempi;
- **equivalenza** — `compile_scenario` invariato su 14 giorni come riferimento, confronto per
  `source_activity_id` dopo conversione dei tick con `TimeAxis.to_datetime`.

---

## 10. Rilievo separato — il bundle non contiene otto mesi di informazione

Emerso durante l'analisi, **non riguarda il compilatore** ed è registrato qui perché condiziona
l'interpretazione di qualunque dataset generato da questo bundle.

I 244 giorni sono sette modelli di giornata ripetuti:

```
giorni totali:                244
firme giornaliere DISTINTE:     8

  Monday    -> modello 1     (35 occorrenze identiche)
  Tuesday   -> modello 2     (35)
  Wednesday -> modello 3     (35)
  Thursday  -> modello 4     (35)
  Friday    -> modello 5     (35)
  Saturday  -> modelli 6, 8  (34 + 1, l'ultimo giorno è troncato)
  Sunday    -> modello 7     (34)
```

La firma confronta, per ogni attività del giorno, `intent`, orario preferito di inizio e durata
preferita. Ogni lunedì è identico a ogni altro lunedì al secondo; il sonno dura sempre 435 minuti
esatti.

La tolleranza è una costante universale:

```
ampiezza delle finestre (latest - earliest):
    12 min : 3 870 attività su 3 870
```

**Le variabili di stato dichiarate non sono mai usate.** Lo scenario dichiara in `initialState`
`fatigue`, `hunger`, `stress`, `socialNeed`, `medicationAvailableDoses`, `foodInventory`, ma:

```
precondizioni sulle attività:   0
effetti sulle attività:         0
occorrenze di quei nomi nel personalProcessPackage: 0 per ciascuno
```

Nessuna di esse viene mai né letta né scritta. Non esiste accumulo di stanchezza, debito di sonno
o retroazione fra stato interno e comportamento.

**Non esiste aleatorietà a runtime.** `runtimeEventCandidates` e `commitments` sono entrambe
vuote; l'unica sorgente di casualità del simulatore
([`simulation/service.py:628`](../../src/smart_home_sim/simulation/service.py)) è alimentata dagli
eventi runtime, quindi il `seed` non ha su cosa agire.

**Conseguenze.**

- Il dataset a otto mesi contiene l'informazione di sette giorni ripetuta 35 volte.
- Le uniche 70 deviazioni dell'intero orizzonte sono le sovrapposizioni cena/TV del sabato
  descritte in §5: un artefatto di un modello di giornata sovrappopolato, non un comportamento.
- Ciò spiega anche `conflicts: 0` (§3.3): non c'è contesa reale da arbitrare in nessun punto
  dell'orizzonte.
- Il collo di bottiglia per uno studio di abitudini, deriva o anomalie non è il compilatore ma il
  generatore che ha prodotto il bundle.

Il difetto di scalabilità resta reale e la soluzione 2 resta necessaria: diventerà anzi più
rilevante quando i giorni saranno effettivamente diversi fra loro, perché la contesa aumenterà.

---

## 11. Implementazione applicata

Modifiche in [`compiler/solver.py`](../../src/smart_home_sim/compiler/solver.py), nessun altro
file toccato:

- **`LockRequest`** — dataclass che descrive un tentativo di fissaggio della politica
  `priority-preference-1.0.0`.
- **`_new_feasibility_solver()`** — deriva da `_new_solver()` azzerando `linearization_level` e
  `cp_model_probing_level`. Usato **solo** dalle sonde di fattibilità.
- **`_declare_lock()` / `_decide_lock()`** — sostituiscono `_try_lock_value()`, separando la
  dichiarazione del letterale dalla decisione, così che il ramo a lotti e quello sequenziale
  condividano lo stesso letterale invece di duplicarlo.
- **`_lock_requests()`** — ciclo a lotti con nuclei di conflitto e ramo di riserva.
- **`_lock_sequentially()`** — ramo di riserva esatto, invocato solo su nuclei non unitari.
- I due cicli in `solve()` sono ora costruzioni di `LockRequest` seguite da una chiamata a
  `_lock_requests()`. Gli stadi lessicografici e il solve finale restano su `_new_solver()`.

I nomi dei letterali (`lock__canonical_optional__…`, `lock__preferred_start__…`) sono invariati.

### Verifica

| controllo | esito |
|---|---|
| `ruff check` sul file modificato | All checks passed |
| `pytest tests/test_compiler.py` | 16 passed |
| `pytest tests/` (suite completa) | 647 passed |
| equivalenza output su 14 giorni | **222/222 attività identiche, 0 differenze** |
| `validate_authoring_file` sul bundle a 244 giorni | **274,0 s** — `valido: True`, 0 errori, 0 warning |

Digest del piano canonico prodotto per il bundle di §1:
`8e5c6a8165c99f5a1fbcb86e5e078117a9628f5b4b13360f2eac13d4d05d87b0`.

La catena di equivalenza è: implementazione → prototipo (§8.5) → compilatore originale, ciascun
anello verificato su 14 giorni con confronto per `source_activity_id` su `scheduled_start` e
`scheduled_end`.

I 274 s end-to-end comprendono l'intera ingestione (validazione JSON, compilazione, validazione
comportamentale, precondizioni deterministiche, contingenze) contro i 162 s della sola
compilazione misurata in §8.4.

### Non fatto

- **Budget globale di compilazione** (§7): non implementato. Resta necessario perché una
  compilazione fuori scala continua a non emettere alcun segnale.
- **Bump di `compilerVersion` e ADR** (§8.6): non effettuato. Dovuto prima di considerare
  chiusa la modifica rispetto ad ADR-003, con golden plan rigenerati.
- **Ramo di riserva non esercitato**: `_lock_sequentially()` non è coperto da alcun test, perché
  nessuno scenario disponibile produce un nucleo di conflitto non unitario. Serve un caso di
  prova costruito ad arte con due preferenze mutuamente esclusive ma singolarmente fattibili.
