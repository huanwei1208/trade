import { defineConfig, devices } from "@playwright/test";

// Accessibility config (frozen runner: `npm run test:a11y`). Kept as an
// independently executable target even though it is Playwright-driven (axe). It
// runs only the a11y specs so it can be invoked without the full E2E flow.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.a11y\.spec\.ts/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
