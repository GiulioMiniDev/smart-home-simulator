/**
 * The pack's own furniture drawings, as `<symbol>` elements the two canvases can `<use>`.
 *
 * Rendered beside `FurnitureSymbols` wherever that is, so `#furn-custom-bookcase` resolves the same
 * way `#furn-bed` does.
 *
 * The SVG is injected as markup. It comes from a file in the researcher's own workspace, written by
 * them in this application — the same trust boundary as the rest of the workspace, which the app
 * already reads and executes simulation plans from.
 */

import type { ReactElement } from "react";
import { customSymbols, useCustomSymbolRevision } from "./symbol-registry";

export function CustomFurnitureSymbols(): ReactElement {
  useCustomSymbolRevision();
  return (
    <>
      {Object.entries(customSymbols()).map(([entityType, body]) => (
        <symbol
          key={entityType}
          id={`furn-custom-${entityType}`}
          viewBox="-24 -24 48 48"
          dangerouslySetInnerHTML={{ __html: body }}
        />
      ))}
    </>
  );
}
