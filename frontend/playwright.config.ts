import { defineConfig, devices } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';

// A new file for each run; never reuse a developer's database or servers.
const databasePath = process.env.E2E_DATABASE_PATH || join(homedir(), `procurem-playwright-${randomUUID()}`, 'test.sqlite');
const python = process.env.E2E_PYTHON || join(homedir(), 'venvs', 'procurem', 'bin', 'python');
process.env.E2E_DATABASE_PATH = databasePath;
process.env.E2E_PYTHON = python;
export default defineConfig({
  testDir: './e2e',
  workers: 1, // journeys mutate the same isolated seed
  use: { baseURL: 'http://127.0.0.1:13100', ...devices['Desktop Chrome'], screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  reporter: 'list',
  webServer: [
    {
      command: '"$E2E_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 18100',
      cwd: '../backend',
      env: { E2E_PYTHON: python, DATABASE_PATH: databasePath, SEED_ON_STARTUP: 'true', PYTHONPATH: '.' },
      url: 'http://127.0.0.1:18100/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 13100',
      env: { API_PROXY_TARGET: 'http://127.0.0.1:18100', NEXT_PUBLIC_API_URL: '' },
      url: 'http://127.0.0.1:13100/',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
