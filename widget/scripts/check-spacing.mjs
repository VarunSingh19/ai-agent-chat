// Fails on raw px margins/paddings in widget source (Rules.md §4, Design.md §4).
// Spacing must come from the --pdk-s1..s6 tokens; 0 and env(safe-area-inset-*) fallbacks are
// allowed. Tokens are defined in src/styles/tokens.css.ts, the only exempt file.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const EXEMPT = new Set(['styles/tokens.css.ts']);
const RULE = /\b(margin|padding)(-(top|right|bottom|left|inline|block)(-(start|end))?)?\s*:\s*([^;}]*)/g;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (path.endsWith('.ts')) yield path;
  }
}

const problems = [];
for (const file of walk(root)) {
  const rel = relative(root, file).replaceAll('\\', '/');
  if (EXEMPT.has(rel)) continue;
  const lines = readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, i) => {
    for (const match of line.matchAll(RULE)) {
      const value = match[6] ?? '';
      if (/\d*\.?\d+(px|rem|em)\b/.test(value.replace(/(var|env)\([^)]*\)/g, ''))) {
        problems.push(`${rel}:${i + 1}: ${match[0].trim()}`);
      }
    }
  });
}

if (problems.length > 0) {
  console.error('Raw spacing values found (use --pdk-s1..s6):');
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('check-spacing: OK (margins and paddings use spacing tokens only)');
