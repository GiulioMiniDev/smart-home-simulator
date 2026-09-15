# Orizzonte multi-residente — documento di immaginazione

- Data: 2026-09-09
- Stato: **implementato**. Le quattro questioni aperte della prima stesura sono decise (§15) e
  tradotte in codice il 2026-09-12; la decisione è registrata in
  [ADR-026](../decisions/ADR-026-the-household-as-the-subject-of-an-outline.md), il contratto è
  `horizon-outline` 2.0.0 e il prompt che lo insegna è
  [`generate-horizon-outline-2.0.0`](../../prompts/generate-horizon-outline-2.0.0.md).
  Scostamenti rispetto a quanto scritto qui, motivati nell'ADR: il roster di §5 non è una lista a
  parte ma è `residents[]` stesso, perché una persona divisa su due elenchi è una persona che può
  desincronizzarsi; la ground truth delle abitudini (§10) non è misurata sul piano ma sulla traccia
  di esecuzione della run, al momento dell'export, e il motore esegue davvero i partecipanti di
  un'attività condivisa — il piano che lo ha stabilito è
  [2026-09-12-ground-truth-sull-esecuzione-piano.md](2026-09-12-ground-truth-sull-esecuzione-piano.md);
  la degradazione di §6.3.2 è accesa di default e il ramo condiviso non scende sotto
  `minimumSharedMinutes`. La serializzazione di §6.2 esisteva nel compilatore e nel motore ma
  nessun piano la dichiarava: dal 2026-09-13 l'espansore scrive su ogni attività gli oggetti che
  il suo processo accende o usa come sanitario (`required_resources`), e due lavaggi allo stesso
  lavandino si danno il turno invece di fermare la run. Il criterio di §12 e la misura di §13 sono
  stati eseguiti il 2026-09-13: gli esiti sono in fondo alle due sezioni. Lo stesso giorno sono stati
  chiusi gli ultimi tre punti rimasti aperti — l'attesa massima di §6.3, la casa che segue la
  famiglia di §11 e il confronto dichiarato/realizzato di §15.2 — con una nota di esito in ciascuna.
- Ambito: authoring dell'outline, espansione, compilazione, proiezione sensoriale, ground truth
- Instradamento di roadmap: il multi-residente è già assegnato a M8 (`ROADMAP.md:372`) e la
  fusione automatica di scenari indipendenti è esplicitamente fuori dal perimetro M6.1
  (`ROADMAP.md:460`). Questo documento non anticipa quella milestone: prepara il terreno
  decidendo *quale* forma dare al multi-residente prima di scrivere una riga.

---

## 1. La domanda che ha aperto il documento

Se in casa vive più di una persona, come si struttura l'orizzonte? Le due strade ovvie sono:

1. **un solo orizzonte congiunto**: si chiede all'LLM di scrivere in una volta la struttura di
   tutti i residenti;
2. **generazione sequenziale**: si scrive il primo residente, si espande, e si chiede all'LLM il
   secondo *in conseguenza* dei giorni concreti del primo.

La risposta di questo documento è: **né l'una né l'altra nella forma ingenua**. Si adotta una
variante della prima — un solo outline, con un livello household esplicito e i profili individuali
costruiti contro di esso — e si respinge la seconda per i motivi della §3.

---

## 2. Cosa esiste già (l'inventario è più incoraggiante del previsto)

Il multi-residente non va costruito da zero. Metà della macchina lo prevede già.

| Livello | Stato | Riferimento |
|---|---|---|
| Modello di dominio | `Scenario.residents` è già una lista; `Activity` ha `actor_id`, `participant_ids`, `can_overlap_for_actor` | `src/smart_home_sim/domain/models.py:418` |
| Compilatore | costruisce un `add_no_overlap` **per ogni residente**, tramite `occupied_residents()`, e i commitment filtrano già per partecipanti | `src/smart_home_sim/compiler/solver.py:289`, `:991` |
| Risorse | `Resource.capacity` + `add_cumulative`: una doccia sola è già esprimibile come contesa | `domain/models.py:118`, `solver.py:1026` |
| Ambiente | le berth esistono **esattamente** per due corpi che condividono un letto o un divano | `src/smart_home_sim/environment/occupancy.py:15` |
| Sensori | `_MotionPulse.resident_ids` è già una tupla, e gli `resident_ids` viaggiano sul link oracle, non sull'osservabile | `src/smart_home_sim/sensors/service.py:278`, `:1417` |
| Ground truth | `HabitGroundTruth` porta già `resident_id` | `src/smart_home_sim/hybrid_planning/outline.py:674` |
| Export | il profilo pubblicato itera già su `profile.residents` | `src/smart_home_sim/application/export.py:569` |

**Il buco è tutto nello strato di authoring ed espansione**, e ha due punti precisi:

- `HorizonOutline.resident_id: str` — un solo residente per costruzione
  (`hybrid_planning/outline.py:402`), con un solo `profile` e un solo `rhythm`;
- `actor_id = world.residents[0].resident_id` — l'attore della giornata è letteralmente il primo
  della lista (`hybrid_planning/day_generation.py:578`).

Questa asimmetria è la notizia buona del documento: la maggior parte del lavoro è *dichiarare*
meglio, non *risolvere* meglio.

---

## 3. Perché non la generazione sequenziale

Condizionare il residente B sui giorni espansi di A sembra la strada realistica — è così che
funziona una convivenza — ma rompe quattro cose contemporaneamente.

1. **Rimette nel prompt ciò che il prompt 1.3.0 ha appena tolto.** Per condizionare B su A bisogna
   mostrare all'LLM i giorni *concreti* di A. Otto mesi di giornate non entrano nel contesto e non
   si comprimono. È esattamente l'input la cui crescita con l'orizzonte ha prodotto il rapporto di
   firme distinte 1.00 → 0.74 → 0.03 documentato in `prompts/generate-horizon-outline-1.3.0.md`.
2. **Rende l'accoppiamento asimmetrico.** B si adatta ad A; A non si adatta mai a B. Si ottiene un
   residente primario e un satellite, non una convivenza. Nessuna coppia reale funziona così, e
   soprattutto: la ground truth di A sarebbe stata misurata *prima* di sapere che B esiste, quindi
   sarebbe falsa nel momento in cui B entra nella stessa stanza.
3. **Rompe la storia del riuso del piano.** Oggi vale «un orizzonte, un solve», ed è il fingerprint
   del compilatore a renderlo sicuro. Due solve su timeline intrecciate significano che rigenerare
   B invalida A senza che il fingerprint possa dirlo.
4. **Raddoppia la superficie non deterministica.** Una seconda passata LLM sull'output della prima
   moltiplica i punti in cui la riproducibilità dipende da un modello esterno.

## 3-bis. Perché nemmeno «tutto insieme» nella forma ingenua

Se si chiede semplicemente «scrivi l'outline della famiglia», un modello linguistico fa due cose
prevedibili e sbagliate:

- **sincronizza troppo**: pianta la cena alle 19:30 per entrambi, cioè restringe la banda proprio
  dove al motore di piazzamento serve margine per risolvere le collisioni. Il prompt 1.3.0 già
  avverte che una banda stretta rende l'orizzonte infeasible o inutilizzabilmente lento;
- **duplica invece di condividere**: scrive «cena» due volte, una per residente, con due bande
  simili ma non identiche. Il solver non ha nessun motivo di allinearle, divergono di quaranta
  minuti, e nel dataset compaiono **due cene** dove ce n'era una.

Da qui il vincolo strutturale della §4.

---

## 4. Il principio, esteso all'accoppiamento

Il principio del 1.3.0 è: **l'LLM dichiara la struttura, l'espansore deterministico genera i
giorni**. Il multi-residente lo estende senza cambiarlo:

> L'LLM dichiara *la propensione a condividere*. L'espansore deterministico decide *quali
> occorrenze concrete sono condivise*.

Ne segue tutto il resto. L'autore non scrive «martedì 14 cenano insieme»: scrive «la cena è
un'attività congiunta quando entrambi sono in casa». Chi sia effettivamente in casa quel martedì
lo sa solo l'espansore, dopo aver piazzato i commitment e calcolato i drive.

---

## 5. Struttura dell'outline proposta

Un solo documento, tre livelli, tutti O(1) nella lunghezza dell'orizzonte.

```
HorizonOutline 2.0.0
├── household                     ← NUOVO
│   ├── residents[]               ← roster: id, nome, età, salute, cronotipo
│   ├── relations[]               ← {between: [r1, r2], kind: couple | housemates | ...}
│   ├── sharingPolicy[]           ← §6, il cuore del documento
│   ├── locationPrivacy[]         ← §6.2
│   └── jointActivities[]         ← attività dichiarate una volta sola, con participantIds
├── world                         ← invariato, condiviso: una casa, una geometria, un set di risorse
└── residents[]                   ← per residente: profile, rhythm, habits, fixedCommitments
    └── (portfolio gate applicato per residente, non alla famiglia)
```

Tre punti non negoziabili:

- **le attività congiunte sono dichiarate una volta sola**, nel livello household, con
  `participantIds` esplicito e **una** banda. Mai due volte nei profili individuali. È la regola
  che impedisce le due cene della §3-bis;
- **il portfolio gate (3 anchor / 2 contextual / 2 optional / 1 rare) vale per residente.** Un
  residente con due abitudini proprie e tutto il resto in comune non è una persona, è un'ombra;
- **il condizionamento avviene dentro la stessa risposta.** Il prompt attuale già ordina
  «Construct the outline first, then the process package against it, then check both together».
  Stessa mossa: household prima, profili individuali dopo *contro* l'household, poi il controllo
  incrociato. B è scritto sapendo di A, ma il prompt resta O(1) e i residenti restano simmetrici.

---

## 6. La politica di condivisione

È la parte che il documento esiste per fissare, e nasce da un'osservazione precisa: **la
condivisione dipende dalla relazione, non dall'attività**. Due amici che dividono l'affitto non
fanno la doccia insieme e non dormono nello stesso letto; una coppia sì, o almeno può. E anche
fra coppie non è uniforme: c'è chi entra in bagno mentre l'altro si lava e chi aspetta fuori.
Nessuna di queste è deducibile dall'intent. **Va dichiarata dall'autore nella descrizione.**

### 6.1 Quattro modalità, non due

Il punto sottile è che «insieme o no» sono due domande diverse mascherate da una:

| Modalità | Significato | Esempio |
|---|---|---|
| `joint` | una sola attività, un solo intervallo, più partecipanti | la cena di una coppia; dormire nello stesso letto |
| `optional_joint` | insieme *quando capita*, con una propensione dichiarata | guardare la televisione; il caffè del mattino |
| `independent` | ciascuno la propria, tempi liberi, si contendono solo le risorse fisiche | il pranzo di due persone con turni diversi |
| `exclusive` | ciascuno la propria, **e** l'altro non può stare nella stessa stanza mentre accade | il bagno fra coabitanti |

L'esempio del pranzo che hai sollevato è precisamente `independent`: se uno stacca alle 13 e
l'altro rientra alle 15, non c'è nulla da sincronizzare, e forzare una cena comune sarebbe
un'invenzione. Ma la cucina resta una sola, e la contesa la risolve già il compilatore.

Per `optional_joint` l'autore dichiara una **propensione**, non un calendario: un numero indicizzato
per classe di giorno, più una soglia di sovrapposizione minima — la forma è fissata in §15.2.
L'espansore, per ogni giorno e con il seme dell'orizzonte, verifica che le bande dei due residenti
si sovrappongano e poi estrae: se esce condivisa emette **una** attività con due partecipanti, se
no ne emette due indipendenti. È il §4 applicato: propensione dichiarata, occorrenze calcolate.

### 6.2 La privacy, non la capienza — decisa

**Decisione: privacy di prim'ordine; `Location.capacity` scartata.**

La prima stesura proponeva di dare una capienza alle stanze. È sbagliato, e il motivo è che **la
capienza conta i corpi, e nessuna stanza ha una capienza vera**: a tavola uno può sedersi in braccio
all'altro, e in una cabina doccia ci si sta fisicamente in due. Quello che decide non è un numero di
posti, è una norma fra due persone specifiche — e una norma è *direzionale* e *per attività*, due
cose che un intero non sa dire.

Resta però una distinzione che la capienza aveva colto e che va salvata: **`Resource.capacity` non
ha mai contato i corpi, conta gli usi simultanei.** Un getto d'acqua, un water, un cestello. La
differenza si vede proprio sulla doccia:

- la doccia in due è **un** uso con due partecipanti, e passa;
- due docce indipendenti nello stesso istante sono **due** usi di un getto solo, e sono rifiutate —
  senza che il modello debba mai pronunciarsi su quante persone stiano in cabina.

Quindi due dichiarazioni ortogonali, e nessuna delle due conta le persone:

| | Cosa dichiara | Chi la decide | Meccanismo |
|---|---|---|---|
| **Privacy** | chi può essere co-presente nella stanza mentre faccio questa cosa | la relazione, dichiarata dall'autore | nuovo, §6.2.1 |
| **Serializzazione** | quanti usi simultanei regge questo apparecchio | la fisica | `Resource.capacity` + `add_cumulative`, esiste già |

#### 6.2.1 Forma del vincolo di privacy

La privacy **non è cumulativa**: è un non-overlap a coppie fra l'attività privata di `r1` e
qualunque attività di `r2` situata nella stessa stanza. Costa più vincoli di una capienza, ma dice
la cosa vera, ed è l'unica delle due che il preflight sappia spiegare a parole:

> «Marco non condivide il bagno mentre si lava, e la mattina di Luca non ha altre finestre»

è un errore leggibile da un ricercatore; `capacity 1 exceeded` no. Era già l'argomento della domanda
aperta n. 3 della prima stesura, e ora è l'argomento decisivo.

**Direzionale, con abbreviazione simmetrica.** Fra due adulti la norma è quasi sempre reciproca e si
dichiara una volta; fra genitore e figlio piccolo non lo è, e un contratto solo simmetrico non
saprebbe esprimerlo.

### 6.3 Aspettare l'altro

Il caso: di solito pranzano insieme, uno rientra mezz'ora prima, cucina, e **aspetta** che torni
l'altro — purché dopo pranzo non abbia nulla di stringente.

La cosa importante è che **questo non è un caso di `optional_joint`.** Non c'è nessuna moneta da
lanciare: è un `joint` con una banda larga, ancorato al partecipante che arriva più tardi. E in
buona parte funziona già oggi, senza nulla di nuovo:

1. `prepare_simple_lunch` — attore `r1`, banda 12:00–13:00;
2. `eat_lunch` — congiunto, `participantIds: [r1, r2]`, che dipende dalla preparazione:
   `_cook_before_eating` (`hybrid_planning/expander.py:1209`) inserisce già quella dipendenza da
   solo;
3. una seconda dipendenza da `commute_home` di `r2` con `maximumLagMinutes: 20` — e
   `DependencyGroup` ha già `minimum_lag_minutes` e `maximum_lag_minutes`
   (`domain/models.py:354`). È la forma esatta di «arriva, e poi mangiano insieme»;
4. il solver spinge l'intervallo congiunto oltre il rientro di `r2`, perché la catena di
   no-overlap di `r2` lo tiene occupato nel tragitto.

**Esito (2026-09-13).** Il punto 3 è implementato come scritto, con una sola generalizzazione:
l'assenza a cui ancorarsi non è un `commute_home`, che il catalogo non ha, ma qualunque assenza
obbligatoria in un luogo esterno — un turno, un evento — di un partecipante.
L'espansore aggiunge all'attività condivisa una dipendenza dall'assenza che finisce per ultima, con
`maximumLagMinutes: 20` (`SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES`), e solo dove non può fabbricare un
giorno impossibile: l'assenza deve finire dentro la finestra dell'attività condivisa qualunque cosa
ne faccia il compilatore. Un rientro ben prima che la banda si apra non comporta attesa e non viene
ancorato. Compilando il lunedì della coppia con il turno serale, la cena parte entro venti minuti
dalla fine del turno. Per un residente solo non cambia nulla.

**L'attesa è un residuo, non un meccanismo.** `r1` finisce di cucinare alle 12:40, il pranzo parte
alle 13:05, e quei venticinque minuti escono dal modello senza che nessuno li abbia scritti. È il
risultato più pulito di tutto il documento: ancorare un'attività congiunta al partecipante più
tardo *produce* l'attesa.

Restano due cose da decidere, e sono vere.

#### 6.3.1 L'attesa deve essere qualcosa, non un buco

Oggi quei venticinque minuti sono esattamente ciò che `simulation/behaviour.py` conta come *long
idle* — la stessa famiglia dei 402 minuti al giorno e del 22.7% di log sensoriale emesso da un corpo
fermo. In una casa condivisa il buco non è un difetto di riempimento: è un'attesa, e ha una forma
riconoscibile. Avviene **nella stanza dove accadrà l'attività congiunta** o vicino alla porta, è
interrompibile, e finisce nell'istante in cui l'altro arriva.

Proposta: `_seed_filler_candidates` acquisisce il caso multi-residente — un vuoto che *termina in
un'attività congiunta* viene riempito con attività di bassa intensità collocate nella stanza di
quell'attività. `r1` riordina la cucina, si fa un caffè, legge. **Non** si conia un intent
`wait_for_resident`: il catalogo è chiuso, coniare è vietato, e comunque nessuno «aspetta» — si fa
altro guardando l'orologio.

#### 6.3.2 «Se non ha un'attività stringente» — la degradazione

Se `r1` ha un impegno alle 13:30, aspettare fino alle 13:05 per un pranzo di quaranta minuti non ci
sta. In quel caso devono mangiare **separatamente**, non comprimere il pranzo condiviso. Serve un
congiunto *degradabile*: congiunto se ci sta, altrimenti due indipendenti. Chi lo decide?

- **l'autore** (una soglia tipo `maxWaitMinutes`): semplice, ma è l'autore che indovina uno slack
  che non può calcolare. Livello sbagliato;
- **l'espansore**: dovrebbe replicare il ragionamento di fattibilità del compilatore. È la trappola
  che il progetto conosce già — un piano che sembra giusto può essere insolubile, e lo scopri
  compilando;
- **il compilatore**: è l'unico strato che conosce lo slack. **Raccomandato.**

Il meccanismo esiste *quasi*. `ActivationMode.fallback` compila in rami alternativi veri
(`compiler/service.py:621`), ma i suoi trigger — `precondition_failed`, `activity_cancelled` — sono
entrambi eventi di **runtime**. Non c'è un «la versione congiunta non entrava» risolto a tempo di
compilazione. Servono quindi o un terzo trigger, o un gruppo di alternative mutuamente esclusive fra
cui il solver sceglie: la seconda è più pulita, perché il solver ha già le variabili di selezione
reificate (`compiler/solver.py:90`).

**Trappola da segnalare a chi implementa**, presa dal commento di `_cook_before_eating`: il solver
legge una dipendenza come `presence(meal) <= presence(cooking)`, quindi legare un pasto obbligatorio
a una preparazione facoltativa rende obbligatoria la preparazione dalla porta di servizio. Con la
degradazione, i due pranzi indipendenti del ramo di riserva devono avere **ciascuno la propria**
preparazione: ereditare quella del ramo congiunto viola `CROSS_BRANCH_DEPENDENCY`
(`compiler/service.py:638`).

#### 6.3.3 Conseguenza sulla tassonomia

Questo caso **restringe** `optional_joint`, e in meglio. Molte cose che avrei classificato come
opzionali sono in realtà `joint` con banda larga e ancoraggio: il pranzo è deterministico data la
fattibilità, non è un lancio di moneta. La propensione resta per ciò che è genuinamente stocastico
*a parità di co-presenza* — la televisione la sera. Meno peso sulla propensione significa che la
scelta della §15.2 pesa meno di quanto sembrasse.

### 6.4 I default devono essere restrittivi

Se l'autore non dichiara nulla, si assume `independent`, e le stanze con un solo apparecchio
sanitario sono `exclusive`. Il motivo è asimmetrico: il costo di un default permissivo sbagliato è
un dataset in cui due persone fanno la doccia nella stessa cabina — fisicamente impossibile e
silenziosamente falso a valle. Il costo di un default restrittivo sbagliato è una convivenza un po'
formale, visibile e correggibile. **Le impostazioni permissive si scelgono, non si ereditano.**

---

## 7. Come ogni modalità atterra sulla macchina esistente

Questa tabella è il motivo per cui la §6 è implementabile: quasi nulla di nuovo nel compilatore.

| Modalità | Cosa emette l'espansore | Cosa fa il compilatore | Serve codice nuovo? |
|---|---|---|---|
| `joint` | una `Activity`, `actor_id = r1`, `participant_ids = [r1, r2]` | `occupied_residents()` occupa entrambi | **no** |
| `optional_joint` | per giorno: una congiunta oppure due indipendenti | come sopra, o come sotto | **no** (logica nell'espansore) |
| `independent` | due `Activity` con `actor_id` diversi e bande proprie | due catene `no_overlap`, più `add_cumulative` sugli usi delle risorse comuni | **no** |
| `exclusive` | come `independent`, più il vincolo di privacy | non-overlap a coppie fra l'attività privata e le attività dell'altro nella stessa stanza | **sì**, §6.2.1 |
| `joint` degradabile | il ramo congiunto e i due indipendenti, mutuamente esclusivi | sceglie il ramo che sta nello slack | **sì**, §6.3.2 |

Osservazione non ovvia: **`joint` riduce lo spazio di ricerca**, perché sostituisce due intervalli
con uno. `exclusive` lo aumenta. Il costo di compilazione di una famiglia non è monotono nel numero
di residenti: dipende da quanto della giornata è condiviso. Non va stimato, va misurato (§11).

---

## 8. Ritmi e drive

Il debito di sonno è personale: ogni residente ha il proprio `RhythmProfile` e la propria catena di
`plan_rhythms`. Due conseguenze da non perdere:

- **le attività congiunte consumano i drive di tutti i partecipanti.** `_scheduled_drive_load`
  (`hybrid_planning/horizon.py`) conta oggi pasti e contatti sociali per giorno su un attore solo.
  Una cena condivisa deve scalare la fame di *entrambi*, altrimenti il residente non-attore accumula
  fame all'infinito, arriva al tetto e smette di variare — cioè esattamente il difetto che quella
  funzione esiste per evitare;
- **il contatto sociale in casa è un drive soddisfatto.** Oggi il bisogno di compagnia si consuma
  con le uscite e le visite. Con un coabitante, una cena condivisa lo soddisfa. Se non lo si
  collega, si ottiene un residente che vive con qualcuno ed esce ogni sera perché è solo.

Un accoppiamento che **non** modelliamo ora, ma che sarà la prima domanda di un revisore: se due
persone dividono il letto e una va a dormire alle 23:30 e l'altra all'01:00, il rientro della
seconda è un disturbo per la prima. È fuori perimetro (§12), ma va detto che è fuori perimetro,
non taciuto.

---

## 9. Sensori: il PIR deve restare ambiguo

Questa è la parte che rende il multi-residente interessante per la tesi anziché essere solo il
doppio del lavoro.

**Un PIR segnala movimento, non identità.** È la sua natura, non un limite da compensare: il
commento a `sensors/service.py:85` già lo dice per un residente solo («is a warm body moving in
front of me», non «is the resident executing a catalogued action»). Con due corpi la stessa frase
diventa la proprietà scientifica del dataset: l'osservabile non sa chi si è mosso, l'oracolo sì.

L'architettura è già impostata così — `resident_ids` viaggia sul link oracle
(`sensors/service.py:1417`), mai sul record osservabile — quindi **non c'è niente da separare**.
C'è però una cosa da aggiungere, ed è precisa:

> **La fusione dei pulse.** Oggi i pulse sono generati per attore (`by_actor_actions`,
> `sensors/service.py:323`) e ciascuno nasce con `resident_ids = (actor,)`. Due corpi che si
> muovono nello stesso cono entro la finestra di ri-trigger produrrebbero **due** record dove un
> PIR reale ne emette **uno**. Il record osservabile va fuso, e il suo link oracle deve nominare
> entrambi.

Non è un dettaglio cosmetico, ed è la stessa lezione già imparata una volta: il commento a
`sensors/service.py:263` racconta che disegnare i pulse dentro ciascun sensore rendeva i rilevatori
statisticamente indipendenti, e che contro CASAS Aruba la co-attivazione entro due secondi risultava
5.1% contro il 29.5% reale — «la geometria era già giusta, mancava solo la correlazione». Sommare
due flussi indipendenti di due corpi ripete lo stesso errore su un altro asse: sovrastima il conteggio
di eventi, perché ignora il mascheramento da ri-trigger.

Gli altri sensori non sono toccati: contatti e consumi sono per dispositivo, e un frigorifero aperto
è un frigorifero aperto chiunque l'abbia aperto.

---

## 10. Ground truth e profili: separati, più uno

La tua indicazione — nella ground truth va detto chi fa cosa — si traduce in tre documenti, non uno.

1. **Una `HabitGroundTruth` per residente.** Lo schema porta già `resident_id`
   (`hybrid_planning/outline.py:674`), quindi si emettono N documenti e non si tocca nulla. È anche
   la scelta giusta rispetto alla letteratura: la segmentazione delle abitudini è definita su una
   persona, e una ground truth «familiare» non sarebbe confrontabile con Aruba.
2. **Una ground truth di household**, per ciò che una per-residente strutturalmente non può dire:
   gli intervalli di co-presenza, chi era in casa quando, quali episodi sono stati congiunti. Un
   esperimento che gira su un log condiviso ha bisogno di sapere quanta parte del segnale è
   attribuibile a più di un corpo — altrimenti misura un confondente e lo chiama errore.
3. **Un profilo per residente** più la pagina di household. `export.py` itera già su
   `profile.residents` (`:569`), quindi la forma plurale è già prevista dall'export.

E un campo nuovo che secondo me è **il** numero della tesi multi-residente:

> Per ogni banda della ground truth per-residente, la **quota di ambiguità**: la frazione dei
> minuti della banda durante i quali un altro residente era nella stessa stanza. È la misura di
> quanto quella banda sia recuperabile da un log che non distingue i corpi, e sta accanto a
> `unaccounted_share` come secondo asse di difficoltà. Senza di essa, un algoritmo che fallisce su
> una banda condivisa e uno che fallisce su una banda rumorosa producono lo stesso numero.

Si collega naturalmente a `mining_difficulty`, che l'outline già dichiara.

**Decisione: la quota di ambiguità è un campo di `HabitObservation`**, non un documento affiancato.
Risponde alla stessa domanda di `unaccounted_share` — quanto è recuperabile questa banda — e
tenerla fuori costringerebbe a una join per `habit_id` fra due file per leggere un numero. Costa un
passaggio dello schema a 1.3.0, che è esattamente ciò per cui lo schema è versionato.

**Decisione: un solo dataset per casa**, con un log sensoriale condiviso, N ground truth
per-residente e una di household. Un dataset per residente duplicherebbe lo stesso log osservabile N
volte e perderebbe l'unica cosa che rende il caso interessante, cioè che il log è uno solo.

---

## 11. Scalabilità a N

Il documento parla di due residenti perché è il caso che si vuole prima, ma nulla qui è binario.

- **Nessun campo «entrambi».** Ogni cosa condivisa porta `participantIds` esplicito. In una
  famiglia di quattro, la cena ha quattro partecipanti e l'accompagnamento a scuola ne ha due: se
  il contratto sa dire solo «insieme», il secondo caso è inesprimibile.
- **Le relazioni sono a coppie.** `relations[]` fra `r_i` e `r_j`, perché la politica di
  condivisione di una coppia con un figlio adolescente non è la stessa fra i due genitori e fra
  genitore e figlio. La politica si risolve sulla coppia, non sulla casa.
- **Il gate del portfolio per residente moltiplica il carico dell'LLM** (N=4 significa almeno 32
  attività ricorrenti). È un secondo argomento a favore del livello household: tutto ciò che è
  condiviso viene scritto una volta, e i profili individuali restano corti.
- **La casa deve seguire la famiglia.** `design_dwelling` già pesca l'archetipo da un
  `Household.from_persona` che oggi legge una stringa (`dwelling.py:262`). Con un roster vero,
  quella derivazione diventa esplicita: due amici hanno due camere, una coppia ne ha una. Ed è un
  vincolo *duro*, non estetico — se la casa ha una camera sola, `sleep` non può essere
  `independent` con stanza esclusiva, l'orizzonte è infeasible e va rifiutato in preflight, non
  scoperto dal solver dopo tre ore.

**Esito (2026-09-13).** Tre pezzi, perché «la casa segue la famiglia» ne aveva tre.

- **Il generatore.** `Household.from_roster` ricava le camere dall'elenco dei residenti e dalle
  coppie di persone che dormono insieme: due amici due camere, una coppia una, una coppia con due
  figli tre. `design_dwelling(household=...)` tratta il numero di camere come vincolo duro, come la
  scala: sceglie solo archetipi che le hanno e, oltre il massimo del catalogo, aggiunge camere
  arredate con un letto proprio invece di far dormire qualcuno in due. Il percorso dalla persona
  in testo libero disegna le stesse case di prima.
- **Il piano.** C'era un difetto più concreto del generatore: `startLocationId` metteva il
  coinquilino nella seconda camera per la prima mezzanotte, e ogni notte successiva entrambi
  andavano a dormire nella `bedroom` del catalogo, nello stesso letto. Ora sonno, risveglio,
  pisolino e rientro dalla visita notturna al bagno avvengono nella stanza da cui il residente
  parte, se lì c'è un letto. Verificato simulando due giorni: ciascuno dorme nella propria camera,
  il secondo sul letto singolo.
- **Il rifiuto.** Due residenti dichiarati `housemates` o `other` che dormirebbero nella stessa
  stanza sono rifiutati prima di espandere, con una frase, a meno che la casa non condivida la
  stanza in `sharedLocationIds`. Coppie, genitore e figlio, fratelli possono condividerla. Il prompt
  2.0.0 lo insegna.

---

## 12. Migrazione e determinismo

- `HorizonOutline` passa a **2.0.0**: `residents[]` sostituisce `resident_id` + `profile` +
  `rhythm`. È un cambio incompatibile e va registrato in un ADR, sulla scia di ADR-018.
- **Un outline mono-residente è il caso N=1**, non un percorso separato. Nessun ramo `if
  len(residents) == 1`.
- Il criterio di accettazione della migrazione: **ri-espandere un caso esistente e ottenere lo
  stesso piano compilato**. Non gli stessi byte — la riproducibilità byte-a-byte non è un requisito
  — ma lo stesso piano, verificato compilando l'orizzonte intero e non guardando i primi giorni.
  Un piano che sembra giusto può essere insolubile più avanti.
- `day_generation.py:578` (`world.residents[0]`) è il punto in cui la migrazione si vede: è lì che
  oggi il codice decide che esiste una sola persona.

**Esito (2026-09-13).** Verificato su un caso esistente, il bundle di cinque mesi di Filippo
Bottiglia: espanso e compilato su tutti i 153 giorni dal codice 1.0.0 committato e da quello
attuale dopo il lift, le 4 392 attività pianificate hanno lo stesso inizio e la stessa fine, anche
con gli usi degli apparecchi scritti su 2 436 di esse. L'esempio di riferimento Meredith non poteva
servire: è irrisolvibile il 2026-10-15 con entrambi i codici (un turno di otto ore e un evento
obbligatorio nella stessa data), un difetto dell'esempio e non della migrazione.

Il criterio ha trovato un difetto vero lungo la strada. Messe nel modello delle risorse, le
candidate che il motore può scartare (visite al bagno, riempitivi) spostavano le abitudini
dell'autore per restare al loro posto: 66 attività, una visita al bagno obbligatoria di tre ore e
mezza. Ora ne restano fuori, come restano fuori dalla catena di no-overlap del loro residente, e il
motore le lascia cadere quando trova l'oggetto occupato.

---

## 13. Costo di compilazione — da misurare, non da stimare

`MAX_FEASIBILITY_PROBES = 20 000` e `FEASIBILITY_DETERMINISTIC_TIME` sono tarati su un residente
(`compiler/solver.py:18`–`:35`, e la storia dietro quei numeri è in
`docs/plans/2026-08-03-compilazione-orizzonti-lunghi-diagnosi-e-partizione-design.md`).

Due residenti raddoppiano le catene di no-overlap e le accoppiano attraverso la contesa di risorse
e stanze. Ma per la §7 le attività congiunte *riducono* il modello, quindi il verso dell'effetto
non è deducibile a tavolino.

Nota rassicurante: **la partizione per giorno regge**. `build_horizon` compila un giorno alla volta
e i residenti vivono nello stesso giorno, quindi l'accoppiamento è interamente intra-giornaliero e
non attraversa la frontiera che rende la partizione valida.

Misura minima prima di dichiarare fattibile la cosa: un orizzonte di un mese, due residenti, con e
senza la stanza esclusiva, confrontato con lo stesso mese mono-residente. Se le probe esplodono,
il colpevole più probabile è una banda stretta su un'attività `exclusive`, non il numero di persone.

**Esito (2026-09-13).** Un mese della coppia di test, compilato intero, una run alla volta:

| | attività | tempo | probe |
|---|---|---|---|
| un residente | 728 | 36 s | 230 |
| coppia | 1 635 | 135 s | 1 583 |
| coppia, bagno esclusivo | 1 635 | 168 s | 1 573 |
| coppia, senza usi degli apparecchi | 1 635 | 130 s | 1 456 |

Prima delle due correzioni qui sotto la coppia **non compilava**: `SOLVER_NOT_OPTIMAL` dopo dodici
minuti con il bagno condiviso, sette e mezzo con quello esclusivo. `exclusive` allarga il modello come
previsto (+24%). Le probe però non esplodevano dove immaginato, ma in due punti strutturali:

- **la divisione in finestre non contava i residenti.** La soglia era in giorni, tarata su una
  persona, quindi il mese di una coppia era un solo solve e le prime probe esaurivano il budget. Ora
  conta i giorni-residente: per un residente è il numero di giorni e nulla cambia. La nota sopra su
  `build_horizon` era imprecisa — il percorso reale è `compile_scenario`, che divide a settimane — ma
  la sostanza regge: l'accoppiamento resta dentro il giorno;
- **il ramo perdente di §6.3.2 era un rifiuto garantito.** La canonicalizzazione bloccava le attività
  dei rami una per una, e ogni giorno il ramo che perde costava una bisezione. Ora la scelta è un
  solo blocco per gruppo, sul ramo che vale di più.

Restano i rifiuti ordinari della contesa serale fra risveglio, televisione condivisa, igiene e sonno.
Lungo la misura è emerso anche un difetto di §11: tre cene separate a quaranta superavano una cena
condivisa a novanta, quindi una famiglia di tre non avrebbe mai mangiato insieme. La priorità del
ramo separato ora si divide per il numero di partecipanti.

---

## 14. Fuori perimetro (dichiarato, non taciuto)

- collisione fisica fra corpi in corridoio — già esclusione deliberata di roadmap;
- disturbo reciproco del sonno (§8);
- conversazione, negoziazione, cambi di piano indotti dall'altro residente: un residente non
  reagisce a ciò che l'altro fa se non attraverso i vincoli dichiarati;
- fusione automatica di due scenari mono-residente già esistenti in una casa condivisa. Resta
  quello che è nella roadmap: fuori. Il multi-residente si autora, non si assembla a posteriori.

---

## 15. Decisioni

Le quattro questioni aperte della prima stesura sono chiuse.

- **15.1 — Un dataset solo.** Deciso (§10).
- **15.3 — Privacy, non capienza.** Deciso; `Location.capacity` scartata (§6.2).
- **15.4 — La quota di ambiguità sta dentro `HabitObservation`.** Deciso (§10).

### 15.2 — La forma della propensione di `optional_joint`: numero indicizzato — deciso

Un numero è semplice, O(1) e verificabile; una condizione è più espressiva ma è un linguaggio nuovo
da validare. Quattro casi concreti su cui è stata provata:

| Caso | Numero puro | Condizione pura |
|---|---|---|
| **TV la sera** — coppia quasi sempre in casa | `0.7`: sette sere su dieci insieme. Corretto | «quando entrambi in casa»: *tutte* le sere. Sovra-accoppia, sparisce la sera in cui uno è stanco |
| **Cena con i turni** — uno rientra alle 21:30 due volte a settimana | estrarrebbe «insieme» anche dove le bande non si sovrappongono. **Il numero non può mai stare da solo**: la co-presenza è sempre una precondizione verificata dall'espansore | la esprime, ma è la parte che la macchina sa derivare da sé |
| **Colazione** — uno esce alle 7:00, l'altro alle 8:30 | metà dei giorni una colazione condivisa di dodici minuti schiacciata contro il commitment | «solo se restano almeno venti minuti in comune»: è una soglia di durata, e un numero puro non la esprime |
| **Weekend** — insieme sabato e domenica, quasi mai in settimana | `0.4` media i due regimi e sparge cene condivise a caso nella settimana: **fabbrica un pattern falso nella ground truth**, proprio nella distinzione per cui esiste `day_types` | la esprime correttamente |

**Decisione**: non un linguaggio di predicati, ma un numero indicizzato sugli assi che l'outline già
possiede.

```
sharing: optional_joint
propensity: { default: 0.25, weekend: 0.85 }
minimumSharedMinutes: 20
```

`weekdays` esiste già in `HabitSegment`, `day_types` esiste già nella ground truth, e gli override
di fase passano da `ActivityOverride`. Copre il weekend e la colazione — i due casi in cui la
condizione serviva davvero — senza inventare una grammatica.

Tre conseguenze a favore:

- **la ground truth può confrontare dichiarato ed effettivo** («0.85 dichiarato nel weekend, 0.79
  realizzato su 34 fine settimana»). Con un predicato libero si può riportare solo il realizzato,
  perché il dichiarato non è un numero. È la stessa forma di `window_start` contro `effective_start`;
- **un modello piccolo emette un numero, non una sintassi.** Un linguaggio di condizioni è
  esattamente la superficie su cui gli LLM inventano — è già successo con gli intent, ed è il motivo
  per cui il prompt urla «Never coin an intent»;
- **il determinismo resta banale**: un'estrazione per (attività, giorno) dal seme dell'orizzonte, che
  è già il pattern dell'espansore. Un predicato richiederebbe un ordine di valutazione e un
  tie-break, e lì un baco è silenzioso.

Rischio residuo, valido per entrambe le opzioni: una propensione `> 0` su un'attività le cui bande
non si sovrappongono mai produce un'attività congiunta dichiarata che non accade mai. Il preflight
deve controllare la fattibilità della co-presenza a prescindere da come è scritta la propensione.

**Esito (2026-09-13).** Il confronto è pubblicato. La dichiarazione delle attività condivise viaggia
nello scenario accanto alle fasce (`declaredHabits.jointActivities`), e la ground truth della casa
porta `sharing`: per ogni attività condivisa e per classe di giorno, la propensione dichiarata, i
giorni in cui l'attività è avvenuta — insieme o separati —, quelli in cui è stata condivisa e la
quota realizzata, misurata sulla traccia della run. L'export la pubblica come ruolo
`household_sharing`. Per un `joint`, che non dichiara una propensione, la quota realizzata è ciò
che i giorni hanno permesso: co-presenza e scelta del compilatore di degradare.

Nota di ridimensionamento: dopo la §6.3.3 questa scelta pesa meno di quanto sembrasse. Il pranzo
condiviso con attesa non è `optional_joint` ma `joint` ancorato, quindi la propensione copre solo
ciò che è genuinamente stocastico a parità di co-presenza.
