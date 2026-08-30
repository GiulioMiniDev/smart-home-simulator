/**
 * Furniture drawings that came from the workspace's vocabulary rather than from this build.
 *
 * The bundled glyphs are React components, so a researcher who adds a kind of furniture cannot add
 * a drawing for it without a frontend release — and until they do, their new object is a dashed box
 * on the plan and in the replay. The pack carries an SVG body per type for exactly that case; this
 * module is what makes it reach the two places that draw.
 *
 * A module-level registry rather than a context: `PlanCanvas` and `SceneStage` resolve a glyph deep
 * inside a memoised layout computation, and threading a provider through both would be a much
 * larger change than the feature is worth. It is loaded once, at startup, by `useCustomSymbols`.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type { VocabularyView } from "./types";

let registry: Record<string, string> = {};
/**
 * What the workspace says each kind of furniture is for.
 *
 * Loaded from the same request as the drawings, because it answers the other half of the same
 * question: adding a wardrobe to a plan means giving it a footprint *and* saying what a wardrobe
 * does, and inventing the second half in the editor would be inventing vocabulary.
 */
let declared: Record<string, { capabilities: string[]; roleAliases: string[]; displayName: string }> = {};
const listeners = new Set<() => void>();

export function setCustomSymbols(bodies: Record<string, string>): void {
  registry = bodies;
  for (const listener of listeners) listener();
}

export function customSymbols(): Record<string, string> {
  return registry;
}

export function declaredEntityTypes(): Record<
  string,
  { capabilities: string[]; roleAliases: string[]; displayName: string }
> {
  return declared;
}

export function setDeclaredEntityTypes(
  types: Record<string, { capabilities: string[]; roleAliases: string[]; displayName: string }>,
): void {
  declared = types;
  for (const listener of listeners) listener();
}

/** The symbol id for a type the pack draws, or `undefined` if the bundled glyphs must answer. */
export function customSymbolId(entityType: string | undefined): string | undefined {
  if (!entityType) return undefined;
  return registry[entityType] ? `custom-${entityType}` : undefined;
}

/** Re-render whatever is drawing the pack's symbols when the pack changes under it. */
export function useCustomSymbolRevision(): number {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const listener = () => setRevision((value) => value + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return revision;
}

/**
 * Load the workspace's furniture drawings once, at startup.
 *
 * Failure is silent on purpose: a plan that draws a box where it could have drawn a bookcase is a
 * far smaller problem than an error banner on every page because one optional request did not
 * answer.
 */
export function useCustomSymbols(): void {
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const view = await api<VocabularyView>("/vocabulary");
        if (cancelled) return;
        setCustomSymbols(
          Object.fromEntries(
            view.pack.entityTypes
              .filter((item) => item.symbolBody)
              .map((item) => [item.entityType, item.symbolBody as string]),
          ),
        );
        setDeclaredEntityTypes(
          Object.fromEntries(
            view.pack.entityTypes.map((item) => [item.entityType, {
              capabilities: item.capabilities,
              roleAliases: item.roleAliases,
              displayName: item.displayName,
            }]),
          ),
        );
      } catch {
        // Keep whatever is already registered, which at startup is nothing.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
}
