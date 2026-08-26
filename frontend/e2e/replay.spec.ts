import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";
import axe from "axe-core";

type ReplayRun = { runId: string };

async function replayRun(): Promise<ReplayRun> {
  return JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as ReplayRun;
}

/** Put the run back at its beginning, so a test never inherits where the last one stopped. */
async function resetReplaySession(page: Page, run: ReplayRun): Promise<void> {
  const tokenResponse = await page.request.get("/api/session");
  expect(tokenResponse.status()).toBe(200);
  const { token } = await tokenResponse.json() as { token: string };
  const headers = { "X-Workspace-Token": token };
  const verification = await page.request.post(`/api/runs/${encodeURIComponent(run.runId)}/replay/verify`, { headers });
  expect(verification.status()).toBe(200);
  expect((await verification.json()) as { matches: boolean }).toMatchObject({ matches: true });

  const response = await page.request.put(`/api/runs/${encodeURIComponent(run.runId)}/replay/session`, {
    headers,
    data: { positionAt: null, filters: { speed: 1 } },
  });
  expect(response.status()).toBe(200);
  expect(await response.json() as { playable: boolean; positionAt: string | null })
    .toMatchObject({ playable: true, positionAt: null });
}

async function openScene(page: Page, run: ReplayRun): Promise<void> {
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("region", { name: "Replay controls" })).toBeVisible();
  // The ribbon only reports a count once the day behind the scene has arrived.
  await expect(page.getByLabel(/^The day, [1-9]/)).toBeVisible();
}

async function expectNoAxeViolations(page: Page): Promise<void> {
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

async function expectNoPageHorizontalOverflow(page: Page): Promise<void> {
  const sizes = await page.evaluate(() => ({
    documentElement: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
    body: { scrollWidth: document.body.scrollWidth, clientWidth: document.body.clientWidth },
  }));
  expect(sizes.documentElement.scrollWidth, `documentElement widths: ${JSON.stringify(sizes.documentElement)}`).toBeLessThanOrEqual(sizes.documentElement.clientWidth);
  expect(sizes.body.scrollWidth, `body widths: ${JSON.stringify(sizes.body)}`).toBeLessThanOrEqual(sizes.body.clientWidth);
}

test("shows the flat, the resident in it, and what the day has them doing", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await openScene(page, run);

  const scene = page.getByRole("img", { name: /flat, seen from above/ });
  await expect(scene).toBeVisible();
  await expect(scene.locator(".scene-floor").first()).toBeVisible();
  await expect(scene.locator(".scene-avatar")).toHaveCount(1);
  await expect(scene.locator(".scene-furniture use").first()).toBeVisible();

  // The whole day is one bar, and every block on it is somewhere the viewer can jump to.
  const ribbon = page.getByLabel(/^The day, [1-9]/);
  const firstActivity = ribbon.getByRole("button").first();
  const label = await firstActivity.getAttribute("aria-label");
  await firstActivity.click();
  await expect(page.getByRole("heading", { level: 2 })).toContainText(/\w/);
  expect(label).toMatch(/^\d\d:\d\d, /);
});

test("plays in real time, tells the viewer what happens, and can be skipped past", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await openScene(page, run);
  const scrub = page.getByRole("slider", { name: "Replay time" });
  const start = await scrub.inputValue();

  await expect(page.getByLabel("Playback speed")).toHaveValue("1");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await expect.poll(() => scrub.inputValue()).not.toBe(start);
  await page.getByRole("button", { name: "Pause" }).click();

  // An activity that runs for hours is crossed with the control, not with the scrubber.
  const paused = Number(await scrub.inputValue());
  await page.getByRole("button", { name: "Skip ahead" }).click();
  await expect.poll(async () => Number(await scrub.inputValue())).toBeGreaterThan(paused);
  await expect(page.locator(".scene-beat")).toContainText(/\w/);
});

test("keeps the scene, its caption and its controls inside the viewport in dark theme", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await openScene(page, run);
  // The theme control lives in a sidebar the narrow layout collapses, so it is used when it is
  // there and the assertion holds either way.
  const darkTheme = page.getByRole("button", { name: "Use dark theme" });
  if (await darkTheme.isVisible()) await darkTheme.click();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");

  await expect(page.locator(".scene-canvas")).toBeVisible();
  await expect(page.locator(".scene-clock")).toContainText(/^\d\d:\d\d:\d\d$/);
  await expectNoPageHorizontalOverflow(page);
  await expectNoAxeViolations(page);
  const lightTheme = page.getByRole("button", { name: "Use light theme" });
  if (await lightTheme.isVisible()) await lightTheme.click();
});

test("returns to the instant the viewer left it at", async ({ page }) => {
  const run = await replayRun();
  await resetReplaySession(page, run);
  await openScene(page, run);
  const scrub = page.getByRole("slider", { name: "Replay time" });

  const target = page.getByLabel(/^The day, [1-9]/).getByRole("button").nth(2);
  await target.click();
  const chosen = await scrub.inputValue();
  expect(chosen).not.toBe("");
  // The save is debounced, so the reload has to come after the server has been told.
  await page.waitForTimeout(1_200);

  await page.reload();
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("region", { name: "Replay controls" })).toBeVisible();
  await expect.poll(() => page.getByRole("slider", { name: "Replay time" }).inputValue()).toBe(chosen);
});
