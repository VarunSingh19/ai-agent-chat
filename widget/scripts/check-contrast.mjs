// Re-checks the Design.md §2 contrast minimums against PALETTE in src/styles/tokens.css.ts.
// Body text pairs need >= 4.5:1; UI boundaries (borders, focus ring) need >= 3:1.
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/styles/tokens.css.ts', import.meta.url), 'utf8');

function scheme(name) {
  const block = source.match(new RegExp(`${name}:\\s*\\{([^}]*)\\}`));
  if (!block) throw new Error(`PALETTE.${name} not found in tokens.css.ts`);
  const tokens = {};
  for (const [, token, hex] of block[1].matchAll(/'(--pdk-[\w-]+)':\s*'#([0-9A-Fa-f]{6})'/g)) {
    tokens[token] = hex;
  }
  return tokens;
}

function luminance(hex) {
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

// [foreground, background, minimum, use]
const PAIRS = [
  ['--pdk-text', '--pdk-bg', 4.5, 'body text on panel'],
  ['--pdk-text', '--pdk-surface', 4.5, 'assistant bubble, composer'],
  ['--pdk-text', '--pdk-staff-bg', 4.5, 'staff bubble'],
  ['--pdk-text-muted', '--pdk-bg', 4.5, 'timestamps, hints'],
  ['--pdk-text-muted', '--pdk-surface', 4.5, 'hints on surface'],
  ['--pdk-on-accent', '--pdk-accent', 4.5, 'user bubble, primary button'],
  ['--pdk-warn-text', '--pdk-warn-bg', 4.5, 'handoff waiting, degraded'],
  ['--pdk-ok', '--pdk-bg', 4.5, 'confirmed state'],
  ['--pdk-ok', '--pdk-surface', 4.5, 'confirmed state on slip stub'],
  ['--pdk-danger', '--pdk-bg', 3, 'error icon, emergency accent bar'],
  ['--pdk-border', '--pdk-bg', 3, 'input borders'],
  ['--pdk-border', '--pdk-surface', 3, 'composer input border'],
  ['--pdk-focus', '--pdk-bg', 3, 'focus ring'],
  ['--pdk-focus', '--pdk-surface', 3, 'focus ring on surface'],
];

let failed = false;
for (const name of ['light', 'dark']) {
  const t = scheme(name);
  for (const [fg, bg, min, use] of PAIRS) {
    if (!t[fg] || !t[bg]) {
      console.error(`${name}: missing token ${t[fg] ? bg : fg}`);
      failed = true;
      continue;
    }
    const r = ratio(t[fg], t[bg]);
    const ok = r >= min;
    if (!ok) failed = true;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name.padEnd(5)} ${fg} on ${bg}: ${r.toFixed(2)}:1 (min ${min}) ${use}`);
  }
}
if (failed) process.exit(1);
console.log('check-contrast: OK');
