import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SceneStage } from "../replay/SceneStage";
import type { SceneWorld } from "../replay/replay-world";
import type { HomeModel } from "../types";

const home = {
  schemaVersion: "1.0.0", documentType: "home_model", homeId: "home", homeVersion: "1", coordinateSystem: {},
  regions: [
    { regionId: "kitchen", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } },
    { regionId: "supermarket", kind: "external", traversable: true, boundary: { vertices: [{ x: 20, y: 20 }, { x: 24, y: 20 }, { x: 24, y: 24 }, { x: 20, y: 24 }] } },
  ],
  connections: [],
  obstacles: [
    { obstacleId: "obstacle_refrigerator", regionId: "kitchen", boundary: { vertices: [{ x: .2, y: .2 }, { x: .9, y: .2 }, { x: .9, y: .9 }, { x: .2, y: .9 }] } },
    { obstacleId: "obstacle_crate", regionId: "kitchen", boundary: { vertices: [{ x: 2, y: 2 }, { x: 3, y: 2 }, { x: 3, y: 3 }, { x: 2, y: 3 }] } },
  ],
  interactionPoints: [],
  entities: [
    { entityId: "refrigerator", entityType: "refrigerator", regionId: "kitchen" },
    { entityId: "crate", entityType: "mystery_object", regionId: "kitchen" },
  ],
  locationBindings: [], resourceBindings: [], kinematicDefaults: {},
} as unknown as HomeModel;

function world(part: Partial<SceneWorld> = {}): SceneWorld {
  return {
    atMs: 0,
    entities: { refrigerator: { open: true, active: false }, crate: { open: false, active: true } },
    residents: [{
      residentId: "resident_mario_rossi", name: "Mario Rossi", posture: "standing", carrying: [],
      regionId: "kitchen", position: { x: 1, y: 1 }, moving: false, away: false,
      routes: [], anchorPosition: { x: 1, y: 1 },
    }],
    ...part,
  };
}

describe("SceneStage", () => {
  afterEach(cleanup);

  it("draws the dwelling and leaves the places that are not part of it out of frame", () => {
    const { container } = render(<SceneStage home={home} world={world()} activeRegionId="kitchen" />);

    expect(container.querySelectorAll(".scene-floor")).toHaveLength(1);
    expect(container.querySelector("[data-region-id='kitchen']")).toHaveClass("is-occupied");
    expect(container.querySelector("[data-region-id='supermarket']")).toBeNull();
  });

  it("uses the furniture glyph a thing has, and a plain block for a thing that has none", () => {
    const { container } = render(<SceneStage home={home} world={world()} />);

    expect(container.querySelector("use[href='#furn-refrigerator']")).toBeInTheDocument();
    expect(container.querySelectorAll(".scene-block")).toHaveLength(1);
  });

  it("shows a thing that is open apart from a thing that is switched on", () => {
    const { container } = render(<SceneStage home={home} world={world()} />);
    const things = [...container.querySelectorAll(".scene-thing")];

    expect(things[0]).toHaveClass("is-open");
    expect(things[0]).not.toHaveClass("is-active");
    expect(things[1]).toHaveClass("is-active");
    // Only something switched on is worth a halo; an open door is not a light.
    expect(container.querySelectorAll(".scene-thing-glow")).toHaveLength(1);
  });

  it("draws nobody the world gives no position, and says so when there is no home to draw", () => {
    const placeless = render(<SceneStage home={home} world={world({ residents: [{ ...world().residents[0]!, position: undefined }] })} />);
    expect(placeless.container.querySelector(".scene-avatar")).toBeNull();
    cleanup();

    const homeless = render(<SceneStage home={undefined} world={world()} />);
    expect(homeless.getByRole("status")).toHaveTextContent("The home for this run is not available.");
    cleanup();

    const empty = render(<SceneStage home={{ ...home, regions: [] }} world={world()} />);
    expect(empty.getByRole("status")).toHaveTextContent("The home for this run is not available.");
  });

  it("poses each posture the trace records", () => {
    for (const posture of ["standing", "sitting", "lying"]) {
      const { container } = render(<SceneStage home={home} world={world({ residents: [{ ...world().residents[0]!, posture }] })} />);
      expect(container.querySelector(".scene-avatar")).toHaveAttribute("data-posture", posture);
      cleanup();
    }
  });

  it("shows what somebody is carrying, and follows the clock when one is offered", () => {
    const carrying = render(<SceneStage home={home} world={world({ residents: [{ ...world().residents[0]!, carrying: ["ingredients"], moving: true }] })} />);
    expect(carrying.container.querySelector(".scene-avatar-load")).toBeInTheDocument();
    expect(carrying.container.querySelector(".scene-avatar")).toHaveAttribute("data-moving", "true");
    cleanup();

    let emit: ((atMs: number) => void) | undefined;
    const { container } = render(<SceneStage
      home={home}
      world={world()}
      motion={{
        subscribe: (listener) => { emit = listener; return () => { emit = undefined; }; },
        sample: (atMs) => ({ resident_mario_rossi: { position: { x: atMs, y: 2 }, heading: Math.PI / 2, travelled: [{ x: 0, y: 0 }, { x: atMs, y: 2 }] } }),
      }}
    />);

    emit?.(3);

    expect(container.querySelector(".scene-people > g")).toHaveAttribute("transform", "translate(3 2) rotate(90)");
    expect(container.querySelector(".scene-trail")).toHaveAttribute("points", "0,0 3,2");
  });

  it("leaves a marker alone when the clock offers no pose for it", () => {
    const { container } = render(<SceneStage
      home={home}
      world={world()}
      motion={{ subscribe: () => () => undefined, sample: () => ({}) }}
    />);

    expect(container.querySelector(".scene-people > g")).toHaveAttribute("transform", "translate(1 1)");
  });
});
