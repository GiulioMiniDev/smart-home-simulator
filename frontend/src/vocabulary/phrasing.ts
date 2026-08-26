/**
 * Saying what a step does in a sentence, instead of showing a function call.
 *
 * An activity is stored as `open(target: food_storage)`. That is precise and unreadable, and the
 * whole point of this editor is that someone who is not a programmer can change what an activity
 * *is*. So every step is rendered twice: the sentence, which is what they read, and the call,
 * which is what they are editing.
 *
 * The dictionaries below are the only place in the system where an action or a role has an English
 * reading. An action the researcher invents will not be in them, which is deliberate — it falls
 * back to its own identifier rather than to a wrong guess, and the editor asks for a sentence when
 * a new action is created.
 */

import type { ProcessNode, ValueExpression, VocabularyAction, VocabularyPack } from "./types";

/** `{0}` is the action's own argument, already turned into a noun. */
const ACTION_PHRASES: Record<string, string> = {
  move_to: "Walks to where the activity happens",
  move_to_capability: "Walks over to {0}",
  change_posture: "{0}",
  open: "Opens {0}",
  close: "Closes {0}",
  take_item: "Picks up {0}",
  put_item: "Puts {0} down",
  activate: "Switches on {0}",
  deactivate: "Switches off {0}",
  wait: "Waits — {0}",
  inspect: "Checks {0}",
  consume: "Eats or drinks {0}",
  personal_care: "{0}",
  clean: "Cleans {0}",
  laundry_step: "Laundry: {0}",
  organize: "Tidies {0}",
  dress: "Gets dressed",
  manage_medication: "Medication: {0}",
  leave_home: "Leaves the flat",
  enter_home: "Comes back into the flat",
  travel_to: "Travels to {0}",
  shop: "Does the shopping",
  communicate: "Talks over {0}",
  perform_work: "Works",
  exercise: "Exercises — {0}",
  leisure: "Relaxes — {0}",
  prepare_food: "Cooks {0}",
};

/**
 * Two actions are nothing but their argument. `change_posture` reads as "Sits down", which is right
 * in a step and useless in a list of actions, where there is no argument to stand in.
 */
const ACTION_SUMMARIES: Record<string, string> = {
  change_posture: "Sits, stands or lies down",
  personal_care: "Washes, showers or uses the toilet",
};

/** Argument values that read as a phrase rather than as a noun. */
const VALUE_PHRASES: Record<string, string> = {
  sitting: "Sits down",
  standing: "Stands up",
  lying: "Lies down",
  evening_hygiene: "Washes and brushes her teeth for the night",
  use_toilet: "Uses the toilet",
  shower: "Showers",
  wash_face: "Washes her face",
  wash_hands: "Washes her hands",
  take: "takes the dose",
  hang: "hangs it out to dry",
  collect: "gathers the washing",
  load: "loads the drum",
  start: "starts the cycle",
  rest: "resting",
  nap: "napping",
  sleep: "asleep",
  walking: "a walk",
  indoor_light_exercise: "light exercise indoors",
  read: "reading",
  focused_work: "at her desk",
  phone: "the phone",
  hot_drink: "a hot drink",
  kitchen_surfaces: "the kitchen surfaces",
};

/** What a role is, said the way someone describes their own flat. */
const ROLE_NOUNS: Record<string, string> = {
  food_storage: "the fridge",
  coffee_and_breakfast_storage: "the breakfast cupboard",
  cleaning_product_storage: "the cleaning cupboard",
  household_storage: "the household cupboard",
  medication_cabinet: "the medicine cabinet",
  medication_storage: "the medicine cabinet",
  laundry_storage: "the laundry basket",
  laundry_equipment: "the washing machine",
  washing_machine: "the washing machine",
  cooking_appliance: "the hob",
  food_preparation_area: "the worktop",
  coffee_equipment: "the moka pot",
  consumption_area: "the table",
  table: "the table",
  washing_area: "the sink",
  sink: "the sink",
  sink_faucet: "the tap",
  drinking_water_source: "the tap",
  personal_care_fixture: "the basin",
  toilet: "the toilet",
  shower: "the shower",
  shower_water: "the shower",
  television: "the television",
  ingredients: "the ingredients",
  prepared_meal: "the meal",
  prepared_food_portions: "the portions",
  drink: "the drink",
  drinking_glass: "a glass",
  drinking_water: "some water",
  medication_dose_container: "the pill box",
  cleaning_tool: "the cloth",
  purchases: "the shopping",
  walking_area: "the front door",
  drying_area: "the drying rack",
  exercise_area: "a clear bit of floor",
  tidying_area: "the room",
  retail_area: "the shop",
  communication_area: "the armchair",
};

export const CATEGORY_LABELS: Record<string, string> = {
  sleep_wake: "Getting up and going to bed",
  hygiene: "Washing and the bathroom",
  medication: "Taking medicine",
  meal: "Sitting down to eat",
  cooking: "Making food and drink",
  chores: "Tidying and cleaning",
  laundry: "Washing clothes",
  exercise: "Moving on purpose",
  outdoor: "Time outside the flat",
  errand: "Going out to fetch something",
  leisure: "Free time at home",
  social: "Contact with other people",
  home_work: "Paid work done indoors",
};

/** The order the enum declares, which is roughly the order a day runs through them. */
export const CATEGORY_ORDER = [
  "sleep_wake",
  "hygiene",
  "medication",
  "meal",
  "cooking",
  "chores",
  "laundry",
  "exercise",
  "outdoor",
  "errand",
  "leisure",
  "social",
  "home_work",
];

export function roleNoun(role: string): string {
  return ROLE_NOUNS[role] ?? VALUE_PHRASES[role] ?? role.replace(/_/g, " ");
}

/** Parameter kinds that name something in the flat, as opposed to a mode or a procedure. */
const BINDING_KINDS = new Set(["capability", "environment_entity"]);

export function isBindingParameter(action: VocabularyAction | undefined, name: string): boolean {
  const parameter = action?.definition.parameters.find((item) => item.parameterName === name);
  return parameter ? BINDING_KINDS.has(parameter.referenceKind) : false;
}

/** How an action reads on its own, for a list where there is no argument to stand in. */
export function actionSummary(actionType: string): string {
  const summary = ACTION_SUMMARIES[actionType];
  if (summary) return summary;
  const phrase = ACTION_PHRASES[actionType];
  if (!phrase) return `Performs ${actionType.replace(/_/g, " ")}`;
  return phrase.replace("{0}", "…");
}

function literalOf(argument: ValueExpression): string | null {
  if (argument.source !== "literal") return null;
  return typeof argument.value === "string" ? argument.value : null;
}

/**
 * One step, as a sentence.
 *
 * A literal reads as itself. `activity_intent` and `activity_location` are only filled in per
 * activity at run time, so a literal sibling is preferred first — `prepare_food(mealKind:
 * activity_intent, outputRole: prepared_meal)` reads as "Cooks the meal" rather than as "Cooks
 * what this activity calls for".
 */
export function stepPhrase(node: ProcessNode): string {
  const actionType = node.actionType ?? "";
  const template = ACTION_PHRASES[actionType];
  if (!template) return `Performs ${actionType.replace(/_/g, " ") || "nothing"}`;
  if (!template.includes("{0}")) return template;

  let fallback: string | null = null;
  for (const argument of Object.values(node.arguments)) {
    const literal = literalOf(argument);
    if (literal !== null) {
      return template.replace("{0}", VALUE_PHRASES[literal] ?? ROLE_NOUNS[literal] ?? literal);
    }
    if (fallback === null) {
      fallback = argument.source === "activity_location" ? "the room" : "what this activity calls for";
    }
  }
  return template.replace("{0}", fallback ?? "it");
}

/** The machine truth, under the sentence. */
export function stepCall(node: ProcessNode): string {
  const parts = Object.entries(node.arguments).map(([name, argument]) => {
    const literal = literalOf(argument);
    return `${name}: ${literal ?? argument.source}`;
  });
  return `${node.actionType ?? "?"}(${parts.join(", ")})`;
}

export type EvidenceKind = "walk" | "object" | "contact" | "presence";

export interface StepEvidence {
  kind: EvidenceKind;
  label: string;
}

/** Which furniture types can answer a role — the inverse of the pack's alias table. */
export function typesForRole(pack: VocabularyPack, role: string): string[] {
  const matches = pack.entityTypes
    .filter((item) => item.roleAliases.includes(role))
    .map((item) => item.entityType);
  // A type names itself, but only a type that declares aliases at all: admitting every furniture
  // name as a role would be wider than the binder actually is.
  const named = pack.entityTypes.find((item) => item.entityType === role);
  if (named && named.roleAliases.length > 0) matches.push(role);
  return [...new Set(matches)].sort();
}

/** What the sensor log gains from this step. */
export function stepEvidence(pack: VocabularyPack, node: ProcessNode): StepEvidence[] {
  const action = pack.actions.find((item) => item.definition.actionType === node.actionType);
  if (!action) return [{ kind: "presence", label: "presence only" }];
  const evidence: StepEvidence[] = [];
  if (action.isTravel) evidence.push({ kind: "walk", label: "motion along the way" });
  if (action.observability.motionAtObject) {
    evidence.push({ kind: "object", label: "motion at the object" });
  }
  if (node.actionType === "open" || node.actionType === "close") {
    for (const [name, argument] of Object.entries(node.arguments)) {
      if (!isBindingParameter(action, name)) continue;
      const literal = literalOf(argument);
      if (literal === null) continue;
      const instrumented = typesForRole(pack, literal).filter(
        (type) => pack.entityTypes.find((item) => item.entityType === type)?.contactInstrumented,
      );
      if (instrumented.length > 0) {
        const noun = pack.entityTypes.find((item) => item.entityType === instrumented[0]);
        evidence.push({ kind: "contact", label: `${noun?.displayName ?? instrumented[0]} door` });
      }
    }
  }
  return evidence.length > 0 ? evidence : [{ kind: "presence", label: "presence only" }];
}

/** The furniture this step will actually touch, and the role that asked for it. */
export function stepBinding(
  pack: VocabularyPack,
  node: ProcessNode,
): { role: string | null; types: string[] } {
  const action = pack.actions.find((item) => item.definition.actionType === node.actionType);
  for (const [name, argument] of Object.entries(node.arguments)) {
    if (!isBindingParameter(action, name)) continue;
    const literal = literalOf(argument);
    if (literal === null) continue;
    return { role: literal, types: typesForRole(pack, literal) };
  }
  return { role: null, types: [] };
}

/** How long a step lasts, said in words rather than in a number that needs explaining. */
export function stepTiming(action: VocabularyAction | undefined, node: ProcessNode): string {
  if (!action) return "unknown";
  if (action.isTravel && action.gestureSeconds === 0) return "as long as the walk";
  if (action.gestureSeconds === null) return `fills the activity · weight ${(node.durationWeight ?? 1).toFixed(1)}`;
  return `${action.gestureSeconds}s, fixed`;
}
