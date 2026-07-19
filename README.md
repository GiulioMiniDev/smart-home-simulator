# Smart Home Simulator

Prototipo headless per la Proposta 2 della tesi: prende un piano strutturato, lo valida, lo compila in primitive di microesecuzione, simula il movimento in una casa e genera un log sensoriale grezzo separato dalla ground truth.

Questa prima versione è volutamente piccola. Supporta un residente, una giornata, una casa rappresentata come grafo e sensori PIR. La struttura è predisposta per aggiungere cataloghi di attività, contatti, smart plug, rumore, più residenti e scenari longitudinali.

## Avvio rapido

Requisiti: [`uv`](https://docs.astral.sh/uv/). Il progetto usa Python 3.12 in un ambiente isolato; non modifica il Python di sistema.

```bash
uv sync
uv run smart-home-sim validate examples/minimal_scenario.json
uv run smart-home-sim run examples/minimal_scenario.json
```

Il comando `run` crea, per impostazione predefinita:

```text
outputs/latest/raw_sensor_events.jsonl
outputs/latest/ground_truth.jsonl
outputs/latest/activity_executions.jsonl
```

Per generare il JSON Schema iniziale:

```bash
uv run smart-home-sim schema --output outputs/scenario.schema.json
```

Per eseguire i controlli:

```bash
uv run pytest
uv run ruff check .
```

## Pipeline implementata

```text
scenario JSON
    -> modelli Pydantic
    -> validazione referenziale e temporale
    -> compilatore di attività
    -> primitive di microesecuzione
    -> SimPy + grafo della casa
    -> modello PIR
    -> raw sensor log + ground truth
```

Il log grezzo non contiene `actorId` o `activityId`. La ground truth li conserva in un file separato.

## Limiti della versione 0.1

- una sola persona;
- attività domestiche sequenziali;
- destinazioni interne alla casa;
- solo PIR con segnali `ON`/`OFF`;
- template di microesecuzione iniziali, non ancora calibrati su CASAS Aruba;
- nessuna integrazione LLM: il confine di ingresso è già il JSON validato.

Il prossimo obiettivo tecnico è calibrare frequenze di movimento, reset e distribuzioni temporali usando segmenti reali di Aruba, prima di aumentare il numero di attività.

Vedi [docs/architecture.md](docs/architecture.md) per i confini tra i moduli.
