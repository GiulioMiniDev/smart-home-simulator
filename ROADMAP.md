# Roadmap

Ogni milestone è una feature autonoma con contratto, test e criterio di completamento. Una milestone successiva non deve introdurre logica nella precedente né modificarne retroattivamente le responsabilità senza una decisione architetturale esplicita.

| Milestone | Feature | Input | Output verificabile | Stato |
|---:|---|---|---|---|
| 0 | Specifica e confini | proposta di ricerca | contratti e invarianti | Completata |
| 1 | Motore di validazione | scenario JSON | validation report | Implementata, da revisionare |
| 2 | Compilatore del piano | scenario valido | canonical daily plan | Non iniziata |
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

- schema versionato `0.1.0`;
- modelli Pydantic strict-by-default;
- validazione strutturale, referenziale, temporale e semantica iniziale;
- rapporto testuale e JSON;
- JSON Schema distribuibile;
- esempi validi e invalidi;
- codici di errore stabili;
- test di accettazione della CLI.

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
- nessuna dipendenza da SimPy, NetworkX o librerie grafiche.

## Regola di avanzamento

La Milestone 2 inizierà soltanto dopo aver congelato `scenario-0.1.0.schema.json` e aver validato almeno uno scenario settimanale rappresentativo.
