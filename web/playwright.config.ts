import { defineConfig, devices } from "@playwright/test";

// Uses the system Google Chrome (channel "chrome"), so no browser download is needed. The server under test is the real
// `arven.web` API over a synthetic fixture (scripts/web_fixture_server.py) - never the real database.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8123", channel: "chrome", headless: true, trace: "off" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 900 } } },
    { name: "phone", use: { ...devices["Pixel 7"], channel: "chrome" } },
  ],
  webServer: {
    command: '"../.venv/Scripts/python.exe" ../scripts/web_fixture_server.py 8123',
    url: "http://127.0.0.1:8123/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
    env: { PYTHONPATH: "../src" },
  },
});
