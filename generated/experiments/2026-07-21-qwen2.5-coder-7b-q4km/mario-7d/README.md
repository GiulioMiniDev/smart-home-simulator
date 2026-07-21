# Mario Rossi — prova valida di 7 giorni

Questa è la catena completa e verificata dell'esperimento:

- `authoring-bundle.json`: risposta attribuita al modello locale;
- `ingestion-report.json`: ingestion valida con zero errori e zero warning;
- `ingested/`: i due input canonici pubblicati atomicamente;
- `simulation/`: workspace completo, con 17 artefatti elencati nel manifest più il
  `workspace-manifest.json` stesso.

Il workspace completa 98 attività su 98, con 487 azioni, 86 movimenti, 647 transizioni di
stato e 11.340 osservazioni sensoriali.

La validità formale non implica plausibilità realistica. La risposta contiene, fra le altre,
queste anomalie note:

- sonno preferito di 30 minuti per notte;
- `short_evening_walk` alle 10:30 e localizzata presso il bar;
- `wash_breakfast_dishes` alle 13:30, dopo pranzo;
- terapia mattutina non motivata dal profilo del residente;
- routine quasi identica nei sette giorni;
- `generatedAt` futuro rispetto alla data reale dell'esperimento.

Questi limiti sono analizzati nel report di valutazione e non sono stati corretti
manualmente negli artefatti.

