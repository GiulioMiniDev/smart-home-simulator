from __future__ import annotations

import json
import re
import textwrap
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

# Prompt 1.3.0 is 1.2.0 plus the state-continuity contract. The 1.2.0 trials passed schema,
# compilation and behavior validation and were still rejected by the deterministic replay, because
# no prompt before this one told the model that action preconditions carry across activities and
# days. 1.2.0 stays frozen so the trials already recorded against it remain reproducible.
PROMPT_1_3_PATH = ROOT / "prompts/generate-simulation-inputs-1.3.0.md"
ACTION_STATE_FRAGMENT = ROOT / "prompts/templates/action-state-continuity-1.3.0.fragment.md"
ACTION_STATE_CHECKS = (
    "- every `leave_home`, `enter_home`, `put_item`, `open`, `close`, `activate` and "
    "`deactivate`\n"
    "  satisfies its catalog precondition in the chronological ledger, across activities and "
    "days;\n"
    "- every `travel` component performed away from home carries the mandatory\n"
    "  `move_to_capability(home_entrance) -> enter_home` bridge;\n"
    "- every `take_item` or `put_item` of a stored role opens and closes its container, so the\n"
    "  fridge is not the only object in the home a contact sensor ever observes;"
)

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


def _insert_before(prompt: str, insertion_point: str, text: str, separator: str = "\n") -> str:
    if prompt.count(insertion_point) != 1:
        raise RuntimeError(f"Prompt insertion point missing or ambiguous: {insertion_point}")
    return prompt.replace(insertion_point, f"{text}{separator}{insertion_point}")


def _render_action_state_contract(action_catalog: dict[str, Any]) -> str:
    """Restate the replayed preconditions and effects from the catalog the prompt embeds.

    Retyping them is how the 1.2.0 trial rules drifted from the validators; rendering them means a
    catalog that gains an action with a precondition cannot leave the prompt silently incomplete.
    """
    actions = sorted(action_catalog["actions"], key=lambda item: item["actionType"])
    preconditions = [
        f"{action['actionType']:19} requires {item['factTemplate']} "
        f"{item['operator']} {json.dumps(item['value'])}"
        for action in actions
        for item in action["preconditions"]
    ]
    effects = [
        f"{action['actionType']:19} {item['operation']:9} {item['factTemplate']} "
        f"= {json.dumps(item['value'])}"
        for action in actions
        for item in action["effects"]
    ]
    return _fence(["Preconditions", *preconditions, "", "Effects", *effects])


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
        prompt_1_2 = _insert_before(
            prompt_1_2,
            insertion_point,
            fragment_path.read_text(encoding="utf-8").strip(),
            separator,
        )
    PROMPT_1_2_PATH.write_text(
        _embed_authoritative_artifacts(prompt_1_2), encoding="utf-8", newline="\n"
    )

    # The replay uses action catalog 1.0.0, the one this prompt family embeds, so the restated
    # contract is rendered from that exact file rather than from the simplified prompt's 1.1.0.
    action_catalog = json.loads(
        (CATALOG_DIR / "action-catalog-1.0.0.json").read_text(encoding="utf-8")
    )
    state_fragment = (
        ACTION_STATE_FRAGMENT.read_text(encoding="utf-8")
        .strip()
        .replace("{{ACTION_STATE_CONTRACT}}", _render_action_state_contract(action_catalog))
        .replace("{{CARRYING_GRANTS}}", _render_carrying_grants(action_catalog))
        .replace("{{CONTAINER_ROLES}}", _render_container_roles())
    )
    prompt_1_3 = prompt_1_2.replace("1.2.0", "1.3.0")
    prompt_1_3 = _insert_before(
        prompt_1_3, "## Required final consistency checks", state_fragment, "\n\n"
    )
    prompt_1_3 = _insert_before(
        prompt_1_3,
        "- output provenance is truthful and the JSON is complete.",
        ACTION_STATE_CHECKS.strip(),
        "\n",
    )
    PROMPT_1_3_PATH.write_text(
        _embed_authoritative_artifacts(prompt_1_3), encoding="utf-8", newline="\n"
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


def _carrying_grants(action_catalog: dict[str, Any]) -> list[tuple[str, str]]:
    """Every action other than `take_item` that leaves the resident holding a role."""
    prefix = "resident.carrying."
    return [
        (action["actionType"], effect["factTemplate"][len(prefix) :])
        for action in sorted(action_catalog["actions"], key=lambda item: item["actionType"])
        if action["actionType"] != "take_item"
        for effect in action["effects"]
        if effect["factTemplate"].startswith(prefix) and effect["value"] is True
    ]


def _render_carrying_grants(action_catalog: dict[str, Any]) -> str:
    """Which actions satisfy a later `put_item`, spelled from the catalog rather than asserted.

    "`take_item` is the only action that grants a carrying fact" is true of action catalog 1.0.0
    and false of 1.1.0, where `prepare_food`, `shop` and `dress` each hand over a role. The outline
    prompt embeds 1.1.0 while inheriting this rule from the 1.3.0 prompt, which embeds 1.0.0, so
    the sentence reached its author as a flat contradiction of the catalog printed underneath it.
    """
    granted = _carrying_grants(action_catalog)
    if granted:
        listed = ", ".join(f"`{action}` grants `{role}`" for action, role in granted)
        text = (
            f"`take_item` grants the role it names, and so do these: {listed}. Any one of them "
            "satisfies a later `put_item` of that same role, with no `take_item` in between."
        )
    else:
        text = "`take_item` is the only action in this catalog that grants a carrying fact."
    # Continues the numbered item it is inserted into, so it carries the list's own indent.
    return textwrap.fill(text, width=98, initial_indent="   ", subsequent_indent="   ")


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


# The outline prompt reuses the process-package half of 1.3.0 verbatim. It is extracted from the
# frozen prompt rather than restated, so a change there cannot leave this one teaching the old
# contract — the same reason the catalogs are embedded instead of retyped.
OUTLINE_TEMPLATE_PATH = ROOT / "prompts/templates/generate-horizon-outline-1.0.0.template.md"
OUTLINE_PROMPT_PATH = ROOT / "prompts/generate-horizon-outline-1.0.0.md"
OUTLINE_BUNDLE_SCHEMA_PATH = ROOT / "schemas/horizon-authoring-bundle-1.0.0.schema.json"
REUSED_FROM_1_3_0 = ("## Personal ADL process-model rules", "## Required final consistency checks")


def _section_span(prompt: str, start_heading: str, end_heading: str) -> str:
    start = prompt.index(start_heading)
    end = prompt.index(end_heading, start)
    return prompt[start:end].rstrip() + "\n"


def _render_activity_portfolio() -> str:
    from smart_home_sim.hybrid_planning.recurring_activities import (
        MIN_RECURRING_ACTIVITIES,
        REQUIRED_KINDS,
    )

    lines = [
        f"Author at least {MIN_RECURRING_ACTIVITIES} recurring activities, with at least "
        "these counts "
        "per kind "
        "(the portfolio gate rejects an unbalanced profile):",
        "",
    ]
    lines.extend(f"- `{kind}`: {count}" for kind, count in sorted(REQUIRED_KINDS.items()))
    return "\n".join(lines) + "\n"


def _render_catalog_rooms() -> str:
    from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG

    rooms = sorted({spec.default_location for spec in INTENT_CATALOG})
    listed = ", ".join(f"`{room}`" for room in rooms)
    return (
        "`world.locations` must declare every room the activity catalog places an intent in, "
        f"under exactly these identifiers: {listed}. A missing one is rejected before any day "
        "is built.\n"
    )


def _render_catalog_intents() -> str:
    # Both halves of what `intent_spec` accepts are rendered. Listing only the home intents while
    # the prose asks for "one of the away intents below" is what made an author coin its own.
    from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, away_intent_specs

    lines = [
        "Every `intent` must be one of the canonical intents below, spelled exactly. The room "
        "given is where the activity catalog places it. These two lists are exhaustive: an "
        "identifier outside them does not exist, however reasonable it looks.",
        "",
        "**Inside the home:**",
        "",
    ]
    lines.extend(
        f"- `{spec.intent_id}` — {spec.default_location}"
        for spec in sorted(INTENT_CATALOG, key=lambda item: item.intent_id)
    )
    lines.extend(
        [
            "",
            "**Away from home** — the only intents an absence may carry, whether it is a fixed "
            "commitment, a recurring activity or an event:",
            "",
        ]
    )
    lines.extend(
        f"- `{spec.intent_id}` — {spec.default_location}"
        for spec in sorted(away_intent_specs(), key=lambda item: item.intent_id)
    )
    return "\n".join(lines) + "\n"


def _render_container_roles() -> str:
    """Roles whose provider is a piece of furniture with a door, rendered from the alias map.

    A `take_item` on one of these without an `open` is what left an eight-month log with the fridge
    as the only object ever opened, and the flat with two contact sensors instead of six.
    """
    from smart_home_sim.materialization.service import RESOURCE_ROLE_ALIASES

    containers = ("refrigerator", "storage_cabinet", "wardrobe")
    lines = []
    for resource_type in containers:
        roles = sorted(RESOURCE_ROLE_ALIASES[resource_type])
        lines.append(f"   - `{resource_type}` — {', '.join(f'`{role}`' for role in roles)}")
    return "\n".join(lines)


def _render_furniture_catalog() -> str:
    """The furniture the materialiser knows how to bind, and what each piece provides.

    Rendered from `RESOURCE_ROLE_ALIASES` rather than restated, for the same reason the intents are:
    a `resourceType` outside this map satisfies no role, so every activity that wanted one falls to
    the per-room placeholder — silently.
    """
    from smart_home_sim.materialization.service import RESOURCE_ROLE_ALIASES

    lines = [
        "`world.resources` declares the objects the home contains. Use these `resourceType` "
        "values, spelled exactly: they are the only ones that bind to anything, and the roles "
        "beside each are what that piece of furniture can be used for.",
        "",
    ]
    for resource_type, roles in sorted(RESOURCE_ROLE_ALIASES.items()):
        served = sorted(role for role in roles if role != resource_type)
        lines.append(
            f"- `{resource_type}` — {', '.join(served)}" if served else f"- `{resource_type}`"
        )
    return "\n".join(lines) + "\n"


def _render_rhythm_intents() -> str:
    from smart_home_sim.hybrid_planning.day_generation import RHYTHM_EMITTED_INTENTS
    from smart_home_sim.hybrid_planning.intents import intent_spec

    lines = [
        "The drive layer places these on its own — a wake and a night every day, plus a nap, a "
        "nocturnal bathroom trip or an unplanned reach-out when the resident's state calls for "
        "one:",
        "",
    ]
    lines.extend(
        f"- `{intent}` — {intent_spec(intent).label.lower()}"
        for intent in sorted(RHYTHM_EMITTED_INTENTS)
    )
    return "\n".join(lines) + "\n"


# The catalogs the outline path actually runs against.
#
# `PLACEHOLDERS` pins the legacy 1.0.0 documents, which are right for the frozen prompts that were
# written against them and wrong here: the expander requires the package to implement every intent
# the drive layer emits, and `phone_call` is not in the 1.0.0 activity catalog. Embedding it handed
# the author a vocabulary that could not satisfy the contract — declaring 1.0.0 was rejected for an
# intent the catalog does not define, and declaring the version that defines it was rejected for
# disagreeing with what the prompt showed. These are the same versions the local pipeline emits.
OUTLINE_PLACEHOLDERS = {
    "{{ACTIVITY_CATALOG_JSON}}": CATALOG_DIR
    / f"activity-catalog-{SIMPLIFIED_ACTIVITY_CATALOG_VERSION}.json",
    "{{VARIABLE_CATALOG_JSON}}": CATALOG_DIR
    / f"variable-catalog-{SIMPLIFIED_VARIABLE_CATALOG_VERSION}.json",
    "{{ACTION_CATALOG_JSON}}": CATALOG_DIR
    / f"action-catalog-{SIMPLIFIED_ACTION_CATALOG_VERSION}.json",
}


def _retarget_action_state_contract(section: str) -> str:
    """Re-render the replayed contract against the catalog the outline prompt embeds.

    The process-model half is lifted verbatim from the 1.3.0 prompt, which embeds action catalog
    1.0.0. The outline path runs on 1.1.0 and embeds it, so the lifted text arrived describing a
    different catalog from the one printed below it — silently, because both are rendered and
    neither is retyped. Under 1.0.0 `prepare_food` has no effect, so the table omitted the three
    actions that hand the resident a role and the rule above them said no such action exists.
    """
    frozen_catalog = json.loads(
        (CATALOG_DIR / "action-catalog-1.0.0.json").read_text(encoding="utf-8")
    )
    outline_catalog = json.loads(
        OUTLINE_PLACEHOLDERS["{{ACTION_CATALOG_JSON}}"].read_text(encoding="utf-8")
    )
    for render in (_render_action_state_contract, _render_carrying_grants):
        stale = render(frozen_catalog)
        if section.count(stale) != 1:
            raise RuntimeError(f"Outline prompt: cannot retarget {render.__name__}")
        section = section.replace(stale, render(outline_catalog))
    return section


def build_outline_prompt() -> None:
    frozen = PROMPT_1_3_PATH.read_text(encoding="utf-8")
    prompt = OUTLINE_TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = prompt.replace("{{ACTIVITY_PORTFOLIO}}", _render_activity_portfolio())
    prompt = prompt.replace("{{CATALOG_ROOMS}}", _render_catalog_rooms())
    prompt = prompt.replace("{{CATALOG_INTENTS}}", _render_catalog_intents())
    prompt = prompt.replace("{{FURNITURE_CATALOG}}", _render_furniture_catalog())
    prompt = prompt.replace("{{RHYTHM_INTENTS}}", _render_rhythm_intents())
    prompt = prompt.replace(
        "{{PROCESS_MODEL_SECTIONS}}",
        _retarget_action_state_contract(_section_span(frozen, *REUSED_FROM_1_3_0)),
    )
    prompt = prompt.replace(
        "{{OUTLINE_BUNDLE_SCHEMA_JSON}}", _compact_json(OUTLINE_BUNDLE_SCHEMA_PATH)
    )
    for placeholder, path in OUTLINE_PLACEHOLDERS.items():
        prompt = prompt.replace(placeholder, _compact_json(path))
    unresolved = [item for item in OUTLINE_PLACEHOLDERS if item in prompt]
    if unresolved:
        raise RuntimeError(f"Unresolved outline prompt placeholders: {unresolved}")
    OUTLINE_PROMPT_PATH.write_text(prompt, encoding="utf-8", newline="\n")


def main() -> None:
    build_prompt()
    build_simplified_prompt()
    build_outline_prompt()
    build_example()


if __name__ == "__main__":
    main()
