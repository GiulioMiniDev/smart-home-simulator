# Roadmap

Ogni milestone consegna una feature completa nel perimetro dichiarato, con contratti,
implementazione, test di accettazione e artefatti utilizzabili. Una milestone non può
essere dichiarata completata se contiene stub, handler fittizi, output soltanto astratti
rispetto alla feature promessa o logica indispensabile rinviata a una milestone
successiva.

Una milestone successiva può consumare o proiettare gli artefatti già completi, ma non
può renderli validi retroattivamente. Le interfacce necessarie a una feature devono essere
definite e validate prima che inizi la sua implementazione. I contratti pubblici già
congelati restano immutati; nuove esigenze producono artefatti versionati paralleli e
relativi controlli di compatibilità.

## Ordine delle milestone

| Milestone | Feature completa | Input | Output verificabile | Stato |
|---:|---|---|---|---|
| 0 | Specifica e confini | proposta di ricerca | contratti e invarianti | Completata |
| 1 | Motore di validazione | scenario JSON | validation report | **Completata e congelata — 1.0.0** |
| 2 | Compilatore del piano | scenario valido | canonical daily plan | **Completata e congelata — 1.0.0** |
| 3 | Authoring comportamentale e modelli di processo ADL | profilo, abitudini, calendario e vocabolario delle azioni | scenario + pacchetto personale di process model validati | **Completata e congelata — 1.0.0** |
| 4 | Ambiente domestico eseguibile e binding | process model + definizione della casa | home model validato + simulation bundle completamente risolto | **Completata e congelata — 1.0.0** |
| 5 | Motore di simulazione completo | simulation bundle | execution trace spazio-temporale, semantica e causale | Non iniziata |
| 6 | Sensori e separazione oracle/observable | execution trace + sensor model | sensor log osservabile + oracle mapping | Non iniziata |
| 7 | Applicazione UI, workspace, export e replay | artefatti M1–M6 completi | applicazione moderna end-to-end + dataset JSONL/CSV/XES + replay deterministico | Non iniziata |
| 8 | Esecuzione longitudinale | orizzonti validati + stato persistente | simulazioni annuali e repliche Monte Carlo | Non iniziata |
| 9 | Calibrazione e valutazione sperimentale | dati reali e sintetici | rapporto riproducibile di qualità e utilità | Non iniziata |

## Regola generale di avanzamento

Una milestone può iniziare soltanto quando:

- tutti i suoi input hanno un produttore e un contratto identificati;
- gli artefatti necessari sono validabili indipendentemente;
- le dipendenze precedenti sono complete e non richiedono implementazioni provvisorie;
- i criteri di accettazione coprono l'intera feature dichiarata;
- ciò che resta fuori perimetro non è necessario per attribuire significato o validità
  all'output della milestone.

Una demo, uno spike o un benchmark non costituiscono completamento. Possono essere usati
come strumenti interni, ma il relativo codice non diventa fondazione del prodotto finché
non soddisfa il contratto e la definition of done della milestone.

## Milestone 0 — Specifica e confini

### Criteri di completamento

- scenario, piano canonico, modelli di processo personali, ambiente, traccia eseguita e
  osservazioni sono concetti distinti;
- ogni artefatto ha un'autorità e un produttore identificati;
- le invarianti fondamentali sono documentate;
- nessuna specifica richiede una particolare libreria di simulazione.

## Milestone 1 — Motore di validazione

### Contenuto

- schema scenario e report versionati `1.0.0`;
- modelli Pydantic strict-by-default;
- validazione strutturale, referenziale, temporale e semantica completa per il contratto;
- rapporto testuale e JSON;
- JSON Schema distribuibile;
- esempi validi e invalidi;
- codici di errore stabili;
- test di accettazione della CLI;
- parsing robusto di file, UTF-8 e JSON;
- settimana rappresentativa completa e migrazione riproducibile;
- golden report e copertura minima obbligatoria del 95%.

### Fuori perimetro

- scelta degli orari esatti dentro le finestre;
- risoluzione dei conflitti;
- esecuzione delle attività;
- percorsi, coordinate e sensori;
- correzioni tramite LLM.

### Definition of done

- tutti gli esempi validi terminano con exit code `0`;
- tutti gli esempi invalidi terminano con exit code `1`;
- il rapporto JSON è machine-readable e deterministico;
- lo schema generato è valido JSON;
- test e lint passano;
- nessuna dipendenza da SimPy, NetworkX o librerie grafiche;
- ogni codice registrato è esercitato dalla matrice di test;
- i due JSON Schema superano la metaschema Draft 2020-12 e coincidono con i modelli.

La regola di avanzamento è soddisfatta: `scenario-1.0.0.schema.json` è congelato e la
settimana di Mario Rossi, composta da 7 giorni e 173 attività, è un acceptance test valido.
Qualunque estensione futura del contratto richiede una nuova versione secondo ADR-002;
non riapre né muta `1.0.0`.

## Milestone 2 — Compilatore del piano

### Contenuto

- gate obbligatorio sul validatore `1.0.0`;
- modello CP-SAT per finestre, durate, dipendenze, residenti, impegni e risorse;
- selezione opzionale ottima e tie-break deterministico;
- tempo esatto al microsecondo e gestione del fuso IANA;
- patch giornaliere per fallback e condizioni;
- piano e compilation report versionati `1.0.0`;
- CLI, schemi, checksum, golden week e test di invarianti.

### Fuori perimetro

- esecuzione e stato runtime;
- campionamento degli eventi;
- riparazione di contingenze simultanee;
- topologia, coordinate, microazioni, sensori ed export.

### Definition of done

- il caso minimo e la settimana completa compilano con esito `OPTIMAL`;
- un piano impossibile fallisce senza artefatto parziale;
- output e digest sono deterministici;
- gli schemi pubblici coincidono con i modelli e superano la metaschema;
- vincoli di non sovrapposizione, capacità, dipendenza e commitment sono testati sull'output;
- suite completa, lint e copertura minima obbligatoria del 95% passano.

La regola di avanzamento della Milestone 2 è soddisfatta dai contratti congelati in
ADR-003 e dalla compilazione golden di `examples/valid/mario_week.json`.

## Milestone 3 — Authoring comportamentale e modelli di processo ADL

### Responsabilità

Produrre e validare, prima dell'implementazione del mondo virtuale, tutti gli artefatti che
descrivono **come la persona simulata svolge le proprie attività**. Il ricercatore usa un
LLM esterno soltanto nella fase iniziale di authoring; il simulatore non dipende da un
provider né invoca un LLM durante validazione, compilazione o simulazione.

### Contenuto

- catalogo canonico e versionato delle attività specifiche del progetto, ricavato dalla
  settimana di accettazione e normalizzato eliminando sinonimi, ambiguità e combinazioni
  non strutturate;
- eventuali mapping verso tassonomie o dataset esterni conservati soltanto come metadati
  di interoperabilità, non come identificatori autorevoli del runtime;
- catalogo tipizzato delle variabili personali, domestiche, sociali, stagionali e di
  calendario, con regole di derivazione e precedenza;
- vocabolario chiuso e versionato delle azioni atomiche e dei relativi parametri,
  precondizioni, effetti e requisiti di capacità;
- contratto JSON versionato dei process model personali, comprendente applicabilità,
  sequenza, scelta, opzionalità, parallelismo, cicli limitati, durate e provenienza;
- pacchetto versionato che associa residente, `intent` e contesto applicabile a uno e un
  solo process model, con fallback espliciti e senza risoluzioni implicite;
- prompt ufficiali, istruzioni e JSON Schema per far generare a un LLM esterno sia lo
  scenario sia i process model personali;
- prompt end-to-end unico e autosufficiente, arricchito dal ricercatore con una descrizione
  libera della persona e generato deterministicamente dagli schemi e cataloghi ufficiali;
- envelope JSON di trasporto per ricevere scenario e process model nella stessa risposta,
  con ingestione transazionale che non pubblica input parziali;
- validazione strutturale, referenziale e semantica dei process model, inclusi
  raggiungibilità, terminazione, completezza dei rami e uso esclusivo di azioni ammesse;
- CLI e report machine-readable per validare un pacchetto comportamentale e verificarne
  la compatibilità con uno scenario;
- ciclo di riparazione esterno e versionato che impacchetta bundle rifiutato, errori,
  percorsi JSON, schema e cataloghi in una singola richiesta autosufficiente, senza
  correzioni locali o dipendenze LLM nel runtime;
- provenance completa di modello, prompt, parametri, timestamp, revisione umana e digest.

Il formato autorevole è strutturato e validabile. Una rappresentazione Mermaid può essere
aggiunta in futuro come proiezione visuale, ma non è un requisito né una dipendenza del
runtime.

### Fuori perimetro

- chiamate automatiche a provider LLM dal simulatore;
- esecuzione temporale dei process model;
- binding delle azioni a oggetti concreti di una casa;
- traiettorie, interazioni fisiche e sensori.

### Definition of done

- ogni `intent` dichiarato dal catalogo ha semantica, variabili e granularità documentate;
- ogni attività selezionabile nella settimana di accettazione risolve senza ambiguità a
  un process model applicabile per il residente e il contesto corretti;
- nessun nodo usa testo libero al posto di un'azione tipizzata;
- ogni modello termina, non contiene nodi morti e possiede rami completi o fallback
  espliciti;
- gli output prodotti seguendo i prompt ufficiali sono accettati dagli stessi validatori
  usati per gli artefatti scritti manualmente;
- il ricercatore allega un solo prompt, non deve creare un profilo intermedio strutturato e
  ottiene una risposta JSON univocamente parsabile;
- un bundle valido viene separato nei due contratti canonici, mentre qualunque errore in
  uno dei due impedisce atomicamente la pubblicazione di entrambi;
- input invalidi o incompatibili producono report completi senza correzioni silenziose;
- un input rifiutato e riparabile produce una richiesta autosufficiente; ogni risposta
  completa dell'LLM rientra da zero negli stessi gate e soltanto un esito valido viene
  pubblicato;
- schemi, checksum, esempi, CLI, golden report, test, lint e copertura minima obbligatoria
  del 95% sono completi;
- lo scenario e il canonical plan congelati non vengono modificati retroattivamente.

La regola di avanzamento della Milestone 3 è soddisfatta dai contratti e cataloghi
congelati in ADR-004. Il pacchetto comportamentale della settimana di Mario contiene 91
process model personali specifici per intento, 91 binding e copre senza ambiguità tutte
le 173 attività dello scenario; il caso minimo copre 2 attività su 2. Gli intenti composti
sono verificati rispetto alla loro decomposizione ordinata, non soltanto rispetto alla
presenza nominale di un binding. Il flusso a prompt singolo è congelato da ADR-005: il
prompt distribuibile incorpora schema e cataloghi. ADR-006 aggiunge il gate del compilatore
dopo la prima prova esterna; ADR-007 promuove il prompt `1.2.0` con la matrice esplicita tra
sorgenti dei valori e riferimenti delle azioni. ADR-008 congela il contratto della richiesta
di riparazione `1.0.0` e il ciclo esterno a risposta completa. L'envelope deve superare
validazione dello scenario, compilazione completa e validazione del comportamento prima
della pubblicazione.

## Milestone 4 — Ambiente domestico eseguibile e binding

### Responsabilità

Definire una casa virtuale completa per il livello di fedeltà scelto e dimostrare che ogni
azione richiesta dai process model può essere risolta su stanze, percorsi, oggetti e
capacità concrete prima che inizi l'esecuzione.

### Contenuto

- contratto versionato del `home model` con stanze, aree esterne, porte, connettività,
  geometria metrica 2D, ostacoli, regioni attraversabili e punti di interazione;
- oggetti, risorse, capacità, stato iniziale, vincoli di accesso e operazioni supportate;
- validazione topologica e geometrica completa, inclusi contenimento, adiacenza,
  aperture, ostacoli, raggiungibilità e coerenza delle unità di misura;
- route planner deterministico attraverso stanze e porte e path planner collision-free
  nella geometria dichiarata;
- modello cinematico completo per velocità, postura, tempi di percorrenza e traiettorie
  timestampabili, parametrizzato dal profilo del residente;
- binding deterministico tra ogni azione atomica e una capacità concreta dell'ambiente;
- contratto versionato del `simulation bundle`, che lega scenario, canonical plan,
  pacchetto comportamentale, home model, versioni, digest e seed;
- validatore e report di compatibilità dell'intero bundle;
- almeno un ambiente domestico di accettazione completo di tutti gli elementi richiesti
  dalla settimana rappresentativa.

### Fuori perimetro

- avanzamento del clock e scelta dei rami dei process model;
- applicazione runtime delle azioni e delle contingenze;
- produzione di misure sensoriali;
- rendering interattivo o motore grafico 3D.

### Definition of done

- ogni luogo, oggetto, risorsa e capacità referenziati dal bundle si risolvono senza
  fallback impliciti;
- ogni azione di ogni modello applicabile possiede un binding eseguibile oppure il bundle
  viene rifiutato prima della simulazione;
- tutte le destinazioni sono raggiungibili secondo i vincoli dichiarati e i percorsi non
  attraversano muri o ostacoli;
- tempi e geometrie di movimento rispettano profilo, unità e invarianti spaziali;
- bundle non coerenti falliscono con report completo e senza artefatti parziali;
- schema, checksum, esempi, CLI, golden environment, test, lint, benchmark e copertura
minima obbligatoria del 95% sono completi.

La regola di avanzamento della Milestone 4 è soddisfatta dai contratti congelati in
ADR-009. La casa di Mario contiene 14 regioni, 13 connessioni, 14 punti di interazione,
13 entità concrete e quattro ostacoli metrici. Il bundle settimanale risolve 766 istanze di
azione e verifica tutte le 441 coppie ordinate fra i 21 binding di luogo. I tre contratti
pubblici, il report, i digest, la CLI, il benchmark e gli artefatti golden sono versionati
`1.0.0`; lo stesso input produce lo stesso bundle. Un benchmark visuale interattivo
generato dagli stessi artefatti ispeziona la planimetria, le sei porte, i quattro ingombri,
le nove risorse fisiche, le sei entità domestiche e le 49 rotte fra i sette ambienti. Il
catalogo SVG è chiuso sul vocabolario effettivamente presente: l'assenza di un simbolo, un
ID fantasma o un digest stale fanno fallire il gate. Questo non introduce dipendenze
runtime né anticipa la UI applicativa della Milestone 7.
La matrice di evidenza terminale è congelata in
`docs/audits/milestone-4-closure.md`; la Milestone 5 non può demandare correzioni o
interpretazioni dell'ambiente al runtime.

## Milestone 5 — Motore di simulazione completo

### Responsabilità

Eseguire integralmente il simulation bundle. La milestone non produce una traccia
provvisoria composta soltanto da inizio e fine delle attività: interpreta i process model,
sceglie i rami, applica tutte le azioni all'ambiente e registra la realtà spazio-temporale,
semantica e causale effettivamente simulata.

### Contenuto

- clock autorevole a eventi discreti dietro un'interfaccia posseduta dal progetto;
- istanziazione dei process model personali per attività, residente e contesto;
- scelta riproducibile di rami, durate e variazioni tramite stream casuali nominati;
- esecuzione completa del vocabolario delle azioni definito in Milestone 3;
- movimento topologico, traiettorie geometriche, posture e interazioni con oggetti e
  risorse tramite l'ambiente di Milestone 4;
- acquisizione, attesa, pre-emption e rilascio delle risorse condivise;
- valutazione live di precondizioni ed effetti e mantenimento dello stato di residenti,
  risorse e ambiente;
- campionamento degli eventi runtime, ritardi, estensioni, interruzioni, fallback,
  contingenze simultanee e riparazione locale secondo la policy dichiarata;
- contratto versionato dell'execution trace con attività, azioni, movimenti, stati,
  causalità, deviazioni dal piano e provenance completa;
- simulation report, failure contract, replay deterministico interno e benchmark della
  settimana di accettazione.

### Fuori perimetro

- proiezione del ground truth in misure di sensori;
- formati pubblici di esportazione e interfaccia di replay;
- rendering 3D e fisica rigida non richiesti dal vocabolario delle azioni congelato.

### Definition of done

- la settimana rappresentativa viene eseguita da input a output senza handler mancanti,
  azioni ignorate, sostituzioni fittizie o stati non risolti;
- ogni attività selezionata termina, devia o fallisce con una causa esplicita e tracciata;
- ogni azione produce gli effetti temporali, spaziali e di stato definiti dal contratto;
- nessun residente attraversa muri, occupa due posizioni incompatibili o usa risorse oltre
  la capacità;
- interruzioni e contingenze lasciano sempre il mondo in uno stato valido oppure terminano
  la simulazione secondo il failure contract;
- stesso bundle e seed producono lo stesso digest semantico della traccia;
- output impossibili o bundle invalidi non generano tracce parziali presentate come valide;
- schemi, checksum, esempi, CLI, golden trace, test, lint, benchmark end-to-end e copertura
  minima obbligatoria del 95% sono completi;
- il target prestazionale dichiarato per una settimana completa è misurato e rispettato.

## Milestone 6 — Sensori e separazione oracle/observable

### Responsabilità

Proiettare la realtà completa della simulazione in osservazioni realistiche senza
trasferire nel dataset informazioni oracle non misurabili dai dispositivi.

### Contenuto

- contratto versionato del sensor model e del log osservabile;
- supporto completo dei tipi di sensore scelti per i dataset di riferimento, almeno
  movimento/PIR, contatto/porta e temperatura;
- posizione, copertura, latenza, cooldown, jitter, dropout, falsi positivi, falsi negativi
  e guasti secondo le capacità di ciascun tipo;
- valutazione event-driven delle traiettorie e delle transizioni di oggetti e ambiente;
- stream casuale indipendente per ogni sensore;
- oracle mapping separato tra osservazioni, cause, persone, azioni e attività;
- report di proiezione con conteggi, perdite, rumore e provenance.

### Fuori perimetro

- modifica del comportamento dei residenti sulla base di informazioni oracle;
- identificatori di persona o attività nei record di dispositivi che non possono
  osservarli;
- tipi di sensore non dichiarati nel catalogo versionato della milestone.

### Definition of done

- ogni tipo dichiarato implementa integralmente semantica nominale, temporizzazione e
  modello d'errore;
- i log osservabili non contengono identificatori oracle vietati;
- ogni record osservabile può essere ricondotto separatamente alle cause simulate;
- rumore e perdita sono riproducibili e non modificano gli eventi comportamentali;
- schema, checksum, esempi, golden log, test, lint, benchmark e copertura minima
  obbligatoria del 95% sono completi.

## Milestone 7 — Applicazione UI, workspace, export e replay

### Responsabilità

Consegnare un'applicazione moderna con cui il ricercatore possa usare senza CLI tutte le
funzioni disponibili fino alla Milestone 7: creare e organizzare ambienti e residenti,
importare, validare e configurare gli input, avviare e seguire simulazioni, ispezionare i
risultati, effettuare replay ed esportare dataset riproducibili. La UI è un client dei
medesimi contratti e servizi applicativi usati dalla CLI e non introduce semantica
alternativa né aggira alcun gate.

### Contenuto

- shell applicativa desktop-first, moderna, accessibile e adattabile alle comuni
  risoluzioni, con navigazione coerente, tema chiaro/scuro e stati vuoti, di caricamento e
  di errore completi;
- workspace persistente con dashboard dei recenti, ricerca e filtri, organizzato per
  ambiente domestico; ogni casa raggruppa residenti, scenari, modelli comportamentali,
  configurazioni sensoriali, bundle ed esecuzioni, inclusi ambienti multi-residente;
- flussi guidati di creazione, importazione e modifica con validazione progressiva, errori
  collegati ai campi o agli elementi grafici e pubblicazione atomica soltanto dopo gli
  stessi gate autorevoli delle milestone precedenti;
- configuratore grafico 2D dell'ambiente per stanze e aree esterne, geometrie, porte,
  passaggi, ostacoli, punti di interazione, oggetti, risorse, capacità, stato iniziale e
  vincoli di accesso, con anteprima di connettività e percorsi;
- configuratore visuale dei sensori con catalogo dei tipi supportati, posizionamento sulla
  planimetria, orientamento e copertura, parametri temporali, rumore, dropout, guasti e
  verifica immediata della validità del sensor model;
- centro simulazioni con coda locale, avvio, annullamento sicuro, dettaglio delle fasi,
  progresso reale, conteggi, tempi trascorsi, log strutturati ed esiti
  `queued/running/completed/failed/cancelled`;
- viste per simulazioni in corso e recenti, raggruppate per ambiente, con confronto fra
  configurazione, seed, residenti, stato, warning e artefatti prodotti;
- writer streaming per JSONL, CSV e XES;
- esportazioni separate per log osservabile, oracle, tracce, piano/esecuzione e stato
  finale;
- manifest con schemi, versioni, digest, seed e relazioni fra file;
- replay deterministico dell'esecuzione da artefatti persistiti;
- debugger visuale sincronizzato fra timeline, planimetria, residenti, attività, azioni,
  traiettorie, stato, risorse e sensori, con separazione esplicita fra vista osservabile e
  dati oracle;
- import ed export dall'interfaccia con controlli di integrità, compatibilità, anteprima
  del manifest e messaggi di errore completi, senza artefatti parziali;
- guida minimale integrata: primo avvio, percorso rapido fino alla prima simulazione,
  spiegazioni contestuali dei concetti e collegamenti alla documentazione tecnica;
- service layer applicativo versionato e indipendente dalla tecnologia UI, gestione
  robusta dei processi in background e persistenza transazionale del workspace;
- test unitari, di componente, integrazione ed end-to-end, regressione visuale,
  accessibilità da tastiera e benchmark delle viste e dei workspace di accettazione.

La scelta fra applicazione web locale, desktop shell o altra tecnologia frontend viene
presa con un ADR all'inizio della milestone. Il contratto del service layer, il formato
del workspace e la separazione tra UI e motore devono restare indipendenti dal framework.

### Fuori perimetro

- rendering 3D o motore fisico usato come fonte autorevole della simulazione;
- collaborazione cloud multiutente, account remoti e sincronizzazione fra installazioni;
- app mobile nativa;
- editor generico che permetta di bypassare schemi, cataloghi o validatori;
- comandi UI per feature non ancora implementate, in particolare esecuzione annuale e
  calibrazione, che vengono aggiunti dalle rispettive milestone successive.

### Definition of done

- l'intero flusso M1–M7, dalla creazione o importazione degli input al replay e all'export,
  è completabile dalla UI senza ricorrere alla CLI o modificare manualmente JSON;
- la casa golden può essere ricostruita o importata nel configuratore, validata e salvata
  senza perdita semantica; porte, ostacoli, capacità e percorsi errati sono evidenziati
  direttamente sulla planimetria;
- tutti i tipi di sensore M6 possono essere posizionati e configurati visualmente e la UI
  distingue sempre campi osservabili e oracle;
- una simulazione può essere avviata, monitorata e annullata; avanzamento e stato mostrati
  derivano da eventi reali del backend e sopravvivono al riavvio dell'interfaccia;
- dashboard e viste recenti raggruppano correttamente bundle ed esecuzioni per casa e
  supportano almeno un ambiente con più residenti;
- errori di validazione, incompatibilità e fallimenti runtime sono comprensibili,
  localizzabili e non lasciano workspace o output presentati come validi;
- tutti i formati dichiarati effettuano round-trip senza perdita dei campi di competenza;
- file grandi vengono prodotti in streaming senza trattenere l'intero dataset in memoria;
- il replay ricostruisce lo stesso digest semantico dell'esecuzione originale;
- nessun export osservabile incorpora accidentalmente oracle data;
- i principali flussi sono utilizzabili con tastiera, hanno focus e contrasto verificati e
  non dipendono esclusivamente dal colore per comunicare stato o validità;
- refresh, chiusura o crash della UI non corrompono configurazioni, simulazioni o export;
- service layer, formato workspace, schemi, checksum, guida, esempi, golden export, test,
  lint, benchmark e copertura minima obbligatoria del 95% sono completi.

## Milestone 8 — Esecuzione longitudinale

### Responsabilità

Eseguire orizzonti successivi preservando lo stato reale della simulazione. Gli scenari
restano artefatti prodotti all'esterno da un essere umano, un generatore a regole o un LLM;
il runtime non richiede né invoca un LLM.

### Contenuto

- contratto versionato di handoff dello stato fra orizzonti;
- rolling horizon con continuità di attività, fatti, inventario, risorse e causalità;
- validazione e compilazione di ogni nuovo orizzonte contro lo stato effettivo precedente;
- gestione esplicita dei confini temporali e delle attività che li attraversano;
- stream casuali stabili fra settimane e indipendenti fra repliche;
- esecuzioni annuali e repliche Monte Carlo isolate e riproducibili;
- output streaming e checkpoint recuperabili senza alterare la semantica;
- integrazione nella UI M7 per configurare rolling horizon e repliche, monitorare lavori
  lunghi, mostrare checkpoint e riprendere esecuzioni interrotte.

### Definition of done

- una simulazione annuale non introduce reset impliciti ai confini settimanali;
- un'esecuzione interrotta e ripresa da checkpoint coincide semanticamente con quella
  continua;
- repliche e stream casuali non si contaminano fra loro;
- il target prestazionale annuale è misurato e rispettato sul caso di accettazione;
- i flussi longitudinali sono gestibili end-to-end dalla UI senza perdere la possibilità
  di eseguirli headless;
- contratti, esempi, golden handoff, test, lint, benchmark e copertura minima obbligatoria
  del 95% sono completi.

## Milestone 9 — Calibrazione e valutazione sperimentale

### Responsabilità

Valutare con procedure riproducibili quali proprietà dei dataset sintetici sono garantite
per costruzione e quali risultano plausibili rispetto ai dati reali di riferimento.

### Contenuto

- protocollo sperimentale versionato e separazione fra calibrazione, validazione e test;
- confronto di distribuzioni temporali, transizioni spaziali, pattern sensoriali,
  frequenze delle attività e variabilità inter- e intra-persona;
- metriche di fedeltà dei processi e delle tracce senza imporre le etichette dei dataset
  esterni come tassonomia autorevole del simulatore;
- valutazione di rumore, copertura, casi rari, anomalie e concorrenza;
- verifica dell'utilizzabilità degli export da parte di strumenti esterni di activity
  recognition e process mining;
- esperimenti riproducibili, risultati versionati e rapporto finale con limiti espliciti;
- viste UI per configurare protocolli, seguire esperimenti e consultare metriche e confronti
  senza trasformare la UI nella fonte autorevole dei risultati.

### Definition of done

- ogni risultato dichiarato è riproducibile da configurazioni e script versionati;
- dati di calibrazione e valutazione restano separati;
- configurazione ed esplorazione dei risultati sono disponibili sia via UI sia headless;
- il rapporto distingue correttezza per costruzione, plausibilità empirica e limiti;
- dataset, configurazioni, metriche, risultati e provenance sono completi e verificati.
