/**
 * The vocabulary pack, as the API sends it.
 *
 * Mirrors `smart_home_sim.domain.vocabulary`. Kept as plain types rather than as a validation
 * layer: the server validates, and a second set of rules here could only disagree with it. What
 * the editor owns is the shape of an *edit*, which is `draft.ts`.
 */

export type ValueSource =
  | "literal"
  | "variable"
  | "activity_intent"
  | "activity_location"
  | "resident_profile";

export interface ValueExpression {
  source: ValueSource;
  value: string | number | boolean | null;
  variableId: string | null;
  index: number | null;
}

export type ReferenceKind = "none" | "location" | "capability" | "environment_entity" | "variable";

export interface ActionParameterDefinition {
  parameterName: string;
  description: string;
  valueType: string;
  required: boolean;
  referenceKind: ReferenceKind;
  allowedValues: unknown[];
}

export interface CapabilityRequirement {
  role: string;
  capability: string;
  parameterName: string | null;
}

export interface ActionDefinition {
  actionType: string;
  description: string;
  parameters: ActionParameterDefinition[];
  requiredCapabilities: CapabilityRequirement[];
  preconditions: unknown[];
  effects: unknown[];
}

export interface ActionObservability {
  /** Working at an object: pulses the detector watching that object. */
  motionAtObject: boolean;
  /** Crossing the flat: pulses every detector along the planned path. */
  motionAlongPath: boolean;
}

export interface VocabularyAction {
  definition: ActionDefinition;
  /** `null` is elastic — the action absorbs the activity's time. A number is a fixed gesture. */
  gestureSeconds: number | null;
  observability: ActionObservability;
  isTravel: boolean;
}

export interface VocabularyEntityType {
  entityType: string;
  displayName: string;
  capabilities: string[];
  roleAliases: string[];
  contactInstrumented: boolean;
  symbolId: string | null;
  /** SVG drawn in a -24..24 box, for a type the bundled glyphs do not cover. */
  symbolBody: string | null;
}

export type ProcessNodeKind =
  | "start"
  | "end"
  | "action"
  | "choice"
  | "parallel_split"
  | "parallel_join"
  | "loop";

export interface ProcessNode {
  nodeId: string;
  kind: ProcessNodeKind;
  actionType: string | null;
  arguments: Record<string, ValueExpression>;
  duration: unknown | null;
  durationWeight: number | null;
  preconditions: unknown[];
  effects: unknown[];
  maxIterations: number | null;
}

export interface ProcessEdge {
  sourceNodeId: string;
  targetNodeId: string;
  condition: unknown | null;
  isDefault: boolean;
}

export interface ProcessModel {
  processModelId: string;
  processModelVersion: string;
  residentId: string;
  title: string;
  description: string;
  implementedComponents: string[];
  nodes: ProcessNode[];
  edges: ProcessEdge[];
}

export interface VocabularyIntent {
  intentId: string;
  label: string;
  category: string;
  defaultLocation: string;
  returnLocation: string | null;
  description: string;
  components: string[];
  externalMappings: Record<string, string>;
  processModel: ProcessModel;
}

export interface VocabularyAwayIntent {
  intentId: string;
  label: string;
  description: string;
  externalMappings: Record<string, string>;
}

export interface VocabularyPack {
  schemaVersion: string;
  documentType: string;
  packId: string;
  basePackId: string;
  sourceCatalogs: Record<string, string>;
  actions: VocabularyAction[];
  entityTypes: VocabularyEntityType[];
  intents: VocabularyIntent[];
  awayIntents: VocabularyAwayIntent[];
}

export interface VocabularyView {
  pack: VocabularyPack;
  /** False means nothing is stored and this is the vocabulary the simulator ships with. */
  customised: boolean;
  digest: string;
  /** Covers the intents alone. A change here means the ground-truth labels moved. */
  labelSpaceDigest: string;
}

export type GapSeverity = "blocking" | "warning" | "note";

export interface VocabularyGap {
  code: string;
  severity: GapSeverity;
  subject: string;
  message: string;
  consequence: string;
  details: Record<string, string[]>;
}

export interface VocabularyGapsReport {
  packId: string;
  digest: string;
  gaps: VocabularyGap[];
}

export interface VocabularyReview {
  digest: string;
  labelSpaceDigest: string;
  report: VocabularyGapsReport;
}
