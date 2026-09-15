/**
 * The decisions behind the vocabulary review, kept apart from the component that draws them.
 *
 * Which additions an outline asks for, the vocabulary entry an accepted activity becomes, and the
 * copy of the document that is imported once the researcher has chosen a known type for an object:
 * all of it pure, so it is tested without rendering anything.
 */

import type { ProcessModel, VocabularyEntityType, VocabularyIntent, VocabularyPack } from "../vocabulary/types";
import type { ActivityProposalView, FurnitureProposalView, HorizonReading, RawProcessModel } from "./types";

export interface ReviewActions {
  substitutions: Record<string, string>;
  onSubstitute: (from: string, to: string | undefined) => void;
  onAddFurniture: (entity: VocabularyEntityType) => Promise<void>;
  onAddActivity: (intent: VocabularyIntent) => Promise<void>;
}

export interface FurnitureItem {
  entityType: string;
  rooms: string[];
  /** Every place it sits is outside the home, where nothing is furnished and nothing is checked. */
  outside: boolean;
  proposal?: FurnitureProposalView;
  /** In the vocabulary already, but with nothing declared it is for — as permissive as unknown. */
  declaredEmpty: boolean;
}

export interface ActivityItem {
  intentId: string;
  proposal?: ActivityProposalView;
  model?: RawProcessModel;
}


/** Everything the review has to ask about, given what the vocabulary already holds. */
export function reviewItems(reading: HorizonReading, pack: VocabularyPack): { furniture: FurnitureItem[]; activities: ActivityItem[] } {
  const types = new Map(pack.entityTypes.map((item) => [item.entityType, item]));
  const proposedFurniture = new Map(reading.proposals.furniture.map((item) => [item.entityType, item]));
  const furniture = new Map<string, FurnitureItem>();
  const note = (entityType: string, where?: string) => {
    const known = types.get(entityType);
    if (known && known.capabilities.length) return;
    const item = furniture.get(entityType) ?? { entityType, rooms: [], outside: false, proposal: proposedFurniture.get(entityType), declaredEmpty: !!known };
    if (where && !item.rooms.includes(where)) item.rooms.push(where);
    item.outside = item.rooms.length > 0 && item.rooms.every((place) => !reading.rooms.includes(place));
    furniture.set(entityType, item);
  };
  for (const object of reading.furniture) note(object.resourceType, object.room);
  for (const proposal of reading.proposals.furniture) note(proposal.entityType);

  const intents = new Set([...pack.intents.map((item) => item.intentId), ...pack.awayIntents.map((item) => item.intentId)]);
  const activities = new Map<string, ActivityItem>();
  for (const proposal of reading.proposals.activities) {
    if (!intents.has(proposal.intentId)) activities.set(proposal.intentId, { intentId: proposal.intentId, proposal, model: proposal.processModel });
  }
  for (const intent of reading.usedIntents) {
    if (!intents.has(intent) && !activities.has(intent)) activities.set(intent, { intentId: intent, model: reading.proposals.modelsByIntent[intent] });
  }
  return { furniture: [...furniture.values()], activities: [...activities.values()] };
}


export type AdviceTone = "add" | "remove" | "check" | "none";

export interface Advice {
  tone: AdviceTone;
  text: string;
}

/**
 * What the review recommends for an object, in one sentence the researcher can act on.
 *
 * The recommendation is only ever read off facts the preview already has: where the object sits,
 * whether anyone proposed it, and whether what it claims to be for is something an action needs.
 * It decides nothing; the three buttons are still the researcher's.
 */
export function furnitureAdvice(item: FurnitureItem, capabilities: readonly string[]): Advice {
  if (item.outside) {
    return {
      tone: "remove",
      text: "Remove it from this import. It sits outside the home, where the simulator builds no furniture and checks no capability — an outing needs no object — so it would never be used.",
    };
  }
  if (!item.rooms.length) {
    return {
      tone: "none",
      text: "Nothing to do for this import: no object in the home has this type. Add it only if you want it available to later outlines.",
    };
  }
  if (item.declaredEmpty) {
    return {
      tone: "check",
      text: "Say what it is for. The vocabulary already has this type but no capability for it, so it is as permissive as an unknown one.",
    };
  }
  if (!item.proposal) {
    return {
      tone: "check",
      text: "Decide what it is. The author used this type without proposing it, so nothing says what it is for: add it with its capabilities, use a known type, or remove it.",
    };
  }
  const invented = item.proposal.capabilities.filter((value) => !capabilities.includes(value));
  if (invented.length) {
    return {
      tone: "check",
      text: `Check it before adding. It claims to be for ${invented.map((value) => value.replace(/_/g, " ")).join(", ")}, which no action needs, so as proposed it would bind nothing.`,
    };
  }
  return {
    tone: "add",
    text: "Add it, if the proposal is right: the form is filled in from it, so check the name and what it is for.",
  };
}

export function activityAdvice(item: ActivityItem): Advice {
  if (!item.model) {
    return {
      tone: "check",
      text: "The import cannot run with it, and the file gives no process to start from: add it on the Vocabulary page, or ask the author to use a listed activity instead.",
    };
  }
  return {
    tone: "add",
    text: "Add it, if the name is right: the import cannot run without it, and it will start from the author's own steps.",
  };
}

/**
 * The vocabulary entry an accepted activity becomes, started from the author's own process.
 *
 * The model is re-addressed as the vocabulary's reference model. Its components are kept when they
 * are the catalog's, so the author's packages keep validating; an `authored__` component, which
 * is what the prompt asks a proposal to declare, is dropped because the vocabulary derives it.
 */
export function intentFromProposal(
  intentId: string,
  { label, category, room: location, description }: { label: string; category: string; room: string; description: string },
  model: RawProcessModel,
): VocabularyIntent {
  const components = (model.implementedComponents ?? []).filter((value) => !value.startsWith("authored__"));
  const processModel = {
    ...model,
    processModelId: `reference__${intentId}`,
    processModelVersion: typeof model.processModelVersion === "string" ? model.processModelVersion : "1.0.0",
    residentId: "reference_resident",
    title: `reference ${label.toLowerCase()} process`,
    description: `Accepted from an outline's proposal for '${intentId}'.`,
    implementedComponents: model.implementedComponents ?? [],
    nodes: model.nodes ?? [],
    edges: model.edges ?? [],
  } as unknown as ProcessModel;
  return {
    intentId,
    label,
    category,
    defaultLocation: location,
    returnLocation: null,
    description,
    components,
    externalMappings: {},
    processModel,
  };
}


/** Chosen as the replacement for a resource type, it removes those objects from the import. */
export const REMOVED = "";

/**
 * The document to import, with the resource types the researcher chose to replace or remove.
 *
 * Both shapes the outline prompt returns carry `world` in the same place relative to the outline:
 * inside `outline` for the envelope, at the top for a bare outline.
 */
export function substituteResourceTypes(document: Record<string, unknown>, substitutions: Record<string, string>): Record<string, unknown> {
  if (!Object.keys(substitutions).length) return document;
  const outline = (document.outline && typeof document.outline === "object" ? document.outline : document) as { world?: { resources?: Array<Record<string, unknown>> } };
  const resources = outline.world?.resources;
  if (!Array.isArray(resources)) return document;
  const decided = (item: Record<string, unknown>) => typeof item.resourceType === "string" && item.resourceType in substitutions ? substitutions[item.resourceType] : undefined;
  const replaced = resources
    .filter((item) => decided(item) !== REMOVED)
    .map((item) => { const to = decided(item); return to ? { ...item, resourceType: to } : item; });
  const world = { ...outline.world, resources: replaced };
  return document.outline && typeof document.outline === "object"
    ? { ...document, outline: { ...(document.outline as object), world } }
    : { ...document, world };
}
