# Prompt semplificato corretto per bundle di simulazione (v1.2.3-simplified)

Genera un solo oggetto JSON valido e compilabile di tipo `SimulationAuthoringBundle` per il caso descritto in fondo.

Regole di risposta non negoziabili:

- restituisci esclusivamente il JSON, senza Markdown, commenti o testo esterno;
- il primo carattere deve essere `{` e l'ultimo `}`;
- non inventare campi diversi da quelli descritti;
- conserva l'intera durata richiesta: questo non e un prompt limitato a un giorno;
- prima di rispondere esegui mentalmente la checklist e il registro di stato della sezione 7.

## 1. Contratto minimo esatto

Usa nomi di campo camelCase. I campi indicati qui sono obbligatori. Ometti i campi opzionali che non servono; non usare `null`.

```typescript
interface SimulationAuthoringBundle {
  schemaVersion: "1.0.0";
  documentType: "simulation_authoring_bundle";
  scenario: {
    schemaVersion: "1.0.0";
    documentType: "life_scenario";
    scenarioId: string;
    title: string;
    language: string;
    timeZone: string;
    simulationWindow: { start: string; end: string };
    seed: number;
    provenance: Provenance;
    modelReferences: {
      activityCatalog: { referenceId: "activity_catalog"; version: "1.3.0" };
      homeModel: { referenceId: string; version: "1.0.0" };
    };
    residents: Array<{ residentId: string; displayName: string; profile?: Record<string, JsonValue> }>;
    locations: Array<{
      locationId: string;
      kind: "room" | "external" | "transit" | "composite";
      memberLocationIds?: string[];
      attributes?: Record<string, JsonValue>;
    }>;
    resources: Array<{
      resourceId: string;
      resourceType: string;
      locationId: string;
      capacity?: number;
      attributes?: Record<string, JsonValue>;
    }>;
    initialState: {
      at: string;
      residents: Array<{
        residentId: string;
        locationId: string;
        facts: Record<string, JsonValue>;
      }>;
      resourceFacts?: Record<string, Record<string, JsonValue>>;
      environmentFacts?: Record<string, JsonValue>;
    };
    days: DayPlan[];
  };
  personalProcessPackage: {
    schemaVersion: "1.0.0";
    documentType: "personal_process_package";
    packageId: string;
    packageVersion: "1.0.0";
    sourceScenarioId: string;
    sourceScenarioVersion: "1.0.0";
    language: string;
    provenance: Provenance;
    catalogs: {
      activityCatalog: { catalogId: "smart_home_activity_catalog"; version: "1.3.0" };
      variableCatalog: { catalogId: "smart_home_variable_catalog"; version: "1.0.0" };
      actionCatalog: { catalogId: "smart_home_action_catalog"; version: "1.1.0" };
    };
    processModels: ProcessModel[];
    bindings: ProcessBinding[];
  };
}

interface Provenance {
  authorType: "external_llm";
  generatorName: "smart-home-simulator-external-llm-authoring";
  generatorVersion: "1.2.3";
  promptTemplateVersion: "generate-simulation-inputs-1.2.3-simplified";
  modelName: string;
  generatedAt: string;
  humanReviewed: false;
}

interface DayPlan {
  date: string;
  context: { dayType: string; facts?: Record<string, JsonValue> };
  activities: Activity[];
}

interface Activity {
  activityId: string;
  actorId: string;
  intent: string;
  locationIds: string[];
  startWindow: { earliest: string; preferred: string; latest: string };
  duration: { minimumMinutes: number; preferredMinutes: number; maximumMinutes: number };
  requiredResources?: Array<{ resourceId: string; units?: number }>;
  priority?: number;
  mandatory?: boolean;
  allowBoundaryTruncation?: boolean;
}

interface ProcessModel {
  processModelId: string;
  processModelVersion: "1.0.0";
  residentId: string;
  title: string;
  description: string;
  implementedComponents: string[];
  nodes: ProcessNode[];
  edges: Array<{ sourceNodeId: string; targetNodeId: string }>;
}

interface ProcessNode {
  nodeId: string;
  kind: "start" | "end" | "action";
  actionType?: string;
  arguments?: Record<string, ValueExpression>;
  durationWeight?: number;
}

interface ProcessBinding {
  bindingId: string;
  residentId: string;
  intent: string;
  processModelId: string;
}

type ValueExpression =
  | { source: "literal"; value: JsonValue }
  | { source: "activity_location"; index: number }
  | { source: "activity_resource"; index: number }
  | { source: "activity_intent" }
  | { source: "actor" };
```

`JsonValue` significa stringa, numero, booleano, oggetto, array o null. Nei `resourceFacts` usa valori JSON normali, per esempio `{"fridge_01":{"open":false}}`: non usare oggetti `ValueExpression`.

## 2. Date, identita e riferimenti

- Tutti gli ID devono essere non vuoti, stabili e univoci nel proprio insieme.
- `sourceScenarioId` deve essere identico a `scenarioId`.
- Le due `language` devono coincidere.
- Usa una timezone IANA reale e timestamp ISO 8601 con offset coerente.
- La fine di `simulationWindow` e esclusiva. Per due giorni interi, per esempio 10 e 11 agosto, usa start `2026-08-10T00:00:00+02:00`, end `2026-08-12T00:00:00+02:00` e genera solo i DayPlan `2026-08-10` e `2026-08-11`.
- Imposta `initialState.at` esattamente uguale a `simulationWindow.start`.
- Ogni location usata deve essere dichiarata. Una location `composite` deve avere `memberLocationIds` non vuoto; le altre non devono averlo.
- Ogni `resource.locationId` e ogni `requiredResources[].resourceId` devono esistere.
- Usa esattamente i riferimenti catalogo mostrati nella sezione 1: `activity_catalog` nello scenario e `smart_home_*_catalog` nel package.
- Usa `[GENERATION_TIMESTAMP]` come valore esatto di `generatedAt` in entrambe le provenance.
- In `modelName` scrivi l'identificativo reale del modello in esecuzione; se non e disponibile usa `unknown-local-model`, senza inventarlo.

## 3. Piano giornaliero

- Crea un DayPlan per ogni data locale compresa nella finestra, esclusa la data dell'estremo `end` quando `end` e a mezzanotte.
- Ordina le attivita per `startWindow.preferred`. Per lo stesso residente non creare sovrapposizioni.
- Ogni attivita deve avere `earliest <= preferred <= latest` e `minimumMinutes <= preferredMinutes <= maximumMinutes`, con durate positive.
- Tutti gli orari e le durate devono stare nella finestra. Solo il sonno finale puo superare `end`, con `allowBoundaryTruncation: true`.
- Mantieni routine, pasti, sonno, salute, lavoro e uscite coerenti con il caso. Non inventare farmaci o condizioni sanitarie.
- Una routine stabile non significa timestamp copiati: varia in modo plausibile `preferred` e `preferredMinutes` fra giorni comparabili, normalmente di alcuni minuti e sempre dentro le finestre. Mantieni esatti soltanto impegni realmente fissi. Evita che sveglia, pasti, rientro e sonno abbiano lo stesso secondo per tutti i giorni.
- Usa fame, fatica, cronotipo, salute, impegni e conseguenze del giorno precedente per motivare le variazioni. Non aggiungere rumore casuale privo di causa e non dichiarare come gia avvenuto un risultato che deve essere deciso dal simulatore.
- Riusa un solo process model per ogni coppia distinta `(residentId, intent)` anche quando l'intent compare in molti giorni.

## 4. Intent ammessi e componenti esatti

Ogni attivita deve usare uno degli intent seguenti. Il process model collegato deve copiare esattamente, nello stesso ordine, l'array di componenti indicato.

```text
buy_fresh_food_and_household_supplies = shop, carry_purchases
buy_groceries = shop, carry_purchases
change_clothes = change_clothes
change_clothes_and_eat_snack = change_clothes, consume_snack
change_clothes_and_have_coffee = change_clothes, consume_drink
change_clothes_and_have_snack = change_clothes, consume_snack
check_calendar_and_household_supplies = check_calendar, inspect_supplies
clean_bathroom = clean_surface
clean_kitchen = clean_surface
collect_belongings_and_leave_home = collect_belongings, leave_home
collect_medication_refill = collect_medication
commute_home = travel, enter_home
commute_to_work = travel
complete_pending_dishwashing = wash_dishes
cook_chicken_and_vegetables = prepare_food
cook_dinner = prepare_food
dress_for_work = change_clothes
eat_afternoon_snack = consume_snack
eat_breakfast = consume_meal
eat_breakfast_and_listen_to_radio = consume_meal, listen_radio
eat_breakfast_and_read_news = consume_meal, read_news
eat_breakfast_with_radio_news = consume_meal, listen_radio
eat_dinner = consume_meal
eat_light_dinner = consume_meal
eat_lunch = consume_meal
evening_hygiene = personal_hygiene
evening_walk = walk
go_to_neighborhood_market = travel
hang_bed_linen = hang_laundry
hang_laundry = hang_laundry
indoor_light_exercise = exercise
iron_work_shirts = iron_laundry
leave_home = leave_home
long_sunday_walk = walk
morning_toilet_and_shower = use_toilet, shower
morning_toilet_and_wash = use_toilet, wash_face
phone_call = phone_call
portion_and_store_prepared_food = portion_food, store_food
post_walk_shower = shower
prepare_and_drink_hot_drink = prepare_drink, consume_drink
prepare_and_eat_breakfast = prepare_food, consume_meal
prepare_breakfast = prepare_food
prepare_coffee_and_drink_on_balcony = prepare_drink, consume_drink
prepare_friday_clothes_and_bag = organize_clothes, organize_bag
prepare_light_dinner = prepare_food
prepare_monday_clothes_bag_and_documents = organize_clothes, organize_bag, organize_documents
prepare_next_workday = organize_clothes, organize_bag
prepare_next_workday_clothes_and_bag = organize_clothes, organize_bag
prepare_quick_pasta_and_salad = prepare_food, prepare_salad
prepare_rice_and_vegetables = prepare_food
prepare_simple_lunch = prepare_food
prepare_sunday_lunch = prepare_food
prepare_to_visit_relative = change_clothes, collect_belongings
prepare_weekend_breakfast = prepare_food
put_groceries_away = store_purchases
read = read
read_and_rest = read, rest
read_in_bed = read_in_bed
reheat_leftover_dinner_and_prepare_salad = reheat_food, prepare_salad
rest = rest
rest_and_read = rest, read
rest_or_nap = rest, nap
return_home_and_store_purchases = travel, enter_home, store_purchases
short_evening_walk = walk
shower_and_get_ready_to_go_out = shower, change_clothes
sleep = sleep
social_drink_out = socialize_in_person, consume_drink
start_bed_linen_laundry = collect_laundry, load_laundry, start_laundry
start_laundry = collect_laundry, load_laundry, start_laundry
take_morning_medication = take_medication
take_recycling_out = carry_recycling, leave_home, discard_recycling
tidy_living_room_and_hallway = tidy_area
travel_home = travel, enter_home
travel_to_neighborhood_bar = travel
travel_to_pharmacy = travel
travel_to_relatives_home = travel
travel_to_supermarket = travel
use_toilet = use_toilet
vacuum_and_dust_apartment = vacuum, dust
visit_relative_and_have_dinner = socialize_in_person, consume_meal
wake_up = wake_up
wake_up_without_alarm = wake_up
wash_breakfast_dishes = wash_dishes
wash_face_and_change_shirt = wash_face, change_clothes
watch_documentary = watch_media
watch_evening_television = watch_media
watch_football_highlights = watch_media
watch_late_news = watch_media
watch_sunday_program = watch_media
watch_television = watch_media
weekly_meal_preparation = prepare_food, portion_food, store_food
work_from_home = work
work_shift = work
```


## 5. Componenti e sequenze obbligatorie di azioni

Per ogni componente, il percorso `start -> end` del modello deve contenere nell'ordine la sequenza indicata. Puoi inserire azioni aggiuntive per movimento o preparazione dello stato, ma non puoi eliminare, invertire o sostituire le azioni obbligatorie.

```text
carry_purchases: take_item
carry_recycling: take_item
change_clothes: take_item -> dress -> put_item
check_calendar: inspect
clean_surface: take_item -> clean -> put_item
collect_belongings: take_item
collect_laundry: laundry_step
collect_medication: manage_medication -> take_item
consume_drink: consume
consume_meal: change_posture -> consume -> change_posture
consume_snack: consume
discard_recycling: put_item
dust: take_item -> clean -> put_item
enter_home: enter_home
exercise: exercise
hang_laundry: laundry_step
inspect_supplies: open -> inspect -> close
iron_laundry: laundry_step
leave_home: leave_home
listen_radio: leisure
load_laundry: laundry_step
nap: change_posture -> wait
organize_bag: organize
organize_clothes: organize
organize_documents: organize
personal_hygiene: personal_care
phone_call: change_posture -> communicate -> change_posture
portion_food: organize
prepare_drink: take_item -> activate -> prepare_food -> deactivate
prepare_food: open -> take_item -> close -> activate -> prepare_food -> deactivate -> put_item
prepare_salad: take_item -> prepare_food -> put_item
read: change_posture -> leisure
read_in_bed: change_posture -> leisure
read_news: leisure
reheat_food: take_item -> activate -> prepare_food -> deactivate
rest: change_posture -> wait
shop: shop
shower: activate -> personal_care -> deactivate
sleep: change_posture -> wait
socialize_in_person: communicate
start_laundry: laundry_step
store_food: open -> put_item -> close
store_purchases: open -> put_item -> close
take_medication: take_item -> manage_medication -> put_item
tidy_area: organize
travel: travel_to
use_toilet: personal_care
vacuum: take_item -> activate -> clean -> deactivate -> put_item
wake_up: change_posture
walk: exercise
wash_dishes: activate -> clean -> deactivate
wash_face: activate -> personal_care -> deactivate
watch_media: change_posture -> activate -> leisure -> deactivate
work: change_posture -> perform_work
```


Attenzione: nella versione congelata `1.0.0`, il componente `travel` include davvero `leave_home -> travel_to`. Non ridurlo al solo `travel_to`.

Queste sequenze sono il **minimo** che il validatore impone, non la forma corretta. Il minimo non apre il contenitore da cui prende un oggetto: un modello che si limita a `take_item` valida senza errori ma non fa mai scattare il sensore di contatto, e produce un dataset in cui l'armadio non viene mai aperto. Usa sempre la forma della sezione 5.1 quando l'intent e' presente.

## 5.1 Modelli di riferimento provati

Per questi intent esiste un modello gia' verificato in simulazione. Riproducilo azione per azione, cambiando soltanto i valori che il caso impone. Se l'intent che ti serve non e' in questa lista, imita la forma del piu' simile: recupera un oggetto solo dopo aver aperto il contenitore che lo custodisce e richiudilo, e raggiungi con `move_to_capability` il ruolo su cui stai per agire.

```text
buy_groceries  [shop, carry_purchases]
  move_to_capability(retail_area) -> shop(<intent>) -> move_to_capability(purchases) -> take_item(purchases)

clean_kitchen  [clean_surface]
  move_to_capability(cleaning_product_storage) -> open(cleaning_product_storage) -> take_item(cleaning_tool) -> close(cleaning_product_storage) ->
  move_to(<activity location>) -> clean(kitchen_surfaces) -> move_to_capability(cleaning_product_storage) -> open(cleaning_product_storage) ->
  put_item(cleaning_tool) -> close(cleaning_product_storage)

eat_breakfast  [consume_meal]
  move_to_capability(food_storage) -> open(food_storage) -> take_item(prepared_meal) -> close(food_storage) ->
  move_to_capability(consumption_area) -> change_posture(sitting) -> consume(prepared_meal) -> change_posture(standing) ->
  move_to_capability(food_storage) -> open(food_storage) -> take_item(ingredients) -> close(food_storage) ->
  move_to_capability(washing_area) -> put_item(prepared_meal)

eat_dinner  [consume_meal]
  move_to_capability(food_storage) -> open(food_storage) -> take_item(prepared_meal) -> close(food_storage) ->
  move_to_capability(consumption_area) -> change_posture(sitting) -> consume(prepared_meal) -> change_posture(standing) ->
  move_to_capability(washing_area) -> put_item(prepared_meal)

eat_lunch  [consume_meal]
  move_to_capability(food_storage) -> open(food_storage) -> take_item(prepared_meal) -> close(food_storage) ->
  move_to_capability(consumption_area) -> change_posture(sitting) -> consume(prepared_meal) -> change_posture(standing) ->
  move_to_capability(washing_area) -> put_item(prepared_meal)

evening_hygiene  [personal_hygiene]
  move_to_capability(personal_care_fixture) -> personal_care(evening_hygiene)

evening_walk  [walk]
  move_to_capability(walking_area) -> exercise(walking)

hang_laundry  [hang_laundry]
  move_to_capability(drying_area) -> laundry_step(hang)

indoor_light_exercise  [exercise]
  move_to_capability(exercise_area) -> exercise(indoor_light_exercise)

morning_toilet_and_shower  [use_toilet, shower]
  move_to_capability(toilet) -> personal_care(use_toilet) -> move_to_capability(shower) -> activate(shower_water) ->
  personal_care(shower) -> deactivate(shower_water)

morning_toilet_and_wash  [use_toilet, wash_face]
  move_to_capability(toilet) -> personal_care(use_toilet) -> move_to_capability(sink) -> activate(sink_faucet) ->
  personal_care(wash_face) -> deactivate(sink_faucet)

phone_call  [phone_call]
  move_to_capability(communication_area) -> change_posture(sitting) -> communicate(phone) -> change_posture(standing)

prepare_and_drink_hot_drink  [prepare_drink, consume_drink]
  move_to(<activity location>) -> move_to_capability(coffee_and_breakfast_storage) -> open(coffee_and_breakfast_storage) -> take_item(ingredients) ->
  close(coffee_and_breakfast_storage) -> move_to_capability(coffee_equipment) -> activate(coffee_equipment) -> prepare_food(hot_drink, drink) ->
  deactivate(coffee_equipment) -> move_to_capability(consumption_area) -> change_posture(sitting) -> consume(drink) ->
  change_posture(standing) -> put_item(ingredients)

prepare_light_dinner  [prepare_food]
  move_to_capability(food_preparation_area) -> open(food_storage) -> take_item(ingredients) -> close(food_storage) ->
  activate(cooking_appliance) -> prepare_food(<intent>, prepared_meal) -> open(food_storage) -> take_item(ingredients) ->
  close(food_storage) -> prepare_food(<intent>, prepared_meal) -> deactivate(cooking_appliance) -> move_to_capability(washing_area) ->
  put_item(prepared_meal)

prepare_simple_lunch  [prepare_food]
  move_to_capability(food_preparation_area) -> open(food_storage) -> take_item(ingredients) -> close(food_storage) ->
  activate(cooking_appliance) -> prepare_food(<intent>, prepared_meal) -> open(food_storage) -> take_item(ingredients) ->
  close(food_storage) -> prepare_food(<intent>, prepared_meal) -> deactivate(cooking_appliance) -> move_to_capability(washing_area) ->
  put_item(prepared_meal)

put_groceries_away  [store_purchases]
  move_to_capability(household_storage) -> open(household_storage) -> put_item(purchases) -> close(household_storage)

read_and_rest  [read, rest]
  move_to(<activity location>) -> change_posture(sitting) -> wait(rest) -> move_to(<activity location>) ->
  change_posture(sitting) -> leisure(read)

rest_or_nap  [rest, nap]
  move_to(<activity location>) -> change_posture(sitting) -> wait(rest) -> change_posture(lying) ->
  wait(nap)

sleep  [sleep]
  move_to(<activity location>) -> change_posture(lying) -> wait(sleep)

start_laundry  [collect_laundry, load_laundry, start_laundry]
  move_to_capability(laundry_storage) -> open(laundry_storage) -> laundry_step(collect) -> close(laundry_storage) ->
  move_to_capability(washing_machine) -> open(laundry_equipment) -> laundry_step(load) -> close(laundry_equipment) ->
  laundry_step(start)

take_morning_medication  [take_medication]
  move_to_capability(medication_storage) -> open(medication_cabinet) -> take_item(medication_dose_container) -> close(medication_cabinet) ->
  move_to_capability(drinking_water_source) -> take_item(drinking_glass) -> manage_medication(take) -> consume(drinking_water) ->
  put_item(drinking_glass) -> move_to_capability(medication_storage) -> open(medication_cabinet) -> put_item(medication_dose_container) ->
  close(medication_cabinet)

tidy_living_room_and_hallway  [tidy_area]
  move_to_capability(tidying_area) -> organize(<intent>)

use_toilet  [use_toilet]
  move_to(<activity location>) -> move_to_capability(toilet) -> personal_care(use_toilet) -> move_to_capability(washing_area) ->
  personal_care(wash_hands)

wake_up  [wake_up]
  move_to(<activity location>) -> change_posture(standing)

watch_television  [watch_media]
  move_to_capability(television) -> change_posture(sitting) -> activate(television) -> leisure(<intent>) ->
  deactivate(television)

weekly_meal_preparation  [prepare_food, portion_food, store_food]
  move_to_capability(food_preparation_area) -> open(food_storage) -> take_item(ingredients) -> close(food_storage) ->
  activate(cooking_appliance) -> prepare_food(<intent>, prepared_meal) -> deactivate(cooking_appliance) -> put_item(prepared_meal) ->
  move_to_capability(food_preparation_area) -> organize(prepared_food_portions) -> move_to_capability(food_storage) -> open(food_storage) ->
  put_item(prepared_food_portions) -> close(food_storage)

work_from_home  [work]
  move_to(<activity location>) -> move_to_capability(table) -> change_posture(sitting) -> perform_work(focused_work) ->
  change_posture(standing)
```


## 6. Grafo e catalogo azioni

Ogni process model deve essere una singola catena lineare:

1. un nodo `start`;
2. come prima azione un movimento (`move_to`, `move_to_capability` oppure `travel_to`);
3. tutte le azioni richieste dai componenti, con eventuali azioni aggiuntive di stato;
4. un nodo `end`;
5. un arco tra ogni coppia consecutiva, senza nodi isolati;
6. `durationWeight: 1` su ogni nodo azione e mai sulle attivita del DayPlan.

Usa soltanto questi actionType e argomenti esatti. Ogni valore dell'argomento deve essere un `ValueExpression`, non una stringa diretta.

```text
activate(target)                    target = literal environment-entity role
change_posture(posture)             posture = standing | walking | sitting | lying
clean(targetRole)                   targetRole = literal capability role
close(target)                       target = literal environment-entity role
communicate(channel)                channel = phone | in_person
consume(itemRole)                   itemRole = literal capability role
deactivate(target)                  target = literal environment-entity role
dress(purpose)                      purpose = literal string
enter_home()
exercise(kind)                      kind = literal string
inspect(targetRole)                 targetRole = literal capability role
laundry_step(operation)             operation = collect | load | start | unload | hang | iron
leave_home()
leisure(kind)                       kind = literal string
manage_medication(operation)        operation = take | refill | store
move_to(destination)                destination = {"source":"activity_location","index":0}
move_to_capability(targetRole)      targetRole = literal capability role
open(target)                        target = literal environment-entity role
organize(targetRole)                targetRole = literal capability role
perform_work(mode)                  mode = literal string
personal_care(procedure)            procedure = literal string
prepare_food(mealKind, outputRole)  mealKind = literal string; outputRole = drink | prepared_food_portions | prepared_meal | prepared_salad
put_item(itemRole)                  itemRole = literal capability role
shop(purpose)                       purpose = literal string
take_item(itemRole)                 itemRole = literal capability role
travel_to(destination)              destination = {"source":"activity_location","index":0}
wait(purpose)                       purpose = literal string
```


Ruoli con arredo dedicato: la generazione della casa li risolve su un oggetto reale, quindi preferiscili sempre. `bed`, `chair`, `cleaning_product_storage`, `cleaning_products`, `clothes`, `clothing_storage`, `coffee_and_breakfast_storage`, `coffee_equipment`, `consumption_area`, `cooking_appliance`, `dining_area`, `dining_seat`, `drinking_water_source`, `entrance`, `food_preparation_area`, `food_storage`, `home_entrance`, `home_exit`, `household_storage`, `household_supplies`, `ingredients`, `laundry`, `laundry_collection`, `laundry_equipment`, `laundry_storage`, `media`, `medication`, `medication_cabinet`, `medication_storage`, `moka_coffee_maker`, `personal_care_fixture`, `prepared_food_portions`, `prepared_meal`, `radio`, `refrigerator`, `rest_area`, `seating`, `shower`, `shower_water`, `sink`, `sink_faucet`, `sleeping_area`, `sofa`, `storage_cabinet`, `stove`, `table`, `television`, `toilet`, `used_clothing`, `wardrobe`, `washbasin`, `washing_area`, `washing_machine`.

Ruoli di area o di oggetto trasportato usati dai modelli provati. Sono ammessi, ma non hanno un arredo dedicato: non inventarne altri fuori da questi due elenchi, perche' un ruolo sconosciuto esegue contro un oggetto inesistente. `cleaning_tool`, `communication_area`, `drink`, `drinking_glass`, `drinking_water`, `drying_area`, `exercise_area`, `kitchen_surfaces`, `medication_dose_container`, `purchases`, `retail_area`, `tidying_area`, `walking_area`.

Per parametri location usa `activity_location`. Per capability ed environment entity usa un literal role. Non usare `activity_resource` come scorciatoia per un parametro capability o environment entity.

Esempio di nodo valido:

```json
{"nodeId":"action_01","kind":"action","actionType":"move_to","arguments":{"destination":{"source":"activity_location","index":0}},"durationWeight":1}
```

## 7. Registro cronologico di stato: obbligatorio

Prima di emettere il JSON, costruisci privatamente un registro per ogni residente, ordinando tutte le attivita di tutti i giorni per `startWindow.preferred`. Non restituire il registro.

Stato iniziale:

- in `initialState.residents[].facts` scrivi sempre `"at_home": true` se il residente parte in casa, altrimenti `false`;
- tieni traccia almeno di `at_home`, `location`, `carrying.<role>`, `entity.<target>.open` ed `entity.<target>.active`.

Transizioni obbligatorie:

- `leave_home` richiede `at_home=true` e lo porta a `false`;
- `enter_home` richiede `at_home=false` e lo porta a `true`;
- `take_item(role)` porta `carrying.role=true`;
- `put_item(role)` richiede lo stesso identico role a `true` e lo porta a `false`;
- anche queste azioni assegnano da sole un `carrying`, quindi non farle precedere da un `take_item` dello stesso role:

```text
dress -> carrying.used_clothing=true
prepare_food -> carrying.{outputRole}=true
shop -> carrying.purchases=true
```

- `open(target)` deve precedere `close(target)` sullo stesso target;
- `activate(target)` deve precedere `deactivate(target)` sullo stesso target.

Regole di costruzione robuste:

- Se una sequenza obbligatoria contiene `take_item ... put_item`, usa lo stesso `itemRole` in entrambi. Non usare, per esempio, `ingredients` nel take e `prepared_meal` nel put.
- Se un componente inizia con `put_item` (`store_food`, `store_purchases`, `discard_recycling`) e il registro non garantisce gia il trasporto dello stesso role, inserisci un `take_item` dello stesso role prima della sequenza obbligatoria. Non serve se il trasporto arriva gia da un'azione dell'elenco sopra: dopo `prepare_food(outputRole: "prepared_meal")` il residente trasporta gia `prepared_meal`.
- Per acquisto e deposito usa sempre il role `purchases`: `shop` porta gia `carrying.purchases=true` e il successivo deposito esegue `put_item("purchases")`.
- Non lasciare una coppia `open/close` o `activate/deactivate` sbilanciata e non cambiare target fra le due azioni.
- Dopo ogni uscita pianifica un rientro prima di una nuova uscita. Non eseguire due `leave_home` consecutivi e non eseguire due `enter_home` consecutivi.

Caso speciale obbligatorio per gli intent di rientro `commute_home`, `travel_home`, `return_home_and_store_purchases`: il catalogo richiede comunque il `leave_home` del componente `travel`, ma il residente normalmente e gia fuori. Per mantenere valido lo stato, dopo il movimento iniziale inserisci questo ponte esplicito:

```text
move_to_capability(home_entrance) -> enter_home [ponte] -> leave_home [travel richiesto] -> travel_to(home) -> enter_home [componente richiesto]
```

Per `return_home_and_store_purchases` continua poi con `take_item(purchases)` se necessario, `open(household_storage) -> put_item(purchases) -> close(household_storage)`. Il primo `enter_home` e un adattamento tecnico richiesto dal catalogo congelato, non un nuovo componente.

## 8. Binding e algoritmo di costruzione

Esegui internamente questi passi nell'ordine:

1. normalizza la finestra temporale con `end` esclusivo e crea i DayPlan richiesti;
2. scegli solo intent presenti nella sezione 4;
3. raccogli tutte le coppie distinte `(actorId, intent)`;
4. crea esattamente un binding non-fallback per ciascuna coppia e un process model compatibile;
5. copia i componenti esatti dell'intent e riproduci il modello della sezione 5.1; solo se l'intent non e' elencato li', concatena le sequenze minime della sezione 5;
6. aggiungi il movimento iniziale e le sole azioni di preparazione stato necessarie;
7. costruisci la catena completa di nodi e archi;
8. simula cronologicamente il registro della sezione 7 e correggi ogni precondizione sicuramente falsa;
9. emetti solo l'oggetto JSON completo.

Ogni attivita deve risolvere a esattamente un binding con stessi `actorId/residentId` e `intent`. Ogni binding deve puntare a un process model esistente dello stesso residente. Non creare binding inutilizzati.

## 9. Checklist finale

Prima della risposta verifica tutto:

- un solo JSON puro, nessun campo sconosciuto;
- `scenario.language` e `personalProcessPackage.language` presenti e uguali;
- `personalProcessPackage.documentType` presente;
- riferimenti catalogo esatti della sezione 1;
- end temporale esclusivo e DayPlan senza giorno extra;
- ID e riferimenti esistenti;
- nessuna sovrapposizione per residente;
- `implementedComponents` esatti e sequenze obbligatorie complete, incluso `travel = leave_home -> travel_to`;
- ogni azione ha esattamente gli argomenti richiesti e `durationWeight`;
- ogni coppia `take/put`, `open/close`, `activate/deactivate` usa lo stesso role o target;
- ogni `take_item` da un contenitore e preceduto da `open` dello stesso contenitore e seguito da `close`;
- per ogni intent presente nella sezione 5.1 il modello riproduce quella sequenza;
- il registro cronologico non contiene mai `leave_home` quando `at_home=false`, `enter_home` quando `at_home=true`, o `put_item(role)` senza `carrying.role=true`;
- copertura binding del 100%;
- sonno, pasti, salute, luoghi e orari plausibili per il caso.

## Caso da simulare

[PERSON_AND_CASE_DESCRIPTION]
