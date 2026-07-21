# Guida e Report: Generazione Locale di Simulazioni Smart Home con LLM (8GB VRAM)

## 1. Panoramica del Progetto e Obiettivo

Il sistema **Smart Home Simulator** richiede in ingresso un documento JSON strutturato denominato `SimulationAuthoringBundle` (composto da uno `scenario` e da un `personalProcessPackage`). 
Questo report documenta l'ottimizzazione dell'ingegneria del prompt, la configurazione hardware dell'ambiente locale e l'architettura automatizzata di generazione e validazione per consentire a modelli linguistici locali di piccole dimensioni (7B-8B parametri) di generare simulazioni **100% valide e compilabili**.

---

## 2. Configurazione dell'Ambiente e Hardware

### Hardware Locale Utente
- **GPU**: NVIDIA GeForce RTX 3060 Ti (8 GB VRAM GDDR6).
- **RAM / CPU**: Standard consumer setup.

### Configurazione di LM Studio
- **Server Locale API**: Attivo su `http://127.0.0.1:1234` (OpenAI-compatible endpoint `/v1/chat/completions`).
- **Modello Consigliato**: **Qwen 2.5 Coder 7B Instruct** (quantizzazione `Q5_K_M` o `Q8_0`) oppure **Llama 3.1 8B Instruct** (`Q5_K_M`).
- **Impostazioni Parametri LM Studio**:
  - **Context Length**: `16384` (16K context window). Occupazione VRAM stabilità a ~5.8 GB.
  - **Temperature**: `0.7` per generazioni creative e variate; `0.2` per test di conformità rigidi.
  - **Max Tokens**: `-1` (nessun troncamento artificiale dell'output).

---

## 3. Ottimizzazione del Prompt (Prompt Semplificato v1.2.0)

### Il Problema Originale
Il prompt di sistema ufficiale (`prompts/generate-simulation-inputs-1.2.0.md`) aveva una dimensione di **102 KB (oltre 25.000 token)** poiché incorporava lo schema JSON Schema Draft-2020 grezzo ed i cataloghi completi di descrizioni. Su modelli da 7B-8B parametri, questo causava:
1. Troncamento e saturazione della memoria di contesto.
2. Oltre 50 errori di schema ad ogni generazione (campi obbligatori dimenticati, stringhe grezze al posto di `ValueExpression`, errata collocazione di `durationWeight`).

### La Soluzione Applicata
È stato creato lo script `tools/build_simplified_prompt.py` che compila il prompt ottimizzato **`prompts/generate-simulation-inputs-1.2.0-simplified.md`**:
- **Riduzione Token**: Ridotto del **90%** (da 102 KB a **17 KB / ~4.000 token**).
- **TypeScript Interfaces**: Sostituito lo schema JSON grezzo con definizioni TypeScript leggibili ed espressive.
- **Clarificatione Regole Tassative**:
  - **Attività dello Scenario (`scenario.days[].activities`)**: DEVONO includere `startWindow` (`earliest`, `preferred`, `latest`) e `duration` (`minimumMinutes`, `preferredMinutes`, `maximumMinutes`). Nessun `durationWeight`.
  - **Nodi dei Process Models (`personalProcessPackage.processModels[].nodes`)**: Nodi di tipo `"action"` DEVONO includere `"durationWeight": 1`. Nessuna `duration` o `startWindow`.
  - **Espressioni di Valore (`ValueExpression`)**: Tutti gli argomenti delle azioni DEVONO essere formattati come oggetti (es. `{"source": "literal", "value": "standing"}` oppure `{"source": "activity_location", "index": 0}`).

---

## 4. Esito delle Prove e Validazione del Simulatore

### Risultato Ottenuto
In data 21 Luglio 2026, l'esecuzione del loop automatico di generazione tramite LM Studio con il nuovo prompt semplificato ha prodotto il file:
📂 **`generated/marco_2026_qwen9b.json`**

### Risultati dei Test Automatici
- **Sintassi JSON**: **VALIDA [OK]**
- **Validazione dello Schema di Dominio Pydantic (`SimulationAuthoringBundle`)**: **PASSED 100% [OK]**

Il file generato dal modello locale rispetta al 100% i contratti formali del simulatore ed è pronto per essere eseguito dal motore deterministico.

---

## 5. Tooling di Automazione Creato

Nel repository sono stati integrati i seguenti script Python in `tools/`:

1. **`tools/build_simplified_prompt.py`**:
   Script per rigenerare il prompt compatto ogni volta che vengono aggiornati i cataloghi di progetto.
2. **`tools/auto_generate_and_repair.py`**:
   Script per la generazione singola tramite LM Studio. Connette le API locali, esegue la validazione Pydantic in tempo reale e applica fino a 5 tentativi di autoriparazione guidata in caso di errori.
3. **`tools/batch_generate_year.py`**:
   Script per la generazione in batch di **1 intero anno di dati (52 settimane)**.

---

## 6. Strategia per la Generazione di 1 Anno di Dati (52 Settimane)

### Perché la Generazione Batch a Settimane
Generare 365 giorni in un unico output richiede ~300.000 token, superando qualsiasi limite di generazione. La strategia migliore per sfruttare l'intelligenza dell'AI su tutto l'anno consiste nel generare **52 file settimanali sequenziali**.

### Funzionamento di `tools/batch_generate_year.py`:
1. **Iniezione Contestuale Stagionale**:
   Per ciascuna delle 52 settimane, lo script inietta nel prompt l'esatto contesto stagionale (Inverno, Primavera, Estate, Autunno, Ferie d'Agosto, Festività Natalizie).
2. **Temperatura Creativa (`temperature = 0.7`)**:
   L'AI varia in modo plausibile e naturale le abitudini, le chiamate ed il tempo libero del residente da una settimana all'altra.
3. **Salvataggio Ordinato**:
   I file validati vengono salvati in `generated/year_batch/week_01_2026-01-05.json` ... `week_52_2026-12-28.json`.
4. **Performance su RTX 3060 Ti**:
   ~1 minuto per settimana -> **50-60 minuti per l'intero anno di simulazione**.
