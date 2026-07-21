# Esperimento locale Qwen 2.5 Coder 7B Q4_K_M — 2026-07-21

Questa directory raccoglie esclusivamente gli artefatti dell'esperimento sul prompt
semplificato per LLM locali. Le fixture golden del simulatore restano nelle loro directory
storiche e non dipendono da questi risultati.

## Contenuto

- `generation-metadata.json`: configurazione registrata, dati mancanti e verifica
  cross-platform;
- `prompt-used.sha256`: digest del prompt effettivamente associato alla prova;
- `mario-7d/`: catena completa e valida dalla risposta LLM al workspace sintetico;
- `marco-2d/`: benchmark di confronto i cui due input ingested sono disponibili, ma la cui
  risposta LLM grezza non è stata conservata;
- `failed-trials/`: prima risposta Marco rifiutata e relativo ingestion report.

Il report scientifico è in
`docs/evaluation/esperimento_simulazione_7giorni_mario_rossi.md`.

## Ordine degli artefatti

Per Mario la pipeline documentata è:

```text
authoring-bundle.json
  -> ingestion-report.json + ingested/{scenario,personal-process-package}.json
  -> simulation/{17 artefatti verificati + workspace-manifest.json}
```

Il manifest elenca 17 artefatti. La directory `simulation/` contiene quindi 18 file fisici
includendo il manifest stesso.

