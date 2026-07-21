# Prompt Semplificato per LLM Locali (v1.2.0-simplified)

Genera un singolo oggetto JSON valido e compilabile che rappresenti un bundle di simulazione (`SimulationAuthoringBundle`) per la descrizione fornita alla fine.
Restituisci **ESCLUSIVAMENTE** l'oggetto JSON, senza racchiuderlo in blocchi markdown (no ```json ... ```) e senza alcun testo prima o dopo.

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
  timeZone: string; // Timezone IANA valida (es. "Europe/Rome" o "UTC")
  simulationWindow: { start: string; end: string }; // ISO datetime con offset (es. "2026-10-30T00:00:00+01:00")
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
  days: DayPlan[]; // Esattamente un DayPlan per ogni giorno nella simulationWindow (es. dal giorno start al giorno end inclusi)
}

interface Provenance {
  authorType: "external_llm";
  generatorName: "smart-home-simulator-external-llm-authoring";
  generatorVersion: "1.2.0";
  promptTemplateVersion: "generate-simulation-inputs-1.2.0-simplified";
  humanReviewed: false;
  modelName: string; // Identificativo completo del modello (es. "qwen2.5-coder-7b-q4_k_m")
  generatedAt: string; // ISO datetime coerente con le date dello scenario
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
  memberLocationIds?: string[]; // Obbligatorio e non vuoto SOLO per kind "composite"
  attributes?: Record<string, any>;
}

interface Resource {
  resourceId: string;
  resourceType: string;
  locationId: string; // Deve corrispondere a una delle locationId dichiarate
  capacity?: number; // default 1
  attributes?: Record<string, any>;
}

interface InitialState {
  at: string; // ISO timestamp uguale all'inizio della simulationWindow
  residents: { residentId: string; locationId: string; facts?: Record<string, any> }[];
  resourceFacts?: Record<string, Record<string, any>>; // I fatti delle risorse devono essere oggetti ValueExpression literal! Es. {"open": {"source": "literal", "value": false}}
}

interface DayPlan {
  date: string; // formato YYYY-MM-DD
  context: { dayType: "weekday" | "weekend"; facts?: Record<string, any> };
  activities: Activity[];
}

interface Activity {
  activityId: string; // Univoco per lo scenario (es. "act_wake_up_day1")
  actorId: string; // Deve corrispondere a un residentId dichiarato
  intent: string; // Deve corrispondere a uno degli Intent nel catalogo attività (Sez. 4)
  locationIds: string[]; // Almeno 1 locationId dichiarato
  requiredResources?: { resourceId: string; units?: number }[];
  startWindow: DateTimeWindow; // OBBLIGATORIO nelle attività dello scenario
  duration: DurationRange;     // OBBLIGATORIO nelle attività dello scenario
  priority?: number; // 0-100 (default 50)
  mandatory?: boolean; // default true
  activation?: { mode: "always" | "conditional" | "fallback"; condition?: any; fallbackForActivityId?: string };
}

interface DateTimeWindow {
  earliest: string; // ISO timestamp con offset (es. "2026-10-30T07:00:00+01:00")
  preferred: string; // ISO timestamp con offset
  latest: string; // ISO timestamp con offset
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
  language: string; // es. "it"
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
  processModelId: string; // ID univoco per il modello (es. "pm_marco_wake_up")
  processModelVersion: "1.0.0";
  residentId: string; // Resident a cui si applica il modello
  title: string;
  description: string;
  implementedComponents: string[]; // Deve corrispondere ESATTAMENTE ai components dell'intent associato nel catalogo (Sez. 4)
  nodes: ProcessNode[];
  edges: ProcessEdge[];
}

interface ProcessNode {
  nodeId: string; // es. "start", "move_1", "act_1", "end"
  kind: "start" | "end" | "action" | "choice" | "loop";
  actionType?: string; // Solo se kind == "action". DEVE essere un'azione primitiva del catalogo azioni (Sez. 6), MAI un intent o un componente!
  arguments?: Record<string, ValueExpression>; // Solo se kind == "action"
  durationWeight?: number; // OBBLIGATORIO se kind == "action" (usa durationWeight: 1). MAI nelle attività dello scenario!
  maxIterations?: number; // Solo se kind == "loop"
}

interface ProcessEdge {
  sourceNodeId: string;
  targetNodeId: string;
  condition?: any;
  isDefault?: boolean;
}

interface ProcessBinding {
  bindingId: string; // ID univoco per il binding (es. "bind_marco_wake_up")
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

## 2. DISTINZIONE FONDAMENTALE: INTENT vs COMPONENT vs ACTION TYPE

Non confondere mai i tre livelli dell'architettura di simulazione:

1. **`intent` (Attività)**: Identificatore dell'attività ad alto livello nello scenario (es. `wake_up_without_alarm`, `eat_breakfast`, `prepare_and_eat_breakfast`).
2. **`implementedComponents` (Componenti Semantici)**: Sequenza ordinata di componenti definita dal catalogo per quell'intent.
   - Ad esempio, per l'intent `prepare_and_eat_breakfast`, i componenti sono `["prepare_food", "consume_meal"]`.
   - Il campo `implementedComponents` del `ProcessModel` deve contenere ESATTAMENTE questa lista nell'ordine esatto!
3. **`actionType` (Azioni Primitive)**: Azioni fisiche o logiche atomiche eseguite nel simulatore (Sez. 6).
   - **IMPORTANTE**: Nomi di intent o componenti come `wake_up`, `eat_breakfast`, `shower`, `work_shift`, `sleep`, `morning_toilet_and_shower` **NON SONO ACTION TYPE**!
   - Ogni componente viene espanso in una sequenza ordinata di azioni primitive (Sez. 5).
     Ad esempio: il componente `wake_up` richiede l'azione primitiva `change_posture`. Il componente `shower` richiede `activate` -> `personal_care` -> `deactivate`.

---

## 3. STRUTTURA TASSATIVA DEL GRAFO E MOVIMENTO OBBLIGATORIO

Ogni `ProcessModel` in `processModels` deve essere un grafo valido e completo che rispetta le seguenti regole tassative:

1. **Nodi Obbligatori**:
   - Esattamente **un nodo `start`**: `{"nodeId": "start", "kind": "start"}`
   - Almeno **un nodo `end`**: `{"nodeId": "end", "kind": "end"}`
2. **Movimento Obbligatorio**:
   - Ogni `ProcessModel` DEVE contenere almeno un'azione esplicita di movimento fra `move_to`, `move_to_capability` e `travel_to` come prima azione dopo `start`.
   - Anche per attività stazionarie (sveglia, sonno, lettura, tv), la prima azione deve posizionare il residente tramite un movimento (es. `move_to` con `destination: {"source": "activity_location", "index": 0}`).
3. **Collegamento del Grafo (Niente nodi morti)**:
   - Ogni nodo nell'array `nodes` deve appartenere a un percorso orientato da `start` a `end`.
   - Per una sequenza lineare di nodi `[start, move_node, act_1, act_2, ..., end]`, gli archi in `edges` devono formare la catena continua:
     - `start` -> `move_node`
     - `move_node` -> `act_1`
     - `act_1` -> `act_2` ...
     - `act_N` -> `end`
4. **Parametro `durationWeight`**:
   - Ogni nodo con `"kind": "action"` DEVE avere `"durationWeight": 1`.

### Esempio di Scheletro Canonico per ProcessModel:
Per un intent come `wake_up_without_alarm` (che ha `implementedComponents: ["wake_up"]`, e il componente `wake_up` richiede `change_posture`):

```json
{
  "processModelId": "pm_marco_wake_up",
  "processModelVersion": "1.0.0",
  "residentId": "marco_rossi",
  "title": "Wake up process for Marco",
  "description": "Marco wakes up and gets out of bed",
  "implementedComponents": ["wake_up"],
  "nodes": [
    {
      "nodeId": "start",
      "kind": "start"
    },
    {
      "nodeId": "move_to_bed",
      "kind": "action",
      "actionType": "move_to",
      "arguments": {
        "destination": { "source": "activity_location", "index": 0 }
      },
      "durationWeight": 1
    },
    {
      "nodeId": "act_change_posture",
      "kind": "action",
      "actionType": "change_posture",
      "arguments": {
        "posture": { "source": "literal", "value": "standing" }
      },
      "durationWeight": 1
    },
    {
      "nodeId": "end",
      "kind": "end"
    }
  ],
  "edges": [
    { "sourceNodeId": "start", "targetNodeId": "move_to_bed" },
    { "sourceNodeId": "move_to_bed", "targetNodeId": "act_change_posture" },
    { "sourceNodeId": "act_change_posture", "targetNodeId": "end" }
  ]
}
```

---

## 4. Catalogo degli Intent e relativi Componenti

Ogni attività definita nello scenario deve usare uno dei seguenti `intent`. Il `ProcessModel` ad esso associato tramite i `bindings` deve dichiarare `implementedComponents` esattamente uguale all'array `components` specificato qui sotto:

- **aperitivo_with_paolo**: components: ["socialize_in_person", "consume_drink"]
- **buy_fresh_food_and_household_supplies**: components: ["shop", "carry_purchases"]
- **buy_groceries**: components: ["shop", "carry_purchases"]
- **call_friend_paolo**: components: ["phone_call"]
- **call_mother**: components: ["phone_call"]
- **call_sister_lucia**: components: ["phone_call"]
- **change_clothes**: components: ["change_clothes"]
- **change_clothes_and_eat_snack**: components: ["change_clothes", "consume_snack"]
- **change_clothes_and_have_coffee**: components: ["change_clothes", "consume_drink"]
- **change_clothes_and_have_snack**: components: ["change_clothes", "consume_snack"]
- **check_calendar_and_household_supplies**: components: ["check_calendar", "inspect_supplies"]
- **clean_bathroom**: components: ["clean_surface"]
- **clean_kitchen**: components: ["clean_surface"]
- **collect_belongings_and_leave_home**: components: ["collect_belongings", "leave_home"]
- **collect_medication_refill**: components: ["collect_medication"]
- **commute_home**: components: ["travel", "enter_home"]
- **commute_to_work**: components: ["travel"]
- **complete_pending_dishwashing**: components: ["wash_dishes"]
- **cook_chicken_and_vegetables**: components: ["prepare_food"]
- **cook_dinner**: components: ["prepare_food"]
- **dress_for_work**: components: ["change_clothes"]
- **eat_afternoon_snack**: components: ["consume_snack"]
- **eat_breakfast**: components: ["consume_meal"]
- **eat_breakfast_and_listen_to_radio**: components: ["consume_meal", "listen_radio"]
- **eat_breakfast_and_read_news**: components: ["consume_meal", "read_news"]
- **eat_breakfast_with_radio_news**: components: ["consume_meal", "listen_radio"]
- **eat_dinner**: components: ["consume_meal"]
- **eat_light_dinner**: components: ["consume_meal"]
- **eat_lunch**: components: ["consume_meal"]
- **evening_hygiene**: components: ["personal_hygiene"]
- **evening_walk**: components: ["walk"]
- **go_to_neighborhood_market**: components: ["travel"]
- **hang_bed_linen**: components: ["hang_laundry"]
- **hang_laundry**: components: ["hang_laundry"]
- **indoor_light_exercise**: components: ["exercise"]
- **iron_work_shirts**: components: ["iron_laundry"]
- **leave_home**: components: ["leave_home"]
- **long_sunday_walk**: components: ["walk"]
- **morning_toilet_and_shower**: components: ["use_toilet", "shower"]
- **morning_toilet_and_wash**: components: ["use_toilet", "wash_face"]
- **portion_and_store_prepared_food**: components: ["portion_food", "store_food"]
- **post_walk_shower**: components: ["shower"]
- **prepare_and_eat_breakfast**: components: ["prepare_food", "consume_meal"]
- **prepare_breakfast**: components: ["prepare_food"]
- **prepare_coffee_and_drink_on_balcony**: components: ["prepare_drink", "consume_drink"]
- **prepare_friday_clothes_and_bag**: components: ["organize_clothes", "organize_bag"]
- **prepare_light_dinner**: components: ["prepare_food"]
- **prepare_monday_clothes_bag_and_documents**: components: ["organize_clothes", "organize_bag", "organize_documents"]
- **prepare_next_workday**: components: ["organize_clothes", "organize_bag"]
- **prepare_next_workday_clothes_and_bag**: components: ["organize_clothes", "organize_bag"]
- **prepare_quick_pasta_and_salad**: components: ["prepare_food", "prepare_salad"]
- **prepare_rice_and_vegetables**: components: ["prepare_food"]
- **prepare_simple_lunch**: components: ["prepare_food"]
- **prepare_sunday_lunch**: components: ["prepare_food"]
- **prepare_to_visit_mother**: components: ["change_clothes", "collect_belongings"]
- **prepare_weekend_breakfast**: components: ["prepare_food"]
- **put_groceries_away**: components: ["store_purchases"]
- **read**: components: ["read"]
- **read_and_rest**: components: ["read", "rest"]
- **read_in_bed**: components: ["read_in_bed"]
- **reheat_leftover_dinner_and_prepare_salad**: components: ["reheat_food", "prepare_salad"]
- **rest**: components: ["rest"]
- **rest_and_read**: components: ["rest", "read"]
- **rest_or_nap**: components: ["rest", "nap"]
- **return_home_and_store_purchases**: components: ["travel", "enter_home", "store_purchases"]
- **short_evening_walk**: components: ["walk"]
- **shower_and_get_ready_to_go_out**: components: ["shower", "change_clothes"]
- **sleep**: components: ["sleep"]
- **start_bed_linen_laundry**: components: ["collect_laundry", "load_laundry", "start_laundry"]
- **start_laundry**: components: ["collect_laundry", "load_laundry", "start_laundry"]
- **take_morning_medication**: components: ["take_medication"]
- **take_recycling_out**: components: ["carry_recycling", "leave_home", "discard_recycling"]
- **tidy_living_room_and_hallway**: components: ["tidy_area"]
- **travel_home**: components: ["travel", "enter_home"]
- **travel_to_mothers_home**: components: ["travel"]
- **travel_to_neighborhood_bar**: components: ["travel"]
- **travel_to_pharmacy**: components: ["travel"]
- **travel_to_supermarket**: components: ["travel"]
- **vacuum_and_dust_apartment**: components: ["vacuum", "dust"]
- **visit_mother_and_have_dinner**: components: ["socialize_in_person", "consume_meal"]
- **wake_up**: components: ["wake_up"]
- **wake_up_without_alarm**: components: ["wake_up"]
- **wash_breakfast_dishes**: components: ["wash_dishes"]
- **wash_face_and_change_shirt**: components: ["wash_face", "change_clothes"]
- **watch_documentary**: components: ["watch_media"]
- **watch_evening_television**: components: ["watch_media"]
- **watch_football_highlights**: components: ["watch_media"]
- **watch_late_news**: components: ["watch_media"]
- **watch_sunday_program**: components: ["watch_media"]
- **watch_television**: components: ["watch_media"]
- **weekly_meal_preparation**: components: ["prepare_food", "portion_food", "store_food"]
- **work_shift**: components: ["work"]

---

## 5. Mapping dei Componenti nelle Sequenze di Azioni Primitive (`requiredActionTypes`)

Quando componi i nodi di un `ProcessModel`, per ciascun componente in `implementedComponents` devi generare la sequenza di nodi azione corrispondente ai seguenti `requiredActionTypes`:

- **carry_purchases**: `take_item`
- **carry_recycling**: `take_item`
- **change_clothes**: `take_item` -> `dress` -> `put_item`
- **check_calendar**: `inspect`
- **clean_surface**: `take_item` -> `clean` -> `put_item`
- **collect_belongings**: `take_item`
- **collect_laundry**: `laundry_step`
- **collect_medication**: `manage_medication` -> `take_item`
- **consume_drink**: `consume`
- **consume_meal**: `change_posture` -> `consume` -> `change_posture`
- **consume_snack**: `consume`
- **discard_recycling**: `put_item`
- **dust**: `take_item` -> `clean` -> `put_item`
- **enter_home**: `enter_home`
- **exercise**: `exercise`
- **hang_laundry**: `laundry_step`
- **inspect_supplies**: `open` -> `inspect` -> `close`
- **iron_laundry**: `laundry_step`
- **leave_home**: `leave_home`
- **listen_radio**: `leisure`
- **load_laundry**: `laundry_step`
- **nap**: `change_posture` -> `wait`
- **organize_bag**: `organize`
- **organize_clothes**: `organize`
- **organize_documents**: `organize`
- **personal_hygiene**: `personal_care`
- **phone_call**: `change_posture` -> `communicate` -> `change_posture`
- **portion_food**: `organize`
- **prepare_drink**: `take_item` -> `activate` -> `prepare_food` -> `deactivate`
- **prepare_food**: `open` -> `take_item` -> `close` -> `activate` -> `prepare_food` -> `deactivate` -> `put_item`
- **prepare_salad**: `take_item` -> `prepare_food` -> `put_item`
- **read**: `change_posture` -> `leisure`
- **read_in_bed**: `change_posture` -> `leisure`
- **read_news**: `leisure`
- **reheat_food**: `take_item` -> `activate` -> `prepare_food` -> `deactivate`
- **rest**: `change_posture` -> `wait`
- **shop**: `shop`
- **shower**: `activate` -> `personal_care` -> `deactivate`
- **sleep**: `change_posture` -> `wait`
- **socialize_in_person**: `communicate`
- **start_laundry**: `laundry_step`
- **store_food**: `open` -> `put_item` -> `close`
- **store_purchases**: `open` -> `put_item` -> `close`
- **take_medication**: `take_item` -> `manage_medication` -> `put_item`
- **tidy_area**: `organize`
- **travel**: `travel_to`
- **use_toilet**: `personal_care`
- **vacuum**: `take_item` -> `activate` -> `clean` -> `deactivate` -> `put_item`
- **wake_up**: `change_posture`
- **walk**: `exercise`
- **wash_dishes**: `activate` -> `clean` -> `deactivate`
- **wash_face**: `activate` -> `personal_care` -> `deactivate`
- **watch_media**: `change_posture` -> `activate` -> `leisure` -> `deactivate`
- **work**: `change_posture` -> `perform_work`

---

## 6. Catalogo delle Azioni Primitive e dei relativi Argomenti (`ValueExpression`)

Tutti i nodi azione (`kind: "action"`) DEVONO usare uno dei seguenti `actionType` e definire argomenti formattati come oggetti `ValueExpression`:

- **move_to**: `arguments: {"destination": {"source": "activity_location", "index": 0}}`
- **move_to_capability**: `arguments: {"targetRole": {"source": "literal", "value": "home_entrance"}}`
- **travel_to**: `arguments: {"destination": {"source": "activity_location", "index": 0}}`
- **leave_home**: `arguments: {}`
- **enter_home**: `arguments: {}`
- **change_posture**: `arguments: {"posture": {"source": "literal", "value": "standing" | "sitting" | "lying" | "walking"}}`
- **open**: `arguments: {"target": {"source": "literal", "value": "refrigerator"}}` (usa un resourceId dichiarato)
- **close**: `arguments: {"target": {"source": "literal", "value": "refrigerator"}}` (usa lo stesso resourceId di open)
- **activate**: `arguments: {"target": {"source": "literal", "value": "television"}}` (usa un resourceId dichiarato)
- **deactivate**: `arguments: {"target": {"source": "literal", "value": "television"}}` (usa lo stesso resourceId di activate)
- **take_item**: `arguments: {"itemRole": {"source": "literal", "value": "food_storage" | "clothing_storage" | "medication_storage" | "utensils"}}`
- **put_item**: `arguments: {"itemRole": {"source": "literal", "value": "food_storage" | "clothing_storage" | "medication_storage" | "utensils"}}` *(NOTA BENE: `itemRole` in `put_item` deve essere ESATTAMENTE lo stesso valore usato in `take_item` nello stesso modello di processo!)*
- **inspect**: `arguments: {"targetRole": {"source": "literal", "value": "calendar" | "supplies"}}`
- **consume**: `arguments: {"itemRole": {"source": "literal", "value": "meal" | "drink" | "snack"}}`
- **personal_care**: `arguments: {"procedure": {"source": "literal", "value": "hygiene" | "shower" | "toilet"}}`
- **clean**: `arguments: {"targetRole": {"source": "literal", "value": "countertop" | "floor" | "dishes"}}`
- **laundry_step**: `arguments: {"operation": {"source": "literal", "value": "wash" | "dry" | "fold" | "iron"}}`
- **organize**: `arguments: {"targetRole": {"source": "literal", "value": "documents" | "clothes" | "bag"}}`
- **dress**: `arguments: {"purpose": {"source": "literal", "value": "daily_clothing" | "work_wear"}}`
- **manage_medication**: `arguments: {"operation": {"source": "literal", "value": "take_dose" | "refill"}}`
- **wait**: `arguments: {"purpose": {"source": "literal", "value": "resting" | "sleeping" | "napping"}}`
- **shop**: `arguments: {"purpose": {"source": "literal", "value": "groceries" | "supplies"}}`
- **communicate**: `arguments: {"channel": {"source": "literal", "value": "phone" | "in_person"}}`
- **perform_work**: `arguments: {"mode": {"source": "literal", "value": "desk_work" | "remote_work"}}`
- **exercise**: `arguments: {"kind": {"source": "literal", "value": "light_stretching" | "walking"}}`
- **leisure**: `arguments: {"kind": {"source": "literal", "value": "reading" | "watching_tv" | "radio"}}`
- **prepare_food**: `arguments: {"mealKind": {"source": "literal", "value": "breakfast" | "lunch" | "dinner"}}`

---

## 7. REGOLE DEI BINDINGS (COPERTURA OBBLIGATORIA AL 100%)

1. Per **OGNI** attività inclusa in qualsiasi `DayPlan` dello scenario (`days[].activities`), la combinazione `(actorId, intent)` deve avere **ALMENO UN** corrispondente `ProcessBinding` nell'array `personalProcessPackage.bindings`.
2. Se nello scenario compaiono 10 intent distinti (es. `wake_up_without_alarm`, `eat_breakfast`, `work_shift`, `sleep`, ...), ci devono essere ALMENO 10 `bindings` distinti (e 10 `processModels` distinti) in `personalProcessPackage` che li coprono tutti!
3. Ogni `ProcessBinding` deve avere:
   - `bindingId`: ID univoco (es. `bind_marco_wake_up`)
   - `residentId`: l'ID del residente (es. `marco_rossi`)
   - `intent`: l'intent esatto dell'attività (es. `wake_up_without_alarm`)
   - `processModelId`: l'ID del `ProcessModel` corrispondente (es. `pm_marco_wake_up`)

---

## 8. CHECKLIST DI AUTO-CORREZIONE PRIMA DI RESTITUIRE IL JSON

Verifica i seguenti punti prima di emettere l'oggetto JSON finale:

- [ ] **Formato**: L'output è UN SOLO oggetto JSON senza markdown (nessun ```json).
- [ ] **Date e Window**: `simulationWindow` copre tutti i giorni dei `DayPlan`. Tutti i timestamp usano lo stesso formato ISO con offset timezone (es. `+01:00`).
- [ ] **Attività dello Scenario**:
  - Ogni attività in `days[].activities` specifica `startWindow` (`earliest`, `preferred`, `latest`) e `duration` (`minimumMinutes`, `preferredMinutes`, `maximumMinutes`).
  - NESSUNA attività nello scenario contiene `durationWeight`.
- [ ] **Process Models e Grafo**:
  - `implementedComponents` di ogni `ProcessModel` coincide ESATTAMENTE con l'array `components` dell'intent nel catalogo.
  - Ogni `ProcessModel` ha esattamente 1 nodo `"kind": "start"` e 1 nodo `"kind": "end"`.
  - Ogni `ProcessModel` contiene una prima azione di movimento (`move_to`, `move_to_capability` o `travel_to`).
  - Ogni nodo con `"kind": "action"` ha `"durationWeight": 1`.
  - Gli archi in `edges` collegano `start` -> `move_node` -> `action_1` -> ... -> `end` senza nodi isolati o morti.
  - Nessun `actionType` usa nomi astratti di intent/componenti (come `wake_up`, `shower`, `eat_dinner`): si usano SOLO le azioni primitive della Sez. 6!
- [ ] **Copertura Bindings**:
  - Ogni intent usato in `days[].activities` ha una voce corrispondente in `bindings` e un `processModel` dedicato.

---

## SPECIFICA DEL CASO (Genera il JSON per questa descrizione):

[PERSON_AND_CASE_DESCRIPTION]
