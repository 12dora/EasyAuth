import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_FULLSTACK_PORT ?? "8010";
const baseURL = `http://127.0.0.1:${port}`;
const sqlitePath =
  process.env.EASYAUTH_PLAYWRIGHT_SQLITE_PATH ?? `/tmp/easyauth-playwright-${port}.sqlite3`;
const downstreamPort = process.env.EASYAUTH_E2E_DOWNSTREAM_PORT ?? "18010";
const downstreamSecret = process.env.EASYAUTH_E2E_DOWNSTREAM_SECRET ?? "whsec_e2e_handover";
const downstreamHealth = `http://127.0.0.1:${downstreamPort}/health`;

const djangoEnv = [
  'DJANGO_SETTINGS_MODULE="easyauth.config.settings.e2e"',
  "DJANGO_DEBUG=1",
  'DATABASE_URL=""',
  `EASYAUTH_SQLITE_PATH="${sqlitePath}"`,
  'EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS="127.0.0.1"',
  `EASYAUTH_E2E_DOWNSTREAM_PORT="${downstreamPort}"`,
  `EASYAUTH_E2E_DOWNSTREAM_SECRET="${downstreamSecret}"`,
  `EASYAUTH_E2E_MANAGER_USER="${process.env.EASYAUTH_E2E_MANAGER_USER ?? "manager"}"`,
  `EASYAUTH_E2E_SUBJECT_USER="${process.env.EASYAUTH_E2E_SUBJECT_USER ?? "e2e-subject"}"`,
].join(" ");

export default defineConfig({
  testDir: "./e2e-fullstack",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: [
        "cd ..",
        [
          `EASYAUTH_E2E_DOWNSTREAM_PORT="${downstreamPort}"`,
          `EASYAUTH_E2E_DOWNSTREAM_SECRET="${downstreamSecret}"`,
          "PYTHONPATH=sdk/python/src",
          ".venv/bin/python scripts/e2e_handover_downstream.py",
        ].join(" "),
      ].join(" && "),
      url: downstreamHealth,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: [
        "cd ..",
        `rm -f "${sqlitePath}"`,
        `${djangoEnv} .venv/bin/python manage.py migrate --noinput`,
        `${djangoEnv} .venv/bin/python manage.py seed_handover_e2e`,
        `${djangoEnv} .venv/bin/python manage.py runserver 127.0.0.1:${port} --noreload`,
      ].join(" && "),
      url: `${baseURL}/health/`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
