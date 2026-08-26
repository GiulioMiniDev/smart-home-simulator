import { customSymbolId } from "./vocabulary/symbol-registry";

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

/**
 * Every entity type the bundled glyphs cover.
 *
 * The vocabulary editor asks the server which types have no drawing, and the server cannot know:
 * the glyphs live here. So the list travels the other way, and there is no second copy of it to
 * drift from the one that draws.
 */
export function drawableEntityTypes(): string[] {
  return Object.keys(SYMBOL_BY_ENTITY_TYPE).sort();
}

export function furnitureSymbol(entityType: string | undefined): string | undefined {
  if (!entityType) return undefined;
  // A drawing the researcher authored for this type wins over the bundled glyph: they added the
  // type, and if they also drew it they meant that drawing.
  return customSymbolId(entityType) ?? SYMBOL_BY_ENTITY_TYPE[entityType];
}
