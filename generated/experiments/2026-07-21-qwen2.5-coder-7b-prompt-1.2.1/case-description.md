# Caso controllato: Mario Rossi, una settimana

Genera una simulazione completa di sette giorni consecutivi, da lunedì 27 luglio 2026 a
domenica 2 agosto 2026 inclusi, nel fuso `Europe/Rome`. La simulation window inizia il
27 luglio alle 00:00:00 e termina il 2 agosto alle 23:59:59; in queste date l'offset locale
è `+02:00`.

Mario Rossi è un uomo di 72 anni, pensionato, autonomo, mattiniero e vive da solo in un
appartamento a Roma. Non ha condizioni di salute o terapie indicate: non inventare malattie,
farmaci o attività di assunzione di medicinali. Normalmente dorme circa otto ore, si corica
fra le 22:30 e le 23:15 e si sveglia fra le 06:30 e le 07:15.

La casa comprende almeno camera da letto, bagno, cucina, soggiorno e ingresso. Possono
essere aggiunte solo location esterne utili alle attività effettivamente pianificate, per
esempio supermercato, mercato di quartiere, parco o bar.

Ogni giornata deve includere sonno, risveglio, igiene, colazione, pranzo e cena in ordine
plausibile. Mario ama leggere, guardare programmi televisivi, passeggiare, cucinare e
tenere ordinata la casa. Non trasformare però queste preferenze in una sequenza identica
ripetuta ogni giorno.

Durante la settimana devono comparire in modo naturale:

- una spesa alimentare, seguita dal rientro e dalla sistemazione degli acquisti;
- una sessione di bucato e una diversa attività di pulizia domestica;
- almeno due passeggiate, di cui una più lunga nel fine settimana;
- una telefonata a un familiare o a un amico;
- un aperitivo con Paolo il venerdì sera;
- preparazione settimanale di cibo la domenica;
- momenti di lettura, riposo o televisione distribuiti con varietà.

Le stoviglie della colazione devono essere lavate subito dopo la colazione. Le attività con
`morning` o `evening` nel nome devono avvenire nella fascia corrispondente. Una passeggiata
deve avvenire in una location adatta, non al bar. Evita sovrapposizioni irrealistiche e
lascia tempi ragionevoli per spostamenti e transizioni.

Usa esclusivamente intent, componenti e azioni presenti nel prompt. L'istante reale di
inizio della specifica generazione è `[GENERATION_TIMESTAMP]`: usalo esattamente come
`generatedAt` in entrambe le provenance. Il modello effettivo è
`qwen2.5-coder-7b-instruct-q4_k_m`.
