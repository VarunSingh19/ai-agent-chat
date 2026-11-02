import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import { devIssuer } from './dev/dev-issuer.ts';

const widgetRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  plugins: [devIssuer(`${widgetRoot}.dev`)],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Same-origin API in local development: the dev harness calls /v1 on this server.
    proxy: { '/v1': 'http://127.0.0.1:8000' },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    lib: {
      entry: 'src/pdk-assistant.ts',
      formats: ['es'],
      fileName: () => 'pdk-assistant.js',
    },
  },
  test: {
    include: ['tests/unit/**/*.test.ts'],
    environment: 'node',
  },
});
