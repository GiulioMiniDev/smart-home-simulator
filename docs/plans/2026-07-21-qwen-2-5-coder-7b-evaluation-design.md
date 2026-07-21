# Valutazione controllata di Qwen 2.5 Coder 7B con il prompt 1.2.1

## Obiettivo

Verificare se `qwen2.5-coder-7b-instruct`, esposto da LM Studio su
`http://127.0.0.1:1234`, produce bundle settimanali formalmente validi e umanamente
plausibili usando `generate-simulation-inputs-1.2.1-simplified.md`.

La prova non ricostruisce retroattivamente la descrizione sorgente del precedente
esperimento, che non fu conservata. Usa invece un nuovo caso controllato, salvato insieme
agli output, e confronta i risultati con le anomalie documentate del prompt 1.2.0.

## Protocollo

- Eseguire tre generazioni indipendenti con la stessa descrizione e gli stessi parametri.
- Usare il modello dichiarato dall'endpoint LM Studio e registrare modello, parametri,
  orari, durata, token e finish reason restituiti dall'API.
- Salvare ogni risposta grezza senza repair e senza modifiche manuali.
- Sottoporre ciascuna risposta, nell'ordine, a parsing JSON, ingestion atomica e
  `run-synthetic` quando l'ingestion ha successo.
- Non modificare simulatore, schemi, cataloghi, validatori o test per accettare gli output.

Parametri iniziali, coerenti con la prova precedente: temperatura `0.2`, top-p `0.9`,
top-k `40`. Il limite di output e il context length effettivo devono essere registrati o,
se LM Studio non li espone, marcati come non disponibili.

## Valutazione qualitativa

Ogni run viene controllata almeno per:

- sonno notturno realistico e coerente con il risveglio;
- farmaci supportati dalla descrizione e dal profilo;
- coerenza fra nome dell'intent, orario e luogo;
- ordine plausibile di pasti e attività collegate;
- differenze significative fra i sette giorni;
- `generatedAt` reale e provenance corretta;
- fedeltà ai fatti forniti, senza dettagli personali immotivati.

L'originalità viene intesa come varietà plausibile fra giorni e fra run, non come semplice
differenza lessicale. La varietà non deve compromettere la fedeltà al caso.

## Interpretazione

- **Sufficiente per uso assistito:** almeno due run su tre completano l'intera pipeline e
  nessuna presenta anomalie qualitative critiche.
- **Affidabile senza supervisione:** tre run su tre completano la pipeline e risultano
  plausibili secondo la rubrica.
- **Insufficiente:** si osservano troncamenti, errori formali ricorrenti o persistono
  anomalie temporali e semantiche critiche.

Con sole tre run, un esito positivo resta evidenza preliminare. Una raccomandazione generale
per l'uso non supervisionato richiede in seguito una matrice più ampia di persone, finestre
e seed. Un fallimento ripetuto è invece evidenza sufficiente per sconsigliare questa
configurazione nel workflow corrente.

## Artefatti

I nuovi risultati vengono isolati in una directory sperimentale dedicata contenente:

- descrizione controllata del caso;
- prompt o digest del prompt;
- metadata della configurazione;
- richiesta e risposta grezza per ciascuna run;
- report di ingestion;
- workspace di simulazione soltanto per le run accettate;
- valutazione aggregata.

Il report esistente di Mario Rossi viene aggiornato distinguendo chiaramente la prova
storica 1.2.0 dalla nuova serie 1.2.1 e formulando standard di potenza come requisiti
empirici, non come equivalenze rigide fra numero di parametri e qualità.
