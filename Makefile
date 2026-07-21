.PHONY: sync validate validate-runtime-1.1 validate-behavior validate-behavior-1.1 validate-home compile compile-runtime-1.1 bundle bundle-1.1 simulate replay project-sensors run-synthetic compare-sensor-density benchmark-environment benchmark-simulation benchmark-batch-simulation benchmark-sensors benchmark-materialization schema behavior-artifacts runtime-1.1-artifacts behavior-1.1-artifacts environment-artifacts environment-visualization simulation-artifacts sensor-artifacts materialization-artifacts authoring-artifacts test lint check

sync:
	UV_NO_EDITABLE=1 uv sync

validate:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_week.json

validate-runtime-1.1:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_week.runtime-1.1.0.json

compile:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim compile examples/valid/mario_week.json --output examples/compiled/mario_week.plan.json --report-output examples/compiled/mario_week.compilation-report.json

compile-runtime-1.1: runtime-1.1-artifacts
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim compile examples/valid/mario_week.runtime-1.1.0.json --output examples/compiled/mario_week.runtime-1.1.0.plan.json --report-output examples/compiled/mario_week.runtime-1.1.0.compilation-report.json

validate-behavior:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate-behavior examples/behavior/mario_rossi_week_2026_10_12.behavior.json examples/valid/mario_week.json

validate-behavior-1.1:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate-behavior examples/behavior/mario_rossi_week_2026_10_12.behavior-1.1.0.json examples/valid/mario_week.runtime-1.1.0.json

validate-home:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate-home examples/environment/mario_monteverde.home.json

bundle:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim build-simulation-bundle examples/valid/mario_week.json examples/compiled/mario_week.plan.json examples/behavior/mario_rossi_week_2026_10_12.behavior.json examples/environment/mario_monteverde.home.json --output examples/bundles/mario_week.simulation-bundle.json --report-output examples/bundles/mario_week.environment-report.json

bundle-1.1: behavior-1.1-artifacts compile-runtime-1.1
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim build-simulation-bundle examples/valid/mario_week.runtime-1.1.0.json examples/compiled/mario_week.runtime-1.1.0.plan.json examples/behavior/mario_rossi_week_2026_10_12.behavior-1.1.0.json examples/environment/mario_monteverde.home.json --output examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json --report-output examples/bundles/mario_week.environment-report-behavior-1.1.0.json

simulate:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim simulate examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json --output examples/execution/mario_week.execution-trace.json --report-output examples/execution/mario_week.simulation-report.json

replay:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim replay examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json examples/execution/mario_week.execution-trace.json --output examples/execution/mario_week.replay-report.json

project-sensors:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim project-sensors examples/execution/mario_week.execution-trace.json examples/sensors/mario_monteverde.sensor-model.json --bundle examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json --output examples/sensors/mario_week.observable-sensor-log.json --oracle-output examples/sensors/mario_week.oracle-mapping.json --report-output examples/sensors/mario_week.sensor-projection-report.json

run-synthetic:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim run-synthetic generated/mario_rossi_2026_10_30_ingested/scenario.json generated/mario_rossi_2026_10_30_ingested/personal-process-package.json --output-dir generated/mario_rossi_2026_10_30_simulation

compare-sensor-density:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/compare_sensor_density.py

benchmark-environment:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/benchmark_environment.py

benchmark-simulation:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/benchmark_simulation.py

benchmark-batch-simulation:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/benchmark_batch_simulation.py

benchmark-sensors:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/benchmark_sensors.py

benchmark-materialization:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/benchmark_materialization.py

behavior-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_behavior_artifacts.py
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_invalid_behavior_examples.py

runtime-1.1-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/migrate_runtime_scenario_1_1.py

behavior-1.1-artifacts: runtime-1.1-artifacts
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/migrate_behavior_1_1.py

authoring-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_authoring_artifacts.py

environment-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_environment_artifacts.py
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_environment_visualization.py

environment-visualization:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_environment_visualization.py

simulation-artifacts: bundle-1.1
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_simulation_artifacts.py

sensor-artifacts: simulation-artifacts
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_sensor_artifacts.py

materialization-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/migrate_ingested_behavior_1_1.py
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_materialization_artifacts.py

schema:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --output schemas/scenario-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract validation-report --output schemas/validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract canonical-plan --output schemas/canonical-plan-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract compilation-report --output schemas/compilation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract activity-catalog --output schemas/activity-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract variable-catalog --output schemas/variable-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract action-catalog --output schemas/action-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract personal-process-package --output schemas/personal-process-package-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract behavior-validation-report --output schemas/behavior-validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract simulation-authoring-bundle --output schemas/simulation-authoring-bundle-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract authoring-ingestion-report --output schemas/authoring-ingestion-report-1.1.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract authoring-repair-request --output schemas/authoring-repair-request-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract home-model --output schemas/home-model-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract environment-validation-report --output schemas/environment-validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract simulation-bundle --output schemas/simulation-bundle-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract execution-trace --output schemas/execution-trace-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract simulation-report --output schemas/simulation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract replay-report --output schemas/replay-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract simulation-batch-manifest --output schemas/simulation-batch-manifest-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract simulation-batch-report --output schemas/simulation-batch-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract sensor-model --output schemas/sensor-model-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract observable-sensor-log --output schemas/observable-sensor-log-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract oracle-mapping --output schemas/oracle-mapping-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract sensor-projection-report --output schemas/sensor-projection-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract home-generation-policy --output schemas/home-generation-policy-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract home-generation-report --output schemas/home-generation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract sensor-deployment-policy --output schemas/sensor-deployment-policy-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract sensor-deployment-report --output schemas/sensor-deployment-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract synthetic-workspace-manifest --output schemas/synthetic-workspace-manifest-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/write_schema_checksums.py

test:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run pytest

lint:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff check .
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff format --check .

check: behavior-artifacts runtime-1.1-artifacts behavior-1.1-artifacts environment-artifacts simulation-artifacts sensor-artifacts materialization-artifacts schema authoring-artifacts test lint validate validate-runtime-1.1 compile compile-runtime-1.1 validate-behavior validate-behavior-1.1 validate-home bundle bundle-1.1 simulate replay project-sensors benchmark-environment benchmark-simulation benchmark-batch-simulation benchmark-sensors benchmark-materialization
