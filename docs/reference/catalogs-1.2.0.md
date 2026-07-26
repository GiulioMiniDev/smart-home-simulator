# Cataloghi: intenti, componenti, azioni e modelli di processo

Elenco leggibile dei vocabolari usati dal simulatore. **Documento derivato**: la fonte
autorevole restano i JSON in `src/smart_home_sim/catalogs/`. Se i due divergono, vale il JSON.

| Fonte | Contenuto |
|---|---|
| `activity-catalog-1.2.0.json` | 90 intenti, 54 componenti |
| `action-catalog-1.1.0.json` | 27 azioni atomiche |
| `variable-catalog-1.0.0.json` | 18 variabili |
| `reference-process-models-1.2.0.json` | 24 modelli di processo |
| `hybrid_planning/intents.py` | alfabeto ridotto di 24 intenti |

> **Versione 1.2.0.** Il catalogo `1.1.0` ereditava il vocabolario dal caso Mario Rossi e sette
> intenti nominavano persone private. Poiché l'id di un intento **è** l'etichetta di ground truth
> pubblicata nel dataset, una persona generata senza sorelle doveva riusare `call_sister_lucia`
> per esprimere "telefona a un familiare". La `1.2.0` rende il vocabolario neutro: le tre
> telefonate — già identiche per componenti e variabili — collassano in `phone_call`, gli altri
> quattro sono rinominati. Chi c'è dall'altra parte è dato dello scenario (`externalPeople` e
> `participantIds`), non un'etichetta. Le versioni `1.0.0` e `1.1.0` restano intatte, quindi ogni
> artefatto già prodotto continua a validare e a riprodursi identico.

| 1.1.0 | 1.2.0 |
|---|---|
| `call_mother`, `call_sister_lucia`, `call_friend_paolo` | `phone_call` |
| `aperitivo_with_paolo` | `social_drink_out` |
| `prepare_to_visit_mother` | `prepare_to_visit_relative` |
| `travel_to_mothers_home` | `travel_to_relatives_home` |
| `visit_mother_and_have_dinner` | `visit_relative_and_have_dinner` |

---

## 1. Alfabeto ridotto — 24 intenti

Usato dalla **pipeline di generazione locale**. È un sottoinsieme stretto del catalogo completo:
sono esattamente gli intenti per cui esiste un modello di processo di riferimento già provato
simulabile. Ogni intento porta una stanza predefinita, scelta per dare firme sensoriali distinte.

| Intento | Etichetta | Categoria | Stanza | Componenti | Modello (nodi/archi) |
|---|---|---|---|---|---|
| `wake_up` | Wake up | sleep_wake | bedroom | `wake_up` | 4 / 3 |
| `morning_toilet_and_wash` | Morning wash | hygiene | bathroom | `use_toilet`, `wash_face` | 8 / 7 |
| `morning_toilet_and_shower` | Morning shower | hygiene | bathroom | `use_toilet`, `shower` | 8 / 7 |
| `take_morning_medication` | Take medication | medication | kitchen | `take_medication` | 15 / 14 |
| `eat_breakfast` | Eat breakfast | meal | kitchen | `consume_meal` | 16 / 15 |
| `eat_lunch` | Eat lunch | meal | kitchen | `consume_meal` | 12 / 11 |
| `eat_dinner` | Eat dinner | meal | kitchen | `consume_meal` | 12 / 11 |
| `prepare_simple_lunch` | Prepare lunch | cooking | kitchen | `prepare_food` | 15 / 14 |
| `prepare_light_dinner` | Prepare dinner | cooking | kitchen | `prepare_food` | 15 / 14 |
| `weekly_meal_preparation` | Batch cook | cooking | kitchen | `prepare_food`, `portion_food`, `store_food` | 16 / 15 |
| `clean_kitchen` | Clean the kitchen | chores | kitchen | `clean_surface` | 12 / 11 |
| `tidy_living_room_and_hallway` | Tidy the living room | chores | living_room | `tidy_area` | 4 / 3 |
| `start_laundry` | Start laundry | laundry | bathroom | `collect_laundry`, `load_laundry`, `start_laundry` | 11 / 10 |
| `hang_laundry` | Hang laundry | laundry | balcony | `hang_laundry` | 4 / 3 |
| `indoor_light_exercise` | Indoor exercise | exercise | living_room | `exercise` | 4 / 3 |
| `evening_walk` | Walk outdoors | outdoor | outdoors | `walk` | 4 / 3 |
| `buy_groceries` | Go shopping | errand | outdoors | `shop`, `carry_purchases` | 6 / 5 |
| `put_groceries_away` | Put groceries away | chores | kitchen | `store_purchases` | 6 / 5 |
| `watch_television` | Watch television | leisure | living_room | `watch_media` | 7 / 6 |
| `read_and_rest` | Read and rest | leisure | living_room | `read`, `rest` | 8 / 7 |
| `rest_or_nap` | Nap | leisure | bedroom | `rest`, `nap` | 8 / 8 |
| `phone_call` | Phone a relative or friend | social | living_room | `phone_call` | 6 / 5 |
| `evening_hygiene` | Evening hygiene | hygiene | bathroom | `personal_hygiene` | 4 / 3 |
| `sleep` | Sleep | sleep_wake | bedroom | `sleep` | 5 / 4 |

---

## 2. Catalogo completo — 90 intenti

Usato dal **percorso con LLM esterno** e dai casi scritti a mano. Gli intenti dell'alfabeto
ridotto sono marcati con ★.

### communication (1)

| | Intento | Componenti |
|---|---|---|
| ★ | `phone_call` | `phone_call` |

### dressing (10)

| | Intento | Componenti |
|---|---|---|
|  | `change_clothes` | `change_clothes` |
|  | `change_clothes_and_eat_snack` | `change_clothes`, `consume_snack` |
|  | `change_clothes_and_have_coffee` | `change_clothes`, `consume_drink` |
|  | `change_clothes_and_have_snack` | `change_clothes`, `consume_snack` |
|  | `dress_for_work` | `change_clothes` |
|  | `prepare_friday_clothes_and_bag` | `organize_clothes`, `organize_bag` |
|  | `prepare_monday_clothes_bag_and_documents` | `organize_clothes`, `organize_bag`, `organize_documents` |
|  | `prepare_next_workday` | `organize_clothes`, `organize_bag` |
|  | `prepare_next_workday_clothes_and_bag` | `organize_clothes`, `organize_bag` |
|  | `prepare_to_visit_relative` | `change_clothes`, `collect_belongings` |

### eating (8)

| | Intento | Componenti |
|---|---|---|
|  | `eat_afternoon_snack` | `consume_snack` |
| ★ | `eat_breakfast` | `consume_meal` |
|  | `eat_breakfast_and_listen_to_radio` | `consume_meal`, `listen_radio` |
|  | `eat_breakfast_and_read_news` | `consume_meal`, `read_news` |
|  | `eat_breakfast_with_radio_news` | `consume_meal`, `listen_radio` |
| ★ | `eat_dinner` | `consume_meal` |
|  | `eat_light_dinner` | `consume_meal` |
| ★ | `eat_lunch` | `consume_meal` |

### errand (3)

| | Intento | Componenti |
|---|---|---|
|  | `buy_fresh_food_and_household_supplies` | `shop`, `carry_purchases` |
| ★ | `buy_groceries` | `shop`, `carry_purchases` |
| ★ | `put_groceries_away` | `store_purchases` |

### exercise (4)

| | Intento | Componenti |
|---|---|---|
| ★ | `evening_walk` | `walk` |
| ★ | `indoor_light_exercise` | `exercise` |
|  | `long_sunday_walk` | `walk` |
|  | `short_evening_walk` | `walk` |

### housekeeping (6)

| | Intento | Componenti |
|---|---|---|
|  | `clean_bathroom` | `clean_surface` |
| ★ | `clean_kitchen` | `clean_surface` |
|  | `complete_pending_dishwashing` | `wash_dishes` |
| ★ | `tidy_living_room_and_hallway` | `tidy_area` |
|  | `vacuum_and_dust_apartment` | `vacuum`, `dust` |
|  | `wash_breakfast_dishes` | `wash_dishes` |

### hygiene (6)

| | Intento | Componenti |
|---|---|---|
| ★ | `evening_hygiene` | `personal_hygiene` |
| ★ | `morning_toilet_and_shower` | `use_toilet`, `shower` |
| ★ | `morning_toilet_and_wash` | `use_toilet`, `wash_face` |
|  | `post_walk_shower` | `shower` |
|  | `shower_and_get_ready_to_go_out` | `shower`, `change_clothes` |
|  | `wash_face_and_change_shirt` | `wash_face`, `change_clothes` |

### laundry (5)

| | Intento | Componenti |
|---|---|---|
|  | `hang_bed_linen` | `hang_laundry` |
| ★ | `hang_laundry` | `hang_laundry` |
|  | `iron_work_shirts` | `iron_laundry` |
|  | `start_bed_linen_laundry` | `collect_laundry`, `load_laundry`, `start_laundry` |
| ★ | `start_laundry` | `collect_laundry`, `load_laundry`, `start_laundry` |

### leisure (12)

| | Intento | Componenti |
|---|---|---|
|  | `check_calendar_and_household_supplies` | `check_calendar`, `inspect_supplies` |
|  | `read` | `read` |
| ★ | `read_and_rest` | `read`, `rest` |
|  | `rest` | `rest` |
|  | `rest_and_read` | `rest`, `read` |
| ★ | `rest_or_nap` | `rest`, `nap` |
|  | `watch_documentary` | `watch_media` |
|  | `watch_evening_television` | `watch_media` |
|  | `watch_football_highlights` | `watch_media` |
|  | `watch_late_news` | `watch_media` |
|  | `watch_sunday_program` | `watch_media` |
| ★ | `watch_television` | `watch_media` |

### meal_preparation (14)

| | Intento | Componenti |
|---|---|---|
|  | `cook_chicken_and_vegetables` | `prepare_food` |
|  | `cook_dinner` | `prepare_food` |
|  | `portion_and_store_prepared_food` | `portion_food`, `store_food` |
|  | `prepare_and_eat_breakfast` | `prepare_food`, `consume_meal` |
|  | `prepare_breakfast` | `prepare_food` |
|  | `prepare_coffee_and_drink_on_balcony` | `prepare_drink`, `consume_drink` |
| ★ | `prepare_light_dinner` | `prepare_food` |
|  | `prepare_quick_pasta_and_salad` | `prepare_food`, `prepare_salad` |
|  | `prepare_rice_and_vegetables` | `prepare_food` |
| ★ | `prepare_simple_lunch` | `prepare_food` |
|  | `prepare_sunday_lunch` | `prepare_food` |
|  | `prepare_weekend_breakfast` | `prepare_food` |
|  | `reheat_leftover_dinner_and_prepare_salad` | `reheat_food`, `prepare_salad` |
| ★ | `weekly_meal_preparation` | `prepare_food`, `portion_food`, `store_food` |

### medication (2)

| | Intento | Componenti |
|---|---|---|
|  | `collect_medication_refill` | `collect_medication` |
| ★ | `take_morning_medication` | `take_medication` |

### sleep (4)

| | Intento | Componenti |
|---|---|---|
|  | `read_in_bed` | `read_in_bed` |
| ★ | `sleep` | `sleep` |
| ★ | `wake_up` | `wake_up` |
|  | `wake_up_without_alarm` | `wake_up` |

### social_visit (2)

| | Intento | Componenti |
|---|---|---|
|  | `social_drink_out` | `socialize_in_person`, `consume_drink` |
|  | `visit_relative_and_have_dinner` | `socialize_in_person`, `consume_meal` |

### travel (12)

| | Intento | Componenti |
|---|---|---|
|  | `collect_belongings_and_leave_home` | `collect_belongings`, `leave_home` |
|  | `commute_home` | `travel`, `enter_home` |
|  | `commute_to_work` | `travel` |
|  | `go_to_neighborhood_market` | `travel` |
|  | `leave_home` | `leave_home` |
|  | `return_home_and_store_purchases` | `travel`, `enter_home`, `store_purchases` |
|  | `take_recycling_out` | `carry_recycling`, `leave_home`, `discard_recycling` |
|  | `travel_home` | `travel`, `enter_home` |
|  | `travel_to_neighborhood_bar` | `travel` |
|  | `travel_to_pharmacy` | `travel` |
|  | `travel_to_relatives_home` | `travel` |
|  | `travel_to_supermarket` | `travel` |

### work (1)

| | Intento | Componenti |
|---|---|---|
|  | `work_shift` | `work` |

---

## 3. Componenti semantici — 54

Il mattone atomico: un intento è una sequenza ordinata di componenti, e ogni modello di processo
deve dichiarare esattamente gli stessi. Ogni componente impone le proprie azioni richieste.

| Componente | Azioni richieste |
|---|---|
| `carry_purchases` | `take_item` |
| `carry_recycling` | `take_item` |
| `change_clothes` | `take_item`, `dress`, `put_item` |
| `check_calendar` | `inspect` |
| `clean_surface` | `take_item`, `clean`, `put_item` |
| `collect_belongings` | `take_item` |
| `collect_laundry` | `laundry_step` |
| `collect_medication` | `manage_medication`, `take_item` |
| `consume_drink` | `consume` |
| `consume_meal` | `change_posture`, `consume`, `change_posture` |
| `consume_snack` | `consume` |
| `discard_recycling` | `put_item` |
| `dust` | `take_item`, `clean`, `put_item` |
| `enter_home` | `enter_home` |
| `exercise` | `exercise` |
| `hang_laundry` | `laundry_step` |
| `inspect_supplies` | `open`, `inspect`, `close` |
| `iron_laundry` | `laundry_step` |
| `leave_home` | `leave_home` |
| `listen_radio` | `leisure` |
| `load_laundry` | `laundry_step` |
| `nap` | `change_posture`, `wait` |
| `organize_bag` | `organize` |
| `organize_clothes` | `organize` |
| `organize_documents` | `organize` |
| `personal_hygiene` | `personal_care` |
| `phone_call` | `change_posture`, `communicate`, `change_posture` |
| `portion_food` | `organize` |
| `prepare_drink` | `take_item`, `activate`, `prepare_food`, `deactivate` |
| `prepare_food` | `open`, `take_item`, `close`, `activate`, `prepare_food`, `deactivate`, `put_item` |
| `prepare_salad` | `take_item`, `prepare_food`, `put_item` |
| `read` | `change_posture`, `leisure` |
| `read_in_bed` | `change_posture`, `leisure` |
| `read_news` | `leisure` |
| `reheat_food` | `take_item`, `activate`, `prepare_food`, `deactivate` |
| `rest` | `change_posture`, `wait` |
| `shop` | `shop` |
| `shower` | `activate`, `personal_care`, `deactivate` |
| `sleep` | `change_posture`, `wait` |
| `socialize_in_person` | `communicate` |
| `start_laundry` | `laundry_step` |
| `store_food` | `open`, `put_item`, `close` |
| `store_purchases` | `open`, `put_item`, `close` |
| `take_medication` | `take_item`, `manage_medication`, `put_item` |
| `tidy_area` | `organize` |
| `travel` | `travel_to` |
| `use_toilet` | `personal_care` |
| `vacuum` | `take_item`, `activate`, `clean`, `deactivate`, `put_item` |
| `wake_up` | `change_posture` |
| `walk` | `exercise` |
| `wash_dishes` | `activate`, `clean`, `deactivate` |
| `wash_face` | `activate`, `personal_care`, `deactivate` |
| `watch_media` | `change_posture`, `activate`, `leisure`, `deactivate` |
| `work` | `change_posture`, `perform_work` |

---

## 4. Azioni atomiche — 27

Il vocabolario chiuso con cui sono scritti i grafi di processo. Gli effetti sono i fatti di stato
che l'azione modifica al termine dell'esecuzione.

| Azione | Parametri | Effetti |
|---|---|---|
| `activate` | `target` | `entity.{target}.active` |
| `change_posture` | `posture` | `resident.posture` |
| `clean` | `targetRole` | — |
| `close` | `target` | `entity.{target}.open` |
| `communicate` | `channel` | — |
| `consume` | `itemRole` | `capability.{itemRole}.consumed` |
| `deactivate` | `target` | `entity.{target}.active` |
| `dress` | `purpose` | `resident.carrying.used_clothing` |
| `enter_home` | — | `resident.at_home` |
| `exercise` | `kind` | — |
| `inspect` | `targetRole` | — |
| `laundry_step` | `operation` | — |
| `leave_home` | — | `resident.at_home` |
| `leisure` | `kind` | — |
| `manage_medication` | `operation` | — |
| `move_to` | `destination` | `resident.location` |
| `move_to_capability` | `targetRole` | `resident.location` |
| `open` | `target` | `entity.{target}.open` |
| `organize` | `targetRole` | — |
| `perform_work` | `mode` | — |
| `personal_care` | `procedure` | — |
| `prepare_food` | `mealKind`, `outputRole` | `resident.carrying.{outputRole}` |
| `put_item` | `itemRole` | `resident.carrying.{itemRole}` |
| `shop` | `purpose` | `resident.carrying.purchases` |
| `take_item` | `itemRole` | `resident.carrying.{itemRole}` |
| `travel_to` | `destination` | `resident.location` |
| `wait` | `purpose` | — |

---

## 5. Variabili — 18

| Variabile | Nome | Tipo | Scope |
|---|---|---|---|
| `resident.age` | Age | integer | `resident` |
| `resident.household` | Household composition | string | `resident` |
| `resident.health_conditions` | Health conditions | array | `resident` |
| `resident.mobility_profile` | Mobility profile | string | `resident` |
| `resident.walking_speed` | Walking speed | number | `resident` |
| `resident.chronotype` | Chronotype | string | `resident` |
| `resident.preferred_breakfast_drink` | Preferred breakfast drink | string | `resident` |
| `resident.fatigue` | Fatigue | number | `initial_state` |
| `resident.hunger` | Hunger | number | `initial_state` |
| `resident.stress` | Stress | number | `initial_state` |
| `resident.social_need` | Social need | number | `initial_state` |
| `resident.food_inventory` | Food inventory | object | `initial_state` |
| `resident.medication_available_doses` | Medication available doses | integer | `initial_state` |
| `day.type` | Day type | string | `day` |
| `day.weather` | Weather | string | `day` |
| `day.public_holiday` | Public holiday | boolean | `day` |
| `calendar.weekday` | Weekday | integer | `derived_calendar` |
| `calendar.season` | Season | string | `derived_calendar` |

