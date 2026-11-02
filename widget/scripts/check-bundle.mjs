// Bundle size budget (Phases.md Phase 7: starting target <= 60 KB gzipped).
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const BUDGET_BYTES = 60 * 1024;
const file = new URL('../dist/pdk-assistant.js', import.meta.url);
const raw = readFileSync(file);
const gz = gzipSync(raw, { level: 9 }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
console.log(`dist/pdk-assistant.js: ${kb(raw.length)} raw, ${kb(gz)} gzipped (budget ${kb(BUDGET_BYTES)})`);
if (gz > BUDGET_BYTES) {
  console.error('check-bundle: FAIL, over budget');
  process.exit(1);
}
console.log('check-bundle: OK');
