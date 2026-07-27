# Guida all'authoring locale con LLM 7B–8B

## Scopo

Il simulatore accetta un `SimulationAuthoringBundle` composto da `scenario` e
`personalProcessPackage`. Un modello locale può generare questo bundle, ma il risultato è
accettato soltanto dopo i gate deterministici di ingestion e simulazione.

Questo documento descrive il percorso **one-shot**: un prompt unico inviato a mano a un LLM
esterno. La pipeline di generazione locale, che invece orchestra LM Studio in più stadi
deterministicamente validati, è un percorso distinto ed è descritta in
`docs/spec/13-local-generation-pipeline.md`.

Sul percorso one-shot il runtime non integra alcun provider: la chiamata al modello resta
esterna al simulatore e nessuno script la automatizza o autoripara le risposte.

## Prompt disponibili

- `prompts/generate-simulation-inputs-1.3.0.md`: prompt completo e autorevole corrente. È il
  `1.2.0` più la sezione generata «Mandatory action state continuity»: tabella di precondizioni
  ed effetti resa dal catalogo azioni `1.0.0`, registro cronologico che attraversa attività e
  giorni, e ponte obbligatorio per il componente `travel` eseguito fuori casa (ADR-017);
- `prompts/generate-simulation-inputs-1.2.0.md`: revisione storica completa, congelata perché
  la terza prova esterna resti riproducibile. Valida schema, compilazione e comportamento, ma
  non insegna il contratto di stato: la prova del 2026-07-27 è stata respinta da quattro
  `DETERMINISTIC_PRECONDITION_FAILED`;
- `prompts/generate-simulation-inputs-1.2.0-simplified.md`: versione compatta usata nella
  prova Qwen del 2026-07-21;
- `prompts/generate-simulation-inputs-1.2.1-simplified.md`: revisione storica con guardrail
  di plausibilità e provenance, non più consigliata;
- `prompts/generate-simulation-inputs-1.2.2-simplified.md`: revisione storica ancorata al
  catalogo attività `1.0.0`, quindi al vocabolario di intenti che nominava persone private;
- `prompts/generate-simulation-inputs-1.2.3-simplified.md`: versione compatta corrente.
  Non si modifica a mano: è **generata** da
  `prompts/templates/generate-simulation-inputs-1.2.3-simplified.template.md` e dai cataloghi
  congelati con `make authoring-artifacts`. Le sezioni 4, 5, 5.1, 6 e il registro della 7
  sono rese dal catalogo attività `1.2.0`, dal catalogo azioni `1.1.0` e dai 24 modelli di
  processo di riferimento `1.2.0`; un test confronta il file committato con una resa fresca,
  quindi il prompt non può più divergere in silenzio dai contratti.

La 1.2.3 è la prima versione allineata alla pipeline di generazione locale: entrambi i
percorsi etichettano ora i dataset con lo stesso vocabolario neutro, condizione necessaria
perché il confronto fra i due sia leggibile. La sezione 5.1 mostra inoltre i modelli già
provati in simulazione invece del solo minimo imposto dal validatore: il minimo non apre il
contenitore da cui il residente prende un oggetto, quindi valida senza errori ma non fa mai
scattare il sensore di contatto.

Il prompt completo `1.3.0` misura 109.035 byte, il `1.2.0` 103.153. Il prompt semplificato
1.2.0 usato nella prova ne misura 24.717: una riduzione del 75,9% per byte rispetto al
completo dell'epoca. Le riduzioni in token devono essere misurate
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

1. Scegliere un prompt. La guida integrata dell'app inserisce localmente la descrizione del
   caso e, per la versione 1.2.2, un timestamp ISO corrente. Usando direttamente il file,
   sostituire `[PERSON_AND_CASE_DESCRIPTION]` e `[GENERATION_TIMESTAMP]` prima di inviarlo
   al modello.
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
