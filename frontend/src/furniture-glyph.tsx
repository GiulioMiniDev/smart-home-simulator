/**
 * Drawing one piece of furniture into its footprint, the right way round and the right way up.
 *
 * Both places that draw furniture — the plan canvas and the replay scene — had the same four lines
 * of `<use>` with `preserveAspectRatio="xMidYMid meet"` and no rotation, which is what made a bed
 * a small square adrift in a large rectangle and a sofa face the wall. This is the one place that
 * knows how a glyph maps onto a footprint, so there is one place to get it right.
 *
 * Symbols are authored with the wall at the top and the usable front at the bottom, in a viewBox
 * that *is* the footprint in centimetres (see `furniture-symbols.tsx`). Two things follow:
 *
 * - the drawing has to be turned by the obstacle's own orientation. `orientationDegrees` is a
 *   bearing in the home's frame, 0 along +x and 90 along +y, and the canvas plots those axes
 *   directly, so a piece facing +y is a piece drawn facing down and needs no rotation at all —
 *   hence the ninety-degree offset;
 * - once turned, the glyph and its footprint agree on their proportions, so it can be stretched to
 *   fill instead of shrunk to fit. On a home that predates the field there is nothing to turn by,
 *   and the old behaviour — unturned, uniformly scaled — is kept exactly.
 */

import type { ReactElement } from "react";

export interface GlyphBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

interface Props {
  symbol: string;
  box: GlyphBox;
  /** The obstacle's bearing, or `undefined` on a home generated before orientation was recorded. */
  orientationDegrees?: number;
  className?: string;
}

/** Round to the nearest quarter turn: furniture in this generator is axis-aligned. */
function quarterTurn(orientationDegrees: number): number {
  const turns = Math.round((orientationDegrees - 90) / 90);
  return ((turns % 4) + 4) % 4;
}

export function FurnitureGlyph({
  symbol,
  box,
  orientationDegrees,
  className,
}: Props): ReactElement {
  const centreX = (box.minX + box.maxX) / 2;
  const centreY = (box.minY + box.maxY) / 2;
  const width = box.maxX - box.minX;
  const height = box.maxY - box.minY;

  if (orientationDegrees === undefined) {
    return (
      <use
        href={`#furn-${symbol}`}
        x={box.minX}
        y={box.minY}
        width={width}
        height={height}
        className={className}
        preserveAspectRatio="xMidYMid meet"
      />
    );
  }

  const turns = quarterTurn(orientationDegrees);
  // A quarter or three-quarter turn swaps which side of the footprint the glyph's own width runs
  // along, so the box it is drawn into before rotating is the transpose of the one on the canvas.
  const sideways = turns % 2 === 1;
  const drawWidth = sideways ? height : width;
  const drawHeight = sideways ? width : height;
  return (
    <g transform={`rotate(${String(turns * 90)} ${String(centreX)} ${String(centreY)})`}>
      <use
        href={`#furn-${symbol}`}
        x={centreX - drawWidth / 2}
        y={centreY - drawHeight / 2}
        width={drawWidth}
        height={drawHeight}
        className={className}
        preserveAspectRatio="none"
      />
    </g>
  );
}
