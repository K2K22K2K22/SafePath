const { expect } = require("@playwright/test");

const routePayload = {
  origin: { lat: 28.4748, lon: 77.4764 },
  destination: { lat: 28.48, lon: 77.482 },
  route_count: 2,
  routes: [
    {
      id: "route-1",
      type: "safest",
      labels: ["safest"],
      algorithm: "modified_astar",
      geometry: [
        [28.4748, 77.4764],
        [28.477, 77.479],
        [28.48, 77.482],
      ],
      distance_meters: 1336.6,
      duration_seconds: 240,
      risk_score: 0.172021,
      safety_score: 83,
      risk_level: "low",
      risk_data_available: true,
      incident_coverage_ratio: 1,
      explanation:
        "Lowest modeled risk among the generated, eligible routes.",
    },
    {
      id: "route-2",
      type: "shortest",
      labels: ["shortest", "balanced"],
      algorithm: "dijkstra",
      geometry: [
        [28.4748, 77.4764],
        [28.475, 77.478],
        [28.476, 77.479],
        [28.48, 77.482],
      ],
      distance_meters: 527.2,
      duration_seconds: 90,
      risk_score: 0.322668,
      safety_score: 68,
      risk_level: "moderate",
      risk_data_available: true,
      incident_coverage_ratio: 1,
      explanation:
        "Minimum road-edge distance in the loaded graph. Balanced distance and risk objective.",
    },
  ],
};

const heatmapPayload = {
  points: [
    { lat: 28.4748, lon: 77.4764, intensity: 0.8 },
    { lat: 28.477, lon: 77.479, intensity: 0.4 },
  ],
  radius_meters: 200,
  record_count: 2,
  source: "bundled_csv",
};

const transparentPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XwWjJwAAAABJRU5ErkJggg==",
  "base64",
);

async function mockApplication(
  page,
  { routeStatus = 200, heatmapPoints = heatmapPayload.points } = {},
) {
  await page.route("**/api/geocode/**", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q");
    const location =
      query === "Destination"
        ? { lat: 28.48, lon: 77.482, label: "Destination" }
        : { lat: 28.4748, lon: 77.4764, label: "Starting point" };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ results: [location], source: "nominatim" }),
    });
  });

  await page.route("**/api/routes/**", async (route) => {
    await route.fulfill({
      status: routeStatus,
      contentType: "application/json",
      body: JSON.stringify(
        routeStatus === 200
          ? routePayload
          : { detail: "Road data unavailable." },
      ),
    });
  });

  await page.route("**/api/safety-heatmap/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...heatmapPayload,
        points: heatmapPoints,
        record_count: heatmapPoints.length,
      }),
    });
  });

  await page.route(
    /tile\.openstreetmap\.org|basemaps\.cartocdn\.com/,
    async (route) => {
      await route.fulfill({ contentType: "image/png", body: transparentPng });
    },
  );
}

async function submitRoute(page) {
  await page.getByLabel("Starting location").fill("Starting point");
  await page.getByLabel("Destination", { exact: true }).fill("Destination");
  await page.getByRole("button", { name: "Find routes" }).click();
  await expect(page.locator("[data-route-card]")).toHaveCount(2);
}

module.exports = {
  heatmapPayload,
  mockApplication,
  routePayload,
  submitRoute,
};
