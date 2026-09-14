import { defineConfig } from "@playwright/test";
import player from "./playwright.player.config.mjs";

export default defineConfig({
  ...player,
  testMatch: "marking.spec.mjs",
});
