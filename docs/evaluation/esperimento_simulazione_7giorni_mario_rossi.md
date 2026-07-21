# Report Esperimento: Simulazione Smart Home 7 Giorni (Mario Rossi) & Benchmark 2 Giorni (Marco Rossi)

**Data dell'Esperimento**: 21 Luglio 2026  
**Autore / Pair Programming**: AI Assistant (Antigravity) & Utente  
**Framework**: `smart_home_sim` (Smart Home Behavioral & Environmental Simulator)  
**Versione Prompt**: `v1.2.0-simplified` ([prompts/generate-simulation-inputs-1.2.0-simplified.md](file:///c:/vscode/smart-home-simulator/prompts/generate-simulation-inputs-1.2.0-simplified.md))

---

## 1. Obiettivo dell'Esperimento

Valutare la capacità del sistema di authoring e del motore di simulazione comportamentale di gestire scenari sintetici **ad alto carico (stress test su 7 giorni consecutivi)** per il residente **Mario Rossi** (72 anni, pensionato, Roma), confrontando le prestazioni ed i dati di telemetria prodotte con la simulazione di benchmark su **2 giorni** del residente **Marco Rossi**.

Tutti i dati dell'esperimento sono stati generati rispettando rigidamente la specifica dei prompt semplificati ed eseguiti end-to-end senza alcuna modifica al codice Python del simulatore o ai cataloghi congelati.

---

## 2. Hardware, Piattaforma & Configurazione LM Studio

### 2.1 Ambiente Host & Runtime
* **Sistema Operativo**: Windows 11 Home (Build 64-bit)
* **Shell & Execution**: PowerShell 7 / Python 3.13.x
* **Simulatore**: `smart_home_sim` (CLI e pacchetto di simulazione ad eventi discreti)

### 2.2 Configurazione LM Studio (Inference Engine)
* **Modello LLM di Authoring**: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`
* **Nome File Quantizzato**: `qwen2.5-coder-7b-q4_k_m.gguf`
* **Quantizzazione**: `Q4_K_M` (4-bit medium quantization with 6-bit state tensors)
* **Context Window**: 8.192 – 16.384 token
* **Temperatura**: `0.2` (risposta deterministica orientata al codice JSON)
* **Top-P / Top-K**: `0.9` / `40`
* **CPU/GPU Acceleration**: Offload dei layer su GPU / CUDA / Metal API (dove disponibile)

---

## 3. Specifiche del Prompt Usato (`v1.2.0-simplified`)

Il prompt utilizzato per l'authoring è disponibile al path [prompts/generate-simulation-inputs-1.2.0-simplified.md](file:///c:/vscode/smart-home-simulator/prompts/generate-simulation-inputs-1.2.0-simplified.md).

### 3.1 Regole e Vincoli Rispettati
1. **Separazione Azioni Primitive vs Intenti/Componenti**:
   - `actionType` ammessi soltanto tra i 24 tipi primitivi del catalogo `smart_home_action_catalog` v1.0.0 (es. `move_to`, `take_item`, `put_item`, `leave_home`, `enter_home`, `change_posture`, `prepare_food`, `consume`, `leisure`, `exercise`).
2. **Struttura dei Grafi di Processo (DAG)**:
   - Nodo di `start` → Nodi di movimento (`move_to` / `travel_to`) → Nodi azione con `durationWeight: 1` → Nodo `end`.
3. **Regola dei Precondizioni Item Role (`take_item` / `put_item`)**:
   - `put_item` deve utilizzare lo stesso identico valore di `itemRole` invocato da `take_item` (es. `medication_storage` → `medication_storage` oppure `food_storage` → `food_storage`) per soddisfare il fatto `resident.carrying.{itemRole} == true`.
4. **Ciclo Autocontenuto per Attività Esterne**:
   - Ogni attività che comporta l'uscita dall'abitazione (`buy_groceries`, `walk`, `travel_to_pharmacy`, `travel_to_neighborhood_bar`) esegue la sequenza:  
     `leave_home` (imposta `at_home = false`) → `travel_to` (destinazione) → Azione principale → `move_to_capability` (home_entrance) → `enter_home` (ripristina `at_home = true`).
5. **Copertura 100% Process Binding**:
   - Ogni intento generato nello scenario ha un binding univoco ad un `processModel` corrispondente.

---

## 4. Risultati della Simulazione & Statistiche Comportamentali

La simulazione è stata validata attraverso la pipeline a 6 Gate del simulatore:
- **Gate 0-5 (Ingestion & Authoring Bundle Validation)**: PASSED (0 Errori, 0 Warning)
- **Gate 6 (Synthetic Discrete Event Simulation)**: PASSED (0 Errori, 0 Warning)

### 4.1 Tabella Comparativa (Mario 7 Giorni vs Marco 2 Giorni)

| Metrica di Simulazione | **Mario Rossi (Stress Test 7g)** | **Marco Rossi (Benchmark 2g)** | **Variazione (%)** |
| :--- | :--- | :--- | :--- |
| **Finestra Temporale** | 30/10/2026 – 05/11/2026 (7g) | 30/10/2026 – 31/10/2026 (2g) | **+250%** |
| **Tasso di Completamento** | **100.0% (98 / 98)** | **100.0% (15 / 15)** | **Stabile a 100%** |
| **Attività Fallite / Dropped** | **0 / 0** | **0 / 0** | **0 Errori** |
| **Azioni Eseguite (`actionExecutionCount`)** | **487** | **75** | **+549.3%** |
| **Spostamenti Domestici (`movementCount`)** | **86** | **12** | **+616.7%** |
| **Transizioni di Stato Ambientali** | **647** | **95** | **+581.1%** |
| **Tasso di Errore / Warning Engine** | **0 / 0** | **0 / 0** | **100% Clean Run** |

---

## 5. Statistiche e Telemetria dei Log Sensoriali (`observable-sensor-log.json`)

Il modulo sensoriale del simulatore proietta le tracce di esecuzione in eventi e misurazioni di sensori fisici e ambientali.

### 5.1 Confronto della Telemetria Sensoriale

| Parametro Log Sensori | **Mario Rossi (7 Giorni)** | **Marco Rossi (2 Giorni)** | **Note Comparative** |
| :--- | :--- | :--- | :--- |
| **Totale Record Rilevati** | **11.340 record** | **2.082 record** | **+444,7%** volume dati prodotto |
| **Media Letture / Giorno** | **1.620,0 record/giorno** | **1.041,0 record/giorno** | **+55,6%** densità giornaliera per Mario |
| **Sensori Attivi Installati** | **12 sensori** | **9 sensori** | Layout casa Mario include il corridoio |
| **Rilevamenti Movimento (PIR)** | **7.914** (69,8%) | **1.306** (62,7%) | 1.130 PIR/giorno per Mario vs 653/giorno per Marco |
| **Campionamenti Temperatura** | **3.360** (29,6%) | **768** (36,9%) | Campionamento continuo su 5 ambienti per Mario |
| **Eventi Contatto (Porte/Frigo/Armadi)**| **66** (0,6%) | **8** (0,4%) | 9,4 contatti/giorno per Mario vs 4,0 per Marco |

### 5.2 Ripartizione Top Sensori per la Simulazione di Mario Rossi
1. 🍳 **`pir_kitchen`**: **4.962 rilevamenti** *(708,8 eventi/giorno)* – Cucina molto vissuta per pasti (colazione, pranzo, cena), lavaggio piatti e preparazione cibo.
2. 🚿 **`pir_bathroom`**: **1.456 rilevamenti** *(208,0 eventi/giorno)* – Uso quotidiano di doccia e servizi igienici di prima mattina e sera.
3. 📺 **`pir_living_room`**: **1.024 rilevamenti** *(146,3 eventi/giorno)* – Attività di lettura, relax pomeridiano, TV serale ed esercizio leggero.
4. 🌡️ **`temperature_*`** (cucina, soggiorno, camera, bagno, corridoio): **672 letture ciascuno** *(96 letture/giorno per stanza)*.
5. 🚪 **`pir_hallway`**: **388 rilevamenti** *(55,4 eventi/giorno)* – Passaggi interni tra gli ambienti e accesso al mobile medicinali.
6. 🛏️ **`pir_bedroom`**: **84 rilevamenti** *(12,0 eventi/giorno)* – Transizioni di riposo notturno e risvegli.

### 5.3 Volume Giornaliero Rilevato (Mario Rossi)
- **2026-10-30 (Venerdì)**: 1.662 record *(Spesa al supermercato + routine casa)*
- **2026-10-31 (Sabato)**: 1.578 record *(Passeggiata breve + routine)*
- **2026-11-01 (Domenica)**: 1.586 record *(Passeggiata domenicale estesa + routine)*
- **2026-11-02 (Lunedì)**: 1.570 record *(Uscita farmacia + routine)*
- **2026-11-03 (Martedì)**: 1.604 record *(Caffè/Aperitivo al bar di quartiere + routine)*
- **2026-11-04 (Mercoledì)**: 1.662 record *(Scorte e spesa fresca + routine)*
- **2026-11-05 (Giovedì)**: 1.678 record *(Ginnastica indoor + routine)*

---

## 6. Localizzazione degli Artefatti Generati

Tutti i risultati della simulazione sono stati salvati ed archiviati nelle directory locali:

* **Documento di Report**: [docs/evaluation/esperimento_simulazione_7giorni_mario_rossi.md](file:///c:/vscode/smart-home-simulator/docs/evaluation/esperimento_simulazione_7giorni_mario_rossi.md)
* **Bundle Generato**: [generated/mario_week_2026_simplified.authoring-bundle.json](file:///c:/vscode/smart-home-simulator/generated/mario_week_2026_simplified.authoring-bundle.json)
* **Ingested Package**: [generated/mario_week_simplified_ingested/](file:///c:/vscode/smart-home-simulator/generated/mario_week_simplified_ingested/)
* **Risultati di Simulazione (17 file)**: [generated/mario_week_simplified_simulation/](file:///c:/vscode/smart-home-simulator/generated/mario_week_simplified_simulation/)
