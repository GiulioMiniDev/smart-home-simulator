# Ground truth misurata sull'esecuzione, e partecipanti che si muovono davvero — piano

- Data: 2026-09-12
- Stato: **implementato** il 2026-09-12, con le due decisioni della §5 approvate
  (`participantIds` su `ActivityExecution`, degradazione accesa di default). Emerso durante la
  verifica e non risolto qui: due residenti che usano lo stesso apparecchio nello stesso istante
  fanno fallire la simulazione (vedi le conseguenze di ADR-026).
- Segue [2026-09-09-orizzonte-multi-residente-design.md](2026-09-09-orizzonte-multi-residente-design.md)
  e [ADR-026](../decisions/ADR-026-the-household-as-the-subject-of-an-outline.md).

---

## 1. Cosa è stato deciso

Requisito: **la ground truth deve essere vera al 100%.** Non si ottiene comprimendo o facendo
fallire i giorni scomodi, ma misurando ciò che è successo davvero.

1. **Le bande dichiarate** (finestre, giorni, attività attese) restano come sono. Vengono
   dall'outline e sono vere per definizione, perché sono la dichiarazione dell'autore.
2. **Tutto ciò che è misurato** si calcola sulla **traccia di esecuzione**, al momento dell'export:
   composizione, finestra effettiva, dominante, quota non attribuita, quota di ambiguità,
   co-presenza, episodi condivisi.
3. **Gli avvisi di authoring** restano calcolati sul piano espanso, subito dopo l'import, ma
   dichiarati come controlli sul piano. Non vengono più pubblicati come ground truth.

Fino a oggi quella parte era misurata sul piano espanso, prima della compilazione. Usava orari e
durate *preferiti*, contava riempitivi e visite in bagno che il motore può rifiutare, e non vedeva
né le scelte del compilatore né le deviazioni a runtime. È una verità pianificata, e il contratto
lo diceva, ma non soddisfa il requisito.

---

## 2. Cosa è emerso verificando: il motore esegue un corpo solo per attività

Prima di spostare la misura sulla traccia bisognava sapere se la traccia di una casa condivisa è
vera. **Non lo è ancora.**

- `simulation/service.py` non legge mai `participantIds`. `_activity_process` prende il lock del
  solo `actorId`, muove solo quel corpo e registra un `ActivityExecution` con un solo attore.
- In una cena condivisa quindi **siede a tavola solo chi la ospita**. L'altro residente ha quel
  tratto libero nel piano, perché il compilatore l'ha occupato per entrambi, ma nella simulazione
  il suo corpo resta dov'era.
- Conseguenze a valle: il log sensori non vede due corpi a cena, la fusione dei pulse PIR non scatta
  sulle attività condivise, e la co-presenza misurata sulla traccia verrebbe quasi nulla.
- C'è anche una scorciatoia minore: le precondizioni degli eventi runtime sono valutate sul primo
  residente (`next(iter(self.state.residents))`, riga 1204).

La verifica dell'implementazione multi-residente si era fermata alla compilazione (30 giorni,
OPTIMAL). La simulazione di una casa condivisa non era mai stata eseguita.

Misurare sulla traccia senza correggere questo misurerebbe fedelmente una convivenza falsa. **Il
motore viene prima.**

Le altre scorciatoie «primo residente» trovate sono innocue: la validazione delle variabili di
scope giornaliero in `behavior/service.py:568` non dipende dal residente, e il percorso di prova in
`materialization/service.py:1829` serve a tarare il deployment dei sensori.

---

## 3. Le fasi

### Fase 1 — I partecipanti nel motore

- `_activity_process` acquisisce i lock di **tutti** i residenti occupati dall'attività (attore e
  partecipanti), in ordine di identificativo, così due attività condivise non possono bloccarsi a
  vicenda.
- Ogni partecipante raggiunge la stanza dell'attività con lo stesso meccanismo di movimento
  dell'attore (`MovementExecution` per partecipante, contratto invariato) e occupa un posto
  proprio: `berth_for` supporta già più corpi sullo stesso mobile.
- Il grafo di azioni resta dell'attore: la preparazione e il servizio sono suoi. Il partecipante
  registra presenza e postura per la durata. Se è ancora impegnato altrove, l'attività attende e il
  ritardo è una `PlanDeviation`, come già avviene per l'attore.
- Le precondizioni degli eventi runtime vengono valutate sul residente che l'evento colpisce.
- **Contratto della traccia**: `ActivityExecution` guadagna `participantIds`. Il campo è additivo e
  porta `execution-trace` a 1.1.0; le tracce 1.0.0 restano leggibili.

Verifica: tre giorni della coppia simulati. Nei `movements` entrambi i corpi arrivano in cucina per
la cena, e i pulse PIR fusi a cena nominano entrambi i residenti nell'oracolo.

### Fase 2 — La misura sulla traccia

- Nuovo modulo `profiling/habits.py`, che riusa `spread` di `profiling/builder.py`: la stessa
  aritmetica per fasce orarie del profilo del residente, che è già vera sulla traccia.
  - **intent e orari**: da `ActivityExecution` con `actualStart`/`actualEnd`; contano solo le
    attività `completed` e `deviated`, mentre `dropped` e `failed` non sono accadute;
  - **stanza e co-presenza**: dalla presenza per regione ricostruita dai `movements`, cioè dove il
    corpo era davvero;
  - **per residente**: attore o partecipante, grazie alla Fase 1.
- **Scenario**: l'estensione porta solo le bande dichiarate (`declaredHabits`, una voce per
  residente), perché l'export non vede l'outline. Sparisce ogni misura dallo scenario.
- **Export**: `habit_ground_truth` e `household_co_presence` diventano ruoli *calcolati*, come
  `resident_profile`, a partire da traccia e bande dichiarate. La pagina di sintesi legge gli
  stessi documenti.
- **Contratti**: `habit-ground-truth` 1.3.0 e `household-ground-truth` 1.0.0 non sono ancora
  committati, quindi assorbono il cambio di significato senza una versione in più. La provenance
  nomina la run e il digest della traccia da cui la misura è stata fatta.
- **CLI**: `expand-outline` scrive le bande dichiarate e stampa i controlli sul piano. Un nuovo
  `measure-habits --trace --scenario` produce la ground truth da una traccia, sul modello del
  comando `profile`.

Criterio di accettazione: la composizione pubblicata coincide **esattamente** con quella
ricostruita da `activities.csv` sugli orari effettivi, cioè con ciò che fa `gt_evaluation.py`.

### Fase 3 — Gli avvisi come controlli sul piano

- L'espansore tiene una misura interna del piano espanso (`PlannedBandCheck`). Non è un contratto
  pubblico e non viene salvata nello scenario.
- `validate_habit_bands_are_inhabited` e `validate_habit_bands_hold_a_stable_stretch` leggono
  quella misura. I codici restano gli stessi; i messaggi dicono esplicitamente «nel piano espanso».

### Fase 4 — La 6.3.2 completa

- Il ramo condiviso ha come durata minima `max(minimo del catalogo, minimumSharedMinutes)`. Così
  il compilatore separa invece di comprimere: nell'esperimento del 2026-09-12, senza soglia, la cena
  condivisa veniva schiacciata a 12 minuti anche con la degradazione accesa.
- Con la ground truth misurata sulla traccia cade il motivo per cui la degradazione era spenta di
  default: le bande descrivono ciò che il piano ha scelto. **Default proposto: accesa.** Costo
  misurato sul caso stretto: circa 6 secondi di compilazione al giorno invece di 2,5.
- Si toglie la marcatura `_is_understudy` dalle misure, che servirà solo alla misura interna del
  piano.

### Fase 5 — Esperimenti e documenti

- `05_experiments/habit_mining_baseline/src/read_habits.py`: la documentazione oggi dice che la
  composizione dell'export è misurata sull'orizzonte eseguito, e fino a questa modifica era falso.
  Dopo la Fase 2 diventa vero; va aggiornata la frase e segnalato quali export precedenti non lo
  sono.
- `05_experiments/giulia_dataset/src/effective_window.py`: resta valido; la finestra pubblicata,
  ora misurata sull'esecuzione, diventa davvero il riferimento autorevole.
- `gt_evaluation.py` non cambia: ricostruiva già tutto dalla traccia.
- ADR-026 (conseguenze sulla degradazione e sulla ground truth), il documento di design
  multi-residente, il README e il prompt 2.0.0 dove parla di ground truth.

---

## 4. Ordine e verifica

Fase 1 → 2 → 3 → 4 → 5. Ogni fase si chiude con i suoi test e la suite completa.

Accettazione finale, su un mese della coppia: espanso, compilato, **simulato** ed esportato.

- composizione pubblicata identica alla ricostruzione da `activities.csv`;
- co-presenza non nulla alle cene condivise, misurata dalle posizioni reali;
- oracolo che nomina entrambi i residenti sui pulse fusi a cena;
- nei giorni in cui il compilatore separa la cena, la ground truth mostra due cene separate.

---

## 5. Da decidere

1. **Come la traccia rappresenta un partecipante.** Proposta: `participantIds` su
   `ActivityExecution` (additivo, `execution-trace` 1.1.0). L'alternativa è un
   `ActivityExecution` per partecipante: più semplice da leggere, ma conterebbe una cena condivisa
   come due attività nel diario realizzato, cioè lo stesso errore evitato nel piano.
2. **Degradazione accesa di default** (Fase 4).

Non cambiano l'oracolo, il log osservabile e i modelli di processo ADL per residente.

---

## 6. A implementazione fatta: dove il codice differisce da questo piano

- **Il modulo di misura** sta in `hybrid_planning/habits.py` e non in `profiling/`, perché produce i
  contratti dell'outline; dal profilo riusa la definizione di cosa occupa un residente
  (`OCCUPYING_STATUSES`), quindi conta anche le attività `failed`, come fa già il profilo.
- **Il controllo sul piano** non è un tipo a parte (`PlannedBandCheck`): è lo stesso
  `HabitGroundTruth` con `measuredOn: expanded_plan`, esposto come `ExpansionResult.planned_bands` e
  mai pubblicato. Il campo `measuredOn` impedisce di scambiarlo per la ground truth.
- **Aggiunto strada facendo**: il controllo del pacchetto dei modelli di processo è per residente;
  il profilo del residente conta le attività condivise anche per i partecipanti; un pezzo d'arredo
  già occupato non viene scelto come posto per un secondo corpo.
- **Verificato in simulazione**: una giornata stretta (turno fino alle 19:30, corso dalle 19:45,
  soglia di 50 minuti) produce due cene separate e una ground truth con due cene e nessun episodio
  condiviso; senza soglia la stessa giornata produce una cena condivisa schiacciata, e la ground
  truth descrive quella (`tests/test_household_degradation.py`).
