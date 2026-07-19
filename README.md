# Smart Home Simulator

Software di ricerca per generare dataset domestici sintetici mediante scenari strutturati, validazione deterministica e simulazione vincolata.

## Stato attuale

Il progetto è nella **Milestone 1: scenario contract e validation engine**.

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

## Documentazione

- [Roadmap e milestone](ROADMAP.md)
- [Confine del sistema](docs/spec/00-system-boundary.md)
- [Contratto dello scenario](docs/spec/01-scenario-contract.md)
- [Motore di validazione](docs/spec/02-validation-engine.md)
- [Contratti downstream](docs/spec/03-downstream-contracts.md)
- [Decisioni architetturali](docs/decisions/ADR-001-feature-milestones.md)
