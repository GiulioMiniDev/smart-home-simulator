# Lucia Rossi — agosto 2026

Simulazione mensile generata usando
`prompts/generate-simulation-inputs-1.2.1-simplified.md` come contratto di authoring.

## Caso

- periodo: 1–31 agosto 2026, `Europe/Rome`;
- residente: Lucia Rossi, 45 anni, figlia di Mario;
- abitazione logica: casa di Mario a Monteverde (`home_mario_monteverde`);
- lavoro: impiegata amministrativa ibrida, con ferie dal 10 al 21 agosto;
- salute: nessuna condizione o terapia inventata.

## Risultato verificato

- 31 `DayPlan` e 411 attivita, tutte compilate e completate;
- 23 sequenze giornaliere di intent distinte;
- 29 process model deduplicati e 37 binding;
- 1.896 azioni, 909 movimenti e 3.773 transizioni di stato;
- 54.701 osservazioni sensoriali;
- 17 artefatti nel workspace transazionale;
- replay deterministico coincidente.

## Artefatti principali

- `authoring-bundle.json`: output completo conforme all'envelope del prompt 1.2.1;
- `case-description.md`: descrizione del caso e timestamp reale di generazione;
- `ingestion-report.json`: ingestion authoring valida, senza errori;
- `canonical-inputs/`: scenario e process package pubblicati dall'ingestor;
- `runtime-inputs-1.1.0/`: copia migrata alle semantiche runtime rigorose;
- `simulation-1.1.0/`: workspace finale con scenario, casa, piano, bundle, trace,
  sensori, report e manifest.

## Compatibilita applicata

Il prompt compatto 1.2.1 contiene tre riferimenti legacy incompatibili con i contratti
effettivi del repository:

1. elenca operazioni `laundry_step` diverse dall'enum del catalogo 1.0.0;
2. fissa `homeModel.version` a `1.0.0`, mentre Casa Monteverde dichiara
   `mario-apartment-0.1-example`;
3. usa il componente `travel` 1.0.0, che include sempre `leave_home` e non e eseguibile
   correttamente nei viaggi di rientro sotto le precondizioni runtime rigorose.

L'authoring usa gli enum autorevoli e la versione reale della casa. Dopo l'ingestion, una
copia separata viene migrata ai cataloghi comportamentali 1.1.0 con
`tools/migrate_lucia_runtime_1_1.py`. L'output authoring originale resta conservato e non
viene riscritto dalla migrazione.

## Riproduzione

```powershell
python tools/build_lucia_august_2026_authoring.py
smart-home-sim ingest-authoring-output `
  generated/lucia_rossi_august_2026/authoring-bundle.json `
  --output-dir generated/lucia_rossi_august_2026/canonical-inputs
python tools/migrate_lucia_runtime_1_1.py
smart-home-sim run-synthetic `
  generated/lucia_rossi_august_2026/runtime-inputs-1.1.0/scenario.json `
  generated/lucia_rossi_august_2026/runtime-inputs-1.1.0/personal-process-package.json `
  --output-dir generated/lucia_rossi_august_2026/simulation-1.1.0
```
