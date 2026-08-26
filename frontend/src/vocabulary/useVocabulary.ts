/**
 * The editing session: one pack, held locally, saved on its own.
 *
 * The researcher never presses save. That is a deliberate choice and it costs something — a
 * mistake is persisted as readily as a correction — so two things pay for it: every edit is
 * undoable while the tab is open, and the whole vocabulary can be reset to the one the simulator
 * ships with.
 *
 * Saving carries the digest the editor last saw. A second tab, or a colleague on the same
 * workspace, will make the server refuse rather than let one window silently overwrite the other's
 * work.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { drawableEntityTypes } from "../furniture";
import type { VocabularyPack, VocabularyReview, VocabularyView } from "./types";

/** Long enough that typing a word is one save, short enough to feel immediate. */
const SAVE_DEBOUNCE_MS = 700;
// The findings should feel like they answer the edit, so they are reviewed sooner than the pack
// is saved — but still on a pause, not on a keystroke. Undebounced, renaming an activity posted
// the whole 120 kB pack ten times for a ten-letter word.
const REVIEW_DEBOUNCE_MS = 350;
/** How many steps back the tab remembers. Bounded so a long session does not hold every pack. */
const UNDO_DEPTH = 40;

export type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; at: number }
  | { status: "conflict"; message: string }
  | { status: "error"; message: string };

export interface VocabularySession {
  pack?: VocabularyPack;
  customised: boolean;
  labelSpaceDigest?: string;
  /** The label space as it was when this session opened — compared to spot a ground-truth change. */
  openedLabelSpaceDigest?: string;
  review?: VocabularyReview;
  loading: boolean;
  error?: ApiError;
  save: SaveState;
  canUndo: boolean;
  edit: (next: VocabularyPack) => void;
  undo: () => void;
  reset: () => Promise<void>;
  reload: () => Promise<void>;
}

export function useVocabulary(): VocabularySession {
  const [pack, setPack] = useState<VocabularyPack | undefined>(undefined);
  const [customised, setCustomised] = useState(false);
  const [labelSpaceDigest, setLabelSpaceDigest] = useState<string | undefined>(undefined);
  const [openedLabelSpaceDigest, setOpened] = useState<string | undefined>(undefined);
  const [review, setReview] = useState<VocabularyReview | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const [undoDepth, setUndoDepth] = useState(0);

  // Not state: changing them must not re-render, and the save timer reads the latest without
  // being re-created on every keystroke.
  const serverDigest = useRef<string | undefined>(undefined);
  const history = useRef<VocabularyPack[]>([]);
  const pending = useRef<number | undefined>(undefined);
  const inFlight = useRef(false);
  const reviewGeneration = useRef(0);

  const adopt = useCallback((view: VocabularyView, opening: boolean) => {
    setPack(view.pack);
    setCustomised(view.customised);
    setLabelSpaceDigest(view.labelSpaceDigest);
    if (opening) setOpened(view.labelSpaceDigest);
    serverDigest.current = view.digest;
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      adopt(await api<VocabularyView>("/vocabulary"), true);
      setError(undefined);
      history.current = [];
      setUndoDepth(0);
      setSave({ status: "idle" });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError(String(reason), 0));
    } finally {
      setLoading(false);
    }
  }, [adopt]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Ask the server what will fail quietly in this pack, without storing it. */
  const runReview = useCallback(async (candidate: VocabularyPack) => {
    const generation = ++reviewGeneration.current;
    try {
      const result = await api<VocabularyReview>("/vocabulary/review", {
        method: "POST",
        body: JSON.stringify({ pack: candidate, drawable_types: drawableEntityTypes() }),
      });
      // A slower review of an older pack must not overwrite a newer one's findings, which would
      // leave the list describing a vocabulary that no longer exists.
      if (generation === reviewGeneration.current) setReview(result);
    } catch {
      // A review that cannot be fetched is not worth interrupting the editor for: the findings are
      // advisory, and the save reports anything that actually blocks.
      if (generation === reviewGeneration.current) setReview(undefined);
    }
  }, []);

  useEffect(() => {
    if (!pack) return undefined;
    const timer = window.setTimeout(() => void runReview(pack), REVIEW_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
    // Only when the pack's content changes, not on every render of a parent.
  }, [pack, runReview]);

  const persist = useCallback(async (candidate: VocabularyPack) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSave({ status: "saving" });
    try {
      const view = await api<VocabularyView>("/vocabulary", {
        method: "PUT",
        body: JSON.stringify({ pack: candidate, expected_digest: serverDigest.current }),
      });
      serverDigest.current = view.digest;
      setCustomised(view.customised);
      setLabelSpaceDigest(view.labelSpaceDigest);
      setSave({ status: "saved", at: Date.now() });
    } catch (reason) {
      const failure = reason instanceof ApiError ? reason : new ApiError(String(reason), 0);
      setSave(
        failure.code === "VOCABULARY_CHANGED_ELSEWHERE"
          ? { status: "conflict", message: failure.message }
          : { status: "error", message: failure.message },
      );
    } finally {
      inFlight.current = false;
    }
  }, []);

  const edit = useCallback(
    (next: VocabularyPack) => {
      setPack((current) => {
        if (current) {
          history.current = [...history.current, current].slice(-UNDO_DEPTH);
          setUndoDepth(history.current.length);
        }
        return next;
      });
      window.clearTimeout(pending.current);
      pending.current = window.setTimeout(() => void persist(next), SAVE_DEBOUNCE_MS);
    },
    [persist],
  );

  const undo = useCallback(() => {
    const previous = history.current.pop();
    setUndoDepth(history.current.length);
    if (!previous) return;
    setPack(previous);
    window.clearTimeout(pending.current);
    pending.current = window.setTimeout(() => void persist(previous), SAVE_DEBOUNCE_MS);
  }, [persist]);

  const reset = useCallback(async () => {
    window.clearTimeout(pending.current);
    setSave({ status: "saving" });
    try {
      adopt(await api<VocabularyView>("/vocabulary", { method: "DELETE" }), false);
      history.current = [];
      setUndoDepth(0);
      setSave({ status: "saved", at: Date.now() });
    } catch (reason) {
      const failure = reason instanceof ApiError ? reason : new ApiError(String(reason), 0);
      setSave({ status: "error", message: failure.message });
    }
  }, [adopt]);

  // A pending save must still land if the researcher navigates away mid-debounce.
  useEffect(() => () => window.clearTimeout(pending.current), []);

  return {
    pack,
    customised,
    labelSpaceDigest,
    openedLabelSpaceDigest,
    review,
    loading,
    error,
    save,
    canUndo: undoDepth > 0,
    edit,
    undo,
    reset,
    reload,
  };
}
