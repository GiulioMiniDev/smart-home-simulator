import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useResource } from "../hooks";
import type { HomeModel, SensorModel } from "../types";
import { replayTimestamp } from "./replay-positioning";
import { scenePlace } from "./replay-place";
import { activityAt, beatsUpTo, residentName, type SceneActivity } from "./replay-script";
import { foldWorld } from "./replay-world";
import { sceneMotion } from "./scene-motion";
import { SceneStage } from "./SceneStage";
import { localParts, SCENE_SPEEDS, useReplayScene, type ReplaySceneController } from "./useReplayScene";

const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;
const HISTORY = 4;
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

type ReplayModels = { homeModel?: HomeModel; sensorModel?: SensorModel };

function two(value: number): string {
  return String(value).padStart(2, "0");
}

function clockText(atMs: number, offsetMs: number): string {
  const local = localParts(atMs, offsetMs);
  return `${two(local.getUTCHours())}:${two(local.getUTCMinutes())}:${two(local.getUTCSeconds())}`;
}

function dayText(atMs: number, offsetMs: number): string {
  const local = localParts(atMs, offsetMs);
  return `${WEEKDAYS[local.getUTCDay()] ?? ""} ${String(local.getUTCDate())} ${MONTHS[local.getUTCMonth()] ?? ""}`;
}

function shortClock(atMs: number, offsetMs: number): string {
  const local = localParts(atMs, offsetMs);
  return `${two(local.getUTCHours())}:${two(local.getUTCMinutes())}`;
}

/**
 * The clock, redrawn every animation frame without redrawing the page around it.
 *
 * At real time the seconds are the thing that says the replay is running at all, and they are
 * the only text on screen that has to keep up with the scene.
 */
function SceneClock({ controller }: { controller: ReplaySceneController }) {
  const label = useRef<HTMLSpanElement | null>(null);
  const offset = useRef(controller.offsetMs);
  const last = useRef(controller.atMs);
  offset.current = controller.offsetMs;
  const write = useCallback((atMs: number) => {
    if (label.current) label.current.textContent = clockText(atMs, offset.current);
  }, []);
  const subscribe = controller.subscribeToClock;
  useEffect(() => subscribe((atMs) => { last.current = atMs; write(atMs); }), [subscribe, write]);
  useLayoutEffect(() => { write(last.current); });
  return <span className="scene-clock" ref={label} aria-live="off">{clockText(controller.atMs, controller.offsetMs)}</span>;
}

/** The whole day as one bar: where the resident is in it, and what is left to watch. */
function DayRibbon({ controller }: { controller: ReplaySceneController }) {
  const { dayStartMs, offsetMs, script } = controller;
  const playhead = useRef<HTMLDivElement | null>(null);
  const day = useRef(dayStartMs);
  day.current = dayStartMs;
  const place = useCallback((atMs: number) => {
    if (!playhead.current || day.current === undefined) return;
    const fraction = Math.min(1, Math.max(0, (atMs - day.current) / MILLISECONDS_PER_DAY));
    playhead.current.style.setProperty("--scene-playhead", String(fraction));
  }, []);
  const subscribe = controller.subscribeToClock;
  useEffect(() => subscribe(place), [place, subscribe]);
  useLayoutEffect(() => { place(controller.atMs); });

  if (dayStartMs === undefined) return null;
  const blocks = script.activities.map((activity, index) => {
    // A block may never reach into the next one's time. On a narrow screen a seven-minute
    // activity is a pixel and a half wide, and a minimum width wide enough to see was enough
    // to cover its neighbour and swallow the tap meant for it.
    const next = script.activities[index + 1];
    const gap = next ? (next.startMs - activity.startMs) / MILLISECONDS_PER_DAY : 1;
    return {
      activity,
      left: Math.max(0, (activity.startMs - dayStartMs) / MILLISECONDS_PER_DAY),
      width: Math.max(0, Math.min(gap, (activity.endMs - activity.startMs) / MILLISECONDS_PER_DAY)),
    };
  });
  const seekToPointer = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    controller.seek(dayStartMs + ((event.clientX - box.left) / box.width) * MILLISECONDS_PER_DAY);
  };
  return (
    <div className="scene-ribbon" aria-label={`The day, ${String(script.activities.length)} activities`}>
      {/* The bar itself is the coarse way through the day; the blocks on it are the precise one. */}
      <div className="scene-ribbon-track" onClick={seekToPointer}>
        {blocks.map(({ activity, left, width }) => (
          <button
            key={activity.eventId}
            type="button"
            className={activity.deviated ? "scene-block is-deviated" : "scene-block"}
            style={{ insetInlineStart: `${String(left * 100)}%`, inlineSize: `${String(width * 100)}%` }}
            title={`${shortClock(activity.startMs, offsetMs)} ${activity.title}`}
            aria-label={`${shortClock(activity.startMs, offsetMs)}, ${activity.title}`}
            onClick={(event) => { event.stopPropagation(); controller.seek(activity.startMs); }}
          />
        ))}
        <div className="scene-ribbon-playhead" ref={playhead} aria-hidden="true" />
      </div>
      <div className="scene-ribbon-hours" aria-hidden="true">
        {[0, 6, 12, 18].map((hour) => <span key={hour} style={{ insetInlineStart: `${String((hour / 24) * 100)}%` }}>{two(hour)}</span>)}
      </div>
    </div>
  );
}

function headline(activity: SceneActivity | undefined, name: string, atMs: number): string {
  if (!activity) return `${name} has nothing planned right now`;
  // The trace calls this field an intent, so saying it as a wish is the plainest reading of it.
  return atMs - activity.startMs < 6_000 ? `${name} ${activity.wish}` : `${name} is ${activity.title}`;
}

export function ReplayScene({ runId }: { runId: string }) {
  const models = useResource<ReplayModels>(`/runs/${encodeURIComponent(runId)}/models`);
  const controller = useReplayScene(runId, models.data?.homeModel);
  const { atMs, offsetMs, script } = controller;

  const place = useMemo(() => scenePlace(models.data?.homeModel), [models.data?.homeModel]);
  const world = useMemo(
    () => foldWorld(script, controller.frame, atMs, place),
    [atMs, controller.frame, place, script],
  );
  const anchorMs = replayTimestamp(controller.frame?.at);
  const motion = useMemo(
    () => sceneMotion(world, anchorMs, controller.subscribeToClock, place.inside),
    [anchorMs, controller.subscribeToClock, place, world],
  );

  const resident = world.residents[0];
  const name = resident?.name ?? residentName(script.activities[0]?.actorId);
  const activity = activityAt(script, atMs, resident?.residentId);
  const beats = beatsUpTo(script, atMs, HISTORY);
  const latest = beats.at(-1);
  const earlier = beats.slice(0, -1).reverse();

  if (controller.status === "blocked") {
    return <section className="scene-page">
      <p className="scene-blocked" role="alert">{controller.error?.message ?? "This replay cannot be shown."}</p>
    </section>;
  }

  return (
    <section className="scene-page" data-status={controller.status}>
      <div className="scene-viewport">
        <SceneStage
          home={models.data?.homeModel}
          world={world}
          motion={motion}
          activeRegionId={resident?.away ? undefined : resident?.regionId}
          usingEntityId={resident?.using?.entityId}
        />
        {resident?.away && <p className="scene-away" role="status">
          {name} is out{resident.regionId ? ` — ${resident.regionId.replaceAll("_", " ")}` : ""}
        </p>}
        {controller.status === "loading" && <p className="scene-loading" role="status">Setting the scene…</p>}
        {controller.status === "verifying" && <p className="scene-loading" role="status">
          Checking this run against the trace it was published from. This happens once per run, and a
          long one takes a few minutes.
        </p>}
        {controller.loadingDay && controller.status === "ready" && <p className="scene-loading is-quiet" role="status">Loading this day…</p>}
      </div>

      <section className="scene-caption" aria-live="polite" aria-atomic="true">
        <p className="scene-when">
          <SceneClock controller={controller} />
          <span className="scene-date">{dayText(atMs, offsetMs)}</span>
          {resident?.regionId && <span className="scene-where">
            {resident.away ? "away · " : "in the "}{resident.regionId.replaceAll("_", " ")}
            {resident.using ? ` · at the ${resident.using.label}` : ""}
          </span>}
        </p>
        <h2 className="scene-headline">{headline(activity, name, atMs)}</h2>
        <p className="scene-beat">{latest?.text ?? "Nothing has happened yet today"}</p>
        <ol className="scene-history">
          {earlier.map((beat) => <li key={`${String(beat.atMs)}-${beat.text}`}>
            <time>{shortClock(beat.atMs, offsetMs)}</time> {beat.text}
          </li>)}
        </ol>
        {resident && resident.carrying.length > 0 && <p className="scene-holding">
          Carrying {resident.carrying.map((item) => item.replaceAll("_", " ")).join(", ")}
        </p>}
      </section>

      <DayRibbon controller={controller} />

      <section className="scene-transport" aria-label="Replay controls">
        <button type="button" className="scene-key" aria-label="Previous day" onClick={() => { controller.stepDay(-1); }}>◀</button>
        <button
          type="button"
          className="scene-play"
          disabled={controller.status !== "ready"}
          onClick={() => { if (controller.playing) controller.pause(); else controller.play(); }}
        >{controller.playing ? "Pause" : "Play"}</button>
        <button
          type="button"
          className="scene-key"
          disabled={controller.status !== "ready"}
          onClick={() => { controller.skip(); }}
        >Skip ahead</button>
        <label className="scene-speed">Speed
          <select
            aria-label="Playback speed"
            value={controller.speed}
            onChange={(event) => { controller.setSpeed(Number(event.target.value)); }}
          >
            {SCENE_SPEEDS.map((speed) => <option key={speed} value={speed}>{speed === 1 ? "Real time" : `${String(speed)}×`}</option>)}
          </select>
        </label>
        <input
          className="scene-scrub"
          type="range"
          aria-label="Replay time"
          min={controller.startMs ?? 0}
          max={controller.endMs ?? 1}
          value={Math.round(atMs)}
          disabled={controller.startMs === undefined}
          onChange={(event) => { controller.seek(Number(event.target.value)); }}
        />
        <button type="button" className="scene-key" aria-label="Next day" onClick={() => { controller.stepDay(1); }}>▶</button>
      </section>

      {script.truncated && <p className="scene-notice" role="status">
        This day holds more evidence than the scene can carry; the later part of it is not shown.
      </p>}
      {models.error && <p className="scene-blocked" role="alert">The home for this run is unavailable: {models.error.message}</p>}
    </section>
  );
}
