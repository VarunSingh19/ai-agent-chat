import { defineConfig } from '@playwright/test';

// Locally: the installed Microsoft Edge (no browser download). CI: Playwright's Chromium.
const channel = process.env['CI'] ? undefined : 'msedge';

export default defineConfig({
  testDir: 'tests',
  testMatch: ['e2e/**/*.spec.ts', 'a11y/**/*.spec.ts'],
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    channel,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'mobile-320', use: { viewport: { width: 320, height: 640 } } },
    { name: 'desktop-1280', use: { viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: 'npx vite',
    url: 'http://127.0.0.1:5173/dev/jwks.json',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
