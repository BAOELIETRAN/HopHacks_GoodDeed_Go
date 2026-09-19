import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const PORT = 8002;

// Config is re-evaluated in each worker; ??= keeps one database per run.
process.env.E2E_DB ??= join(tmpdir(), `gooddeed-e2e-${Date.now()}.db`);

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.mjs",
  outputDir: "./test-results",
  workers: 1, // one shared database
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: "msedge",
    viewport: { width: 390, height: 844 },
    permissions: ["camera", "geolocation"],
    geolocation: { latitude: 39.3299, longitude: -76.6205 },
    launchOptions: {
      // A synthetic camera (a moving test pattern) and auto-accepted permission,
      // so the real getUserMedia path runs with no hardware.
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    // The backend serves the frontend from the same origin, so this is the whole app.
    command: `.venv\\bin\\python.exe -m uvicorn backend.main:app --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/health`,
    // Pinned empty on purpose: a developer's .env holds a real DATABASE_URL (production
    // Postgres) and paid API keys, and python-dotenv never overrides a variable that is
    // already set -- even to "". This run must never touch either.
    env: {
      DATABASE_URL: "",
      OPENAI_API_KEY: "",
      GOOGLE_MAPS_API_KEY: "",
      GOODDEED_USE_MOCKS: "1",
      GOODDEED_DB_PATH: process.env.E2E_DB,
    },
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
