# Valutazione A/B di Qwen3.5 9B DeepSeek V4 Flash

## Obiettivo

Confrontare `qwen3.5-9b-deepseek-v4-flash` con la precedente prova di
`qwen2.5-coder-7b-instruct` sullo stesso task settimanale, isolando il più possibile il
cambio di modello.

## Disegno approvato

- Riutilizzare il prompt `generate-simulation-inputs-1.2.1-simplified.md` senza modifiche.
- Riutilizzare la stessa descrizione controllata di Mario Rossi, cambiando esclusivamente
  il modello dichiarato nella provenance.
- Eseguire tre run con seed 101, 202 e 303, temperatura `0.2`, top-p `0.9`, top-k `40` e
  massimo 24.000 completion token.
- Non usare structured output, JSON schema, repair o modifiche manuali, per mantenere il
  confronto A/B con la prova 7B.
- Conservare richieste, risposte grezze, tempi, token, finish reason e configurazione
  esposta da LM Studio.
- Eseguire parsing, ingestion e simulazione soltanto sugli output grezzi che superano i gate
  precedenti. Eventuali estrazioni diagnostiche devono essere marcate come non accettate.

## Interpretazione

Il 9B è migliore del 7B se aumenta concretamente formato valido, copertura del caso,
varietà settimanale, correttezza temporale e avanzamento nella pipeline. Per essere
sufficiente all'uso assistito deve ottenere almeno due run end-to-end su tre senza anomalie
qualitative critiche; per candidarsi all'uso non supervisionato deve ottenerne tre su tre.

Il verdetto resta specifico per la variante community DeepSeek V4 Flash, quantizzazione
`Q3_K_M`, contesto attivo 32.256 e workflow monolitico one-shot.
