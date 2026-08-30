/**
 * A small vocabulary that exercises every case the editor has to render.
 *
 * Deliberately not a copy of the built-in pack: the tests are about the editor's behaviour, and a
 * fixture with 28 activities would make a failure hard to read. What it does carry is one of each
 * awkward shape — an action with no sensor evidence, a role no furniture answers, a container with
 * a door sensor and one without, and an activity that branches.
 */

import type { ProcessModel, VocabularyAction, VocabularyPack } from "../vocabulary/types";

function action(
  actionType: string,
  overrides: Partial<VocabularyAction> = {},
  parameterName?: string,
  referenceKind: "capability" | "none" = "capability",
): VocabularyAction {
  return {
    definition: {
      actionType,
      description: `Execute '${actionType}'.`,
      parameters: parameterName
        ? [
            {
              parameterName,
              description: "What this is done to.",
              valueType: "string",
              required: true,
              referenceKind,
              allowedValues: [],
            },
          ]
        : [],
      requiredCapabilities: [],
      preconditions: [],
      effects: [],
    },
    gestureSeconds: 3,
    observability: { motionAtObject: true, motionAlongPath: false },
    isTravel: false,
    ...overrides,
  };
}

function chain(id: string, steps: ProcessModel["nodes"]): ProcessModel {
  const ids = ["start", ...steps.map((node) => node.nodeId), "end"];
  return {
    processModelId: `reference__${id}`,
    processModelVersion: "1.0.0",
    residentId: "reference_resident",
    title: `reference ${id}`,
    description: `Decomposition of ${id}.`,
    implementedComponents: ["component"],
    nodes: [
      { nodeId: "start", kind: "start", actionType: null, arguments: {}, duration: null, durationWeight: null, preconditions: [], effects: [], maxIterations: null },
      ...steps,
      { nodeId: "end", kind: "end", actionType: null, arguments: {}, duration: null, durationWeight: null, preconditions: [], effects: [], maxIterations: null },
    ],
    edges: ids.slice(0, -1).map((sourceNodeId, index) => ({
      sourceNodeId,
      targetNodeId: ids[index + 1] as string,
      condition: null,
      isDefault: false,
    })),
  };
}

function step(nodeId: string, actionType: string, args: Record<string, string | null> = {}) {
  return {
    nodeId,
    kind: "action" as const,
    actionType,
    arguments: Object.fromEntries(
      Object.entries(args).map(([name, value]) => [
        name,
        value === null
          ? { source: "activity_location" as const, value: null, variableId: null, index: null }
          : { source: "literal" as const, value, variableId: null, index: null },
      ]),
    ),
    duration: null,
    durationWeight: null,
    preconditions: [],
    effects: [],
    maxIterations: null,
  };
}

export function fixturePack(): VocabularyPack {
  return {
    schemaVersion: "1.0.0",
    documentType: "vocabulary_pack",
    packId: "builtin",
    basePackId: "builtin",
    sourceCatalogs: { actionCatalog: "action-catalog-1.1.0" },
    actions: [
      action("move_to", { gestureSeconds: 0, isTravel: true, observability: { motionAtObject: false, motionAlongPath: true } }, "destination", "none"),
      action("open", {}, "target"),
      action("take_item", {}, "itemRole"),
      action("close", {}, "target"),
      // Elastic, and invisible: a still body waiting leaves nothing but presence.
      action("wait", { gestureSeconds: null, observability: { motionAtObject: false, motionAlongPath: false } }, "purpose", "none"),
      // Declared but used by nothing, so the editor may offer to remove it.
      action("dress", { gestureSeconds: null }, "purpose", "none"),
    ],
    entityTypes: [
      {
        entityType: "refrigerator",
        displayName: "Fridge",
        capabilities: ["openable", "storage_support"],
        roleAliases: ["food_storage", "ingredients"],
        contactInstrumented: true,
        symbolId: null,
        symbolBody: null,
      },
      {
        entityType: "microwave",
        displayName: "Microwave",
        capabilities: ["openable", "food_preparation"],
        roleAliases: ["cooking_appliance"],
        contactInstrumented: false,
        symbolId: null,
        symbolBody: null,
      },
      {
        // A kind of furniture the researcher invented, which is the whole point of the pack: it
        // has no bundled glyph, nothing binds to it, and the editor has to say both of those
        // things. It used to be a bathtub, and a bathtub is drawn now.
        entityType: "aquarium",
        displayName: "Aquarium",
        capabilities: [],
        roleAliases: [],
        contactInstrumented: false,
        symbolId: null,
        symbolBody: null,
      },
    ],
    intents: [
      {
        intentId: "eat_breakfast",
        label: "Eat breakfast",
        category: "meal",
        defaultLocation: "kitchen",
        returnLocation: null,
        description: "Sit down and eat.",
        components: ["consume"],
        externalMappings: { casas_aruba: "Eating" },
        processModel: chain("eat_breakfast", [
          step("step_1", "move_to", { destination: null }),
          step("step_2", "open", { target: "food_storage" }),
          step("step_3", "take_item", { itemRole: "ingredients" }),
          step("step_4", "close", { target: "food_storage" }),
          // A role nothing answers: the gaps report and the step row both say so.
          step("step_5", "take_item", { itemRole: "drinking_glass" }),
        ]),
      },
      {
        intentId: "sleep",
        label: "Sleep",
        category: "sleep_wake",
        defaultLocation: "bedroom",
        returnLocation: null,
        description: "Enter, leave or maintain a sleeping state.",
        components: ["rest"],
        externalMappings: {},
        processModel: chain("sleep", [
          step("step_1", "move_to", { destination: null }),
          step("step_2", "wait", { purpose: "sleep" }),
        ]),
      },
      {
        // Branching, so the editor must show it and refuse to reorder it.
        intentId: "night_toilet_visit",
        label: "Night toilet visit",
        category: "hygiene",
        defaultLocation: "bathroom",
        returnLocation: "bedroom",
        description: "The same trip made in the middle of the night.",
        components: ["personal_care"],
        externalMappings: { casas_aruba: "Bed_to_Toilet" },
        processModel: {
          ...chain("night_toilet_visit", [step("step_1", "move_to", { destination: null })]),
          nodes: [
            ...chain("night_toilet_visit", [step("step_1", "move_to", { destination: null })]).nodes,
            { nodeId: "branch", kind: "choice", actionType: null, arguments: {}, duration: null, durationWeight: null, preconditions: [], effects: [], maxIterations: null },
          ],
        },
      },
    ],
    awayIntents: [
      { intentId: "work_shift", label: "Work Shift", description: "Paid work away.", externalMappings: { casas_aruba: "Work" } },
    ],
  };
}
