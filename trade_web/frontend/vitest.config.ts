import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vitest config for observatory unit tests (frozen runner: `npm run test:unit`).
// Uses jsdom so React components can render without a browser download, keeping
// test:unit runnable in restricted/headless environments.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Playwright specs live under tests/e2e — keep them out of Vitest.
    exclude: ["node_modules/**", "dist/**", "tests/e2e/**"],
  },
});
