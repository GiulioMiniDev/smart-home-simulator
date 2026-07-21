# Esperimento di authoring locale e simulazione end-to-end — Mario Rossi, 7 giorni

- Data dell'esperimento: 2026-07-21
- Commit che ha introdotto gli output: `5d4f497a0b59d3170a107ed8d21d395d6593c4d8`
- Prompt usato: [`generate-simulation-inputs-1.2.0-simplified.md`](../../prompts/generate-simulation-inputs-1.2.0-simplified.md)
- SHA-256 del prompt: `5a7d7900b1fe59651eb006f76b858faee65cf85db73a77ba6244af2803a13295`
- Modello dichiarato: `Qwen2.5-Coder-7B-Instruct`, GGUF `Q4_K_M`
- Stato: **ingestion, materializzazione e simulazione completate con zero errori e warning**

## 1. Obiettivo e corretta interpretazione

L'esperimento verifica che un LLM locale da 7B parametri possa produrre un
`SimulationAuthoringBundle` settimanale capace di attraversare l'intera pipeline
deterministica senza modifiche al codice Python, agli schemi, ai cataloghi o ai validatori.

È un **test funzionale end-to-end di authoring locale su sette giorni**, non uno stress test
prestazionale: non furono registrati tempo di inferenza, memoria di picco o throughput e il
caso contiene 98 attività, meno delle 173 attività del golden settimanale del progetto.

Il benchmark Marco di due giorni è mantenuto come confronto quantitativo. Non è una seconda
prova completa di first-pass authoring, perché la sua risposta LLM grezza accettata e il suo
ingestion report non furono conservati.

## 2. Configurazione registrata e limiti di provenance

La configurazione riportata dall'operatore è:

- piattaforma originale: Windows 11 Home 64-bit;
- shell: PowerShell 7;
- Python: `3.13.x` — patch version non registrata;
- engine: LM Studio — versione non registrata;
- modello: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`;
- file: `qwen2.5-coder-7b-q4_k_m.gguf`;
- temperatura: `0.2`;
- top-p: `0.9`;
- top-k: `40`.

Non furono registrati il context length esatto, il numero di layer offloaded, i log completi
di PowerShell, la descrizione originale dei casi, il numero di tentativi o repair e
l'eventuale presenza di modifiche manuali prima dell'ingestion. Non è quindi corretto
affermare che l'output fu certamente accettato al primo tentativo o non modificato a mano.
Il campo `humanReviewed: false` del bundle descrive la provenance dichiarata dal documento,
ma non sostituisce questi dati sperimentali mancanti.

I dati disponibili e quelli non conservati sono registrati in
[`generation-metadata.json`](../../generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/generation-metadata.json).

## 3. Ordine e localizzazione degli artefatti

La prova è isolata sotto
[`generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/`](../../generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/README.md).

Per Mario la catena è completa e ordinata:

```text
mario-7d/authoring-bundle.json
  -> mario-7d/ingestion-report.json
  -> mario-7d/ingested/scenario.json
  -> mario-7d/ingested/personal-process-package.json
  -> mario-7d/simulation/
```

La directory finale contiene 17 artefatti elencati dal manifest più
`workspace-manifest.json`, quindi 18 file fisici. Il vecchio output incompleto
`generated/mario_week_temp/` non fa parte dell'esperimento.

La directory [`marco-2d/`](../../generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/marco-2d/README.md)
contiene gli input ingested e la simulazione, ma documenta esplicitamente la risposta grezza
mancante. La prima risposta Marco rifiutata è conservata separatamente in
[`failed-trials/`](../../generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/failed-trials/README.md)
con il relativo report da 64 errori; non è la sorgente del benchmark valido.

## 4. Gate superati e verifica cross-platform

Il bundle Mario è stato ricontrollato con:

```bash
PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim ingest-authoring-output \
  generated/experiments/2026-07-21-qwen2.5-coder-7b-q4km/mario-7d/authoring-bundle.json \
  --output-dir <directory-temporanea>/ingested \
  --format json \
  --report-output <directory-temporanea>/ingestion-report.json

PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim run-synthetic \
  <directory-temporanea>/ingested/scenario.json \
  <directory-temporanea>/ingested/personal-process-package.json \
  --output-dir <directory-temporanea>/simulation
```

Risultati verificati:

| Gate | Esito |
|---|---:|
| Sintassi ed envelope Pydantic | superato |
| Validazione scenario | 0 errori, 0 warning |
| Compilazione | `OPTIMAL`, 98 attività pianificate |
| Validazione comportamentale | 0 errori, 0 warning |
| Ingestion atomica | 2 artefatti pubblicati |
| Materializzazione casa e binding | superata |
| Simulazione | 98/98 attività completate |
| Proiezione sensoriale | 11.340 osservazioni |
| Manifest | 17/17 digest canonici coerenti |

Gli artefatti attribuiti all'esecuzione Windows sono stati rigenerati su macOS con Python
3.12.13. Tutti i 17 artefatti sono risultati strutturalmente e canonicalmente identici e il
manifest è identico. Questo fornisce una verifica concreta della deterministica
cross-platform, pur restando assenti i log terminali originali di Windows.

## 5. Risultati di simulazione

| Metrica | Mario, 7 giorni | Marco, 2 giorni | Variazione |
|---|---:|---:|---:|
| Attività completate | 98/98 | 15/15 | 100% entrambi |
| Attività fallite / dropped | 0/0 | 0/0 | invariato |
| Azioni eseguite | 487 | 75 | +549,3% |
| Movimenti | 86 | 12 | +616,7% |
| Transizioni di stato | 647 | 95 | +581,1% |
| Errori / warning | 0/0 | 0/0 | invariato |

Il catalogo autorevole contiene 27 action type. I 15 process model Mario ne usano 21. Il
bundle contiene 20 binding perché alcuni flussi realmente identici sono riutilizzati da più
intent, comportamento ammesso dal simulatore.

## 6. Telemetria sensoriale

| Metrica | Mario, 7 giorni | Marco, 2 giorni |
|---|---:|---:|
| Osservazioni totali | 11.340 | 2.082 |
| Media osservazioni/giorno | 1.620 | 1.041 |
| Sensori installati | 12 | 10 |
| Sensori con almeno un'osservazione | 12 | 9 |
| PIR | 7.914 | 1.306 |
| Temperatura | 3.360 | 768 |
| Contatto | 66 | 8 |

Conteggi giornalieri Mario:

| Data | Osservazioni |
|---|---:|
| 2026-10-30 | 1.662 |
| 2026-10-31 | 1.578 |
| 2026-11-01 | 1.586 |
| 2026-11-02 | 1.570 |
| 2026-11-03 | 1.604 |
| 2026-11-04 | 1.662 |
| 2026-11-05 | 1.678 |

La maggiore densità non dimostra da sola maggiore realismo: deriva dalla casa generata, dal
numero di sensori, dalla durata delle azioni e dalla policy di campionamento.

## 7. Valutazione qualitativa e anomalie note

La prova rappresenta un miglioramento netto rispetto al trial fallito: action type,
componenti, grafi, movimento, argomenti e binding sono formalmente corretti. La validità
formale non rende però il comportamento automaticamente realistico.

Anomalie presenti nell'output, lasciato intenzionalmente invariato:

1. Ogni attività `sleep` ha durata preferita di **30 minuti**, con intervallo 20-45 minuti.
   È incompatibile con un normale sonno notturno.
2. `short_evening_walk` è collocata alle 10:30 del mattino e usa `neighborhood_bar` come
   location, nonostante l'intent descriva una passeggiata serale.
3. `wash_breakfast_dishes` è pianificata alle 13:30, dopo il pranzo anziché dopo la
   colazione.
4. Mario assume una terapia ogni mattina, ma il profilo del residente non registra una
   condizione o una terapia che motivi l'attività.
5. Tutti i giorni contengono esattamente 14 attività e differiscono quasi soltanto per una
   singola attività di metà mattina; la varietà settimanale è limitata.
6. `generatedAt` è `2026-10-29T20:00:00+01:00`, futuro rispetto alla data reale
   dell'esperimento. È coerente con la cronologia simulata, ma non è una provenance reale.

Queste anomalie non richiedono modifiche al simulatore. Sono diventate guardrail espliciti
nel nuovo prompt sperimentale
[`generate-simulation-inputs-1.2.1-simplified.md`](../../prompts/generate-simulation-inputs-1.2.1-simplified.md),
mentre il prompt 1.2.0 usato per questa prova resta immutato e verificabile tramite digest.

## 8. Conclusione

L'obiettivo tecnico è raggiunto: un bundle attribuito a Qwen 2.5 Coder 7B attraversa
ingestion, compilazione, validazione comportamentale, generazione della casa, simulazione e
sensori, producendo lo stesso workspace verificato su Windows e macOS.

Il risultato non dimostra ancora robustezza statistica del prompt né realismo del dataset.
Per sostenere queste affermazioni servono descrizioni sorgente conservate, metadata completi,
più generazioni indipendenti e metriche qualitative su sonno, pasti, terapia, varietà e
coerenza temporale.

## 9. Follow-up controllato con il prompt 1.2.1

Il 2026-07-21 è stata eseguita una nuova serie di tre generazioni con lo stesso modello
locale dichiarato, `Qwen2.5-Coder-7B-Instruct Q4_K_M`, e il prompt
`generate-simulation-inputs-1.2.1-simplified.md`. Poiché la descrizione originale di questa
prova storica non era stata conservata, il follow-up usa un nuovo caso Mario controllato e
salvato: non è presentato come replica esatta.

Risultato del follow-up:

| Controllo | Esito |
|---|---:|
| Generazioni indipendenti | 3 |
| JSON grezzo valido | 0/3 |
| Ingestion valida | 0/3 |
| Simulazione completata | 0/3 |
| Giorni con sequenze diverse nelle run parsabili | 1/7 |

Il prompt nuovo corregge localmente sonno, farmaci e timestamp, ma Qwen 7B ignora ancora il
divieto di Markdown, omette gran parte del caso, ripete giornate identiche e confonde intent,
componenti e azioni primitive. Le run si fermano spontaneamente usando soltanto il 34–70%
del contesto da 32K; il fallimento non è spiegato da un limite di output imposto dal server.

La conclusione aggiornata è quindi che il bundle storico valido era un risultato funzionale
isolato, non evidenza che il 7B sia sufficiente per output settimanali soddisfacenti. Nel
workflow monolitico one-shot questa configurazione è **non consigliata**. Protocollo,
artefatti, analisi e standard per i modelli successivi sono documentati in
[`authoring-prompt-1.2.1-local-qwen2.5-7b.md`](authoring-prompt-1.2.1-local-qwen2.5-7b.md).
