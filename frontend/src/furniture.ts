import { customSymbolId } from "./vocabulary/symbol-registry";

/**
 * Which glyph draws which entity type on the plan canvas and in the replay scene.
 *
 * The glyphs themselves live in `furniture-symbols.tsx`; this map is a plain module so the lookup
 * can be imported without dragging a component along.
 */

const SYMBOL_BY_ENTITY_TYPE: Record<string, string> = {
  armchair: "armchair",
  bathtub: "bathtub",
  bed: "bed",
  bench: "bench",
  bidet: "bidet",
  bookshelf: "bookshelf",
  chair: "chair",
  chest_of_drawers: "chest_of_drawers",
  coat_rack: "coat_rack",
  coffee_machine: "coffee_machine",
  coffee_table: "coffee_table",
  desk: "desk",
  dishwasher: "dishwasher",
  drying_rack: "drying_rack",
  floor_lamp: "floor_lamp",
  garden_chair: "garden_chair",
  garden_planter: "garden_planter",
  houseplant: "houseplant",
  kettle: "kettle",
  kitchen_counter: "kitchen_counter",
  medicine_cabinet: "medicine_cabinet",
  microwave: "microwave",
  mirror: "mirror",
  moka_coffee_maker: "moka_coffee_maker",
  nightstand: "nightstand",
  oven: "oven",
  radio: "radio",
  refrigerator: "refrigerator",
  shoe_rack: "shoe_rack",
  shower: "shower",
  sideboard: "sideboard",
  single_bed: "single_bed",
  sink: "sink",
  sofa: "sofa",
  stool: "stool",
  storage_cabinet: "storage_cabinet",
  stove: "stove",
  table: "table",
  television: "television",
  toilet: "toilet",
  tv_stand: "tv_stand",
  wardrobe: "wardrobe",
  washbasin: "washbasin",
  washing_machine: "washing_machine",
};

/**
 * Spellings a scenario may use for a kind of furniture this build already draws.
 *
 * A scenario names its own resource types, and it names them the way a person would: the generated
 * world says `bedside_table`, an imported one says `night_table`, and neither was a key above — so
 * both fell through to the dashed box, in a flat that had a perfectly good nightstand glyph. The
 * same table exists in `materialization/furnishing.py`, where it decides the piece's dimensions;
 * both are copies of one fact about vocabulary, kept where each is read.
 */
const ALIASES: Record<string, string> = {
  armoire: "wardrobe",
  bath: "bathtub",
  bedside_table: "nightstand",
  book_shelf: "bookshelf",
  bookcase: "bookshelf",
  cabinet: "storage_cabinet",
  coat_stand: "coat_rack",
  cooker: "stove",
  couch: "sofa",
  counter: "kitchen_counter",
  cupboard: "storage_cabinet",
  dining_chair: "chair",
  dining_table: "table",
  dishwashing_machine: "dishwasher",
  dresser: "chest_of_drawers",
  easy_chair: "armchair",
  electric_kettle: "kettle",
  freezer: "refrigerator",
  fridge: "refrigerator",
  hob: "stove",
  kitchen_cabinet: "storage_cabinet",
  kitchen_chair: "chair",
  kitchen_table: "table",
  lamp: "floor_lamp",
  night_table: "nightstand",
  plant: "houseplant",
  potted_plant: "houseplant",
  settee: "sofa",
  side_table: "coffee_table",
  study_desk: "desk",
  tv: "television",
  wash_basin: "washbasin",
  washstand: "washbasin",
  wc: "toilet",
  worktop: "kitchen_counter",
  writing_desk: "desk",
};

/**
 * Every entity type the bundled glyphs cover.
 *
 * The vocabulary editor asks the server which types have no drawing, and the server cannot know:
 * the glyphs live here. So the list travels the other way, and there is no second copy of it to
 * drift from the one that draws.
 */
export function drawableEntityTypes(): string[] {
  return [...new Set([...Object.keys(SYMBOL_BY_ENTITY_TYPE), ...Object.keys(ALIASES)])].sort();
}

export function furnitureSymbol(entityType: string | undefined): string | undefined {
  if (!entityType) return undefined;
  // A drawing the researcher authored for this type wins over the bundled glyph: they added the
  // type, and if they also drew it they meant that drawing.
  return (
    customSymbolId(entityType) ??
    SYMBOL_BY_ENTITY_TYPE[entityType] ??
    SYMBOL_BY_ENTITY_TYPE[ALIASES[entityType] ?? ""]
  );
}

/**
 * The glyph for an obstacle that is part of the building rather than its contents.
 *
 * A staircase has no entity — nothing binds to it and nothing switches it on — so it reaches the
 * canvas as an obstacle with an id and no type. Drawn as an anonymous hatched block it read as a
 * wardrobe abandoned in the middle of the hall.
 */
export function structuralSymbol(obstacleId: string): string | undefined {
  return obstacleId.startsWith("obstacle_stairs_") ? "stairs" : undefined;
}

/**
 * What each kind of furniture measures, as (along the wall, front to back) in metres.
 *
 * The same numbers as `materialization/furnishing.py`, because they are the same objects: the
 * generator sizes a wardrobe from that table and the editor has to hand you the same wardrobe when
 * you drop one. They are also the viewBox of the matching symbol, in centimetres — a symbol is
 * authored at life size — and a test holds the two together.
 */
export const FURNITURE_SIZES: Record<string, readonly [number, number]> = {
  // Sleeping.
  bed: [1.6, 2], single_bed: [0.9, 2], nightstand: [0.45, 0.4],
  wardrobe: [1.2, 0.6], chest_of_drawers: [0.9, 0.5],
  // Sitting.
  sofa: [2, 0.85], armchair: [0.8, 0.8], coffee_table: [1, 0.55],
  television: [1.1, 0.35], tv_stand: [1.2, 0.42], radio: [0.35, 0.25],
  bookshelf: [0.9, 0.32], storage_cabinet: [0.8, 0.4], sideboard: [1.4, 0.45],
  floor_lamp: [0.35, 0.35], houseplant: [0.4, 0.4],
  // Eating and working.
  table: [1.2, 0.8], chair: [0.45, 0.45], stool: [0.38, 0.38], bench: [1.2, 0.4], desk: [1.3, 0.65],
  // Cooking.
  kitchen_counter: [1.2, 0.62], sink: [0.6, 0.55], stove: [0.6, 0.6], oven: [0.6, 0.6],
  dishwasher: [0.6, 0.6], refrigerator: [0.7, 0.7], microwave: [0.5, 0.38],
  kettle: [0.22, 0.22], coffee_machine: [0.3, 0.3], moka_coffee_maker: [0.2, 0.2],
  // Washing.
  washbasin: [0.6, 0.45], toilet: [0.45, 0.7], bidet: [0.4, 0.6], shower: [0.8, 0.8],
  bathtub: [1.7, 0.75], washing_machine: [0.6, 0.55], drying_rack: [0.7, 0.55],
  medicine_cabinet: [0.45, 0.2],
  // Halls and outside.
  shoe_rack: [0.7, 0.3], coat_rack: [0.45, 0.35], mirror: [0.6, 0.12],
  garden_planter: [0.5, 0.4], garden_chair: [0.55, 0.55],
  // Structure. Not offered in the palette: a staircase comes with a storey, not with a room.
  stairs: [1, 2.6],
};

/** The default footprint for a kind of furniture, in metres. */
export function furnitureSize(entityType: string): readonly [number, number] {
  const canonical = ALIASES[entityType] ?? entityType;
  return FURNITURE_SIZES[canonical] ?? [0.6, 0.5];
}

/**
 * The furniture the palette offers, in the order a person looks for it.
 *
 * Grouped rather than alphabetical: somebody adding a bath is thinking about the bathroom, not
 * about the letter b, and forty-four names in one list is a list nobody reads.
 */
export const FURNITURE_GROUPS: ReadonlyArray<{ label: string; types: readonly string[] }> = [
  { label: "Living", types: ["sofa", "armchair", "coffee_table", "television", "tv_stand", "radio", "bookshelf", "sideboard", "floor_lamp", "houseplant"] },
  { label: "Sleeping", types: ["bed", "single_bed", "nightstand", "wardrobe", "chest_of_drawers", "mirror"] },
  { label: "Kitchen", types: ["kitchen_counter", "sink", "stove", "oven", "refrigerator", "dishwasher", "microwave", "kettle", "coffee_machine", "moka_coffee_maker"] },
  { label: "Eating and working", types: ["table", "chair", "stool", "bench", "desk"] },
  { label: "Bathroom and laundry", types: ["toilet", "washbasin", "bidet", "shower", "bathtub", "washing_machine", "drying_rack", "medicine_cabinet", "storage_cabinet"] },
  { label: "Hall and outside", types: ["shoe_rack", "coat_rack", "garden_planter", "garden_chair"] },
];

/** `chest_of_drawers` reads as "Chest of drawers" until the workspace says otherwise. */
export function furnitureLabel(entityType: string): string {
  const words = entityType.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
