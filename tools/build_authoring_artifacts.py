from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas/simulation-authoring-bundle-1.0.0.schema.json"
CATALOG_DIR = ROOT / "src/smart_home_sim/catalogs"
EXAMPLE_PATH = ROOT / "examples/authoring/minimal.authoring-bundle.json"

PLACEHOLDERS = {
    "{{BUNDLE_SCHEMA_JSON}}": SCHEMA_PATH,
    "{{ACTIVITY_CATALOG_JSON}}": CATALOG_DIR / "activity-catalog-1.0.0.json",
    "{{VARIABLE_CATALOG_JSON}}": CATALOG_DIR / "variable-catalog-1.0.0.json",
    "{{ACTION_CATALOG_JSON}}": CATALOG_DIR / "action-catalog-1.0.0.json",
}
PROMPTS = (
    (
        ROOT / "prompts/templates/generate-simulation-inputs-1.0.0.template.md",
        ROOT / "prompts/generate-simulation-inputs-1.0.0.md",
    ),
    (
        ROOT / "prompts/templates/generate-simulation-inputs-1.1.0.template.md",
        ROOT / "prompts/generate-simulation-inputs-1.1.0.md",
    ),
)
PROMPT_1_2_PATH = ROOT / "prompts/generate-simulation-inputs-1.2.0.md"
REFERENCE_COMPATIBILITY_FRAGMENT = (
    ROOT / "prompts/templates/value-source-reference-kind-1.2.0.fragment.md"
)


def _compact_json(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _embed_authoritative_artifacts(prompt: str) -> str:
    for placeholder, path in PLACEHOLDERS.items():
        prompt = prompt.replace(placeholder, _compact_json(path))
    unresolved = [item for item in PLACEHOLDERS if item in prompt]
    if unresolved:
        raise RuntimeError(f"Unresolved prompt placeholders: {unresolved}")
    return prompt


def build_prompt() -> None:
    for template_path, prompt_path in PROMPTS:
        prompt = template_path.read_text(encoding="utf-8")
        prompt_path.write_text(_embed_authoritative_artifacts(prompt), encoding="utf-8")

    prompt_1_2 = PROMPTS[-1][0].read_text(encoding="utf-8").replace("1.1.0", "1.2.0")
    insertion_point = "## Required final consistency checks"
    if prompt_1_2.count(insertion_point) != 1:
        raise RuntimeError("Prompt 1.2 insertion point is missing or ambiguous")
    fragment = REFERENCE_COMPATIBILITY_FRAGMENT.read_text(encoding="utf-8").strip()
    prompt_1_2 = prompt_1_2.replace(insertion_point, f"{fragment}\n\n{insertion_point}")
    PROMPT_1_2_PATH.write_text(_embed_authoritative_artifacts(prompt_1_2), encoding="utf-8")


def build_example() -> None:
    scenario = json.loads((ROOT / "examples/valid/minimal.json").read_text(encoding="utf-8"))
    behavior = json.loads(
        (ROOT / "examples/behavior/minimal_valid_scenario.behavior.json").read_text(
            encoding="utf-8"
        )
    )
    payload = {
        "schemaVersion": "1.0.0",
        "documentType": "simulation_authoring_bundle",
        "scenario": scenario,
        "personalProcessPackage": behavior,
    }
    EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXAMPLE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    build_prompt()
    build_example()


if __name__ == "__main__":
    main()
