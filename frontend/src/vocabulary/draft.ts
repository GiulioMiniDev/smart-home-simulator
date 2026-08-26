/**
 * The edits the editor can make, as functions from one pack to the next.
 *
 * All pure, all returning a new pack: undo is then a stack of previous packs rather than a set of
 * inverse operations, and the autosave has an unambiguous thing to send.
 *
 * The one structural rule worth stating: a process model is a graph, but 27 of the 28 bundled ones
 * are a straight chain — start, a run of actions, end. `setSteps` rebuilds the chain from a list,
 * which is what lets the editor offer "move up" and "insert here" instead of asking someone to
 * think about edges. A model that branches is left alone and shown read-only, because silently
 * flattening a branch would change what the activity means.
 */

import type {
  ProcessModel,
  ProcessNode,
  ValueExpression,
  VocabularyAction,
  VocabularyEntityType,
  VocabularyIntent,
  VocabularyPack,
} from "./types";

export function literal(value: string): ValueExpression {
  return { source: "literal", value, variableId: null, index: null };
}

/** Is this model a straight run of actions, and therefore safe to reorder as a list? */
export function isLinear(model: ProcessModel): boolean {
  return model.nodes.every((node) => node.kind === "start" || node.kind === "end" || node.kind === "action");
}

export function actionNodes(model: ProcessModel): ProcessNode[] {
  return model.nodes.filter((node) => node.kind === "action");
}

/**
 * Rebuild a model from an ordered list of action steps.
 *
 * Node ids are reassigned from position, so a step inserted in the middle does not leave the rest
 * numbered around a hole. Nothing outside this module refers to a node id, and the ids the bundled
 * models use (`step_1`, `step_2`) are positional already.
 */
export function setSteps(model: ProcessModel, steps: ProcessNode[]): ProcessModel {
  const renumbered = steps.map((node, index) => ({ ...node, nodeId: `step_${index + 1}` }));
  const chain = ["start", ...renumbered.map((node) => node.nodeId), "end"];
  return {
    ...model,
    nodes: [
      { ...blankNode("start", "start") },
      ...renumbered,
      { ...blankNode("end", "end") },
    ],
    edges: chain.slice(0, -1).map((sourceNodeId, index) => ({
      sourceNodeId,
      // `slice(0, -1)` guarantees a successor; the compiler cannot see that through an index.
      targetNodeId: chain[index + 1] as string,
      condition: null,
      isDefault: false,
    })),
  };
}

function blankNode(nodeId: string, kind: "start" | "end"): ProcessNode {
  return {
    nodeId,
    kind,
    actionType: null,
    arguments: {},
    duration: null,
    durationWeight: null,
    preconditions: [],
    effects: [],
    maxIterations: null,
  };
}

/** A new step calling `actionType`, with every required argument given a placeholder literal. */
export function newStep(action: VocabularyAction): ProcessNode {
  const args: Record<string, ValueExpression> = {};
  for (const parameter of action.definition.parameters) {
    if (!parameter.required) continue;
    const suggestion =
      (parameter.allowedValues?.[0] as string | undefined) ??
      (parameter.referenceKind === "location" ? "" : parameter.parameterName);
    args[parameter.parameterName] = literal(suggestion || parameter.parameterName);
  }
  return {
    nodeId: "step_new",
    kind: "action",
    actionType: action.definition.actionType,
    arguments: args,
    duration: null,
    durationWeight: action.gestureSeconds === null ? 1 : null,
    preconditions: [],
    effects: [],
    maxIterations: null,
  };
}

function replaceIntent(pack: VocabularyPack, intent: VocabularyIntent): VocabularyPack {
  return {
    ...pack,
    intents: pack.intents.map((item) => (item.intentId === intent.intentId ? intent : item)),
  };
}

export function updateIntentSteps(
  pack: VocabularyPack,
  intentId: string,
  steps: ProcessNode[],
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  return replaceIntent(pack, { ...intent, processModel: setSteps(intent.processModel, steps) });
}

export function moveStep(
  pack: VocabularyPack,
  intentId: string,
  index: number,
  by: -1 | 1,
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  const steps = actionNodes(intent.processModel);
  const target = index + by;
  if (target < 0 || target >= steps.length) return pack;
  const reordered = [...steps];
  const moved = reordered[index] as ProcessNode;
  reordered[index] = reordered[target] as ProcessNode;
  reordered[target] = moved;
  return updateIntentSteps(pack, intentId, reordered);
}

export function removeStep(pack: VocabularyPack, intentId: string, index: number): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  const steps = actionNodes(intent.processModel);
  // A process model needs at least a start and an end, and an activity with no steps is not an
  // activity; the last step is kept and the editor disables the control rather than explaining.
  if (steps.length <= 1) return pack;
  return updateIntentSteps(pack, intentId, steps.filter((_, position) => position !== index));
}

export function insertStep(
  pack: VocabularyPack,
  intentId: string,
  index: number,
  action: VocabularyAction,
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  const steps = actionNodes(intent.processModel);
  const next = [...steps];
  next.splice(index, 0, newStep(action));
  return updateIntentSteps(pack, intentId, next);
}

export function setStepArgument(
  pack: VocabularyPack,
  intentId: string,
  index: number,
  name: string,
  value: string,
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  const steps = actionNodes(intent.processModel).map((node, position) =>
    position === index ? { ...node, arguments: { ...node.arguments, [name]: literal(value) } } : node,
  );
  return updateIntentSteps(pack, intentId, steps);
}

export function setStepWeight(
  pack: VocabularyPack,
  intentId: string,
  index: number,
  weight: number,
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  const steps = actionNodes(intent.processModel).map((node, position) =>
    position === index ? { ...node, durationWeight: weight } : node,
  );
  return updateIntentSteps(pack, intentId, steps);
}

export function updateIntentMeta(
  pack: VocabularyPack,
  intentId: string,
  patch: Partial<VocabularyIntent>,
): VocabularyPack {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  if (!intent) return pack;
  return replaceIntent(pack, { ...intent, ...patch });
}

/** Slug an author's title into an identifier, because an id is what a dataset publishes. */
export function slug(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

export function addIntent(
  pack: VocabularyPack,
  { label, category, room }: { label: string; category: string; room: string },
): { pack: VocabularyPack; intentId: string } {
  const base = slug(label) || "new_activity";
  let intentId = base;
  let counter = 2;
  const taken = new Set([
    ...pack.intents.map((item) => item.intentId),
    ...pack.awayIntents.map((item) => item.intentId),
  ]);
  while (taken.has(intentId)) intentId = `${base}_${counter++}`;

  // A new activity starts with the one step every activity has: walking to where it happens. That
  // is a real step rather than a placeholder, and it means the model is valid from the first save.
  const walk = pack.actions.find((item) => item.definition.actionType === "move_to");
  const steps = walk ? [{ ...newStep(walk), arguments: { destination: { source: "activity_location", value: null, variableId: null, index: null } as ValueExpression } }] : [];

  const intent: VocabularyIntent = {
    intentId,
    label,
    category,
    defaultLocation: room,
    returnLocation: null,
    description: "",
    components: [],
    externalMappings: {},
    processModel: setSteps(
      {
        processModelId: `reference__${intentId}`,
        processModelVersion: "1.0.0",
        residentId: "reference_resident",
        title: `reference ${label.toLowerCase()} process`,
        description: `Authored decomposition of '${intentId}'.`,
        implementedComponents: ["authored"],
        nodes: [],
        edges: [],
      },
      steps,
    ),
  };
  return { pack: { ...pack, intents: [...pack.intents, intent] }, intentId };
}

export function removeIntent(pack: VocabularyPack, intentId: string): VocabularyPack {
  return { ...pack, intents: pack.intents.filter((item) => item.intentId !== intentId) };
}

// --- actions ---------------------------------------------------------------------------------

export function updateAction(
  pack: VocabularyPack,
  actionType: string,
  patch: Partial<VocabularyAction>,
): VocabularyPack {
  return {
    ...pack,
    actions: pack.actions.map((item) =>
      item.definition.actionType === actionType ? { ...item, ...patch } : item,
    ),
  };
}

export interface NewActionDraft {
  actionType: string;
  description: string;
  /** What the resident touches, as a capability an entity offers. Empty means nothing specific. */
  capability: string;
  gestureSeconds: number | null;
  motionAtObject: boolean;
}

export function addAction(pack: VocabularyPack, draft: NewActionDraft): VocabularyPack {
  const actionType = slug(draft.actionType);
  if (!actionType || pack.actions.some((item) => item.definition.actionType === actionType)) {
    return pack;
  }
  // One parameter, naming what the action is done to. Every bundled action but `leave_home` and
  // `enter_home` has exactly this shape, and offering more would be asking an author to design a
  // signature before they have decided what the action is.
  const parameters = draft.capability
    ? [
        {
          parameterName: "targetRole",
          description: "What this is done to.",
          valueType: "string",
          required: true,
          referenceKind: "capability" as const,
          allowedValues: [],
        },
      ]
    : [];
  const action: VocabularyAction = {
    definition: {
      actionType,
      description: draft.description || `Execute the typed atomic action '${actionType}'.`,
      parameters,
      requiredCapabilities: draft.capability
        ? [{ role: "target", capability: draft.capability, parameterName: "targetRole" }]
        : [],
      preconditions: [],
      effects: [],
    },
    gestureSeconds: draft.gestureSeconds,
    observability: { motionAtObject: draft.motionAtObject, motionAlongPath: false },
    isTravel: false,
  };
  return { ...pack, actions: [...pack.actions, action] };
}

/** Which activities still call this action — asked before removing it. */
export function actionUsers(pack: VocabularyPack, actionType: string): string[] {
  return pack.intents
    .filter((intent) => intent.processModel.nodes.some((node) => node.actionType === actionType))
    .map((intent) => intent.intentId);
}

export function removeAction(pack: VocabularyPack, actionType: string): VocabularyPack {
  if (actionUsers(pack, actionType).length > 0) return pack;
  return {
    ...pack,
    actions: pack.actions.filter((item) => item.definition.actionType !== actionType),
  };
}

// --- furniture -------------------------------------------------------------------------------

export function updateEntityType(
  pack: VocabularyPack,
  entityType: string,
  patch: Partial<VocabularyEntityType>,
): VocabularyPack {
  return {
    ...pack,
    entityTypes: pack.entityTypes.map((item) =>
      item.entityType === entityType ? { ...item, ...patch } : item,
    ),
  };
}

export function addEntityType(pack: VocabularyPack, displayName: string): { pack: VocabularyPack; entityType: string } {
  const entityType = slug(displayName);
  if (!entityType || pack.entityTypes.some((item) => item.entityType === entityType)) {
    return { pack, entityType };
  }
  const created: VocabularyEntityType = {
    entityType,
    displayName,
    capabilities: [],
    roleAliases: [],
    contactInstrumented: false,
    symbolId: null,
    symbolBody: null,
  };
  return { pack: { ...pack, entityTypes: [...pack.entityTypes, created] }, entityType };
}

export function removeEntityType(pack: VocabularyPack, entityType: string): VocabularyPack {
  return { ...pack, entityTypes: pack.entityTypes.filter((item) => item.entityType !== entityType) };
}

/** Every capability any furniture in this pack offers, for a picker that suggests rather than asks. */
export function knownCapabilities(pack: VocabularyPack): string[] {
  const values = new Set<string>();
  for (const item of pack.entityTypes) for (const value of item.capabilities) values.add(value);
  for (const action of pack.actions) {
    for (const requirement of action.definition.requiredCapabilities) values.add(requirement.capability);
  }
  return [...values].sort();
}

/** Every role any process model names, for the same reason. */
export function knownRoles(pack: VocabularyPack): string[] {
  const values = new Set<string>();
  for (const item of pack.entityTypes) for (const value of item.roleAliases) values.add(value);
  for (const intent of pack.intents) {
    for (const node of intent.processModel.nodes) {
      const action = pack.actions.find((item) => item.definition.actionType === node.actionType);
      for (const [name, argument] of Object.entries(node.arguments)) {
        const parameter = action?.definition.parameters.find((item) => item.parameterName === name);
        const binding = parameter?.referenceKind === "capability" || parameter?.referenceKind === "environment_entity";
        if (binding && argument.source === "literal" && typeof argument.value === "string") {
          values.add(argument.value);
        }
      }
    }
  }
  return [...values].sort();
}
