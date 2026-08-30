/**
 * Furniture glyphs for the plan canvas and the replay scene.
 *
 * Two things were wrong with the previous set and both were invisible in the code.
 *
 * Every glyph was authored in the same square `-24..24` box and drawn into the obstacle's footprint
 * with `preserveAspectRatio="meet"`. A bed is 1.60 by 2.00 metres, so "meet" shrank the drawing to
 * the narrow side and left a third of the footprint as bare hatching; a television, 1.10 by 0.35,
 * came out as a postage stamp in the middle of a long thin box. The furniture was there and you
 * could not see it.
 *
 * And nothing was ever turned. The placer has always been free to stand a piece against any of the
 * four walls, so half the flat was drawn facing the wrong way — a sofa with its back to the room, a
 * toilet with its cistern in mid-air, a bed you climbed into through the headboard.
 *
 * So the set is authored to a rule instead:
 *
 * - **one unit is one centimetre**, and each symbol's viewBox is exactly the footprint the
 *   generator gives that kind of furniture. The glyph then fills its obstacle rather than floating
 *   inside it, and a stroke width of 2 means two centimetres at any zoom;
 * - **the wall is at the top, the usable front at the bottom.** `FurnitureGlyph` turns the drawing
 *   by the obstacle's own `orientationDegrees`, so which way a thing faces is drawn, not guessed.
 *
 * Symbols are plain inline SVG. No icon CDN and no raster art: a published plan has to render with
 * no network, and the export in `tools/` embeds this same geometry.
 */

import type { ReactElement } from "react";

/* Palette. Teal for fixtures and appliances, warm ochre for anything wooden, per DESIGN.md. */
const SHELL = "#ffffff";
const TEAL = "#dcefed";
const TEAL_DEEP = "#cde6e2";
const WOOD = "#fff4df";
const WOOD_DEEP = "#f2e2c2";

export function FurnitureSymbols(): ReactElement {
  return (
    <>
      {/* ---------------------------------------------------------------- sleeping */}
      <symbol id="furn-bed" viewBox="0 0 160 200">
        <rect x="2" y="2" width="156" height="196" rx="6" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <rect x="10" y="10" width="65" height="42" rx="6" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="85" y="10" width="65" height="42" rx="6" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <path d="M8 68h144v124H8z" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="2.4" />
        <path d="M8 96h144" stroke="currentColor" strokeWidth="2" />
        <path d="M80 96v96" stroke="currentColor" strokeWidth="1.6" opacity=".55" />
      </symbol>
      <symbol id="furn-single_bed" viewBox="0 0 90 200">
        <rect x="2" y="2" width="86" height="196" rx="6" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <rect x="12" y="10" width="66" height="40" rx="6" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <path d="M8 66h74v126H8z" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="2.4" />
        <path d="M8 94h74" stroke="currentColor" strokeWidth="2" />
      </symbol>
      <symbol id="furn-nightstand" viewBox="0 0 45 40">
        <rect x="1.5" y="1.5" width="42" height="37" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.4" />
        <rect x="6" y="20" width="33" height="14" rx="2" fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.8" />
        <circle cx="22.5" cy="27" r="2.2" fill="currentColor" />
      </symbol>
      <symbol id="furn-wardrobe" viewBox="0 0 120 60">
        <rect x="2" y="2" width="116" height="56" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="3" />
        <path d="M60 2v56" stroke="currentColor" strokeWidth="2.2" />
        <path d="M10 12h40M70 12h40" stroke="currentColor" strokeWidth="1.6" opacity=".5" />
        <circle cx="53" cy="46" r="3" fill="currentColor" />
        <circle cx="67" cy="46" r="3" fill="currentColor" />
      </symbol>
      <symbol id="furn-chest_of_drawers" viewBox="0 0 90 50">
        <rect x="2" y="2" width="86" height="46" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.8" />
        <rect x="8" y="24" width="74" height="20" rx="2" fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.8" />
        <path d="M30 34h30" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      </symbol>

      {/* ---------------------------------------------------------------- sitting */}
      <symbol id="furn-sofa" viewBox="0 0 200 85">
        <rect x="2" y="2" width="196" height="81" rx="10" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <rect x="2" y="2" width="196" height="24" rx="9" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="2" y="14" width="26" height="69" rx="9" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="172" y="14" width="26" height="69" rx="9" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <path d="M100 28v55" stroke="currentColor" strokeWidth="1.8" opacity=".6" />
        <path d="M28 74h144" stroke="currentColor" strokeWidth="1.6" opacity=".45" />
      </symbol>
      <symbol id="furn-armchair" viewBox="0 0 80 80">
        <rect x="2" y="2" width="76" height="76" rx="10" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <rect x="2" y="2" width="76" height="22" rx="9" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="2" y="16" width="20" height="62" rx="8" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="58" y="16" width="20" height="62" rx="8" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
      </symbol>
      <symbol id="furn-coffee_table" viewBox="0 0 100 55">
        <rect x="2" y="2" width="96" height="51" rx="8" fill={WOOD} stroke="currentColor" strokeWidth="2.8" />
        <rect x="14" y="12" width="72" height="31" rx="5" fill="none" stroke="currentColor" strokeWidth="1.6" opacity=".55" />
      </symbol>
      <symbol id="furn-television" viewBox="0 0 110 35">
        <rect x="2" y="2" width="106" height="22" rx="2" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="3" />
        <path d="M12 8l18 10 20-12 16 9 14-8" fill="none" stroke="currentColor" strokeWidth="2" opacity=".6" />
        <path d="M40 27h30M55 24v9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-tv_stand" viewBox="0 0 120 42">
        <rect x="2" y="2" width="116" height="38" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.8" />
        <rect x="10" y="20" width="46" height="16" rx="2" fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.6" />
        <rect x="64" y="20" width="46" height="16" rx="2" fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.6" />
      </symbol>
      <symbol id="furn-radio" viewBox="0 0 35 25">
        <rect x="1.5" y="1.5" width="32" height="22" rx="3" fill={SHELL} stroke="currentColor" strokeWidth="2.2" />
        <circle cx="12" cy="12.5" r="6" fill={TEAL} stroke="currentColor" strokeWidth="1.6" />
        <path d="M23 8h7M23 12.5h7M23 17h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-bookshelf" viewBox="0 0 90 32">
        <rect x="2" y="2" width="86" height="28" rx="2" fill={WOOD} stroke="currentColor" strokeWidth="2.6" />
        <g stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <path d="M10 8v16M16 7v17M22 9v15M30 8v16M36 10v14M46 7v17M52 9v15M60 8v16M68 9v15M74 7v17M80 9v15" />
        </g>
      </symbol>
      <symbol id="furn-storage_cabinet" viewBox="0 0 80 40">
        <rect x="2" y="2" width="76" height="36" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.8" />
        <path d="M40 2v36" stroke="currentColor" strokeWidth="2" />
        <circle cx="34" cy="30" r="2.6" fill="currentColor" />
        <circle cx="46" cy="30" r="2.6" fill="currentColor" />
      </symbol>
      <symbol id="furn-sideboard" viewBox="0 0 140 45">
        <rect x="2" y="2" width="136" height="41" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.8" />
        <path d="M48 2v41M92 2v41" stroke="currentColor" strokeWidth="1.8" />
        <g fill="currentColor">
          <circle cx="43" cy="34" r="2.4" />
          <circle cx="53" cy="34" r="2.4" />
          <circle cx="87" cy="34" r="2.4" />
          <circle cx="97" cy="34" r="2.4" />
        </g>
      </symbol>
      <symbol id="furn-floor_lamp" viewBox="0 0 35 35">
        <circle cx="17.5" cy="17.5" r="15.5" fill={SHELL} stroke="currentColor" strokeWidth="2.4" />
        <circle cx="17.5" cy="17.5" r="8" fill={TEAL} stroke="currentColor" strokeWidth="1.8" />
        <circle cx="17.5" cy="17.5" r="2.4" fill="currentColor" />
      </symbol>
      <symbol id="furn-houseplant" viewBox="0 0 40 40">
        <circle cx="20" cy="20" r="18" fill={WOOD} stroke="currentColor" strokeWidth="2.4" />
        <path d="M20 30c0-9-5-14-12-16 1 9 5 14 12 16zM20 30c0-9 5-14 12-16-1 9-5 14-12 16zM20 30V12" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      </symbol>

      {/* ---------------------------------------------------------------- eating and working */}
      <symbol id="furn-table" viewBox="0 0 120 80">
        <rect x="2" y="2" width="116" height="76" rx="10" fill={WOOD} stroke="currentColor" strokeWidth="3" />
        <rect x="16" y="12" width="88" height="56" rx="6" fill="none" stroke="currentColor" strokeWidth="1.6" opacity=".5" />
        <g fill="currentColor" opacity=".7">
          <circle cx="14" cy="14" r="3" />
          <circle cx="106" cy="14" r="3" />
          <circle cx="14" cy="66" r="3" />
          <circle cx="106" cy="66" r="3" />
        </g>
      </symbol>
      <symbol id="furn-chair" viewBox="0 0 45 45">
        <rect x="3" y="10" width="39" height="33" rx="5" fill={WOOD} stroke="currentColor" strokeWidth="2.6" />
        <rect x="2" y="2" width="41" height="11" rx="5" fill={TEAL} stroke="currentColor" strokeWidth="2.2" />
      </symbol>
      <symbol id="furn-stool" viewBox="0 0 38 38">
        <circle cx="19" cy="19" r="16.5" fill={WOOD} stroke="currentColor" strokeWidth="2.6" />
        <circle cx="19" cy="19" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" opacity=".5" />
      </symbol>
      <symbol id="furn-bench" viewBox="0 0 120 40">
        <rect x="2" y="2" width="116" height="36" rx="5" fill={WOOD} stroke="currentColor" strokeWidth="2.6" />
        <path d="M2 14h116M2 26h116" stroke="currentColor" strokeWidth="1.6" opacity=".55" />
      </symbol>
      <symbol id="furn-desk" viewBox="0 0 130 65">
        <rect x="2" y="2" width="126" height="61" rx="4" fill={WOOD} stroke="currentColor" strokeWidth="3" />
        <rect x="86" y="8" width="36" height="49" rx="3" fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.8" />
        <path d="M92 22h24M92 34h24M92 46h24" stroke="currentColor" strokeWidth="1.6" opacity=".6" />
        <rect x="14" y="26" width="56" height="26" rx="3" fill={TEAL} stroke="currentColor" strokeWidth="1.8" />
      </symbol>

      {/* ---------------------------------------------------------------- cooking */}
      <symbol id="furn-kitchen_counter" viewBox="0 0 120 62">
        <rect x="2" y="2" width="116" height="58" rx="3" fill={SHELL} stroke="currentColor" strokeWidth="2.8" />
        <path d="M2 46h116" stroke="currentColor" strokeWidth="1.8" opacity=".55" />
        <rect x="14" y="12" width="42" height="28" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="1.8" />
        <path d="M72 14h34M72 24h34M72 34h22" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" opacity=".6" />
      </symbol>
      <symbol id="furn-sink" viewBox="0 0 60 55">
        <rect x="1.5" y="1.5" width="57" height="52" rx="5" fill={SHELL} stroke="currentColor" strokeWidth="2.6" />
        <path d="M24 4v8c0 4 12 4 12 0V4" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
        <ellipse cx="30" cy="33" rx="20" ry="15" fill={TEAL} stroke="currentColor" strokeWidth="2.2" />
        <circle cx="30" cy="33" r="3" fill="currentColor" />
      </symbol>
      <symbol id="furn-stove" viewBox="0 0 60 60">
        <rect x="1.5" y="1.5" width="57" height="57" rx="4" fill={SHELL} stroke="currentColor" strokeWidth="2.6" />
        <circle cx="18" cy="17" r="9" fill={TEAL} stroke="currentColor" strokeWidth="2" />
        <circle cx="42" cy="17" r="9" fill={TEAL} stroke="currentColor" strokeWidth="2" />
        <circle cx="18" cy="37" r="9" fill={TEAL} stroke="currentColor" strokeWidth="2" />
        <circle cx="42" cy="37" r="9" fill={TEAL} stroke="currentColor" strokeWidth="2" />
        <g fill="currentColor">
          <circle cx="16" cy="52" r="2.6" />
          <circle cx="26" cy="52" r="2.6" />
          <circle cx="36" cy="52" r="2.6" />
          <circle cx="46" cy="52" r="2.6" />
        </g>
      </symbol>
      <symbol id="furn-oven" viewBox="0 0 60 60">
        <rect x="1.5" y="1.5" width="57" height="57" rx="4" fill={SHELL} stroke="currentColor" strokeWidth="2.6" />
        <rect x="9" y="12" width="42" height="30" rx="3" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="2" />
        <path d="M12 51h36" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-dishwasher" viewBox="0 0 60 60">
        <rect x="1.5" y="1.5" width="57" height="57" rx="4" fill={SHELL} stroke="currentColor" strokeWidth="2.6" />
        <rect x="9" y="16" width="42" height="26" rx="3" fill={TEAL} stroke="currentColor" strokeWidth="2" />
        <path d="M9 9h42" stroke="currentColor" strokeWidth="2" opacity=".6" />
        <path d="M12 51h36" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-refrigerator" viewBox="0 0 70 70">
        <rect x="2" y="2" width="66" height="66" rx="4" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <path d="M2 26h66" stroke="currentColor" strokeWidth="2.2" />
        <path d="M52 10v10M52 34v22" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <rect x="10" y="8" width="26" height="12" rx="3" fill={TEAL} stroke="currentColor" strokeWidth="1.6" />
      </symbol>
      <symbol id="furn-microwave" viewBox="0 0 50 38">
        <rect x="1.5" y="1.5" width="47" height="35" rx="3" fill={SHELL} stroke="currentColor" strokeWidth="2.4" />
        <rect x="6" y="7" width="27" height="24" rx="2" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="1.8" />
        <path d="M38 9v20" stroke="currentColor" strokeWidth="1.8" opacity=".6" />
      </symbol>
      <symbol id="furn-kettle" viewBox="0 0 22 22">
        <path d="M4 5h11l2.5 14h-16z" fill={SHELL} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M15.5 8c4 0 4.5 7 1 8.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-coffee_machine" viewBox="0 0 30 30">
        <rect x="2" y="2" width="26" height="26" rx="3" fill={SHELL} stroke="currentColor" strokeWidth="2.2" />
        <path d="M10 10h10v5H10z" fill={TEAL} stroke="currentColor" strokeWidth="1.5" />
        <path d="M9 22h12a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4z" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="1.5" />
      </symbol>
      <symbol id="furn-moka_coffee_maker" viewBox="0 0 20 20">
        <path d="M5 3h10l3 14H2z" fill={SHELL} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M15 7c3.5 0 3.5 6 .5 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M6 10h8" stroke="currentColor" strokeWidth="1.4" opacity=".6" />
      </symbol>

      {/* ---------------------------------------------------------------- washing */}
      <symbol id="furn-washbasin" viewBox="0 0 60 45">
        <rect x="1.5" y="1.5" width="57" height="42" rx="5" fill={SHELL} stroke="currentColor" strokeWidth="2.4" />
        <path d="M25 3v6c0 3 10 3 10 0V3" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        <ellipse cx="30" cy="26" rx="20" ry="13" fill={TEAL} stroke="currentColor" strokeWidth="2.2" />
        <circle cx="30" cy="26" r="2.6" fill="currentColor" />
      </symbol>
      <symbol id="furn-toilet" viewBox="0 0 45 70">
        <rect x="4" y="2" width="37" height="16" rx="3" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <path d="M9 18h27v22a13.5 18 0 0 1-27 0z" fill={SHELL} stroke="currentColor" strokeWidth="2.4" />
        <ellipse cx="22.5" cy="38" rx="9" ry="12" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="1.8" />
        <path d="M13 60h19" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity=".5" />
      </symbol>
      <symbol id="furn-bidet" viewBox="0 0 40 60">
        <path d="M7 4h26v34a13 17 0 0 1-26 0z" fill={SHELL} stroke="currentColor" strokeWidth="2.4" />
        <ellipse cx="20" cy="32" rx="9" ry="12" fill={TEAL} stroke="currentColor" strokeWidth="1.8" />
        <path d="M16 6v4c0 2 8 2 8 0V6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-shower" viewBox="0 0 80 80">
        <rect x="2" y="2" width="76" height="76" rx="5" fill={TEAL} stroke="currentColor" strokeWidth="3" />
        <path d="M2 2h76v76" fill="none" stroke="currentColor" strokeWidth="3" />
        <circle cx="18" cy="18" r="8" fill={SHELL} stroke="currentColor" strokeWidth="2.2" />
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity=".7">
          <path d="M32 34v6M44 34v6M56 34v6M32 50v6M44 50v6M56 50v6M38 42v6M50 42v6" />
        </g>
        <circle cx="60" cy="62" r="4" fill={SHELL} stroke="currentColor" strokeWidth="2" />
      </symbol>
      <symbol id="furn-bathtub" viewBox="0 0 170 75">
        <rect x="2" y="2" width="166" height="71" rx="14" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <rect x="14" y="12" width="142" height="51" rx="10" fill={TEAL} stroke="currentColor" strokeWidth="2.2" />
        <circle cx="141" cy="37" r="5" fill={SHELL} stroke="currentColor" strokeWidth="2" />
        <path d="M18 6v6c0 3 12 3 12 0V6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-washing_machine" viewBox="0 0 60 55">
        <rect x="1.5" y="1.5" width="57" height="52" rx="4" fill={SHELL} stroke="currentColor" strokeWidth="2.6" />
        <path d="M6 12h48" stroke="currentColor" strokeWidth="1.8" opacity=".6" />
        <circle cx="30" cy="34" r="15" fill={TEAL} stroke="currentColor" strokeWidth="2.4" />
        <circle cx="30" cy="34" r="7" fill={SHELL} stroke="currentColor" strokeWidth="1.6" />
        <circle cx="50" cy="7" r="2.4" fill="currentColor" />
      </symbol>
      <symbol id="furn-drying_rack" viewBox="0 0 70 55">
        <rect x="2" y="2" width="66" height="51" rx="4" fill="none" stroke="currentColor" strokeWidth="2.4" />
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity=".75">
          <path d="M2 12h66M2 22h66M2 32h66M2 42h66" />
        </g>
      </symbol>
      <symbol id="furn-medicine_cabinet" viewBox="0 0 45 20">
        <rect x="1.5" y="1.5" width="42" height="17" rx="2.5" fill={SHELL} stroke="currentColor" strokeWidth="2.2" />
        <path d="M22.5 5v10M17.5 10h10" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-mirror" viewBox="0 0 60 12">
        <rect x="1" y="1" width="58" height="10" rx="3" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="2" />
        <path d="M12 9l8-6M26 9l8-6" stroke={SHELL} strokeWidth="2" strokeLinecap="round" />
      </symbol>

      {/* ---------------------------------------------------------------- halls and outside */}
      <symbol id="furn-shoe_rack" viewBox="0 0 70 30">
        <rect x="2" y="2" width="66" height="26" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.4" />
        <path d="M2 15h66" stroke="currentColor" strokeWidth="1.6" opacity=".55" />
        <g fill={WOOD_DEEP} stroke="currentColor" strokeWidth="1.4">
          <ellipse cx="18" cy="9" rx="8" ry="4" />
          <ellipse cx="40" cy="9" rx="8" ry="4" />
          <ellipse cx="29" cy="22" rx="8" ry="4" />
          <ellipse cx="51" cy="22" rx="8" ry="4" />
        </g>
      </symbol>
      <symbol id="furn-coat_rack" viewBox="0 0 45 35">
        <rect x="2" y="2" width="41" height="9" rx="3" fill={WOOD} stroke="currentColor" strokeWidth="2.2" />
        <g stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" fill="none">
          <path d="M11 11v9a4 4 0 0 0 4 4" />
          <path d="M22.5 11v13a4 4 0 0 0 4 4" />
          <path d="M34 11v9a4 4 0 0 0 4 4" />
        </g>
      </symbol>
      <symbol id="furn-garden_planter" viewBox="0 0 50 40">
        <path d="M4 12h42l-4 26H8z" fill={WOOD} stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
        <path d="M25 12c0-8-5-11-11-12 1 7 4 11 11 12zM25 12c0-8 5-11 11-12-1 7-4 11-11 12z" fill={TEAL_DEEP} stroke="currentColor" strokeWidth="1.8" />
      </symbol>
      <symbol id="furn-garden_chair" viewBox="0 0 55 55">
        <rect x="4" y="14" width="47" height="37" rx="6" fill="none" stroke="currentColor" strokeWidth="2.4" />
        <rect x="2" y="3" width="51" height="12" rx="5" fill={TEAL} stroke="currentColor" strokeWidth="2.2" />
        <path d="M12 22v22M27.5 22v22M43 22v22" stroke="currentColor" strokeWidth="1.6" opacity=".5" />
      </symbol>

      {/* ---------------------------------------------------------------- structure */}
      <symbol id="furn-stairs" viewBox="0 0 100 260">
        <rect x="2" y="2" width="96" height="256" rx="3" fill={SHELL} stroke="currentColor" strokeWidth="3" />
        <g stroke="currentColor" strokeWidth="2.2" opacity=".8">
          <path d="M2 30h96M2 58h96M2 86h96M2 114h96M2 142h96M2 170h96M2 198h96M2 226h96" />
        </g>
        <path d="M50 230V44M50 44l-14 16M50 44l14 16" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      </symbol>
    </>
  );
}
