# Roadmap

Ogni milestone è una feature autonoma con contratto, test e criterio di completamento. Una milestone successiva non deve introdurre logica nella precedente né modificarne retroattivamente le responsabilità senza una decisione architetturale esplicita.

| Milestone | Feature | Input | Output verificabile | Stato |
|---:|---|---|---|---|
| 0 | Specifica e confini | proposta di ricerca | contratti e invarianti | Completata |
| 1 | Motore di validazione | scenario JSON | validation report | **Completata e congelata — 1.0.0** |
| 2 | Compilatore del piano | scenario valido | canonical daily plan | **Completata e congelata — 1.0.0** |
| 3 | Motore di simulazione | canonical plan | abstract execution trace | Non iniziata |
| 4 | Ambiente topologico | trace + home graph | transizioni tra luoghi | Non iniziata |
| 5 | Planimetria 2D | topologia + geometria | traiettorie spazio-temporali | Non iniziata |
| 6 | Microesecuzione | attività + ambiente | azioni e interazioni atomiche | Non iniziata |
| 7 | Sensori | traccia effettiva | observable sensor log | Non iniziata |
| 8 | Export e replay | output interni | JSONL/CSV/XES e debugger | Non iniziata |
| 9 | Longitudinale e LLM | stato persistente | settimane e ripianificazioni | Non iniziata |
| 10 | Calibrazione | dati reali e sintetici | rapporto sperimentale | Non iniziata |

## Milestone 0 — Specifica e confini

### Criteri di completamento

- scenario, piano canonico, traccia eseguita e osservazioni sono concetti distinti;
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

## Regola di avanzamento

La regola di avanzamento è soddisfatta: `scenario-1.0.0.schema.json` è congelato e la settimana di Mario Rossi, composta da 7 giorni e 173 attività, è un acceptance test valido. Qualunque estensione futura del contratto richiede una nuova versione secondo ADR-002; non riapre né muta `1.0.0`.

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
- suite completa, lint e copertura minima del 95% passano.

La regola di avanzamento della Milestone 2 è soddisfatta dai contratti congelati in ADR-003 e dalla compilazione golden di `examples/valid/mario_week.json`.
