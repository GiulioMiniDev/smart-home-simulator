/**
 * Which glyph draws which entity type on the plan canvas.
 *
 * The glyphs themselves live in `furniture-symbols.tsx`; this map is a plain module so the lookup
 * can be imported without dragging a component along.
 */

const SYMBOL_BY_ENTITY_TYPE: Record<string, string> = {
  bed: "bed",
  wardrobe: "wardrobe",
  sofa: "sofa",
  television: "television",
  radio: "radio",
  table: "table",
  chair: "chair",
  stove: "stove",
  refrigerator: "refrigerator",
  sink: "sink",
  washbasin: "washbasin",
  storage_cabinet: "cabinet",
  moka_coffee_maker: "kettle",
  shower: "shower",
  toilet: "toilet",
  washing_machine: "washing_machine",
  garden_planter: "planter",
};

export function furnitureSymbol(entityType: string | undefined): string | undefined {
  if (!entityType) return undefined;
  return SYMBOL_BY_ENTITY_TYPE[entityType];
}
