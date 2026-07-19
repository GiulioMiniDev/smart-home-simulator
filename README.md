# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

La **Milestone 1: scenario contract e validation engine è completata e congelata alla versione 1.0.0**. Il prossimo sviluppo previsto è la Milestone 2, il compilatore del piano; il codice presente continua intenzionalmente a contenere solo il validatore.

Sono intenzionalmente assenti:

- motore di simulazione;
- SimPy;
- ambiente e planimetria 2D;
- microesecuzione;
- sensori;
- exporter dei dataset;
- integrazione LLM.

Queste feature verranno sviluppate separatamente solo dopo il completamento dei rispettivi criteri di ingresso descritti in [ROADMAP.md](ROADMAP.md).

## Comandi disponibili

```bash
make sync
make validate
make schema
```

Per validare un file specifico:

```bash
UV_NO_EDITABLE=1 uv run smart-home-sim validate percorso/scenario.json
UV_NO_EDITABLE=1 uv run smart-home-sim validate percorso/scenario.json --format json
```

`UV_NO_EDITABLE=1` evita che le installazioni editable basate su `.pth` vengano ignorate dalle versioni recenti di Python quando macOS assegna a tali file il flag filesystem `hidden`.

Test e qualità:

```bash
make test
make lint
make check
```

Il comando `validate` non corregge lo scenario e non lo esegue. Produce esclusivamente un rapporto stabile con codici, severità, percorso JSON e messaggio.

Gli artefatti pubblici congelati sono:

- `schemas/scenario-1.0.0.schema.json`;
- `schemas/validation-report-1.0.0.schema.json`;
- il registro degli 83 codici in `src/smart_home_sim/domain/codes.py`.

L'accettazione principale è una settimana completa di 173 attività in `examples/valid/mario_week.json`. L'esempio `examples/valid/minimal.json` è utile per imparare il contratto senza il rumore del caso completo.

## Documentazione

- [Roadmap e milestone](ROADMAP.md)
- [Confine del sistema](docs/spec/00-system-boundary.md)
- [Contratto dello scenario](docs/spec/01-scenario-contract.md)
- [Motore di validazione](docs/spec/02-validation-engine.md)
- [Contratti downstream](docs/spec/03-downstream-contracts.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
- [Freeze dei contratti 1.0.0](docs/decisions/ADR-002-freeze-scenario-contract-1.0.0.md)
