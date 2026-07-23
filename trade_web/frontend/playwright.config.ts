import { defineConfig, devices } from "@playwright/test";

// Playwright E2E config (frozen runner: `npm run test:e2e`).
//
// The observatory API is mocked via Playwright route interception (preferred for
// determinism per the task brief), so tests need only a static build served by
// `vite preview`. If Chromium cannot be downloaded in a restricted environment
// the specs self-skip (see tests/e2e/observatory.spec.ts) rather than failing
// unconditionally, and this config still exists so the command is stable.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
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
