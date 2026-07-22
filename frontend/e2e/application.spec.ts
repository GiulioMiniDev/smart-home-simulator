import { expect, test } from "@playwright/test";
import axe from "axe-core";

test("creates a durable home and keeps the application accessible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Good evidence starts with inspectable inputs." })).toBeVisible();
  if (await page.getByRole("button", { name: "Open navigation" }).isVisible()) {
    await page.getByRole("button", { name: "Open navigation" }).click();
  }
  await page.getByRole("link", { name: "Homes" }).click();
  await page.getByRole("button", { name: "New home" }).first().click();
  const homeName = `E2E home ${Date.now()}`;
  await page.getByRole("textbox", { name: "Name", exact: true }).fill(homeName);
  await page.getByLabel("Description").fill("Automated application acceptance");
  await page.getByRole("button", { name: "Create home" }).click();
  await expect(page.getByRole("heading", { name: homeName, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run simulation" })).toBeDisabled();

  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    const result = await (window as typeof window & { axe: { run: (root: Document) => Promise<{ violations: unknown[] }> } }).axe.run(document);
    return result.violations;
  });
  expect(violations).toEqual([]);
});

test("mobile layout has no page-level horizontal overflow", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile"), "mobile project only");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
