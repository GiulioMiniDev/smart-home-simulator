from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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
# Prompt 1.2.0 shares the 1.1.0 template, so anything that must reach 1.2.0 alone — and leave the
# frozen 1.1.0 untouched — is injected here rather than written into the shared template.
ROUTINE_VARIATION_FRAGMENT = ROOT / "prompts/templates/routine-variation-1.2.0.fragment.md"

# The simplified prompt is the one a local model actually receives, so the sections that enumerate
# the frozen vocabularies are rendered from those vocabularies instead of being retyped: the drift
# that made it teach `call_sister_lucia` for months is then a build failure, not a silent defect.
SIMPLIFIED_TEMPLATE_PATH = (
    ROOT / "prompts/templates/generate-simulation-inputs-1.2.3-simplified.template.md"
)
SIMPLIFIED_PROMPT_PATH = ROOT / "prompts/generate-simulation-inputs-1.2.3-simplified.md"

# Pinned to what the local generation pipeline emits (`hybrid_planning.package_authoring`), so both
# authoring paths label their datasets from one vocabulary and stay comparable.
SIMPLIFIED_ACTIVITY_CATALOG_VERSION = "1.2.0"
SIMPLIFIED_VARIABLE_CATALOG_VERSION = "1.0.0"
SIMPLIFIED_ACTION_CATALOG_VERSION = "1.1.0"
SIMPLIFIED_REFERENCE_MODELS = "reference-process-models-1.2.0.json"


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
        prompt_path.write_text(
            _embed_authoritative_artifacts(prompt), encoding="utf-8", newline="\n"
        )

    prompt_1_2 = PROMPTS[-1][0].read_text(encoding="utf-8").replace("1.1.0", "1.2.0")
    for fragment_path, insertion_point, separator in (
        (REFERENCE_COMPATIBILITY_FRAGMENT, "## Required final consistency checks", "\n\n"),
        # This one continues the numbered list right above it, so it joins without a blank line.
        (ROUTINE_VARIATION_FRAGMENT, "\n## Mandatory compilation and contingency rules", "\n"),
    ):
        if prompt_1_2.count(insertion_point) != 1:
            raise RuntimeError(
                f"Prompt 1.2 insertion point missing or ambiguous: {insertion_point}"
            )
        fragment = fragment_path.read_text(encoding="utf-8").strip()
        prompt_1_2 = prompt_1_2.replace(insertion_point, f"{fragment}{separator}{insertion_point}")
    PROMPT_1_2_PATH.write_text(
        _embed_authoritative_artifacts(prompt_1_2), encoding="utf-8", newline="\n"
    )


def _fence(lines: list[str]) -> str:
    return "```text\n" + "\n".join(lines) + "\n```"


def _render_intent_components(activity_catalog: dict[str, Any]) -> str:
    lines = [
        f"{activity['intent']} = {', '.join(activity['components'])}"
        for activity in sorted(activity_catalog["activities"], key=lambda item: item["intent"])
    ]
    return _fence(lines)


def _render_component_sequences(activity_catalog: dict[str, Any]) -> str:
    components = sorted(activity_catalog["components"], key=lambda item: item["componentId"])
    lines = [
        f"{component['componentId']}: {' -> '.join(component['requiredActionTypes'])}"
        for component in components
    ]
    return _fence(lines)


def _parameter_hint(parameter: dict[str, Any]) -> str:
    """Restate ADR-007's value-source/reference-kind matrix for one parameter."""
    allowed = parameter["allowedValues"]
    if allowed:
        return " | ".join(allowed)
    return {
        "location": '{"source":"activity_location","index":0}',
        "capability": "literal capability role",
        "environment_entity": "literal environment-entity role",
        "none": "literal string",
    }[parameter["referenceKind"]]


def _render_action_signatures(action_catalog: dict[str, Any]) -> str:
    actions = sorted(action_catalog["actions"], key=lambda item: item["actionType"])
    signatures = [
        f"{action['actionType']}({', '.join(p['parameterName'] for p in action['parameters'])})"
        for action in actions
    ]
    width = max(len(signature) for signature in signatures)
    lines = []
    for action, signature in zip(actions, signatures, strict=True):
        hints = "; ".join(
            f"{p['parameterName']} = {_parameter_hint(p)}" for p in action["parameters"]
        )
        lines.append(f"{signature.ljust(width)}  {hints}".rstrip())
    return _fence(lines)


def _literal_arguments(node: dict[str, Any]) -> dict[str, str]:
    rendered = {}
    for name, expression in node.get("arguments", {}).items():
        source = expression.get("source")
        if source == "literal":
            rendered[name] = str(expression.get("value"))
        elif source == "activity_intent":
            rendered[name] = "<intent>"
        elif source == "activity_location":
            rendered[name] = "<activity location>"
        else:
            rendered[name] = f"<{source}>"
    return rendered


def _render_reference_models(reference_models: dict[str, Any]) -> str:
    lines: list[str] = []
    for intent, model in sorted(reference_models["models"].items()):
        steps = [
            f"{node['actionType']}({', '.join(_literal_arguments(node).values())})"
            for node in model["nodes"]
            if node.get("kind") == "action"
        ]
        lines.append(f"{intent}  [{', '.join(model['implementedComponents'])}]")
        # Wrapped so a long recipe stays readable in a chat window instead of one endless line.
        chunk: list[str] = []
        for step in steps:
            chunk.append(step)
            if len(chunk) == 4:
                lines.append("  " + " -> ".join(chunk) + " ->")
                chunk = []
        if chunk:
            lines.append("  " + " -> ".join(chunk))
        elif lines[-1].endswith(" ->"):
            lines[-1] = lines[-1][: -len(" ->")]
        lines.append("")
    return _fence(lines[:-1])


def _model_roles(reference_models: dict[str, Any], action_catalog: dict[str, Any]) -> set[str]:
    role_parameters = {
        (action["actionType"], parameter["parameterName"])
        for action in action_catalog["actions"]
        for parameter in action["parameters"]
        if parameter["referenceKind"] in {"capability", "environment_entity"}
    }
    return {
        str(expression["value"])
        for model in reference_models["models"].values()
        for node in model["nodes"]
        for name, expression in node.get("arguments", {}).items()
        if expression.get("source") == "literal"
        and (node.get("actionType"), name) in role_parameters
    }


def _render_canonical_roles(
    reference_models: dict[str, Any], action_catalog: dict[str, Any]
) -> str:
    """Split the roles by what the materialiser can actually put furniture behind.

    A role outside `RESOURCE_ROLE_ALIASES` still simulates, but it resolves to the per-region
    catch-all: the step executes against no real object and fires no contact sensor. The prompt has
    to say which is which, or a model picks an invented role and the defect is invisible.
    """
    from smart_home_sim.materialization.service import RESOURCE_ROLE_ALIASES

    furnished = set(RESOURCE_ROLE_ALIASES) | {
        role for aliases in RESOURCE_ROLE_ALIASES.values() for role in aliases
    }
    furnished |= {"entrance", "home_entrance", "home_exit"}
    area_roles = _model_roles(reference_models, action_catalog) - furnished

    def listed(roles: set[str]) -> str:
        return ", ".join(f"`{role}`" for role in sorted(roles))

    return (
        "Ruoli con arredo dedicato: la generazione della casa li risolve su un oggetto reale, "
        f"quindi preferiscili sempre. {listed(furnished)}.\n\n"
        "Ruoli di area o di oggetto trasportato usati dai modelli provati. Sono ammessi, ma non "
        "hanno un arredo dedicato: non inventarne altri fuori da questi due elenchi, perche' un "
        f"ruolo sconosciuto esegue contro un oggetto inesistente. {listed(area_roles)}."
    )


def _render_carrying_effects(action_catalog: dict[str, Any]) -> str:
    prefix = "resident.carrying."
    lines = []
    for action in sorted(action_catalog["actions"], key=lambda item: item["actionType"]):
        if action["actionType"] in {"take_item", "put_item"}:
            continue
        for effect in action["effects"]:
            template = effect["factTemplate"]
            if template.startswith(prefix) and effect["value"] is True:
                lines.append(f"{action['actionType']} -> carrying.{template[len(prefix) :]}=true")
    return _fence(lines)


def render_simplified_prompt() -> str:
    """Render the prompt without writing it, so a test can assert the committed file matches."""
    activity_catalog = json.loads(
        (CATALOG_DIR / f"activity-catalog-{SIMPLIFIED_ACTIVITY_CATALOG_VERSION}.json").read_text(
            encoding="utf-8"
        )
    )
    action_catalog = json.loads(
        (CATALOG_DIR / f"action-catalog-{SIMPLIFIED_ACTION_CATALOG_VERSION}.json").read_text(
            encoding="utf-8"
        )
    )
    reference_models = json.loads(
        (CATALOG_DIR / SIMPLIFIED_REFERENCE_MODELS).read_text(encoding="utf-8")
    )

    substitutions = {
        "{{ACTIVITY_CATALOG_VERSION}}": SIMPLIFIED_ACTIVITY_CATALOG_VERSION,
        "{{VARIABLE_CATALOG_VERSION}}": SIMPLIFIED_VARIABLE_CATALOG_VERSION,
        "{{ACTION_CATALOG_VERSION}}": SIMPLIFIED_ACTION_CATALOG_VERSION,
        "{{INTENT_COMPONENTS}}": _render_intent_components(activity_catalog),
        "{{COMPONENT_ACTION_SEQUENCES}}": _render_component_sequences(activity_catalog),
        "{{ACTION_SIGNATURES}}": _render_action_signatures(action_catalog),
        "{{CANONICAL_ROLES}}": _render_canonical_roles(reference_models, action_catalog),
        "{{REFERENCE_PROCESS_MODELS}}": _render_reference_models(reference_models),
        "{{CARRYING_EFFECTS}}": _render_carrying_effects(action_catalog),
    }

    prompt = SIMPLIFIED_TEMPLATE_PATH.read_text(encoding="utf-8")
    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)
    unresolved = re.findall(r"\{\{[A-Z_]+\}\}", prompt)
    if unresolved:
        raise RuntimeError(f"Unresolved simplified prompt placeholders: {sorted(set(unresolved))}")

    _assert_reference_models_cover_catalog(activity_catalog, reference_models)
    return prompt


def build_simplified_prompt() -> None:
    SIMPLIFIED_PROMPT_PATH.write_text(render_simplified_prompt(), encoding="utf-8", newline="\n")


def _assert_reference_models_cover_catalog(
    activity_catalog: dict[str, Any], reference_models: dict[str, Any]
) -> None:
    """A reference model bound to an intent the catalog dropped would teach a dead label."""
    known = {activity["intent"] for activity in activity_catalog["activities"]}
    unknown = sorted(set(reference_models["models"]) - known)
    if unknown:
        raise RuntimeError(
            f"Reference process models target intents absent from activity catalog "
            f"{SIMPLIFIED_ACTIVITY_CATALOG_VERSION}: {unknown}"
        )


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
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    build_prompt()
    build_simplified_prompt()
    build_example()


if __name__ == "__main__":
    main()
