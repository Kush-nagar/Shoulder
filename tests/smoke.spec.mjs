import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("local health, approved vectors, self-hosted font, and accessible shell", async ({
  page,
  request,
}, testInfo) => {
  for (const url of [
    "http://127.0.0.1:3000/health",
    "http://127.0.0.1:8000/health",
  ]) {
    const response = await request.get(url);
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  }
  const urls = [];
  const errors = [];
  page.on("request", (request) => urls.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  const sizes = [
    [320, 568],
    [360, 800],
    [390, 844],
    [430, 932],
    [768, 1024],
    [1024, 768],
    [1280, 800],
    [1440, 900],
    [1920, 1080],
  ];
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.evaluate(() => document.fonts.ready);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "A quiet space for development.",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`shell-${width}.png`),
      fullPage: true,
    });
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  for (const [index, name] of [
    "shoulder-wordmark",
    "shoulder-mark",
  ].entries()) {
    const source = readFileSync(`assets/brand/${name}.svg`, "utf8");
    const expectedPaths = [...source.matchAll(/\sd="([^"]+)"/g)].map(
      (match) => match[1],
    );
    const svg = page
      .getByRole("img", { name: "Shoulder", exact: true })
      .nth(index);
    expect(
      await svg
        .locator("path")
        .evaluateAll((paths) => paths.map((path) => path.getAttribute("d"))),
    ).toEqual(expectedPaths);
    expect(await svg.getAttribute("viewBox")).toBe(
      name === "shoulder-mark" ? "0 0 24 24" : "0 0 70 24",
    );
  }
  expect(await page.locator("img").count()).toBe(0);
  expect(
    urls.filter((url) => !url.startsWith("http://127.0.0.1:3000/")),
  ).toEqual([]);
  expect(urls.some((url) => url.endsWith(".woff2"))).toBe(true);
  expect(
    await page.evaluate(async () => {
      const family = getComputedStyle(document.body)
        .fontFamily.split(",", 1)[0]
        .trim();
      await Promise.all(
        [400, 500, 600].map((weight) =>
          document.fonts.load(`${weight} 16px ${family}`),
        ),
      );
      return [400, 500, 600].every((weight) =>
        document.fonts.check(`${weight} 16px ${family}`),
      );
    }),
  ).toBe(true);
  const license = await request.get("/licenses/inter-tight-OFL.txt");
  expect(await license.text()).toBe(
    readFileSync(
      "apps/web/node_modules/@fontsource-variable/inter-tight/LICENSE",
      "utf8",
    ),
  );
  expect(errors).toEqual([]);
});
