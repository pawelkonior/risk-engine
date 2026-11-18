import { defineConfig, devices } from '@playwright/test';

function port(value: string | undefined, fallback: number): number {
  const resolved = Number(value ?? fallback);
  if (!Number.isInteger(resolved) || resolved < 1024 || resolved > 65535) {
    throw new Error('E2E ports must be integers between 1024 and 65535');
  }
  return resolved;
}

const externalBaseURL = process.env['PLAYWRIGHT_BASE_URL'];
const apiPort = port(process.env['E2E_API_PORT'], 8001);
const webPort = port(process.env['E2E_WEB_PORT'], 4173);
const localBaseURL = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  globalTimeout: 5 * 60_000,
  expect: { timeout: 7_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  outputDir: 'test-results',
  use: {
    baseURL: externalBaseURL ?? localBaseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
  ],
  ...(externalBaseURL
    ? {}
    : {
        webServer: [
          {
            name: 'isolated-api',
            command: 'uv run --project ../api --locked python scripts/e2e-api.py',
            url: `http://127.0.0.1:${apiPort}/health/ready`,
            env: { E2E_API_PORT: String(apiPort) },
            timeout: 60_000,
            reuseExistingServer: false,
            stdout: 'ignore' as const,
            stderr: 'pipe' as const,
            gracefulShutdown: { signal: 'SIGTERM' as const, timeout: 5_000 },
          },
          {
            name: 'production-web',
            command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${webPort} --strictPort`,
            url: localBaseURL,
            env: {
              API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
              VITE_API_BASE_URL: '/api/v1',
            },
            timeout: 60_000,
            reuseExistingServer: false,
            stdout: 'ignore' as const,
            stderr: 'pipe' as const,
            gracefulShutdown: { signal: 'SIGTERM' as const, timeout: 5_000 },
          },
        ],
      }),
});
