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
      activityCatalog: { referenceId: "activity_catalog"; version: "{{ACTIVITY_CATALOG_VERSION}}" };
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
      activityCatalog: { catalogId: "smart_home_activity_catalog"; version: "{{ACTIVITY_CATALOG_VERSION}}" };
      variableCatalog: { catalogId: "smart_home_variable_catalog"; version: "{{VARIABLE_CATALOG_VERSION}}" };
      actionCatalog: { catalogId: "smart_home_action_catalog"; version: "{{ACTION_CATALOG_VERSION}}" };
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

{{INTENT_COMPONENTS}}


## 5. Componenti e sequenze obbligatorie di azioni

Per ogni componente, il percorso `start -> end` del modello deve contenere nell'ordine la sequenza indicata. Puoi inserire azioni aggiuntive per movimento o preparazione dello stato, ma non puoi eliminare, invertire o sostituire le azioni obbligatorie.

{{COMPONENT_ACTION_SEQUENCES}}


Attenzione: nella versione congelata `1.0.0`, il componente `travel` include davvero `leave_home -> travel_to`. Non ridurlo al solo `travel_to`.

Queste sequenze sono il **minimo** che il validatore impone, non la forma corretta. Il minimo non apre il contenitore da cui prende un oggetto: un modello che si limita a `take_item` valida senza errori ma non fa mai scattare il sensore di contatto, e produce un dataset in cui l'armadio non viene mai aperto. Usa sempre la forma della sezione 5.1 quando l'intent e' presente.

## 5.1 Modelli di riferimento provati

Per questi intent esiste un modello gia' verificato in simulazione. Riproducilo azione per azione, cambiando soltanto i valori che il caso impone. Se l'intent che ti serve non e' in questa lista, imita la forma del piu' simile: recupera un oggetto solo dopo aver aperto il contenitore che lo custodisce e richiudilo, e raggiungi con `move_to_capability` il ruolo su cui stai per agire.

{{REFERENCE_PROCESS_MODELS}}


## 6. Grafo e catalogo azioni

Ogni process model deve essere una singola catena lineare:

1. un nodo `start`;
2. come prima azione un movimento (`move_to`, `move_to_capability` oppure `travel_to`);
3. tutte le azioni richieste dai componenti, con eventuali azioni aggiuntive di stato;
4. un nodo `end`;
5. un arco tra ogni coppia consecutiva, senza nodi isolati;
6. `durationWeight: 1` su ogni nodo azione e mai sulle attivita del DayPlan.

Usa soltanto questi actionType e argomenti esatti. Ogni valore dell'argomento deve essere un `ValueExpression`, non una stringa diretta.

{{ACTION_SIGNATURES}}


{{CANONICAL_ROLES}}

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

{{CARRYING_EFFECTS}}

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
