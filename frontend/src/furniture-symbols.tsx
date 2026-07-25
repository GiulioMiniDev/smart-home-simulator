/**
 * Furniture glyphs for the plan canvas.
 *
 * These symbols already existed, but only inside `tools/build_environment_visualization.py`, hard
 * wired into a one-off M4 benchmark page for a hand-authored home. The editor drew every obstacle
 * as an anonymous hatched rectangle, so a generated flat was unreadable: you could not tell the bed
 * from the wardrobe. They live here now so the editor and that report draw the same furniture.
 *
 * Each symbol is authored in a -24..24 box and is scaled to its obstacle footprint at use time, so
 * a glyph always matches the metric extent the path planner actually routes around.
 */

import type { ReactElement } from "react";

export function FurnitureSymbols(): ReactElement {
  return (
    <>
      <symbol id="furn-bed" viewBox="-24 -24 48 48">
        <rect x="-19" y="-15" width="38" height="30" rx="3" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <rect x="-16" y="-12" width="13" height="9" rx="2" fill="#dcefed" stroke="currentColor" strokeWidth="1.5" />
        <rect x="3" y="-12" width="13" height="9" rx="2" fill="#dcefed" stroke="currentColor" strokeWidth="1.5" />
        <path d="M-16 1h32v11h-32z" fill="#cde6e2" stroke="currentColor" strokeWidth="1.5" />
      </symbol>
      <symbol id="furn-wardrobe" viewBox="-24 -24 48 48">
        <rect x="-15" y="-19" width="30" height="38" rx="2" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <path d="M0-19v38" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="-3" cy="0" r="1.8" fill="currentColor" />
        <circle cx="3" cy="0" r="1.8" fill="currentColor" />
      </symbol>
      <symbol id="furn-sofa" viewBox="-24 -24 48 48">
        <rect x="-20" y="-8" width="40" height="18" rx="4" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <rect x="-20" y="-14" width="40" height="8" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <rect x="-20" y="-10" width="6" height="18" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <rect x="14" y="-10" width="6" height="18" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
      </symbol>
      <symbol id="furn-television" viewBox="-24 -24 48 48">
        <rect x="-21" y="-14" width="42" height="26" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="2" />
        <path d="M-7 17h14M0 12v5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-radio" viewBox="-24 -24 48 48">
        <rect x="-16" y="-10" width="32" height="20" rx="3" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <circle cx="-6" cy="0" r="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <path d="M6-5h7M6 0h7M6 5h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-table" viewBox="-24 -24 48 48">
        <circle cx="0" cy="0" r="15" fill="#fff4df" stroke="currentColor" strokeWidth="2" />
        <path d="M-9 12l-4 8M9 12l4 8M-9-12l-4-8M9-12l4-8" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-chair" viewBox="-24 -24 48 48">
        <rect x="-11" y="-6" width="22" height="18" rx="3" fill="#fff4df" stroke="currentColor" strokeWidth="2" />
        <rect x="-11" y="-16" width="22" height="8" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="1.7" />
      </symbol>
      <symbol id="furn-stove" viewBox="-24 -24 48 48">
        <rect x="-19" y="-18" width="38" height="36" rx="4" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <circle cx="-8" cy="-7" r="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="8" cy="-7" r="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="-8" cy="8" r="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="8" cy="8" r="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.6" />
      </symbol>
      <symbol id="furn-refrigerator" viewBox="-24 -24 48 48">
        <rect x="-14" y="-21" width="28" height="42" rx="3" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <path d="M-14-5h28M8-15v7M8 1v8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <rect x="-10" y="-17" width="12" height="8" rx="2" fill="#dcefed" />
      </symbol>
      <symbol id="furn-sink" viewBox="-24 -24 48 48">
        <rect x="-19" y="-13" width="38" height="27" rx="4" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <ellipse cx="0" cy="2" rx="12" ry="8" fill="#dcefed" stroke="currentColor" strokeWidth="1.7" />
        <path d="M-4-13v-5c0-4 8-4 8 0v7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-washbasin" viewBox="-24 -24 48 48">
        <ellipse cx="0" cy="2" rx="17" ry="12" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <ellipse cx="0" cy="2" rx="10" ry="6.5" fill="#dcefed" stroke="currentColor" strokeWidth="1.5" />
        <path d="M-3-11v-4c0-3 6-3 6 0v5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-cabinet" viewBox="-24 -24 48 48">
        <rect x="-19" y="-17" width="38" height="34" rx="3" fill="#fff4df" stroke="currentColor" strokeWidth="2" />
        <path d="M0-17v34M-19 0h38" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="-4" cy="-8" r="1.6" fill="currentColor" />
        <circle cx="4" cy="-8" r="1.6" fill="currentColor" />
        <circle cx="-4" cy="8" r="1.6" fill="currentColor" />
        <circle cx="4" cy="8" r="1.6" fill="currentColor" />
      </symbol>
      <symbol id="furn-kettle" viewBox="-24 -24 48 48">
        <path d="M-11-10h19l4 25h-27z" fill="#fff" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M9-5c11 0 12 17 3 20M-6-10v-5h9v5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-shower" viewBox="-24 -24 48 48">
        <path d="M-12 17V-4c0-8 5-13 12-13 6 0 10 3 12 8" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
        <path d="M7-8h10v5H7z" fill="#dcefed" stroke="currentColor" strokeWidth="1.7" />
        <path d="M9 2v2m4-2v2m4-2v2M9 9v2m4-2v2m4-2v2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M-17 17h34" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
      </symbol>
      <symbol id="furn-toilet" viewBox="-24 -24 48 48">
        <rect x="-10" y="-18" width="20" height="13" rx="3" fill="#dcefed" stroke="currentColor" strokeWidth="2" />
        <ellipse cx="0" cy="4" rx="13" ry="10" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <ellipse cx="0" cy="4" rx="7" ry="5" fill="#dcefed" stroke="currentColor" strokeWidth="1.5" />
      </symbol>
      <symbol id="furn-washing_machine" viewBox="-24 -24 48 48">
        <rect x="-18" y="-20" width="36" height="40" rx="4" fill="#fff" stroke="currentColor" strokeWidth="2" />
        <circle cx="0" cy="4" r="11" fill="#dcefed" stroke="currentColor" strokeWidth="2" />
        <path d="M-13-13h14" stroke="currentColor" strokeWidth="2" />
        <circle cx="11" cy="-13" r="2" fill="currentColor" />
      </symbol>
      <symbol id="furn-planter" viewBox="-24 -24 48 48">
        <path d="M-13 2h26l-4 16h-18z" fill="#fff4df" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M0 2c0-9-5-14-11-15 1 8 5 13 11 15zM0 2c0-9 5-14 11-15-1 8-5 13-11 15z" fill="#cde6e2" stroke="currentColor" strokeWidth="1.6" />
      </symbol>
    </>
  );
}
