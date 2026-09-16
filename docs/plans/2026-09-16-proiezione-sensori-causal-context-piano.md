# Proiezione dei sensori: `_causal_context` ricostruisce l'indice a ogni chiamata — piano

- Data: 2026-09-16
- Stato: **implementato e verificato** il 2026-09-16 (non ancora committato). La run di verifica
  `job_ed4aa28e166a4fec` (stessi input, seed 1) ha prodotto i 19 JSON byte-identici a
  `job_c9f6508e6a6949c2`. La proiezione è scesa da 83 a 23 minuti, la run intera da 1 h 55 a 58 min.
- Emerso osservando con `py-spy` il job `job_c9f6508e6a6949c2` (Bellini–Rinaldi, Bologna, un
  anno, casa su due piani, 45 sensori). La simulazione deterministica ha impiegato ~26 min, la
  proiezione dei sensori oltre un'ora.

---

## 1. Il problema

`sensors/service.py:241`, `_causal_context(trace, cause_id)`, costruisce a ogni chiamata due
dizionari sull'intera traccia:

```python
actions = {item.action_execution_id: item for item in trace.action_executions}
activities = {item.activity_execution_id: item for item in trace.activity_executions}
```

Viene chiamata una volta per ogni evento che ha una causa simulata:

- `_contact_candidates` (riga ~798), una volta per ogni transizione di stato del sensore;
- `_temperature_candidates` (riga ~1035), una volta per ogni campione riportato che ha un delta
  dietro;
- un terzo chiamante alla riga ~1073.

Il costo è quindi *(eventi causati) × (azioni + attività)*: quadratico nella dimensione della
traccia. In ogni campione `py-spy` il thread stava dentro `_causal_context`, alle righe 245–246.

| run | azioni | transizioni | traccia | esecuzione | proiezione |
|---|---:|---:|---:|---:|---:|
| `job_a71275e35fa84dc4` (un residente) | — | — | 68 MB | ~7 min | ~11,5 min |
| `job_c9f6508e6a6949c2` (due residenti, 1 anno) | 93 108 | 230 468 | 230 MB | ~26 min | > 70 min |

Il ciclo per sensore in sé è lineare: a pesare è solo la ricostruzione dei dizionari. Il problema
era già stato notato tra i "residui piccoli" della memoria sulla velocità della pipeline. Con una
casa multi-residente lungo un anno smette di essere piccolo.

## 2. La correzione

1. Costruire l'indice **una volta sola** per traccia, in `project_sensors`, subito accanto a
   `_motion_pulses`: un piccolo oggetto `_CausalIndex` (o due dict) con `actions` e `activities`.
2. Passarlo a `_sensor_candidates` → `_contact_candidates` / `_temperature_candidates` / il terzo
   chiamante, e far diventare `_causal_context(index, cause_id)` una semplice lookup.
3. Togliere la variabile `activity` non usata alla riga 249.
4. Nessun cambiamento di semantica: stesso ordine, stessi identificativi, stessi stream casuali.
   L'output deve restare **byte-identico**.

In alternativa si può memoizzare per identità di `trace`, ma è meno leggibile. Meglio passare
l'indice in modo esplicito, come già si fa con `motion`.

## 3. Verifica

- A/B sui digest degli artefatti, come nelle fasi precedenti di velocizzazione: rigenerare
  `observable-sensor-log.json`, `oracle-mapping.json` e `sensor-projection-report.json` su un run
  esistente, prima e dopo, e confrontare gli SHA-256. Candidato: `job_a71275e35fa84dc4`, che è
  veloce. Poi misurare il guadagno su `job_c9f6508e6a6949c2`, se è terminato.
- Test esistenti di `tests/` sulla proiezione dei sensori (usare `PYTHONPATH=src`, non la copia
  installata).
- Ricordarsi che l'app gira dal venv in `~/.smart-home-simulator/venv`: la correzione arriva lì solo
  dopo aver reinstallato il pacchetto.

## 3b. Secondo collo di bottiglia, trovato durante la verifica

Il primo A/B, con il solo indice delle cause, è rimasto più di 28 minuti dentro `_motion_pulses`,
prima ancora del ciclo sui sensori. Il punto era `_resting_at`: per ogni impulso di presenza scorreva
dall'inizio l'intera serie `resting_at` del residente, di nuovo con un costo quadratico. Ora usa
`bisect_right(series, moment, key=...)`. La semantica è la stessa: la serie è ordinata in modo
stabile per istante, quindi il risultato è l'ultimo elemento con `at <= moment`. La firma non cambia,
per cui `tests/test_occupancy.py` resta com'è.

## 4. Da controllare nello stesso passaggio

- Il profilo del 2026-09-07 dava `project_sensors` al 44% del run anche con un residente solo.
  Dopo questa correzione conviene ri-misurare prima di cercare altro.
- Dopo il ciclo sui sensori, lo stesso job ha passato altri ~8 minuti a serializzare e calcolare
  digest (`project_sensors` righe 1767–1815): `_canonical_digest(semantic)` due volte, poi
  `canonical_sha256` su log e oracle, poi i validatori `check_links` / `check_records` /
  `check_artifacts` di `contracts/sensors.py` che ri-serializzano gli stessi oggetti. Il digest
  duplicato era già tra i residui annotati; con 230 MB di traccia conta.
- Il run Bellini–Rinaldi riporta 8 416 attività scartate su 20 369 pianificate (41%): non è un
  problema di prestazioni, ma va guardato insieme all'audit dell'export multi-residente.
