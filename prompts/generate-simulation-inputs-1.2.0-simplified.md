# Prompt Semplificato per LLM Locali (v1.2.0)

Genera un singolo oggetto JSON valido e compilabile che rappresenti un bundle di simulazione per la descrizione fornita alla fine.
Restituisci **ESCLUSIVAMENTE** il JSON, senza racchiuderlo in blocchi markdown o inserire commenti o spiegazioni.

---

## 1. Struttura del JSON (TypeScript Interface)

```typescript
interface SimulationAuthoringBundle {
  schemaVersion: "1.0.0";
  documentType: "simulation_authoring_bundle";
  scenario: ScenarioDocument;
  personalProcessPackage: ProcessPackageDocument;
}

interface ScenarioDocument {
  schemaVersion: "1.0.0";
  documentType: "life_scenario";
  scenarioId: string; // ID univoco per lo scenario (es. "sim_marco_rossi")
  title: string;
  timeZone: string; // Deve essere una timezone IANA valida (es. "Europe/Rome" o "UTC")
  simulationWindow: { start: string; end: string }; // ISO datetime con offset (es. "2024-12-16T08:00:00+01:00")
  seed: number; // default 1
  provenance: Provenance;
  modelReferences: {
    activityCatalog: { referenceId: "smart_home_activity_catalog"; version: "1.0.0" };
    homeModel: { referenceId: string; version: "1.0.0" };
  };
  residents: Resident[];
  locations: Location[]; // kind deve essere uno tra: "room", "external", "transit", "composite"
  resources: Resource[];
  initialState: InitialState;
  days: DayPlan[]; // Un DayPlan per ogni giorno nel simulationWindow
}

interface Provenance {
  authorType: "external_llm";
  generatorName: "smart-home-simulator-external-llm-authoring";
  generatorVersion: "1.2.0";
  promptTemplateVersion: "generate-simulation-inputs-1.2.0";
  humanReviewed: false;
  modelName: string; // Nome del tuo modello (es. "qwen2.5-coder")
  generatedAt: string; // ISO datetime corrente
  parameters?: any;
}

interface Resident {
  residentId: string;
  displayName: string;
  profile: {
    age: number;
    gender: string;
    occupation: string;
    healthConditions?: string[];
    medication?: string[];
    chronotype?: string;
    stressLevel?: number;
    [key: string]: any;
  };
}

interface Location {
  locationId: string;
  kind: "room" | "external" | "transit" | "composite";
  memberLocationIds?: string[]; // SOLO per kind "composite"
  attributes?: Record<string, any>;
}

interface Resource {
  resourceId: string;
  resourceType: string;
  locationId: string; // Deve essere una delle locationId dichiarate
  capacity?: number; // default 1
  attributes?: Record<string, any>;
}

interface InitialState {
  at: string; // ISO timestamp uguale a start window
  residents: { residentId: string; locationId: string; facts?: Record<string, any> }[];
  resourceFacts?: Record<string, Record<string, any>>; // NOTA: I valori dei fatti devono essere oggetti (es. {"open": {"source": "literal", "value": true}}), mai booleani semplici!
}

interface DayPlan {
  date: string; // formato YYYY-MM-DD
  context: { dayType: "weekday" | "weekend"; facts?: Record<string, any> };
  activities: Activity[];
}

interface Activity {
  activityId: string; // Univoco (es. "act_sleep_day1")
  actorId: string;
  intent: string; // Deve corrispondere a uno degli Intent nel catalogo attività sotto
  locationIds: string[]; // Almeno 1 locationId dichiarato
  requiredResources?: { resourceId: string; units?: number }[];
  startWindow: DateTimeWindow; // OBBLIGATORIO: Ogni attività deve sempre definire startWindow!
  duration: DurationRange;     // OBBLIGATORIO: Ogni attività deve sempre definire duration (minimumMinutes, preferredMinutes, maximumMinutes)!
  priority?: number; // 0-100 (default 50)
  mandatory?: boolean; // default true
  activation?: { mode: "always" | "conditional" | "fallback"; condition?: any; fallbackForActivityId?: string };
}

interface DateTimeWindow {
  earliest: string; // ISO timestamp
  preferred: string; // ISO timestamp
  latest: string; // ISO timestamp
}

interface DurationRange {
  minimumMinutes: number;
  preferredMinutes: number;
  maximumMinutes: number;
}

interface ProcessPackageDocument {
  schemaVersion: "1.0.0";
  packageId: string;
  packageVersion: "1.0.0";
  sourceScenarioId: string;
  sourceScenarioVersion: "1.0.0";
  language: string; // es. "it" o "en"
  provenance: Provenance;
  catalogs: {
    activityCatalog: { catalogId: "smart_home_activity_catalog"; version: "1.0.0" };
    variableCatalog: { catalogId: "smart_home_variable_catalog"; version: "1.0.0" };
    actionCatalog: { catalogId: "smart_home_action_catalog"; version: "1.0.0" };
  };
  processModels: ProcessModel[];
  bindings: ProcessBinding[];
}

interface ProcessModel {
  processModelId: string;
  processModelVersion: "1.0.0";
  residentId: string; // Resident a cui si applica il modello
  title: string;
  description: string;
  implementedComponents: string[]; // Deve corrispondere ESATTAMENTE ai components dell'intent associato nel catalogo
  nodes: ProcessNode[];
  edges: ProcessEdge[];
}

interface ProcessNode {
  nodeId: string;
  kind: "start" | "end" | "action" | "choice" | "loop";
  actionType?: string; // Solo per kind "action", deve corrispondere al catalogo azioni sotto
  arguments?: Record<string, ValueExpression>; // Solo per kind "action"
  durationWeight?: number; // OBBLIGATORIO se kind == "action" (es. durationWeight: 1). MAI mettere durationWeight nelle attività dello scenario!
  maxIterations?: number; // Solo per loop
}

interface ProcessEdge {
  sourceNodeId: string;
  targetNodeId: string;
  condition?: any;
  isDefault?: boolean;
}

interface ProcessBinding {
  bindingId: string;
  residentId: string;
  intent: string;
  processModelId: string;
}

type ValueExpression =
  | { source: "activity_location"; index: number } // index fa riferimento alla posizione in locationIds dell'attività
  | { source: "activity_resource"; index: number } // index fa riferimento alla posizione in requiredResources dell'attività
  | { source: "actor" }
  | { source: "literal"; value: any }
  | { source: "variable"; variableId: string };
```

---

## 2. REGOLE DI VALIDAZIONE (EVITARE CONFUSIONE TRA ATTIVITÀ E NODI)

1. **Nelle ATTIVITÀ dello Scenario (`scenario.days[].activities`)**:
   - Ogni attività DEVE contenere **`startWindow`** (`earliest`, `preferred`, `latest`) E **`duration`** (`minimumMinutes`, `preferredMinutes`, `maximumMinutes`).
   - MAI mettere `durationWeight` dentro un'Attività dello scenario!

2. **Nei NODI dei Modelli di Processo (`personalProcessPackage.processModels[].nodes`)**:
   - Ogni nodo di tipo `"action"` DEVE contenere **`"durationWeight": 1`**.
   - MAI mettere `startWindow` o `duration` nei nodi dei modelli di processo!

3. **Argomenti delle Azioni (`ValueExpression`)**:
   - Gli argomenti nei nodi delle azioni (es. `posture`, `destination`, `target`, `itemRole`) DEVONO essere oggetti `ValueExpression` (es. `{"source": "literal", "value": "standing"}`), mai stringhe grezze!

---

## 3. Catalogo delle Attività Autorizzate (Intent & Components)

Ogni attività nel piano giornaliero (`days[].activities`) deve usare uno dei seguenti `intent`. I modelli di processo associati in `processModels` devono dichiarare gli stessi `implementedComponents` nell'ordine esatto specificato qui:

- **aperitivo_with_paolo**: components: ['socialize_in_person', 'consume_drink']
- **buy_fresh_food_and_household_supplies**: components: ['shop', 'carry_purchases']
- **buy_groceries**: components: ['shop', 'carry_purchases']
- **call_friend_paolo**: components: ['phone_call']
- **call_mother**: components: ['phone_call']
- **call_sister_lucia**: components: ['phone_call']
- **change_clothes**: components: ['change_clothes']
- **change_clothes_and_eat_snack**: components: ['change_clothes', 'consume_snack']
- **change_clothes_and_have_coffee**: components: ['change_clothes', 'consume_drink']
- **change_clothes_and_have_snack**: components: ['change_clothes', 'consume_snack']
- **check_calendar_and_household_supplies**: components: ['check_calendar', 'inspect_supplies']
- **clean_bathroom**: components: ['clean_surface']
- **clean_kitchen**: components: ['clean_surface']
- **collect_belongings_and_leave_home**: components: ['collect_belongings', 'leave_home']
- **collect_medication_refill**: components: ['collect_medication']
- **commute_home**: components: ['travel', 'enter_home']
- **commute_to_work**: components: ['travel']
- **complete_pending_dishwashing**: components: ['wash_dishes']
- **cook_chicken_and_vegetables**: components: ['prepare_food']
- **cook_dinner**: components: ['prepare_food']
- **dress_for_work**: components: ['change_clothes']
- **eat_afternoon_snack**: components: ['consume_snack']
- **eat_breakfast**: components: ['consume_meal']
- **eat_breakfast_and_listen_to_radio**: components: ['consume_meal', 'listen_radio']
- **eat_breakfast_and_read_news**: components: ['consume_meal', 'read_news']
- **eat_breakfast_with_radio_news**: components: ['consume_meal', 'listen_radio']
- **eat_dinner**: components: ['consume_meal']
- **eat_light_dinner**: components: ['consume_meal']
- **eat_lunch**: components: ['consume_meal']
- **evening_hygiene**: components: ['personal_hygiene']
- **evening_walk**: components: ['walk']
- **go_to_neighborhood_market**: components: ['travel']
- **hang_bed_linen**: components: ['hang_laundry']
- **hang_laundry**: components: ['hang_laundry']
- **indoor_light_exercise**: components: ['exercise']
- **iron_work_shirts**: components: ['iron_laundry']
- **leave_home**: components: ['leave_home']
- **long_sunday_walk**: components: ['walk']
- **morning_toilet_and_shower**: components: ['use_toilet', 'shower']
- **morning_toilet_and_wash**: components: ['use_toilet', 'wash_face']
- **portion_and_store_prepared_food**: components: ['portion_food', 'store_food']
- **post_walk_shower**: components: ['shower']
- **prepare_and_eat_breakfast**: components: ['prepare_food', 'consume_meal']
- **prepare_breakfast**: components: ['prepare_food']
- **prepare_coffee_and_drink_on_balcony**: components: ['prepare_drink', 'consume_drink']
- **prepare_friday_clothes_and_bag**: components: ['organize_clothes', 'organize_bag']
- **prepare_light_dinner**: components: ['prepare_food']
- **prepare_monday_clothes_bag_and_documents**: components: ['organize_clothes', 'organize_bag', 'organize_documents']
- **prepare_next_workday**: components: ['organize_clothes', 'organize_bag']
- **prepare_next_workday_clothes_and_bag**: components: ['organize_clothes', 'organize_bag']
- **prepare_quick_pasta_and_salad**: components: ['prepare_food', 'prepare_salad']
- **prepare_rice_and_vegetables**: components: ['prepare_food']
- **prepare_simple_lunch**: components: ['prepare_food']
- **prepare_sunday_lunch**: components: ['prepare_food']
- **prepare_to_visit_mother**: components: ['change_clothes', 'collect_belongings']
- **prepare_weekend_breakfast**: components: ['prepare_food']
- **put_groceries_away**: components: ['store_purchases']
- **read**: components: ['read']
- **read_and_rest**: components: ['read', 'rest']
- **read_in_bed**: components: ['read_in_bed']
- **reheat_leftover_dinner_and_prepare_salad**: components: ['reheat_food', 'prepare_salad']
- **rest**: components: ['rest']
- **rest_and_read**: components: ['rest', 'read']
- **rest_or_nap**: components: ['rest', 'nap']
- **return_home_and_store_purchases**: components: ['travel', 'enter_home', 'store_purchases']
- **short_evening_walk**: components: ['walk']
- **shower_and_get_ready_to_go_out**: components: ['shower', 'change_clothes']
- **sleep**: components: ['sleep']
- **start_bed_linen_laundry**: components: ['collect_laundry', 'load_laundry', 'start_laundry']
- **start_laundry**: components: ['collect_laundry', 'load_laundry', 'start_laundry']
- **take_morning_medication**: components: ['take_medication']
- **take_recycling_out**: components: ['carry_recycling', 'leave_home', 'discard_recycling']
- **tidy_living_room_and_hallway**: components: ['tidy_area']
- **travel_home**: components: ['travel', 'enter_home']
- **travel_to_mothers_home**: components: ['travel']
- **travel_to_neighborhood_bar**: components: ['travel']
- **travel_to_pharmacy**: components: ['travel']
- **travel_to_supermarket**: components: ['travel']
- **vacuum_and_dust_apartment**: components: ['vacuum', 'dust']
- **visit_mother_and_have_dinner**: components: ['socialize_in_person', 'consume_meal']
- **wake_up**: components: ['wake_up']
- **wake_up_without_alarm**: components: ['wake_up']
- **wash_breakfast_dishes**: components: ['wash_dishes']
- **wash_face_and_change_shirt**: components: ['wash_face', 'change_clothes']
- **watch_documentary**: components: ['watch_media']
- **watch_evening_television**: components: ['watch_media']
- **watch_football_highlights**: components: ['watch_media']
- **watch_late_news**: components: ['watch_media']
- **watch_sunday_program**: components: ['watch_media']
- **watch_television**: components: ['watch_media']
- **weekly_meal_preparation**: components: ['prepare_food', 'portion_food', 'store_food']
- **work_shift**: components: ['work']

---

## 4. Catalogo delle Azioni Consentite

Ciascun nodo di tipo `action` nei modelli di processo deve riferirsi a una di queste azioni:

- **move_to**: parameters: [destination (string, ref: location, required)]
- **move_to_capability**: parameters: [targetRole (string, ref: capability, required)]
- **change_posture**: parameters: [posture (string, ref: none, required)]
- **open**: parameters: [target (string, ref: environment_entity, required)]
- **close**: parameters: [target (string, ref: environment_entity, required)]
- **take_item**: parameters: [itemRole (string, ref: capability, required)]
- **put_item**: parameters: [itemRole (string, ref: capability, required)]
- **activate**: parameters: [target (string, ref: environment_entity, required)]
- **deactivate**: parameters: [target (string, ref: environment_entity, required)]
- **wait**: parameters: [purpose (string, ref: none, required)]
- **inspect**: parameters: [targetRole (string, ref: capability, required)]
- **consume**: parameters: [itemRole (string, ref: capability, required)]
- **personal_care**: parameters: [procedure (string, ref: none, required)]
- **clean**: parameters: [targetRole (string, ref: capability, required)]
- **laundry_step**: parameters: [operation (string, ref: none, required)]
- **organize**: parameters: [targetRole (string, ref: capability, required)]
- **dress**: parameters: [purpose (string, ref: none, required)]
- **manage_medication**: parameters: [operation (string, ref: none, required)]
- **leave_home**: parameters: []
- **enter_home**: parameters: []
- **travel_to**: parameters: [destination (string, ref: location, required)]
- **shop**: parameters: [purpose (string, ref: none, required)]
- **communicate**: parameters: [channel (string, ref: none, required)]
- **perform_work**: parameters: [mode (string, ref: none, required)]
- **exercise**: parameters: [kind (string, ref: none, required)]
- **leisure**: parameters: [kind (string, ref: none, required)]
- **prepare_food**: parameters: [mealKind (string, ref: none, required)]

---

## 5. Catalogo delle Variabili di Stato Consentite

- `resident.age` (integer): Authoritative behavioral variable: age.
- `resident.household` (string): Authoritative behavioral variable: household composition.
- `resident.health_conditions` (array): Authoritative behavioral variable: health conditions.
- `resident.mobility_profile` (string): Authoritative behavioral variable: mobility profile.
- `resident.walking_speed` (number): Authoritative behavioral variable: walking speed.
- `resident.chronotype` (string): Authoritative behavioral variable: chronotype.
- `resident.preferred_breakfast_drink` (string): Authoritative behavioral variable: preferred breakfast drink.
- `resident.fatigue` (number): Authoritative behavioral variable: fatigue.
- `resident.hunger` (number): Authoritative behavioral variable: hunger.
- `resident.stress` (number): Authoritative behavioral variable: stress.
- `resident.social_need` (number): Authoritative behavioral variable: social need.
- `resident.food_inventory` (object): Authoritative behavioral variable: food inventory.
- `resident.medication_available_doses` (integer): Authoritative behavioral variable: medication available doses.
- `day.type` (string): Authoritative behavioral variable: day type.
- `day.weather` (string): Authoritative behavioral variable: weather.
- `day.public_holiday` (boolean): Authoritative behavioral variable: public holiday.
- `calendar.weekday` (integer): Authoritative behavioral variable: weekday.
- `calendar.season` (string): Authoritative behavioral variable: season.

---

## SPECIFICA DEL CASO (Genera il JSON per questa descrizione):

[PERSON_AND_CASE_DESCRIPTION]
