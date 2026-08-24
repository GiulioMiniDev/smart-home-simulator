import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";
import axe from "axe-core";

type ReplayRun = { runId: string };
type ObservableReplaySession = {
  runId: string;
  playable: boolean;
  positionAt: string | null;
  filters: {
    eventKinds: string[];
    sensorIds: string[];
    statuses: string[];
    detailMode: string;
    visibilityMode: string;
    speed: number;
  };
};

async function replayRun(): Promise<ReplayRun> {
  return JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as ReplayRun;
}

async function resetReplaySession(page: import("@playwright/test").Page, run: ReplayRun): Promise<void> {
  const tokenResponse = await page.request.get("/api/session");
  expect(tokenResponse.status()).toBe(200);
  const { token } = await tokenResponse.json() as { token: string };
  const headers = { "X-Workspace-Token": token };
  const verification = await page.request.post(`/api/runs/${encodeURIComponent(run.runId)}/replay/verify`, { headers });
  expect(verification.status()).toBe(200);
  expect((await verification.json()) as { matches: boolean }).toMatchObject({ matches: true });

  const response = await page.request.put(`/api/runs/${encodeURIComponent(run.runId)}/replay/session`, {
    headers,
    data: {
      positionAt: null,
      filters: {
        eventKinds: [], actorIds: [], sensorIds: [], statuses: [],
        detailMode: "presentation", visibilityMode: "observable", speed: 1, selectedResidentId: null,
      },
    },
  });
  expect(response.status()).toBe(200);
  const session = await response.json() as ObservableReplaySession;
  expect(session).toMatchObject({
    runId: run.runId, playable: true, positionAt: null,
    filters: { eventKinds: [], sensorIds: [], statuses: [], detailMode: "presentation", visibilityMode: "observable", speed: 1 },
  });
  expect(session.filters).not.toHaveProperty("actorIds");
  expect(session.filters).not.toHaveProperty("selectedResidentId");
}

function selectedEvent(page: import("@playwright/test").Page) {
  return page.locator(".replay-track-events button.is-selected, button.replay-cluster-mark.is-selected");
}

async function selectEvent(page: import("@playwright/test").Page): Promise<void> {
  await page.locator("button.replay-cluster-mark").first().click();
  const clustered = page.locator(".replay-cluster-items button").first();
  if (await clustered.isVisible()) {
    await clustered.evaluate((element: HTMLButtonElement) => element.click());
  }
}

async function expectNoAxeViolations(page: import("@playwright/test").Page): Promise<void> {
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    const result = await (
      window as typeof window & {
        axe: { run: (root: Document) => Promise<{ violations: unknown[] }> };
      }
    ).axe.run(document);
    return result.violations;
  });
  expect(violations).toEqual([]);
}

async function expectNoPageHorizontalOverflow(page: import("@playwright/test").Page): Promise<void> {
  const sizes = await page.evaluate(() => ({
    documentElement: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
    body: { scrollWidth: document.body.scrollWidth, clientWidth: document.body.clientWidth },
  }));
  expect(sizes.documentElement.scrollWidth, `documentElement widths: ${JSON.stringify(sizes.documentElement)}`).toBeLessThanOrEqual(sizes.documentElement.clientWidth);
  expect(sizes.body.scrollWidth, `body widths: ${JSON.stringify(sizes.body)}`).toBeLessThanOrEqual(sizes.body.clientWidth);
}

test("replays one verified run in presentation and analysis modes", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByText("Replay verified")).toBeVisible();
  await expect(page.getByRole("button", { name: "Presentation" })).toHaveAttribute("aria-pressed", "true");
  const time = page.getByRole("slider", { name: "Replay time" });
  const initial = await time.inputValue();
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(() => time.inputValue()).not.toBe(initial);
  await page.getByRole("button", { name: "Open evidence" }).click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await selectEvent(page);
  await expect(selectedEvent(page)).toHaveCount(1);
  const selectedSemanticLabel = await selectedEvent(page).getAttribute("aria-label");
  const selectedTime = await time.inputValue();

  await page.getByRole("button", { name: "Presentation" }).click();
  await expect(time).toHaveValue(selectedTime);
  await page.getByRole("button", { name: "Analysis" }).click();
  await expect(time).toHaveValue(selectedTime);
  await expect(selectedEvent(page)).toHaveAttribute("aria-label", selectedSemanticLabel ?? "");

  await page.getByRole("button", { name: "Oracle" }).click();
  await expect(page.getByText("Simulated cause").first()).toBeVisible();
  await expect(time).toHaveValue(selectedTime);
  const oracleSelection = await selectedEvent(page).getAttribute("aria-label");
  // Projection can disclose a richer label, but it must retain the selected instant.
  expect(oracleSelection?.slice(0, 5)).toBe(selectedSemanticLabel?.slice(0, 5));
  await page.getByRole("button", { name: "Observable" }).click();
  await expect(time).toHaveValue(selectedTime);
  await expect(selectedEvent(page)).toHaveAttribute("aria-label", selectedSemanticLabel ?? "");

  await expectNoAxeViolations(page);
});

test("keeps the replay presentation plan passive and its transport visible", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByText("Replay verified")).toBeVisible();
  await expect(page.getByRole("button", { name: "Presentation" })).toHaveAttribute("aria-pressed", "true");

  const canvas = page.locator(".replay-presentation-stage svg.plan-canvas");
  const transport = page.getByRole("region", { name: "Replay transport" });
  await expect(canvas).toBeVisible();
  await expect(transport).toBeVisible();
  expect(await canvas.evaluate((element) => getComputedStyle(element).touchAction)).toBe("auto");
  await expect(canvas).toHaveCSS("cursor", "default");
  expect(await transport.evaluate((element) => ({
    position: getComputedStyle(element).position,
    bottom: getComputedStyle(element).bottom,
  }))).toEqual({ position: "sticky", bottom: "0px" });

  await canvas.hover();
  await page.mouse.down();
  try {
    await expect(canvas).toHaveCSS("cursor", "default");
  } finally {
    await page.mouse.up();
  }

  await page.setViewportSize({ width: 540, height: 900 });
  await expect.poll(() => canvas.evaluate((element) => getComputedStyle(element).minHeight)).toBe("320px");
});

test("replay survives reload and keyboard stepping", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await page.getByRole("button", { name: "Analysis" }).click();
  await expect(page.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
  const time = page.getByRole("slider", { name: "Replay time" });
  const stepStartingPoint = String(Date.parse("2026-10-30T06:14:00.000Z"));
  await time.fill(stepStartingPoint);
  await expect(time).toHaveValue(stepStartingPoint);
  await expect(page.locator("button.replay-cluster-mark").first()).toBeVisible();
  await selectEvent(page);
  await expect(selectedEvent(page)).toHaveCount(1);
  const beforeStep = await time.inputValue();
  const beforeSemanticEvent = await selectedEvent(page).getAttribute("aria-label");
  const next = page.getByRole("button", { name: "Next event" });
  await expect(next).toBeEnabled();
  await next.press("Enter");
  await expect(time).not.toHaveValue(beforeStep);
  await expect(selectedEvent(page)).not.toHaveAttribute("aria-label", beforeSemanticEvent ?? "");
  const saved = await time.inputValue();
  await page.waitForTimeout(750);
  await page.reload();
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("slider", { name: "Replay time" })).toHaveValue(saved);
});

test("keeps replay accessible and within the viewport in dark theme", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await page.goto(`/simulations/${run.runId}`);
  const darkTheme = page.getByRole("button", { name: "Use dark theme" });
  const toggledToDark = await darkTheme.isVisible();
  if (toggledToDark) await darkTheme.click();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByText("Replay verified")).toBeVisible();
  await expect(page.getByRole("button", { name: "Presentation" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open evidence" })).toBeVisible();
  await expect(page.getByRole("group", { name: /Plan of / })).toBeVisible();

  await page.getByRole("button", { name: "Open evidence" }).click();
  await expect(page.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Event timeline" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Inspector" })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Replay time" })).toBeVisible();
  await expectNoAxeViolations(page);
  await expectNoPageHorizontalOverflow(page);
  if (toggledToDark) await page.getByRole("button", { name: "Use light theme" }).click();
});
