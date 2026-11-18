const { defineConfig, devices } = require("@playwright/test");

const pythonExecutable = process.env.SAFEPATH_PYTHON || "venv/bin/python";

module.exports = defineConfig({
  testDir: "./web/e2e",
  timeout: 30000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:8000",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${pythonExecutable} manage.py runserver 127.0.0.1:8000 --noreload`,
    env: {
      DATABASE_URL: "",
      DJANGO_DEBUG: "True",
      SAFEPATH_DATABASE_PATH: "/tmp/safepath-e2e.sqlite3",
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
    url: "http://127.0.0.1:8000/health/",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
