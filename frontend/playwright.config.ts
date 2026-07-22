import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: "http://127.0.0.1:8766",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 5"] } },
  ],
  webServer: {
    command: "uv --project .. run smart-home-sim-app --workspace ../reports/e2e-workspace --name E2E --port 8766 --no-browser",
    url: "http://127.0.0.1:8766/api/session",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { PYTHONPATH: "../src", UV_NO_EDITABLE: "1" },
  },
});
