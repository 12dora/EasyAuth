import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_FULLSTACK_PORT ?? "8001";
const baseURL = `http://127.0.0.1:${port}`;
const sqlitePath = process.env.EASYAUTH_PLAYWRIGHT_SQLITE_PATH ?? `/tmp/easyauth-playwright-${port}.sqlite3`;

export default defineConfig({
  testDir: "./e2e-fullstack",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: {
    command: [
      "cd ..",
      `rm -f "${sqlitePath}"`,
      `DATABASE_URL="" EASYAUTH_SQLITE_PATH="${sqlitePath}" .venv/bin/python manage.py migrate --noinput`,
      `DATABASE_URL="" EASYAUTH_SQLITE_PATH="${sqlitePath}" .venv/bin/python manage.py runserver 127.0.0.1:${port} --noreload`,
    ].join(" && "),
    url: `${baseURL}/health/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
