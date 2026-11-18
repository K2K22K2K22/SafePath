const { test, expect } = require("@playwright/test");

const { mockApplication, submitRoute } = require("./fixtures");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.clear());
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition() {} },
    });
  });
  await page.emulateMedia({ colorScheme: "light" });
});

test("renders every route and changes the selected route", async ({ page }) => {
  await mockApplication(page);
  await page.goto("/");
  await submitRoute(page);

  await expect(page.locator(".leaflet-route-pane path")).toHaveCount(2);
  await expect(page.locator("[data-route-card][data-selected='true']")).toHaveAttribute(
    "data-route-id",
    "route-1",
  );

  await page.locator("button[data-route-id='route-2']").click();

  await expect(page.locator("[data-route-card][data-selected='true']")).toHaveAttribute(
    "data-route-id",
    "route-2",
  );
  await expect(page.locator(".leaflet-route-pane path").nth(1)).toHaveAttribute(
    "stroke-width",
    "8",
  );

  await page.getByRole("button", { name: "Find routes" }).click();
  await expect(page.locator(".leaflet-route-pane path")).toHaveCount(2);
});

test("keeps the heatmap independent from route layers", async ({ page }) => {
  await mockApplication(page);
  await page.goto("/");
  await submitRoute(page);

  await page.getByRole("button", { name: "Safety heatmap" }).click();

  await expect(page.locator(".leaflet-heatmap-layer")).toHaveCount(1);
  await expect(page.locator(".leaflet-route-pane path")).toHaveCount(2);
  await expect(page.locator("#heatmap-toggle")).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Safety heatmap" }).click();

  await expect(page.locator(".leaflet-heatmap-layer")).toHaveCount(0);
  await expect(page.locator(".leaflet-route-pane path")).toHaveCount(2);
});

test("shows an empty heatmap state without creating a layer", async ({ page }) => {
  await mockApplication(page, { heatmapPoints: [] });
  await page.goto("/");

  await page.getByRole("button", { name: "Safety heatmap" }).click();

  await expect(page.locator("#heatmap-status")).toHaveText(
    "No bundled incident records are available.",
  );
  await expect(page.locator(".leaflet-heatmap-layer")).toHaveCount(0);
});

test("switches map tiles without losing route selection", async ({ page }) => {
  await mockApplication(page);
  await page.goto("/");
  await submitRoute(page);
  await page.locator("button[data-route-id='route-2']").click();

  await page.getByRole("button", { name: "Switch to dark theme" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("[data-route-card][data-selected='true']")).toHaveAttribute(
    "data-route-id",
    "route-2",
  );
  await expect(page.locator(".leaflet-route-pane path")).toHaveCount(2);
  await expect(page.locator(".leaflet-tile-pane img").first()).toHaveAttribute(
    "src",
    /dark_all/,
  );
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("safepath-theme")))
    .toBe("dark");
});

test("shows a recoverable route API error state", async ({ page }) => {
  await mockApplication(page, { routeStatus: 503 });
  await page.goto("/");

  await page.getByLabel("Starting location").fill("Starting point");
  await page.getByLabel("Destination", { exact: true }).fill("Destination");
  await page.getByRole("button", { name: "Find routes" }).click();

  await expect(page.locator("#route-status")).toContainText("Road data unavailable.");
  await expect(page.locator("[data-route-card]")).toHaveCount(0);
  await expect(page.locator("#route-empty-state")).toBeVisible();
});

test("loads without console errors and avoids horizontal overflow", async ({ page }) => {
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await mockApplication(page);
  await page.goto("/");
  await submitRoute(page);

  await expect
    .poll(() =>
      page.evaluate(() => ({
        viewport: window.innerWidth,
        content: document.documentElement.scrollWidth,
      })),
    )
    .toEqual(
      expect.objectContaining({
        content: await page.evaluate(() => window.innerWidth),
      }),
    );
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
