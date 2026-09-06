import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

// Playwright sets FORCE_COLOR for children; avoid conflicting inherited settings.
delete process.env.NO_COLOR;

const python =
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python";

export default defineConfig({
  testDir: "./tests",
  testMatch: "smoke.spec.mjs",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
  webServer: [
    {
      command:
        "node apps/web/node_modules/next/dist/bin/next start apps/web --hostname 127.0.0.1",
      url: "http://127.0.0.1:3000/health",
      reuseExistingServer: false,
      env: { NEXT_TELEMETRY_DISABLED: "1" },
    },
    {
      command: `"${resolve(python)}" -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000`,
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
    },
  ],
});
