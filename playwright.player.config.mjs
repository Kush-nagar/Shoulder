import { loadEnvFile } from "node:process";
import { defineConfig } from "@playwright/test";
import smoke from "./playwright.config.mjs";

loadEnvFile("apps/web/.env.local");
if (
  process.env.SUPABASE_URL !== "http://127.0.0.1:54321" ||
  process.env.APP_ORIGIN !== "http://127.0.0.1:3000"
) {
  throw new Error("Player tests require the isolated loopback stack");
}
if (process.env.R2_ENDPOINT_URL !== "http://127.0.0.1:9000") {
  throw new Error("Player tests require the local MinIO endpoint");
}

export default defineConfig({
  ...smoke,
  testMatch: "player.spec.mjs",
  // Each test generates and publishes a real fixture clip with ffmpeg.
  timeout: 120000,
  use: {
    baseURL: process.env.APP_ORIGIN,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: smoke.webServer.map((server) => ({
    ...server,
    env: {
      ...server.env,
      SUPABASE_AUTH_ISSUER: `${process.env.SUPABASE_URL}/auth/v1`,
      // scripts/check-player.ps1 provisions these per run; never stored.
      DATABASE_URL: process.env.DATABASE_URL ?? "",
      OPERATOR_DATABASE_URL: process.env.OPERATOR_DATABASE_URL ?? "",
      OPERATOR_BOOTSTRAP_TOKEN: process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
      R2_ENDPOINT_URL: process.env.R2_ENDPOINT_URL ?? "",
      R2_BUCKET: process.env.R2_BUCKET ?? "",
      R2_REGION: process.env.R2_REGION ?? "auto",
      R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID ?? "",
      R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY ?? "",
    },
    stdout: "ignore",
    stderr: "ignore",
  })),
});
