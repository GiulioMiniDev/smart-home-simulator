import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { HomeModel, ReplayEventWindow, ReplayFrame, ReplayVerification } from "../types";
import { buildScript, type SceneScript } from "./replay-script";

const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;
/** The clock ticks every animation frame; text only needs it often enough to read as live. */
const CLOCK_PUBLISH_MS = 80;
const SESSION_DEBOUNCE_MS = 600;
const DAY_LIMIT = 5_000;
/**
 * The families a scene is made of.
 *
 * Sensor readings are deliberately absent: a day of them is four thousand records that say the
 * same thing the person on screen is already saying, and the dataset is where they belong.
 */
const SCENE_KINDS = "activity,action,movement,state_transition";

/** Real time first. Anything faster is for crossing a quiet stretch, not for reading one. */
export const SCENE_SPEEDS = [1, 2, 5, 15, 60, 300];

/**
 * The offset the trace's own timestamps carry.
 *
 * A day in this simulation is a day in the flat, and the flat is somewhere with a wall clock.
 * Reading the instants as UTC put breakfast at five in the morning and started every day at
 * eleven the night before.
 *
 * It has to be read from something the trace wrote. A frame echoes back the instant it was
 * asked for, so its own `at` carries whatever zone the request used -- always UTC from here.
 */
export function zoneOffsetMs(isoTimestamp: string | null | undefined): number {
  const match = isoTimestamp ? /([+-])(\d{2}):(\d{2})$/.exec(isoTimestamp) : null;
  if (!match) return 0;
  return (match[1] === "-" ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3])) * 60_000;
}

/** Midnight of the local day an instant falls in, as an epoch instant. */
export function startOfDay(positionMs: number, offsetMs = 0): number {
  return Math.floor((positionMs + offsetMs) / MILLISECONDS_PER_DAY) * MILLISECONDS_PER_DAY - offsetMs;
}

/** The parts of the flat's wall clock at an instant. */
export function localParts(atMs: number, offsetMs: number): Date {
  return new Date(atMs + offsetMs);
}

const isAbort = (reason: unknown): boolean => reason instanceof DOMException && reason.name === "AbortError";

const apiError = (reason: unknown): ApiError => reason instanceof ApiError
  ? reason
  : new ApiError(reason instanceof Error ? reason.message : String(reason), 0);

export interface ReplaySceneController {
  status: "loading" | "verifying" | "ready" | "blocked";
  error?: ApiError;
  /** The instant on screen, republished often enough to read rather than every frame. */
  atMs: number;
  startMs?: number;
  endMs?: number;
  dayStartMs?: number;
  /** Minutes-of-offset the flat's clock runs at, already folded into `localParts`. */
  offsetMs: number;
  playing: boolean;
  speed: number;
  script: SceneScript;
  frame?: ReplayFrame;
  home?: HomeModel;
  loadingDay: boolean;
  play(): void;
  pause(): void;
  seek(atMs: number): void;
  setSpeed(speed: number): void;
  /** Jump past whatever is happening now: the rest of this activity, or on to the next. */
  skip(): void;
  stepDay(direction: -1 | 1): void;
  subscribeToClock(listener: (atMs: number) => void): () => void;
}

const EMPTY_SCRIPT: SceneScript = { activities: [], beats: [], movements: [], transitions: [], truncated: false };

interface ReplaySession {
  playable: boolean;
  positionAt?: string | null;
  filters?: { speed?: number };
}

export function useReplayScene(runId: string, home: HomeModel | undefined): ReplaySceneController {
  const [status, setStatus] = useState<"loading" | "verifying" | "ready" | "blocked">("loading");
  const [error, setError] = useState<ApiError>();
  const [atMs, setAtMs] = useState(0);
  const [range, setRange] = useState<{ start: number; end: number }>();
  const [dayStartMs, setDayStartMs] = useState<number>();
  const [offsetMs, setOffsetMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeedState] = useState(1);
  const [script, setScript] = useState<SceneScript>(EMPTY_SCRIPT);
  const [frame, setFrame] = useState<ReplayFrame>();
  const [loadingDay, setLoadingDay] = useState(false);

  const atRef = useRef(0);
  const offsetRef = useRef(0);
  const rangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const listeners = useRef(new Set<(atMs: number) => void>());
  const lastPublish = useRef(0);
  const dayAbort = useRef<AbortController | undefined>(undefined);
  const saveTimer = useRef<number | undefined>(undefined);
  const restored = useRef(false);

  const publish = useCallback((next: number, toReact = true) => {
    atRef.current = next;
    listeners.current.forEach((listener) => { listener(next); });
    if (toReact) setAtMs(next);
  }, []);

  const subscribeToClock = useCallback((listener: (atMs: number) => void) => {
    listeners.current.add(listener);
    listener(atRef.current);
    return () => { listeners.current.delete(listener); };
  }, []);

  // --- the run: verified once, then its bounds decide where the clock may stand ------------
  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading"); setError(undefined); setScript(EMPTY_SCRIPT); setFrame(undefined);
    setPlaying(false); restored.current = false;
    void (async () => {
      try {
        const session = await api<ReplaySession>(`/runs/${encodeURIComponent(runId)}/replay/session`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        // A session is playable when the digest it was verified against is still the trace's
        // own. Verifying again means re-executing the whole simulation -- five minutes for a
        // year of it -- to reach an answer the workspace has already recorded.
        if (!session.playable) {
          setStatus("verifying");
          const verification = await api<ReplayVerification>(`/runs/${encodeURIComponent(runId)}/replay/verify`, { method: "POST", signal: controller.signal });
          if (controller.signal.aborted) return;
          if (!verification.matches) {
            setError(new ApiError("This run's replay no longer matches the trace it was published from.", 0, "REPLAY_DIGEST_MISMATCH"));
            setStatus("blocked");
            return;
          }
        }
        const anchor = await api<ReplayFrame>(`/runs/${encodeURIComponent(runId)}/replay/frame?at=${encodeURIComponent(new Date(0).toISOString())}&include_oracle=true`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        const start = Date.parse(anchor.traceStart);
        const end = Date.parse(anchor.traceEnd);
        const saved = session.positionAt ? Date.parse(session.positionAt) : Number.NaN;
        const at = Number.isFinite(saved) ? Math.min(end, Math.max(start, saved)) : start;
        const offset = zoneOffsetMs(anchor.traceStart);
        rangeRef.current = { start, end };
        offsetRef.current = offset;
        setRange({ start, end });
        setOffsetMs(offset);
        setSpeedState(SCENE_SPEEDS.includes(session.filters?.speed ?? 1) ? session.filters?.speed ?? 1 : 1);
        publish(at);
        setDayStartMs(startOfDay(at, offset));
        restored.current = true;
        setStatus("ready");
      } catch (reason) {
        if (controller.signal.aborted || isAbort(reason)) return;
        setError(apiError(reason));
        setStatus("blocked");
      }
    })();
    return () => { controller.abort(); };
  }, [publish, runId]);

  // --- one day, fetched once: after this the scene runs entirely from the browser ----------
  useEffect(() => {
    if (status !== "ready" || dayStartMs === undefined) return;
    const controller = new AbortController();
    dayAbort.current?.abort(); dayAbort.current = controller;
    setLoadingDay(true);
    const dayEnd = dayStartMs + MILLISECONDS_PER_DAY;
    const parameters = new URLSearchParams({
      start: new Date(dayStartMs).toISOString(),
      end: new Date(dayEnd).toISOString(),
      kinds: SCENE_KINDS,
      limit: String(DAY_LIMIT),
      include_oracle: "true",
    });
    void Promise.all([
      api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?${parameters.toString()}`, { signal: controller.signal }),
      api<ReplayFrame>(`/runs/${encodeURIComponent(runId)}/replay/frame?at=${encodeURIComponent(new Date(dayStartMs).toISOString())}&include_oracle=true`, { signal: controller.signal }),
    ])
      .then(([window, anchor]) => {
        if (controller.signal.aborted) return;
        setScript(buildScript(window, home));
        setFrame(anchor);
        // Daylight saving moves the flat's clock during a long run, and the events of the day
        // are the only things on hand that were written in it.
        offsetRef.current = zoneOffsetMs(window.items[0]?.at ?? anchor.traceStart);
        setOffsetMs(offsetRef.current);
        setLoadingDay(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || isAbort(reason)) return;
        setLoadingDay(false);
        setError(apiError(reason));
        setStatus("blocked");
      });
    return () => { controller.abort(); };
  }, [dayStartMs, home, runId, status]);

  // --- the clock ---------------------------------------------------------------------------
  useEffect(() => {
    if (!playing || status !== "ready") return;
    let animationFrame: number | undefined;
    let previous: number | undefined;
    const tick = () => {
      const now = performance.now();
      const bounds = rangeRef.current;
      if (previous !== undefined && bounds) {
        const next = Math.min(bounds.end, atRef.current + (now - previous) * speed);
        const terminal = next >= bounds.end;
        const toReact = terminal || now - lastPublish.current >= CLOCK_PUBLISH_MS;
        if (toReact) lastPublish.current = now;
        publish(next, toReact);
        const day = startOfDay(next, offsetRef.current);
        if (day !== dayStartMs) setDayStartMs(day);
        if (terminal) { setPlaying(false); return; }
      }
      previous = now;
      animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);
    return () => { if (animationFrame !== undefined) cancelAnimationFrame(animationFrame); };
  }, [dayStartMs, playing, publish, speed, status]);

  // --- where the viewer left off ------------------------------------------------------------
  useEffect(() => {
    if (status !== "ready" || !restored.current) return;
    if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current);
    const timer = window.setTimeout(() => {
      void api(`/runs/${encodeURIComponent(runId)}/replay/session`, {
        method: "PUT",
        body: JSON.stringify({ positionAt: new Date(Math.round(atMs)).toISOString(), filters: { speed } }),
      }).catch(() => undefined);
    }, SESSION_DEBOUNCE_MS);
    saveTimer.current = timer;
    return () => { window.clearTimeout(timer); };
  }, [atMs, runId, speed, status]);

  const seek = useCallback((next: number) => {
    const bounds = rangeRef.current;
    const clamped = bounds ? Math.min(bounds.end, Math.max(bounds.start, next)) : next;
    setPlaying(false);
    publish(clamped);
    setDayStartMs(startOfDay(clamped, offsetRef.current));
  }, [publish]);

  const skip = useCallback(() => {
    const at = atRef.current;
    const running = script.activities.find((activity) => activity.startMs <= at && at < activity.endMs);
    const upcoming = script.activities.find((activity) => activity.startMs > at);
    // Past the end of what is happening, or on to the next thing, or simply an hour on when a
    // day has nothing else to show.
    const target = running ? running.endMs : upcoming ? upcoming.startMs : at + 60 * 60 * 1000;
    const bounds = rangeRef.current;
    const clamped = bounds ? Math.min(bounds.end, Math.max(bounds.start, target)) : target;
    publish(clamped);
    const day = startOfDay(clamped, offsetRef.current);
    if (day !== dayStartMs) setDayStartMs(day);
  }, [dayStartMs, publish, script.activities]);

  const stepDay = useCallback((direction: -1 | 1) => {
    const at = atRef.current;
    const day = startOfDay(at, offsetRef.current);
    seek(direction === 1 ? day + MILLISECONDS_PER_DAY : at - day > 1_000 ? day : day - MILLISECONDS_PER_DAY);
  }, [seek]);

  return {
    status,
    error,
    atMs,
    startMs: range?.start,
    endMs: range?.end,
    dayStartMs,
    offsetMs,
    playing,
    speed,
    script,
    frame,
    home,
    loadingDay,
    play: useCallback(() => { setPlaying(true); }, []),
    pause: useCallback(() => { setPlaying(false); }, []),
    seek,
    setSpeed: useCallback((next: number) => { setSpeedState(next); }, []),
    skip,
    stepDay,
    subscribeToClock,
  };
}
