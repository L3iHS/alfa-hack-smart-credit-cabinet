import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL,
    baseURL: process.env.BASE_URL || "http://localhost:8080",
    viewport: { width: 1366, height: 768 },
    trace: "retain-on-failure",
  },
  reporter: "list",
});
