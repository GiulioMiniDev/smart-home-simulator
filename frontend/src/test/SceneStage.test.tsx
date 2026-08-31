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

  it("shows a running thing doing the thing it does, not all of them glowing alike", () => {
    // `active` is one bit in the trace and it used to be one halo, which made a kettle and a
    // television the same event. A kettle steams and a screen flickers, and the difference is
    // what makes "making coffee" legible without reading the caption under the picture.
    const kitchen = {
      ...home,
      obstacles: [
        ...home.obstacles,
        { obstacleId: "obstacle_moka", regionId: "kitchen", boundary: { vertices: [{ x: 1, y: 1 }, { x: 1.3, y: 1 }, { x: 1.3, y: 1.3 }, { x: 1, y: 1.3 }] } },
        { obstacleId: "obstacle_shower", regionId: "kitchen", boundary: { vertices: [{ x: 3, y: 1 }, { x: 3.8, y: 1 }, { x: 3.8, y: 1.8 }, { x: 3, y: 1.8 }] } },
        { obstacleId: "obstacle_television", regionId: "kitchen", boundary: { vertices: [{ x: 1, y: 3 }, { x: 2, y: 3 }, { x: 2, y: 3.3 }, { x: 1, y: 3.3 }] } },
      ],
      entities: [
        ...home.entities,
        { entityId: "moka", entityType: "moka_coffee_maker", regionId: "kitchen" },
        { entityId: "shower", entityType: "shower", regionId: "kitchen" },
        { entityId: "television", entityType: "television", regionId: "kitchen" },
      ],
    } as unknown as HomeModel;
    const running = world({
      entities: {
        moka: { open: false, active: true },
        shower: { open: false, active: true },
        television: { open: false, active: true },
        crate: { open: false, active: true },
      },
    });
    const { container } = render(<SceneStage home={kitchen} world={running} activeRegionId="kitchen" />);

    expect(container.querySelectorAll(".scene-emit-steam")).toHaveLength(1);
    expect(container.querySelectorAll(".scene-emit-water")).toHaveLength(1);
    expect(container.querySelectorAll(".scene-emit-screen")).toHaveLength(1);
    // A thing with nothing particular to show still gets the halo: the halo is the general case.
    expect(container.querySelectorAll(".scene-thing-glow")).toHaveLength(4);
    expect(container.querySelectorAll("[class^=scene-emit]")).toHaveLength(3);
  });

  it("puts a body onto the furniture it is recorded as using, not beside it", () => {
    // An interaction point is by construction a patch of free floor, because that is the only
    // place the router may stand a body. So the trace drew her lying rigidly on the carpet next
    // to the bed and standing beside the chair she is recorded as sitting on. The evidence was
    // never wrong: what it names is where you stand to use a thing, not where you end up.
    const furnished = {
      ...home,
      obstacles: [
        ...home.obstacles,
        { obstacleId: "obstacle_bed", regionId: "kitchen", boundary: { vertices: [{ x: 1, y: 1 }, { x: 3, y: 1 }, { x: 3, y: 2.4 }, { x: 1, y: 2.4 }] } },
        { obstacleId: "obstacle_chair", regionId: "kitchen", boundary: { vertices: [{ x: .2, y: 3 }, { x: .7, y: 3 }, { x: .7, y: 3.5 }, { x: .2, y: 3.5 }] } },
      ],
      entities: [...home.entities,
        { entityId: "bed", entityType: "bed", regionId: "kitchen" },
        { entityId: "chair", entityType: "chair", regionId: "kitchen" },
      ],
    } as unknown as HomeModel;
    const at = (part: Record<string, unknown>) => world({
      residents: [{
        residentId: "resident_mario_rossi", name: "Mario Rossi", carrying: [],
        regionId: "kitchen", moving: false, away: false, routes: [],
        posture: "standing", position: { x: .5, y: 1.7 }, anchorPosition: { x: .5, y: 1.7 },
        ...part,
      }],
    } as unknown as Partial<SceneWorld>);
    const marker = (element: HTMLElement) => element.querySelector(".scene-people > g") as SVGGElement;

    // Standing at the fridge is exactly where the trace says, and stays there.
    const standing = render(<SceneStage home={furnished} world={at({ using: { entityId: "refrigerator", label: "refrigerator" } })} />);
    expect(marker(standing.container).style.getPropertyValue("--scene-seat-x")).toBe("0px");
    cleanup();

    // In bed: onto the middle of it, and turned along its long side rather than along whichever
    // way she happened to be walking when she got there.
    const abed = render(<SceneStage home={furnished} world={at({ posture: "lying", using: { entityId: "bed", label: "bed" } })} />);
    expect(marker(abed.container).style.getPropertyValue("--scene-seat-x")).toBe("1.5px");
    expect(marker(abed.container).style.getPropertyValue("--scene-seat-y")).toBe("0px");
    expect(marker(abed.container).style.getPropertyValue("--scene-recline")).toBe("0deg");
    cleanup();

    // On the chair: most of the way, not all of it, so a seat reads as taken and a double bed
    // does not read as swallowing her.
    const seated = render(<SceneStage home={furnished} world={at({ posture: "sitting", position: { x: .45, y: 2.6 }, using: { entityId: "chair", label: "chair" } })} />);
    expect(Number.parseFloat(marker(seated.container).style.getPropertyValue("--scene-seat-y"))).toBeCloseTo(.507);
    expect(marker(seated.container).style.getPropertyValue("--scene-recline")).toBe("");
    cleanup();

    // A thing you operate rather than get onto is left alone, whatever the posture says.
    const perched = render(<SceneStage home={furnished} world={at({ posture: "sitting", using: { entityId: "refrigerator", label: "refrigerator" } })} />);
    expect(marker(perched.container).style.getPropertyValue("--scene-seat-x")).toBe("0px");
  });

  it("draws the front door and swings it on the state the trace gives it", () => {
    const withDoor = {
      ...home,
      connections: [{
        connectionId: "transit_kitchen_supermarket", kind: "transit",
        regionAId: "kitchen", regionBId: "supermarket", bidirectional: true, widthMeters: 1,
        portalA: { x: 2, y: 0 }, portalB: { x: 22, y: 22 },
      }],
      interactionPoints: [{ interactionPointId: "point_door", regionId: "kitchen", position: { x: 2, y: .4 }, approachRadiusMeters: .3 }],
      entities: [
        ...home.entities,
        {
          entityId: "entrance_door", entityType: "entrance_door", regionId: "kitchen",
          interactionPointId: "point_door",
          capabilities: [{ capability: "portal", roles: [], supportedOperations: ["leave_home", "enter_home"] }],
        },
      ],
    } as unknown as HomeModel;

    const shut = render(<SceneStage home={withDoor} world={world()} />);
    expect(shut.container.querySelector(".scene-door-leaf")).toHaveAttribute("data-open", "false");
    cleanup();

    const open = render(<SceneStage
      home={withDoor}
      world={world({ entities: { entrance_door: { open: true, active: false } } })}
    />);
    expect(open.container.querySelector(".scene-door-leaf")).toHaveAttribute("data-open", "true");
  });

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
        sample: (atMs) => ({ resident_mario_rossi: { position: { x: atMs, y: 2 }, heading: Math.PI / 2, travelled: [{ x: 0, y: 0 }, { x: atMs, y: 2 }], climbing: 0, level: 0 } }),
      }}
    />);

    emit?.(3);

    // The marker carries the position only. Facing rides as a custom property on an inner group,
    // so the body turns with its own easing and the name above her head stays upright.
    const marker = container.querySelector(".scene-people > g") as SVGGElement;
    expect(marker).toHaveAttribute("transform", "translate(3 2)");
    expect(marker.style.getPropertyValue("--scene-facing")).toBe("90deg");
    expect(marker.style.getPropertyValue("--scene-climbing")).toBe("0");
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
