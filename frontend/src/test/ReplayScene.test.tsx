import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReplayScene } from "../replay/ReplayScene";

const start = "2026-10-30T00:00:00+01:00";
const end = "2026-10-31T00:00:00+01:00";
const digest = "a".repeat(64);

const home = {
  schemaVersion: "1.0.0", documentType: "home_model", homeId: "home", homeVersion: "1", coordinateSystem: {},
  regions: [
    { regionId: "kitchen", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } },
    { regionId: "bedroom", kind: "room", traversable: true, boundary: { vertices: [{ x: 4, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 4 }, { x: 4, y: 4 }] } },
    { regionId: "outdoors", kind: "external", traversable: true, boundary: { vertices: [{ x: 0, y: 20 }, { x: 6, y: 20 }, { x: 6, y: 24 }, { x: 0, y: 24 }] } },
  ],
  connections: [
    { connectionId: "door", regionAId: "kitchen", regionBId: "bedroom", kind: "doorway", bidirectional: true, widthMeters: .9 },
    { connectionId: "transit_out", regionAId: "kitchen", regionBId: "outdoors", kind: "transit", bidirectional: true, widthMeters: 1 },
  ],
  obstacles: [{ obstacleId: "obstacle_refrigerator", regionId: "kitchen", boundary: { vertices: [{ x: .2, y: .2 }, { x: .9, y: .2 }, { x: .9, y: .9 }, { x: .2, y: .9 }] } }],
  interactionPoints: [{ interactionPointId: "point_fridge", regionId: "kitchen", position: { x: 2, y: 2 } }],
  entities: [{ entityId: "refrigerator", entityType: "refrigerator", regionId: "kitchen", interactionPointId: "point_fridge" }],
  locationBindings: [], resourceBindings: [], kinematicDefaults: {},
};

const activities = [
  { at: "2026-10-30T07:52:00+01:00", end: "2026-10-30T08:10:00+01:00", kind: "activity", eventId: "breakfast", label: "prepare_weekend_breakfast", status: "completed", actorId: "resident_mario_rossi", waypoints: [], details: {} },
  { at: "2026-10-30T22:05:00+01:00", end: "2026-10-31T07:05:00+01:00", kind: "activity", eventId: "sleep", label: "sleep", status: "deviated", actorId: "resident_mario_rossi", waypoints: [], details: {} },
];

const dayItems = [
  ...activities,
  {
    at: "2026-10-30T07:42:00+01:00", end: "2026-10-30T07:42:40+01:00", kind: "movement", eventId: "walk",
    label: "", status: "completed", actorId: "resident_mario_rossi", details: {},
    waypoints: [
      { at: "2026-10-30T07:42:00+01:00", regionId: "bedroom", traversalMode: "walking", position: { x: 6, y: 2 } },
      { at: "2026-10-30T07:42:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 2, y: 2 } },
    ],
  },
  { at: "2026-10-30T07:52:06+01:00", kind: "state_transition", eventId: "fridge", label: "entity.open", waypoints: [], details: { value: true, subjectId: "refrigerator" } },
  {
    at: "2026-10-30T09:00:00+01:00", end: "2026-10-30T09:00:40+01:00", kind: "movement", eventId: "leave",
    label: "", status: "completed", actorId: "resident_mario_rossi", details: {},
    waypoints: [
      { at: "2026-10-30T09:00:00+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 2, y: 2 } },
      { at: "2026-10-30T09:00:40+01:00", regionId: "outdoors", traversalMode: "walking", position: { x: 3, y: 22 } },
    ],
  },
];

const frame = {
  runId: "run_1", at: start, traceStart: start, traceEnd: end,
  residents: [{ residentId: "resident_mario_rossi", regionId: "bedroom", position: { x: 6, y: 2 }, posture: "lying", executionState: "idle", heldResourceIds: [], facts: {} }],
  sensorStates: [], entityStates: { refrigerator: { open: false, active: false } },
  environmentFacts: {}, resourceAvailableUnits: {},
};

let verified = true;
let requests: string[] = [];

function respond(path: string): unknown {
  if (path.includes("/replay/verify")) return { runId: "run_1", verifiedAt: start, matches: verified, expectedSemanticDigest: digest, actualSemanticDigest: verified ? digest : "b".repeat(64) };
  // A workspace only reports a session as playable once the trace it holds has been verified.
  if (path.includes("/replay/session")) return { runId: "run_1", verifiedDigest: verified ? digest : null, playable: verified, positionAt: null, filters: { speed: 1 } };
  if (path.includes("/models")) return { homeModel: home };
  if (path.includes("/replay/events")) return { items: dayItems, total: dayItems.length, traceStart: start, traceEnd: end, windowStart: start, windowEnd: end };
  if (path.includes("/replay/frame")) return frame;
  return {};
}

/** The transport appears before the day does; the ribbon only counts once the day is in. */
async function sceneReady(): Promise<void> {
  await screen.findByLabelText("The day, 2 activities");
}

async function settle(): Promise<void> {
  await act(async () => { for (let tick = 0; tick < 16; tick += 1) await Promise.resolve(); });
}

describe("ReplayScene", () => {
  beforeEach(() => {
    verified = true;
    requests = [];
    sessionStorage.setItem("habitat-lab-session", "token");
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      requests.push(String(input));
      return Promise.resolve(new Response(JSON.stringify(respond(String(input))), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("draws the flat, the person in it, and says what they want", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    const scene = await screen.findByRole("img", { name: /flat, seen from above/ });
    expect(scene.querySelectorAll(".scene-floor")).toHaveLength(2);
    expect(scene.querySelector(".scene-avatar")).toHaveAttribute("data-posture", "lying");
    // The clock reads the flat's own wall clock, which the trace writes into every instant.
    expect(screen.getByText("00:00:00")).toBeInTheDocument();
    expect(screen.getByText("Friday 30 October")).toBeInTheDocument();
  });

  it("asks for one day of the trace's own families and never for the sensor readings", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    const day = requests.find((path) => path.includes("/replay/events"));
    expect(day).toBeDefined();
    const query = decodeURIComponent(day ?? "");
    expect(query).toContain("kinds=activity,action,movement,state_transition");
    expect(query).not.toContain("observation");
    expect(query).toContain("start=2026-10-29T23:00:00.000Z");
  });

  it("moves through the day, telling the viewer what is happening in words", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scrub = screen.getByRole("slider", { name: "Replay time" });

    fireEvent.change(scrub, { target: { value: String(Date.parse("2026-10-30T07:42:20+01:00")) } });
    await waitFor(() => expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Mario Rossi has nothing planned"));
    const walking = screen.getByRole("img", { name: /flat, seen from above/ }).querySelector(".scene-avatar");
    expect(walking).toHaveAttribute("data-moving", "true");

    fireEvent.change(scrub, { target: { value: String(Date.parse("2026-10-30T07:53:00+01:00")) } });
    await waitFor(() => expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Mario Rossi is preparing weekend breakfast"));
    expect(screen.getByText("The refrigerator opens")).toBeInTheDocument();
    expect(screen.getByText("Mario Rossi walks to the kitchen")).toBeInTheDocument();
  });

  it("names the thing somebody is standing at, and rings it on the plan", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    fireEvent.change(screen.getByRole("slider", { name: "Replay time" }), { target: { value: String(Date.parse("2026-10-30T07:53:00+01:00")) } });

    // Without this, "watching television" is a person on one side of the room and a lit screen
    // on the other, with nothing saying they belong together.
    await waitFor(() => expect(screen.getByText(/at the refrigerator/)).toBeInTheDocument());
    expect(screen.getByRole("img", { name: /flat, seen from above/ }).querySelector(".scene-thing-use")).toBeInTheDocument();
  });

  it("draws nobody once the trace takes them out of the flat", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scene = screen.getByRole("img", { name: /flat, seen from above/ });

    fireEvent.change(screen.getByRole("slider", { name: "Replay time" }), { target: { value: String(Date.parse("2026-10-30T10:00:00+01:00")) } });

    // The trace puts the office twenty metres south of the flat, so the leg that reaches it is
    // a departure; drawn as a walk it crosses the kitchen and a wall.
    await waitFor(() => expect(screen.getByText(/Mario Rossi is out/)).toBeInTheDocument());
    expect(screen.getByText(/away · outdoors/)).toBeInTheDocument();
    expect(scene.querySelector(".scene-avatar")).toBeNull();
    expect(scene.querySelector(".scene-trail")?.getAttribute("points")).toBeFalsy();
  });

  it("skips past the rest of what is happening rather than sitting through it", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scrub = screen.getByRole("slider", { name: "Replay time" });

    // Nine hours of sleep is not something a viewer should have to scrub across by hand.
    fireEvent.change(scrub, { target: { value: String(Date.parse("2026-10-30T22:30:00+01:00")) } });
    await waitFor(() => expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Mario Rossi is sleeping"));
    fireEvent.click(screen.getByRole("button", { name: "Skip ahead" }));

    await waitFor(() => expect(scrub).toHaveValue(String(Date.parse(end))));
  });

  it("skips forward to whatever happens next when nothing is happening now", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scrub = screen.getByRole("slider", { name: "Replay time" });

    fireEvent.change(scrub, { target: { value: String(Date.parse("2026-10-30T05:00:00+01:00")) } });
    fireEvent.click(screen.getByRole("button", { name: "Skip ahead" }));

    await waitFor(() => expect(scrub).toHaveValue(String(Date.parse("2026-10-30T07:52:00+01:00"))));
  });

  it("shows the day as blocks that can be jumped to, and starts at real time", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    const ribbon = screen.getByLabelText("The day, 2 activities");
    expect(within(ribbon).getByRole("button", { name: "07:52, preparing weekend breakfast" })).toBeInTheDocument();
    expect(within(ribbon).getByRole("button", { name: "22:05, sleeping" })).toBeInTheDocument();
    expect(screen.getByLabelText("Playback speed")).toHaveDisplayValue("Real time");

    fireEvent.click(within(ribbon).getByRole("button", { name: "07:52, preparing weekend breakfast" }));
    await waitFor(() => expect(screen.getByRole("slider", { name: "Replay time" }))
      .toHaveValue(String(Date.parse("2026-10-30T07:52:00+01:00"))));
  });

  it("plays, pauses and changes speed without leaving the day it is in", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Play" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Playback speed"), { target: { value: "15" } });
    await waitFor(() => expect(screen.getByLabelText("Playback speed")).toHaveDisplayValue("15×"));
  });

  it("steps whole days and clamps to the trace", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scrub = screen.getByRole("slider", { name: "Replay time" });

    fireEvent.click(screen.getByRole("button", { name: "Next day" }));
    await waitFor(() => expect(scrub).toHaveValue(String(Date.parse(end))));
    fireEvent.click(screen.getByRole("button", { name: "Previous day" }));
    await waitFor(() => expect(scrub).toHaveValue(String(Date.parse(start))));
  });

  it("runs the clock at real time, and at whatever multiple of it is chosen", async () => {
    const frames: Array<() => void> = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => { frames.push(callback); return frames.length; }));
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    render(<ReplayScene runId="run_1" />);
    await sceneReady();
    const scrub = screen.getByRole("slider", { name: "Replay time" });
    const from = Number((scrub as HTMLInputElement).value);

    const run = async (seconds: number) => {
      for (let frame = 0; frame < seconds * 60; frame += 1) {
        now += 1000 / 60;
        const callback = frames.shift();
        await act(async () => { callback?.(); await Promise.resolve(); });
      }
    };
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await run(2);

    // Two seconds of animation frames is two seconds of the resident's day, and nothing else.
    expect(Number((scrub as HTMLInputElement).value) - from).toBeCloseTo(2_000, -2);

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    fireEvent.change(screen.getByLabelText("Playback speed"), { target: { value: "15" } });
    await settle();
    const faster = Number((screen.getByRole("slider", { name: "Replay time" }) as HTMLInputElement).value);
    frames.length = 0;
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await run(2);

    expect(Number((screen.getByRole("slider", { name: "Replay time" }) as HTMLInputElement).value) - faster)
      .toBeCloseTo(30_000, -3);
  });

  it("fetches the next day as the clock walks into it", async () => {
    const frames: Array<() => void> = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => { frames.push(callback); return frames.length; }));
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    const days = () => requests.filter((path) => path.includes("/replay/events")).length;
    const before = days();
    fireEvent.change(screen.getByRole("slider", { name: "Replay time" }), { target: { value: String(Date.parse("2026-10-30T23:59:50+01:00")) } });
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await act(async () => { frames.shift()?.(); await Promise.resolve(); });
    now = 60_000;
    await act(async () => { frames.shift()?.(); await Promise.resolve(); });
    await settle();

    // Crossing midnight is the one moment the scene has to go back to the server for more.
    expect(days()).toBeGreaterThan(before);
  });

  it("stops itself at the end of the trace rather than running past it", async () => {
    const frames: Array<() => void> = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => { frames.push(callback); return frames.length; }));
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await act(async () => { frames.shift()?.(); await Promise.resolve(); });
    // More wall clock than the day is long, so the clock has to stop rather than overrun it.
    now = 200_000_000;
    await act(async () => { frames.shift()?.(); await Promise.resolve(); });

    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveValue(String(Date.parse(end)));
    expect(await screen.findByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("opens where the viewer left off and writes back where they get to", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      requests.push(`${init?.method ?? "GET"} ${path}`);
      const body = path.includes("/replay/session") && init?.method !== "PUT"
        ? { runId: "run_1", verifiedDigest: digest, playable: true, positionAt: "2026-10-30T09:30:00+01:00", filters: { speed: 5 } }
        : respond(path);
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    try {
      render(<ReplayScene runId="run_1" />);
      await act(async () => { await vi.advanceTimersByTimeAsync(50); });
      await act(async () => { await vi.advanceTimersByTimeAsync(50); });

      expect(screen.getByRole("slider", { name: "Replay time" })).toHaveValue(String(Date.parse("2026-10-30T09:30:00+01:00")));
      expect(screen.getByLabelText("Playback speed")).toHaveDisplayValue("5×");

      fireEvent.change(screen.getByRole("slider", { name: "Replay time" }), { target: { value: String(Date.parse("2026-10-30T12:00:00+01:00")) } });
      await act(async () => { await vi.advanceTimersByTimeAsync(900); });

      const saved = requests.filter((entry) => entry.startsWith("PUT") && entry.includes("/replay/session"));
      expect(saved.length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops when the day behind the scene cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/replay/events")) {
        return Promise.resolve(new Response(JSON.stringify({ error: { message: "Evidence is unreadable" } }), { status: 500, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify(respond(path)), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText("Evidence is unreadable")).toBeInTheDocument();
  });

  it("does not re-verify a run the workspace has already verified", async () => {
    render(<ReplayScene runId="run_1" />);
    await sceneReady();

    // Verifying re-executes the whole simulation; on a year-long run that is five minutes to
    // reach an answer the session already carries.
    expect(requests.some((path) => path.includes("/replay/verify"))).toBe(false);
  });

  it("verifies a run the workspace has not, and says why the wait is happening", async () => {
    verified = false;
    let answer: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      requests.push(path);
      if (path.includes("/replay/verify")) return new Promise<Response>((resolve) => { answer = resolve; });
      return Promise.resolve(new Response(JSON.stringify(respond(path)), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText(/Checking this run against the trace/)).toBeInTheDocument();
    verified = true;
    answer?.(new Response(JSON.stringify({ runId: "run_1", verifiedAt: start, matches: true, expectedSemanticDigest: digest, actualSemanticDigest: digest }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await sceneReady();
  });

  it("refuses to show a run whose replay no longer matches its trace", async () => {
    verified = false;
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText(/no longer matches the trace/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Replay controls" })).not.toBeInTheDocument();
  });

  it("says so when a day carries more than the scene was given", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      const body = path.includes("/replay/events")
        ? { items: dayItems, total: 9_000, traceStart: start, traceEnd: end, windowStart: start, windowEnd: end }
        : respond(path);
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText(/more evidence than the scene can carry/)).toBeInTheDocument();
  });

  it("says the home is missing without pretending the run is broken", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/models")) {
        return Promise.resolve(new Response(JSON.stringify({ error: { message: "The home model was deleted" } }), { status: 404, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify(respond(path)), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText(/The home for this run is unavailable/)).toBeInTheDocument();
    // The clock and the transport still work: only the picture is missing.
    expect(screen.getByRole("region", { name: "Replay controls" })).toBeInTheDocument();
  });

  it("reports a local server that stopped answering rather than a broken replay", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("The connection was lost"))));
    render(<ReplayScene runId="run_1" />);

    expect(await screen.findByText(/local server stopped responding/)).toBeInTheDocument();
  });

  it("keeps the transport out of the way while the run is still being read", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    render(<ReplayScene runId="run_1" />);
    await settle();

    expect(screen.getByText("Setting the scene…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
  });
});
