# Lucia Rossi: simulazione mensile di agosto 2026

## Obiettivo

Generare un singolo `SimulationAuthoringBundle` compilabile che descriva le attivita di
Lucia Rossi per tutti i 31 giorni di agosto 2026. La generazione usa
`prompts/generate-simulation-inputs-1.2.1-simplified.md` come contratto vincolante e riusa
la casa di Mario Rossi a Monteverde come ambiente domestico.

## Persona e ambito

Lucia Rossi ha 45 anni, e la figlia di Mario e vive con lui. Lavora come impiegata
amministrativa con una routine ibrida fra ufficio e smart working. Il bundle pianifica
soltanto le attivita di Lucia; Mario resta parte del contesto della casa, ma non riceve un
secondo calendario mensile.

La simulation window va dal `2026-08-01T00:00:00+02:00` al
`2026-08-31T23:59:59+02:00` nel fuso `Europe/Rome`.

## Contenuto comportamentale

Ogni giorno include sonno, risveglio, igiene e pasti in ordine plausibile. I feriali
alternano lavoro in ufficio e lavoro remoto. Weekend, ferie estive e Ferragosto introducono
variazioni coerenti: spesa, bucato, pulizie, passeggiate, lettura, televisione, telefonate e
uscite. Le giornate non sono copie identiche e le transizioni lasciano margini temporali
realistici.

Non vengono inventate condizioni mediche o terapie. Le attivita usano esclusivamente gli
intent del prompt 1.2.1; componenti e azioni primitive rispettano i mapping prescritti.

## Strategia di generazione

Il mese viene progettato in blocchi settimanali, poi assemblato deterministicamente in un
solo bundle. I process model sono definiti una volta per ciascun flusso realmente distinto,
i binding coprono esattamente ogni coppia `(residentId, intent)` usata e i riferimenti
equivalenti vengono deduplicati.

Questa strategia limita omissioni e incoerenze rispetto a una generazione monolitica e
mantiene maggiore varieta rispetto all'espansione di pochi archetipi giornalieri.

## Ambiente

Il bundle riusa l'identificatore della casa di Mario presente nel repository. Le location e
le risorse dichiarate nello scenario sono allineate con il modello domestico esistente. Una
camera dedicata a Lucia viene aggiunta solo se il modello della casa non offre una location
compatibile; in caso contrario viene riutilizzata la camera disponibile.

Le location esterne sono limitate a quelle effettivamente necessarie, per esempio ufficio,
supermercato, parco e bar o ristorante.

## Verifica e criteri di successo

Il risultato deve:

1. contenere esattamente 31 `DayPlan`, uno per ogni data della window;
2. superare parsing JSON, ingestion e validazione comportamentale;
3. compilare senza errori e completare una simulazione end-to-end;
4. avere copertura binding del 100%;
5. usare grafi di processo con movimento iniziale, azioni primitive valide e nessun nodo
   morto;
6. mantenere orari, durate, luoghi e sequenze quotidiane plausibili;
7. conservare descrizione del caso, bundle sorgente e report prodotti per la verifica.

Gli eventuali warning non bloccanti vengono riportati esplicitamente; nessun errore viene
nascosto o riclassificato come successo.
