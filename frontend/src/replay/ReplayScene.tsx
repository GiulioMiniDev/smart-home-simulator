import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useResource } from "../hooks";
import type { HomeModel, SensorModel } from "../types";
import { activitiesOf, beatsFor, castOf, houseBeats, type CastMember } from "./replay-cast";
import { replayTimestamp } from "./replay-positioning";
import { scenePlace } from "./replay-place";
import { activityAt, beatsUpTo, residentName, type SceneActivity } from "./replay-script";
import { foldWorld, type WorldResident } from "./replay-world";
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

/**
 * One track of the day: a row of activity blocks under a moving playhead.
 *
 * The playhead is written straight to the DOM from the clock, like the clock's own text, so a
 * household of several tracks costs no re-render per frame.
 */
function RibbonTrack({ controller, activities, label, tone }: {
  controller: ReplaySceneController;
  activities: readonly SceneActivity[];
  label: string;
  tone?: number;
}) {
  const { dayStartMs, offsetMs } = controller;
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
  const blocks = activities.map((activity, index) => {
    // A block may never reach into the next one's time. On a narrow screen a seven-minute
    // activity is a pixel and a half wide, and a minimum width wide enough to see was enough
    // to cover its neighbour and swallow the tap meant for it.
    const next = activities[index + 1];
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
    // The bar itself is the coarse way through the day; the blocks on it are the precise one.
    <div className={tone === undefined ? "scene-ribbon-track" : `scene-ribbon-track scene-tone-${String(tone)}`} onClick={seekToPointer} aria-label={label}>
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
  );
}

function RibbonHours() {
  return (
    <div className="scene-ribbon-hours" aria-hidden="true">
      {[0, 6, 12, 18].map((hour) => <span key={hour} style={{ insetInlineStart: `${String((hour / 24) * 100)}%` }}>{two(hour)}</span>)}
    </div>
  );
}

/**
 * The whole day: one bar for one resident, one lane each for a household.
 *
 * With two people on one bar their activities lay over each other, and "skip ahead" landed on
 * whichever boundary came first — usually the other person's. Each lane has its own skip, which
 * moves the one shared clock past *that* resident's activity: time still passes for everyone.
 */
function DayRibbon({ controller, cast }: { controller: ReplaySceneController; cast: readonly CastMember[] }) {
  const { dayStartMs, script } = controller;
  if (dayStartMs === undefined) return null;
  const household = cast.length > 1;
  return (
    <div className={household ? "scene-ribbon is-household" : "scene-ribbon"} aria-label={`The day, ${String(script.activities.length)} activities`}>
      {household ? cast.map((member) => {
        const activities = activitiesOf(script, member.residentId);
        return (
          <div className="scene-lane" key={member.residentId}>
            <span className={`scene-lane-name scene-tone-${String(member.tone)}`}><i aria-hidden="true" />{member.name}</span>
            <RibbonTrack controller={controller} activities={activities} tone={member.tone} label={`${member.name}'s day, ${String(activities.length)} activities`} />
            <button
              type="button"
              className="scene-lane-skip"
              disabled={controller.status !== "ready"}
              aria-label={`Skip ahead for ${member.name}`}
              title={`Past ${member.name}'s current activity, or on to their next one`}
              onClick={() => { controller.skip(member.residentId); }}
            >Skip ▸</button>
          </div>
        );
      }) : <RibbonTrack controller={controller} activities={script.activities} label="The day" />}
      <div className={household ? "scene-lane is-hours" : undefined}>
        {household && <span />}
        <RibbonHours />
        {household && <span />}
      </div>
    </div>
  );
}

function headline(activity: SceneActivity | undefined, name: string, atMs: number): string {
  if (!activity) return `${name} has nothing planned right now`;
  // The trace calls this field an intent, so saying it as a wish is the plainest reading of it.
  return atMs - activity.startMs < 6_000 ? `${name} ${activity.wish}` : `${name} is ${activity.title}`;
}

function whereText(resident: WorldResident | undefined): string | undefined {
  if (!resident?.regionId) return undefined;
  const room = resident.regionId.replaceAll("_", " ");
  return `${resident.away ? "away · " : "in the "}${room}${resident.using ? ` · at the ${resident.using.label}` : ""}`;
}

/**
 * One resident's side of the moment: where they are, what they are doing, and what they just did.
 *
 * A single caption for a household named only whoever was listed first and interleaved both
 * people's last few actions into one list, so "Giulia is preparing lunch" sat above "Paolo wants
 * to prepare breakfast" with nothing to say the two lines were about different people.
 */
function ResidentCard({ member, resident, controller, household, beats: told }: {
  member: CastMember;
  resident: WorldResident | undefined;
  controller: ReplaySceneController;
  household: boolean;
  /** What to list instead of this resident's own beats: one resident keeps the whole day's. */
  beats?: ReturnType<typeof beatsUpTo>;
}) {
  const { atMs, offsetMs, script } = controller;
  const activity = activityAt(script, atMs, member.residentId);
  const beats = told ?? beatsFor(script, atMs, member.residentId, HISTORY);
  const latest = beats.at(-1);
  const earlier = beats.slice(0, -1).reverse();
  const where = whereText(resident);
  return (
    <article className={`scene-person-card scene-tone-${String(member.tone)}`} aria-label={member.name}>
      {household && <p className="scene-person-name"><i aria-hidden="true" />{member.name}</p>}
      {where && <p className="scene-where">{where}</p>}
      <h2 className="scene-headline">{headline(activity, member.name, atMs)}</h2>
      <p className="scene-beat">{latest?.text ?? (household ? `Nothing from ${member.name} yet today` : "Nothing has happened yet today")}</p>
      <ol className="scene-history">
        {earlier.map((beat) => <li key={`${String(beat.atMs)}-${beat.text}`}>
          <time>{shortClock(beat.atMs, offsetMs)}</time> {beat.text}
        </li>)}
      </ol>
      {resident && resident.carrying.length > 0 && <p className="scene-holding">
        Carrying {resident.carrying.map((item) => item.replaceAll("_", " ")).join(", ")}
      </p>}
    </article>
  );
}

/** The stretch the scrubber covers: the day on screen, not the whole horizon.
 *
 * Spanning the run put a month behind one slider, where a pixel was a quarter of an hour and
 * nothing could be reached on purpose. The days are stepped with the arrows either side of it, so
 * the slider is free to be what it is useful as — a way of moving inside the day you are watching.
 * It is clipped to the run at both ends, so the first and last days do not offer hours that are
 * not there. */
function dayBounds(controller: ReplaySceneController): { min: number; max: number } {
  const { startMs, endMs, dayStartMs } = controller;
  if (startMs === undefined || endMs === undefined) return { min: 0, max: 1 };
  if (dayStartMs === undefined) return { min: startMs, max: endMs };
  return {
    min: Math.max(startMs, dayStartMs),
    max: Math.min(endMs, dayStartMs + MILLISECONDS_PER_DAY),
  };
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
    () => sceneMotion(world, anchorMs, controller.subscribeToClock, place),
    [anchorMs, controller.subscribeToClock, place, world],
  );

  const cast = useMemo(() => {
    const members = castOf(world.residents, script.activities);
    return members.length ? members : [{ residentId: script.activities[0]?.actorId ?? "resident", name: residentName(script.activities[0]?.actorId), tone: 0 }];
  }, [script.activities, world.residents]);
  const household = cast.length > 1;
  const byId = new Map(world.residents.map((resident) => [resident.residentId, resident]));
  const away = world.residents.filter((resident) => resident.away);
  // Doors and appliances name no one, so in a household they are said once, for the flat.
  const house = household ? houseBeats(script, atMs, 1).at(-1) : undefined;
  // One resident keeps the one list of everything, the fridge included, as it always had.
  const single = household ? undefined : beatsUpTo(script, atMs, HISTORY);

  if (controller.status === "blocked") {
    return <section className="scene-page">
      <p className="scene-blocked" role="alert">{controller.error?.message ?? "This replay cannot be shown."}</p>
    </section>;
  }

  return (
    <section className="scene-page" data-status={controller.status}>
      {/* The picture and what is said about it sit side by side where the screen is wide enough, so
          the whole moment — the flat, each resident's card and the day below — fits without scrolling. */}
      <div className={household ? "scene-main is-household" : "scene-main"}>
      <div className="scene-viewport">
        <SceneStage
          home={models.data?.homeModel}
          world={world}
          motion={motion}
          activeRegionIds={world.residents.flatMap((resident) => !resident.away && resident.regionId ? [resident.regionId] : [])}
          usingEntityIds={world.residents.flatMap((resident) => resident.using?.entityId ? [resident.using.entityId] : [])}
        />
        {away.length > 0 && <p className="scene-away" role="status">
          {away.map((resident) => `${resident.name} is out${resident.regionId ? ` — ${resident.regionId.replaceAll("_", " ")}` : ""}`).join(" · ")}
        </p>}
        {controller.status === "loading" && <p className="scene-loading" role="status">Setting the scene…</p>}
        {controller.status === "verifying" && <p className="scene-loading" role="status">
          Checking this run against the trace it was published from. This happens once per run, and a
          long one takes a few minutes.
        </p>}
        {controller.loadingDay && controller.status === "ready" && <p className="scene-loading is-quiet" role="status">Loading this day…</p>}
      </div>

      <section className={household ? "scene-caption is-household" : "scene-caption"} aria-live="polite" aria-atomic="true">
        <p className="scene-when">
          <SceneClock controller={controller} />
          <span className="scene-date">{dayText(atMs, offsetMs)}</span>
        </p>
        {household ? (
          <div className="scene-cast">
            {cast.map((member) => <ResidentCard key={member.residentId} member={member} resident={byId.get(member.residentId)} controller={controller} household />)}
          </div>
        ) : (
          <ResidentCard member={cast[0]!} resident={byId.get(cast[0]!.residentId) ?? world.residents[0]} controller={controller} household={false} beats={single} />
        )}
        {house && <p className="scene-house"><span>In the flat</span> <time>{shortClock(house.atMs, offsetMs)}</time> {house.text}</p>}
      </section>
      </div>

      <DayRibbon controller={controller} cast={cast} />

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
          aria-label="Back 15 seconds"
          disabled={controller.status !== "ready"}
          onClick={() => { controller.nudge(-1); }}
        >−15s</button>
        <button
          type="button"
          className="scene-key"
          aria-label="Forward 15 seconds, stopping before a walk"
          disabled={controller.status !== "ready"}
          onClick={() => { controller.nudge(1); }}
        >+15s</button>
        {/* A household skips from each resident's own lane, where it is clear whose activity it passes. */}
        {!household && <button
          type="button"
          className="scene-key"
          disabled={controller.status !== "ready"}
          onClick={() => { controller.skip(); }}
        >Skip ahead</button>}
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
          {...dayBounds(controller)}
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
