# Replay Static UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the replay plan centred and immune to pointer pan/wheel zoom while keeping its transport visible at the bottom of the viewport.

**Architecture:** Add an explicit passive interaction mode to the shared `PlanCanvas`, defaulting to its existing interactive behaviour so editor callers are unchanged. Replay opts into passive mode, and replay-only CSS makes the presentation transport sticky without changing controller state or simulation data.

**Tech Stack:** React 19, TypeScript 5.8, CSS, Vitest, Testing Library

## Global Constraints

- Work directly on the local `main` branch as requested.
- Do not modify replay clock, frame fetching, verification, resident semantics, simulation data, or night behaviour.
- Reuse the simulator's existing colour, spacing, border, radius, and typography tokens.
- Preserve the existing interactive plan behaviour for non-replay callers.

---

### Task 1: Passive replay plan and sticky presentation transport

**Files:**
- Modify: `frontend/src/components.tsx:447-633`
- Modify: `frontend/src/replay/ReplayStage.tsx:123-132`
- Modify: `frontend/src/replay/replay.css:21-36`
- Test: `frontend/src/test/components.test.tsx`
- Test: `frontend/src/test/ReplayWorkbench.test.tsx`

**Interfaces:**
- Consumes: the existing `PlanCanvas` viewport calculation and the existing replay presentation DOM.
- Produces: `PlanCanvas` prop `interactionMode?: "interactive" | "passive"`, defaulting to `"interactive"`; passive canvases expose `data-interaction-mode="passive"` and bind no plan-level pointer-pan or wheel-zoom handlers.

- [ ] **Step 1: Write failing component tests for passive interaction**

Add this test to `frontend/src/test/components.test.tsx`:

```tsx
it("keeps passive plans fitted while the wheel remains available to page scrolling", () => {
  const passive = render(<PlanCanvas home={home} sensors={sensors} interactionMode="passive" />);
  const passivePlan = passive.container.querySelector("svg.plan-canvas") as SVGSVGElement;
  const initialViewBox = passivePlan.getAttribute("viewBox");
  const passiveWheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 120 });

  fireEvent(passivePlan, passiveWheel);

  expect(passiveWheel.defaultPrevented).toBe(false);
  expect(passivePlan).toHaveAttribute("data-interaction-mode", "passive");
  expect(passivePlan).toHaveAttribute("viewBox", initialViewBox);

  passive.unmount();
  const interactive = render(<PlanCanvas home={home} sensors={sensors} />);
  const interactivePlan = interactive.container.querySelector("svg.plan-canvas") as SVGSVGElement;
  const interactiveWheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 120 });

  fireEvent(interactivePlan, interactiveWheel);

  expect(interactiveWheel.defaultPrevented).toBe(true);
  expect(interactivePlan).toHaveAttribute("data-interaction-mode", "interactive");
});
```

Extend the presentation assertion in `frontend/src/test/ReplayWorkbench.test.tsx`:

```tsx
expect(view.container.querySelector(".replay-presentation-stage svg.plan-canvas"))
  .toHaveAttribute("data-interaction-mode", "passive");
expect(screen.getByRole("region", { name: "Replay transport" }))
  .toHaveClass("replay-presentation-transport");
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
npm test -- frontend/src/test/components.test.tsx frontend/src/test/ReplayWorkbench.test.tsx
```

Expected: FAIL because `PlanCanvas` does not accept `interactionMode` and replay does not mark the canvas passive.

- [ ] **Step 3: Add the passive interaction boundary**

In `frontend/src/components.tsx`, add `interactionMode = "interactive"` to the destructuring and this prop to the type:

```tsx
interactionMode?: "interactive" | "passive";
```

Create conditional plan-level handlers immediately before the return:

```tsx
const planInteractions = interactionMode === "interactive" ? {
  onPointerDown: beginPan,
  onPointerMove: (event: ReactPointerEvent) => { continueDrag(event); continuePan(event); },
  onPointerUp: endDrag,
  onPointerCancel: endDrag,
  onPointerLeave: endDrag,
  onWheel: wheelZoom,
} : {};
```

Replace the six unconditional plan-level handlers on the `<svg>` with:

```tsx
data-interaction-mode={interactionMode}
{...planInteractions}
```

In `frontend/src/replay/ReplayStage.tsx`, opt replay into the passive mode:

```tsx
<PlanCanvas
  home={models.homeModel}
  sensors={models.sensorModel}
  replayOverlay={overlay}
  showExternalPlaces={hasVisibleExternalTrajectory}
  interactionMode="passive"
/>
```

- [ ] **Step 4: Make the presentation transport sticky and keep the plan centred**

Update the replay presentation rules in `frontend/src/replay/replay.css`:

```css
.replay-presentation-stage { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(360px, 1fr) auto auto; }
[data-mode="presentation"] .replay-stage { display: grid; min-height: 0; place-items: center; padding: .7rem; border-right: 0; }
[data-mode="presentation"] .replay-stage > .plan-canvas-wrap { width: 100%; }
[data-mode="presentation"] .replay-stage > .plan-canvas-wrap > .plan-canvas { min-height: clamp(360px, 56vh, 560px); cursor: default; }
.replay-presentation-transport { position: sticky; z-index: 4; bottom: 0; padding: .6rem .85rem; border-top: 1px solid var(--line); background: var(--surface); box-shadow: 0 -.4rem 1rem color-mix(in srgb, var(--text) 8%, transparent); }
```

Remove the superseded `[data-mode="presentation"] .replay-stage > .plan-canvas { min-height: 470px; }` rule. Do not change the analysis layout.

- [ ] **Step 5: Run focused tests and type checking**

Run:

```powershell
npm test -- frontend/src/test/components.test.tsx frontend/src/test/ReplayWorkbench.test.tsx
npm run typecheck
```

Expected: both focused suites PASS and TypeScript exits with code 0.

- [ ] **Step 6: Run frontend regression checks**

Run:

```powershell
npm run lint
npm run build
```

Expected: ESLint exits with zero warnings and the Vite production build succeeds.

- [ ] **Step 7: Commit the UI change**

```powershell
git add -- frontend/src/components.tsx frontend/src/replay/ReplayStage.tsx frontend/src/replay/replay.css frontend/src/test/components.test.tsx frontend/src/test/ReplayWorkbench.test.tsx docs/superpowers/plans/2026-08-24-replay-static-ui.md
git commit -m "fix: keep replay plan static and controls visible"
```
