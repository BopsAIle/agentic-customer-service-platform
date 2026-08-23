import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./e2e/tests",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    launchOptions: process.env.PLAYWRIGHT_CHROME_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH }
      : undefined,
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
