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

/**
 * A change the researcher made to the imported copy, to get past something the outline cannot do.
 *
 * Two kinds, the two repairs a room that cannot host an activity has: furnish the room, or send the
 * activity somewhere that already can. Like a substitution, an amendment touches only the copy that
 * is sent; the file on disk stays as the author wrote it. `reason` is the finding it answers, kept
 * so the change can be explained wherever it is listed.
 */
export type OutlineAmendment =
  | { kind: "add_furniture"; key: string; resourceId: string; resourceType: string; room: string; reason: string }
  | { kind: "move_activity"; key: string; recurringActivityId: string; from: string; room: string; reason: string };

type Json = Record<string, unknown>;

function outlineOf(document: Json): Json {
  return (document.outline && typeof document.outline === "object" ? document.outline : document) as Json;
}

function withOutline(document: Json, outline: Json): Json {
  return document.outline && typeof document.outline === "object" ? { ...document, outline } : outline;
}

/** Every resource identifier the document already uses, so a new one cannot collide with it. */
export function resourceIds(document: Json): Set<string> {
  const world = outlineOf(document).world as { resources?: Array<{ resourceId?: unknown }> } | undefined;
  return new Set((world?.resources ?? []).map((item) => item.resourceId).filter((value): value is string => typeof value === "string"));
}

/** `living_room_bookshelf`, then `living_room_bookshelf_2`, and so on, until nothing uses it. */
export function newResourceId(room: string, resourceType: string, taken: Set<string>): string {
  const base = `${room}_${resourceType}`;
  if (!taken.has(base)) return base;
  let index = 2;
  while (taken.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

/**
 * A recurring activity sent to another room, wherever the document keeps it.
 *
 * Recognised by carrying a `cadence` as well as the identifier: a phase override names the same
 * identifier and has no room of its own to change.
 */
function moveActivity(value: unknown, recurringActivityId: string, room: string): unknown {
  if (Array.isArray(value)) return value.map((item) => moveActivity(item, recurringActivityId, room));
  if (!value || typeof value !== "object") return value;
  const object = value as Json;
  if (object.recurringActivityId === recurringActivityId && "cadence" in object) return { ...object, location: room };
  return Object.fromEntries(Object.entries(object).map(([key, item]) => [key, moveActivity(item, recurringActivityId, room)]));
}

/** The document to import, with every amendment the researcher made, in the order they made them. */
export function applyAmendments(document: Json, amendments: readonly OutlineAmendment[]): Json {
  let outline = outlineOf(document);
  for (const amendment of amendments) {
    if (amendment.kind === "add_furniture") {
      const world = (outline.world ?? {}) as Json;
      const resources = Array.isArray(world.resources) ? world.resources : [];
      outline = {
        ...outline,
        world: { ...world, resources: [...resources, { resourceId: amendment.resourceId, resourceType: amendment.resourceType, locationId: amendment.room }] },
      };
    } else {
      outline = moveActivity(outline, amendment.recurringActivityId, amendment.room) as Json;
    }
  }
  return amendments.length ? withOutline(document, outline) : document;
}

/** What one amendment did, in a sentence. */
export function describeAmendment(amendment: OutlineAmendment): string {
  const words = (value: string) => value.replace(/_/g, " ");
  return amendment.kind === "add_furniture"
    ? `Added a ${words(amendment.resourceType)} (${amendment.resourceId}) to the ${words(amendment.room)}.`
    : `Moved ${amendment.recurringActivityId} from the ${words(amendment.from)} to the ${words(amendment.room)}.`;
}

/** The provenance parameter the expander carries into the scenario, and the summary page lists. */
export const RESEARCHER_CHANGES = "researcherChanges";

/**
 * Every change made at import, as the records the scenario keeps of it.
 *
 * Substitutions first, in the order of their types, then the amendments in the order they were made:
 * the same order the document was changed in. The `key` of an amendment belongs to the page and is
 * left out.
 */
export function researcherChanges(substitutions: Record<string, string>, amendments: readonly OutlineAmendment[]): Json[] {
  const substituted: Json[] = Object.entries(substitutions).map(([from, to]) =>
    to === REMOVED ? { kind: "remove_type", resourceType: from } : { kind: "substitute_type", from, to },
  );
  const amended: Json[] = amendments.map((amendment) => Object.fromEntries(Object.entries(amendment).filter(([name]) => name !== "key")));
  return [...substituted, ...amended];
}

/**
 * The document to import, saying in its own provenance what the researcher changed in it.
 *
 * Appended to whatever the outline already lists, so a copy changed twice keeps both rounds. An
 * outline without a provenance object is left as it is: there is nowhere valid to say it.
 */
export function recordResearcherChanges(document: Json, changes: readonly Json[]): Json {
  if (!changes.length) return document;
  const outline = outlineOf(document);
  const provenance = outline.provenance;
  if (!provenance || typeof provenance !== "object" || Array.isArray(provenance)) return document;
  const parameters = ((provenance as Json).parameters && typeof (provenance as Json).parameters === "object" ? (provenance as Json).parameters : {}) as Json;
  const earlier = Array.isArray(parameters[RESEARCHER_CHANGES]) ? parameters[RESEARCHER_CHANGES] : [];
  return withOutline(document, {
    ...outline,
    provenance: { ...provenance, parameters: { ...parameters, [RESEARCHER_CHANGES]: [...earlier, ...changes] } },
  });
}
