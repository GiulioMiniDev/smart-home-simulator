# Valutazione del prompt 1.2.1 con Qwen 2.5 Coder 7B locale

- Data: 2026-07-21
- Engine: LM Studio, versione non esposta dall'API
- Modello: `qwen2.5-coder-7b-instruct`, GGUF `Q4_K_M`
- Prompt: `prompts/generate-simulation-inputs-1.2.1-simplified.md`
- Caso: Mario Rossi, sette giorni, nuova descrizione controllata conservata
- Esito: **0/3 first-pass; nessuna simulazione avviabile**

## Domanda sperimentale

La prova verifica se il nuovo prompt corregge non soltanto la validità formale, ma anche i
difetti di tempi, provenance e varietà osservati nel bundle storico. La descrizione sorgente
storica non fu conservata; il confronto è quindi fra comportamenti osservati, non una replica
identica dello stesso input.

Le tre risposte sono state conservate integralmente senza repair o modifiche manuali sotto
`generated/experiments/2026-07-21-qwen2.5-coder-7b-prompt-1.2.1/`.

## Configurazione osservata

L'endpoint locale ha riportato:

- architettura `qwen2`, 7B parametri;
- quantizzazione `Q4_K_M`, file da 4.683.074.048 byte;
- context length caricato 32.768 token;
- eval batch 2.048, physical batch 512, parallel 4;
- Flash Attention e KV cache offload su GPU attivi.

La richiesta ha usato temperatura `0.2`, top-p `0.9`, top-k `40`, 24.000 max output token
e seed 101, 202, 303. L'API ha misurato 8.587 prompt token in ogni run.

## Risultati quantitativi

| Run | Seed | Durata | Prompt | Completion | Totale | Contesto usato | Token/s | Finish |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 101 | 272,825 s | 8.587 | 14.428 | 23.015 | 70,2% | 52,88 | `stop` |
| 2 | 202 | 47,973 s | 8.587 | 2.698 | 11.285 | 34,4% | 56,24 | `stop` |
| 3 | 303 | 245,788 s | 8.587 | 13.105 | 21.692 | 66,2% | 53,32 | `stop` |

La velocità di decoding è stabile; la forte variazione di durata dipende dalla quantità di
testo che il modello sceglie di produrre. Nessuna run raggiunge il limite di output o il
context length. I fallimenti non possono quindi essere attribuiti a un troncamento imposto
dal server.

## Gate formali

Tutte le risposte sono racchiuse in una fence Markdown etichettata `json`, nonostante il
divieto esplicito. Il tasso di successo del Gate 0 è quindi 0/3.

La run 2 contiene inoltre commenti e un placeholder `// ...`, copre soltanto parte del primo
giorno e non contiene JSON interno valido. Le run 1 e 3 hanno un JSON interno estraibile;
sono state create copie diagnostiche separate per misurare i gate successivi, senza
riclassificare le risposte grezze come valide.

| Run | JSON interno | Ingestion diagnostica | Errori | Simulazione |
|---:|---|---|---:|---|
| 1 | valido | fallita | 3 | non avviata |
| 2 | invalido | non eseguita | n/d | non avviata |
| 3 | valido | fallita | 11 | non avviata |

La run 1 contiene una `startWindow` con ordine invalido; scenario invalido, compilazione e
behavior validation sono saltati. La run 3 assegna i sonni al giorno successivo e porta
l'ultimo sonno fuori dalla simulation window. Nessuna run pubblica i due input canonici.

## Plausibilità e originalità

Il nuovo prompt produce tre miglioramenti osservabili rispetto al bundle storico:

- sonno preferito di 480–540 minuti invece di 30 minuti;
- assenza di attività farmacologiche non supportate;
- `generatedAt` uguale all'istante reale fornito nella richiesta.

Questi miglioramenti non bastano. Le run 1 e 3 hanno una sola sequenza di intent distinta
per sette giorni: l'originalità settimanale è quindi nulla. La run 1 ripete 8 attività al
giorno e la run 3 ne ripete 7. Entrambe omettono quasi tutti gli eventi settimanali richiesti,
fra cui spesa con sistemazione, bucato, telefonata, aperitivo con Paolo e meal preparation
domenicale.

Sono presenti ulteriori errori semantici:

- `eat_light_dinner` viene usato come pranzo nel pomeriggio;
- colazione e lavaggio stoviglie sono collocati molto tardi;
- `evening_hygiene` compare alle 16:15 o alle 19:15;
- i process model dichiarano spesso l'intent come `implementedComponents`;
- nomi di componenti come `sleep`, `shower`, `clean_surface` o `consume_meal` vengono usati
  come action type, nonostante siano richieste azioni primitive.

Il modello ha quindi seguito alcuni guardrail locali, ma non ha mantenuto contemporaneamente
formato, completezza, tassonomia, varietà e coerenza temporale.

## Verdetto su Qwen 2.5 Coder 7B

`Qwen2.5-Coder-7B-Instruct Q4_K_M` **non è sufficiente per generare in un solo passaggio un
bundle settimanale monolitico soddisfacente con questo prompt**. Il risultato è 0/3 al primo
gate, 0/3 all'ingestion e 0/3 alla simulazione. Anche ignorando diagnosticamente le fence,
restano errori bloccanti e una grave perdita di contenuto.

Il verdetto riguarda questa combinazione di modello, quantizzazione, prompt, forma
monolitica e parametri. Non dimostra che ogni modello 7B fallisca, né isola l'effetto della
quantizzazione dalla dimensione. Qwen 7B può ancora essere valutato per sottocompiti più
piccoli, generazione assistita o flussi deterministici a più fasi, ma non deve essere
presentato come autore settimanale one-shot affidabile.

## Standard consigliati per i prossimi LLM

La potenza nominale non sostituisce i gate empirici. Lo standard vincolante resta:

1. tre run iniziali: 3/3 JSON grezzo valido, almeno 2/3 end-to-end per uso assistito e 3/3
   per candidarsi all'uso non supervisionato;
2. matrice finale di almeno 10 casi: almeno 90% first-pass end-to-end, nessun errore critico
   di plausibilità e nessuna correzione manuale conteggiata come successo;
3. quantizzazione non più aggressiva di `Q4_K_M` durante la qualifica;
4. contesto attivo minimo 32K e consigliato 64K per margine operativo su prompt più output;
5. supporto affidabile a JSON/schema-constrained output, fermo restando che il constrained
   decoding non corregge omissioni o incoerenze semantiche.

Come **fascia candidata**, non ancora validata dal repository, il prossimo test dovrebbe
partire da un moderno instruct/coder da almeno 14B–16B a Q4/Q5. Per un obiettivo realmente
non supervisionato è prudente provare anche una classe 30B–32B. Queste soglie sono una
raccomandazione di selezione conseguente al fallimento del 7B, non la prova che un 14B o 32B
supererà il benchmark: ogni modello deve comunque soddisfare i gate sopra indicati.

Se l'hardware resta limitato a 7B, la strada consigliata è cambiare il workflow: generare
separatamente scenario, process model e binding, validare ogni blocco e assemblare in modo
deterministico. Sarebbe un nuovo esperimento architetturale, non una rivalutazione positiva
del one-shot qui testato.
