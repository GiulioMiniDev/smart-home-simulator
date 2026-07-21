# Guida all'authoring locale con LLM 7B–8B

## Scopo

Il simulatore accetta un `SimulationAuthoringBundle` composto da `scenario` e
`personalProcessPackage`. Un modello locale può generare questo bundle, ma il risultato è
accettato soltanto dopo i gate deterministici di ingestion e simulazione.

Il runtime non integra LM Studio né altri provider: la chiamata al modello resta esterna al
simulatore. Nel repository non sono presenti script automatici per invocare LM Studio,
autoriparare risposte o generare un intero anno.

## Prompt disponibili

- `prompts/generate-simulation-inputs-1.2.0.md`: prompt completo e autorevole;
- `prompts/generate-simulation-inputs-1.2.0-simplified.md`: versione compatta usata nella
  prova Qwen del 2026-07-21;
- `prompts/generate-simulation-inputs-1.2.1-simplified.md`: revisione successiva che aggiunge
  guardrail di plausibilità e provenance.

Il prompt completo misura 102.717 byte. Il prompt semplificato 1.2.0 usato nella prova ne
misura 24.717: una riduzione del 75,9% per byte. Le riduzioni in token devono essere misurate
con il tokenizer del modello effettivamente usato.

## Configurazione sperimentale registrata

La prova riuscita ha dichiarato:

- LM Studio;
- Qwen 2.5 Coder 7B Instruct GGUF;
- quantizzazione `Q4_K_M`;
- temperatura `0.2`;
- top-p `0.9`;
- top-k `40`;
- esecuzione originale riportata su Windows 11 con PowerShell 7 e Python `3.13.x`.

Non furono conservati versione di LM Studio, patch version di Python, context length esatto,
GPU offload, prompt del caso, terminal log, numero di tentativi o storia delle eventuali
correzioni manuali. Questi valori non devono essere ricostruiti o presentati come misurati.

## Procedura

1. Scegliere un prompt e sostituire `[PERSON_AND_CASE_DESCRIPTION]` con la descrizione del
   caso.
2. Salvare la descrizione, il prompt o il suo digest e tutti i parametri di inference.
3. Inviare il prompt al modello esterno e salvare la risposta JSON senza modificarla.
4. Eseguire l'ingestion:

```bash
PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  risposta.authoring-bundle.json \
  --output-dir generated/esperimento/ingested \
  --format json \
  --report-output generated/esperimento/ingestion-report.json
```

Il successo richiede exit code `0`, `valid: true`, zero errori e la pubblicazione dei due
input canonici. Il solo parsing Pydantic non è sufficiente.

5. Eseguire la pipeline completa:

```bash
PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim run-synthetic \
  generated/esperimento/ingested/scenario.json \
  generated/esperimento/ingested/personal-process-package.json \
  --output-dir generated/esperimento/simulation
```

Il successo richiede un workspace con 17 artefatti verificati più
`workspace-manifest.json`.

## Risultati documentati

La prima risposta compatta Marco, ambientata nel 2024, superava struttura e compilazione ma
falliva il gate comportamentale con 64 errori. È conservata con il suo ingestion report in
`generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/failed-trials/`.

La prova Mario di sette giorni supera tutti i gate e completa 98 attività su 98. I 17
artefatti prodotti su Windows sono stati rigenerati identici su macOS. Bundle, ingestion
report, workspace, metadata e limiti qualitativi sono raccolti in
`generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/` e analizzati in
`docs/evaluation/esperimento_simulazione_7giorni_mario_rossi.md`.

## Limiti qualitativi osservati

La prova valida contiene comunque sonno di 30 minuti, terapia non motivata dal profilo,
un'attività serale al mattino, lavaggio delle stoviglie della colazione dopo pranzo,
giornate molto ripetitive e un `generatedAt` futuro. Zero errori del simulatore significa
conformità formale, non realismo umano.

Il prompt 1.2.1 introduce controlli espliciti per questi casi. Per dichiarare robusto il
workflow servono più persone, più seed, descrizioni sorgente conservate e una matrice che
riporti first-pass success, repair attempt, errori e valutazione di plausibilità.

## Requisiti consigliati dopo la prova 1.2.1

Tre nuove generazioni con Qwen 2.5 Coder 7B Q4_K_M e prompt 1.2.1 hanno ottenuto 0/3 JSON
grezzi validi, 0/3 ingestion valide e 0/3 simulazioni. Il modello non è quindi consigliato
per il bundle settimanale monolitico one-shot, anche se alcuni guardrail qualitativi sono
migliorati.

Per qualificare un modello alternativo:

- usare almeno tre seed per lo smoke test e almeno dieci casi per una raccomandazione;
- richiedere 100% JSON grezzo valido e almeno 90% first-pass end-to-end nella matrice finale;
- non contare repair o modifiche manuali come successi first-pass;
- usare quantizzazione `Q4_K_M` o migliore;
- usare almeno 32K di contesto attivo, preferibilmente 64K per margine;
- partire, come fascia candidata ancora da validare, da un moderno 14B–16B; valutare una
  classe 30B–32B per l'uso non supervisionato.

Il numero di parametri è un filtro di selezione, non un criterio di accettazione. Anche un
modello più grande deve superare ingestion, simulazione e rubrica qualitativa. Se si resta su
7B, occorre sperimentare un workflow a più fasi con artefatti più piccoli e validazione fra
le fasi, non riusare la prova one-shot come evidenza di affidabilità.
