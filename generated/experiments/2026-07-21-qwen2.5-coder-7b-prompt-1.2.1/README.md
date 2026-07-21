# Qwen 2.5 Coder 7B Q4_K_M con prompt 1.2.1 — tre run controllate

Stato: **0/3 risposte accettabili; modello non sufficiente per l'authoring settimanale
monolitico nel setup provato**.

La descrizione originale dell'esperimento 1.2.0 non era stata conservata. Questa directory
contiene quindi un nuovo caso controllato, non una replica retroattiva.

## Protocollo

- endpoint: LM Studio `http://127.0.0.1:1234`;
- modello: `qwen2.5-coder-7b-instruct`, 7B, GGUF `Q4_K_M`;
- contesto caricato: 32.768 token;
- prompt: `generate-simulation-inputs-1.2.1-simplified.md`;
- prompt tokens misurati dall'API: 8.587 per run;
- temperatura `0.2`, top-p `0.9`, top-k `40`;
- seed: 101, 202 e 303;
- nessun repair e nessuna modifica manuale alle risposte.

## Risultato

| Run | Durata | Completion token | Token/s | Finish | JSON grezzo | Gate finale |
|---:|---:|---:|---:|---|---|---|
| 1 | 272,825 s | 14.428 | 52,88 | `stop` | no, fence Markdown | ingestion diagnostica non valida |
| 2 | 47,973 s | 2.698 | 56,24 | `stop` | no, fence/commenti/ellissi | non ingeribile |
| 3 | 245,788 s | 13.105 | 53,32 | `stop` | no, fence Markdown | ingestion diagnostica non valida |

Le run 1 e 3 contenevano un JSON interno estraibile meccanicamente. Le copie
`authoring-bundle.diagnostic-extracted.json` servono soltanto a diagnosticare gli errori
successivi: non sono risposte accettate e non cambiano l'esito del Gate 0.

- run 1: 3 errori di ingestion, inclusa una finestra temporale non ordinata;
- run 3: 11 errori di ingestion, soprattutto sonno assegnato al giorno successivo e ultimo
  sonno fuori dalla simulation window;
- run 2: placeholder `// ...` e generazione interrotta dopo una parte del primo giorno.

Nessuna run ha prodotto input canonici o un workspace simulabile.

## Qualità

Il prompt 1.2.1 ha corretto alcuni difetti storici: le durate del sonno sono 8–9 ore,
`generatedAt` coincide con il timestamp fornito e non vengono inventati farmaci. Restano
però difetti critici:

- run 1 e 3 ripetono la stessa sequenza in tutti e sette i giorni;
- sono ignorati spesa, bucato, telefonata, aperitivo, preparazione settimanale e gran parte
  della varietà richiesta;
- pasti e fasce giornaliere sono semanticamente errati;
- intent e componenti vengono usati come `implementedComponents` o `actionType`, nonostante
  il prompt distingua esplicitamente i tre livelli;
- tutte le risposte violano il formato tassativo senza Markdown.

Il report completo è in
`docs/evaluation/authoring-prompt-1.2.1-local-qwen2.5-7b.md`.
