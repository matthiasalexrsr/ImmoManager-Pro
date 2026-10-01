import { defineConfig } from '@playwright/test';

if (!process.env.IMMO_E2E_URL) {
  throw new Error('Run npm run test:e2e so the isolated test server is started.');
}

export default defineConfig({
  testDir: '.',
  // The separate extension keeps browser tests out of Vitest's unit-test discovery.
  testMatch: process.env.IMMO_E2E_MODE === 'setup' ? '**/auth.pw.mjs' : '**/*.pw.mjs',
  testIgnore: process.env.IMMO_E2E_MODE === 'setup' ? [] : ['**/auth.pw.mjs'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: process.env.IMMO_E2E_MODE === 'setup' ? '../test-results/auth' : '../test-results',
  reporter: [
    ['list'],
    ['html', { outputFolder: process.env.IMMO_E2E_MODE === 'setup' ? '../playwright-report/auth' : '../playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: process.env.IMMO_E2E_URL,
    browserName: 'chromium',
    // Windows can reuse installed Edge; CI uses Playwright's pinned Chromium.
    channel: process.env.IMMO_E2E_CHANNEL || 'chromium',
    viewport: { width: 1440, height: 1000 },
    locale: 'de-DE',
    timezoneId: 'Europe/Berlin',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
