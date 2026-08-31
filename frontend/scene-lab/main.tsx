/*
 * The scene lab: the replay stage, on a real two-storey house, with no backend behind it.
 *
 * Motion is the one thing the unit tests cannot see. This page mounts the real `SceneStage` over
 * the real `foldWorld`/`sceneMotion` pipeline, fed by a day generated from the real router, so a
 * walk, a climb, a posture and an appliance can all be watched and judged rather than asserted.
 *
 * Dev only: it lives outside `src`, so it is neither bundled by the app build nor counted by the
 * coverage thresholds.
 */
import "@fontsource-variable/source-sans-3";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { scenePlace } from "../src/replay/replay-place";
import { buildScript } from "../src/replay/replay-script";
import { replayTimestamp } from "../src/replay/replay-positioning";
import { foldWorld } from "../src/replay/replay-world";
import { sceneMotion } from "../src/replay/scene-motion";
import { SceneStage } from "../src/replay/SceneStage";
import type { HomeModel, ReplayEventWindow, ReplayFrame } from "../src/types";
import "../src/styles.css";
import "../src/replay/scene.css";
import "./lab.css";
import homeJson from "./home.json";
import dayJson from "./day.json";

const home = homeJson as unknown as HomeModel;
const day = dayJson as unknown as { events: ReplayEventWindow; frame: ReplayFrame };
const script = buildScript(day.events, home);
const place = scenePlace(home);
const anchorMs = replayTimestamp(day.frame.at);
const OFFSET_MS = 60 * 60 * 1000;

/** The moments worth landing on, so a judgement about one does not need a hunt for it. */
const MARKS: Array<{ label: string; at: string }> = [
  { label: "In bed", at: "07:00:10" },
  { label: "Gets up", at: "07:00:25" },
  { label: "Walk + climb down", at: "07:00:46" },
  { label: "Shower running", at: "07:05:00" },
  { label: "Climb to kitchen", at: "07:10:06" },
  { label: "Moka + fridge", at: "07:12:05" },
  { label: "Carrying", at: "07:12:40" },
  { label: "Sits to eat", at: "07:16:30" },
  { label: "Walk to sofa", at: "07:45:23" },
  { label: "Watching TV", at: "07:50:00" },
  { label: "Climb to study", at: "08:10:27" },
  { label: "At the desk", at: "08:20:00" },
  { label: "Front door opens", at: "08:42:35" },
  { label: "Out", at: "08:45:00" },
];

const DAY_START = Date.parse("2026-10-30T00:00:00+01:00");
function markMs(at: string): number {
  const [h, m, s] = at.split(":").map(Number);
  return DAY_START + ((h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0)) * 1000;
}

function clockText(atMs: number): string {
  const local = new Date(atMs + OFFSET_MS);
  const two = (value: number) => String(value).padStart(2, "0");
  return `${two(local.getUTCHours())}:${two(local.getUTCMinutes())}:${two(local.getUTCSeconds())}`;
}

// eslint-disable-next-line react-refresh/only-export-components -- an entry point, not a module
function SceneLab() {
  const [atMs, setAtMs] = useState(markMs("07:00:10"));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const listeners = useRef(new Set<(atMs: number) => void>());
  const now = useRef(atMs);
  now.current = atMs;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // One clock for the whole page, exactly as the real controller runs it: every frame to the
  // subscribers that draw, and a coarser republish for the React state that captions it.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    let published = 0;
    const step = (frameAt: number) => {
      const advanced = (frameAt - last) * speed;
      last = frameAt;
      now.current += advanced;
      for (const listener of listeners.current) listener(now.current);
      if (frameAt - published > 100) {
        published = frameAt;
        setAtMs(now.current);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); setAtMs(now.current); };
  }, [playing, speed]);

  const subscribe = useMemo(() => (listener: (atMs: number) => void) => {
    listeners.current.add(listener);
    return () => { listeners.current.delete(listener); };
  }, []);

  const world = useMemo(() => foldWorld(script, day.frame, atMs, place), [atMs]);
  const motion = useMemo(() => sceneMotion(world, anchorMs, subscribe, place), [world, subscribe]);
  const resident = world.residents[0];

  const seek = (to: number) => {
    now.current = to;
    setAtMs(to);
    for (const listener of listeners.current) listener(to);
  };

  return (
    <div className="lab">
      <header className="lab-bar">
        <strong>Scene lab</strong>
        <button type="button" onClick={() => { setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
        <label>
          Speed
          <select value={speed} onChange={(event) => { setSpeed(Number(event.target.value)); }}>
            {[.25, .5, 1, 2, 5, 15, 60].map((item) => <option key={item} value={item}>{item}x</option>)}
          </select>
        </label>
        <span className="lab-clock">{clockText(atMs)}</span>
        <span className="lab-where">
          {resident?.away ? "away" : resident?.regionId?.replaceAll("_", " ") ?? "—"}
          {resident?.using ? ` · at the ${resident.using.label}` : ""}
          {resident?.posture ? ` · ${resident.posture}` : ""}
          {resident?.carrying.length ? ` · carrying ${resident.carrying.join(", ")}` : ""}
        </span>
        <button type="button" onClick={() => { setTheme(theme === "light" ? "dark" : "light"); }}>{theme === "light" ? "Dark" : "Light"}</button>
      </header>

      <div className="lab-marks">
        {MARKS.map((mark) => (
          <button key={mark.label} type="button" onClick={() => { seek(markMs(mark.at)); }}>
            {mark.label}<small>{mark.at}</small>
          </button>
        ))}
      </div>

      <div className="lab-stage app-shell" data-theme={theme}>
        <section className="scene-page">
          <div className="scene-viewport">
            <SceneStage
              home={home}
              world={world}
              motion={motion}
              activeRegionId={resident?.away ? undefined : resident?.regionId}
              usingEntityId={resident?.using?.entityId}
            />
            {resident?.away && <p className="scene-away" role="status">Mario is out</p>}
          </div>
        </section>
      </div>

      <input
        className="lab-scrub"
        type="range"
        min={markMs("07:00:00")}
        max={markMs("08:50:00")}
        step={200}
        value={atMs}
        onChange={(event) => { seek(event.target.valueAsNumber); }}
      />
    </div>
  );
}

// One root across hot reloads, or every edit stacks another copy of the page on the last.
const container = document.getElementById("root")! as HTMLElement & { _root?: ReactDOM.Root };
container._root ??= ReactDOM.createRoot(container);
container._root.render(<SceneLab />);
