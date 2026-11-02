/**
 * axe checks in every component state (Phases.md Phase 7 exit: no serious or critical
 * issues), light and dark, plus a sample host theme (Design.md §2).
 */
import { createRequire } from 'node:module';
import { expect, test, type Page } from '@playwright/test';
import { answer, mockApi, openWidget, type Scenario } from '../e2e/mock-api.ts';

const require = createRequire(import.meta.url);
const AXE_PATH = require.resolve('axe-core/axe.min.js');

interface AxeViolation {
  id: string;
  impact: string | null;
  help: string;
  nodes: Array<{ target: unknown }>;
}

async function seriousViolations(page: Page): Promise<AxeViolation[]> {
  // Let finite animations (120 ms message fade, 180 ms panel) settle so axe measures final colours.
  await page.waitForFunction(() => {
    const root = document.querySelector('pdk-assistant')?.shadowRoot;
    return (root?.getAnimations() ?? []).every(
      (a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity,
    );
  }, undefined, { polling: 100, timeout: 5_000 });
  await page.addScriptTag({ path: AXE_PATH });
  const violations = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (ctx: unknown, opts: unknown) => Promise<{ violations: AxeViolation[] }> } }).axe;
    const result = await axe.run(
      { include: [['pdk-assistant']] },
      { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } },
    );
    return result.violations;
  });
  return violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
}

async function send(page: Page, text: string): Promise<void> {
  await page.locator('pdk-assistant #pdk-composer').fill(text);
  await page.keyboard.press('Enter');
}

const STATES: Array<{ name: string; scenario: Scenario; act?: (page: Page) => Promise<void> }> = [
  { name: 'empty', scenario: {} },
  {
    name: 'answered with sources',
    scenario: { replies: [answer('a1', 2, 'Quiet hours are 10pm to 7am.', [['source', { document_id: 'd1', title: 'House rules (2026)' }]])] },
    act: (p) => send(p, 'quiet hours?'),
  },
  {
    name: 'answered without a source',
    scenario: { replies: [answer('a1', 2, 'I am not sure.')] },
    act: (p) => send(p, 'pool hours?'),
  },
  {
    name: 'request slip pending',
    scenario: {
      replies: [answer('a1', 2, 'Please review.', [['confirm.card', { id: 'c1', tool: 'create_request', summary: 'Leaking sink', expires_at: '2099-01-01T00:00:00Z' }]])],
    },
    act: (p) => send(p, 'sink leaking'),
  },
  {
    name: 'handoff waiting',
    scenario: { status: 'waiting', history: [{ id: 'm1', seq: 1, sender_role: 'user', content: 'Need a person' }] },
  },
  {
    name: 'staff active',
    scenario: { status: 'staff', history: [{ id: 'm1', seq: 1, sender_role: 'staff', content: 'Hi, I can help.' }] },
  },
  {
    name: 'emergency',
    scenario: { replies: [answer('a1', 2, 'Call 911 now.', [['handoff', { state: 'waiting' }]], { emergency: true })] },
    act: (p) => send(p, 'fire'),
  },
  {
    name: 'degraded',
    scenario: { replies: [answer('a1', 2, 'Common answer.', [], { degraded: true, code: 'BUDGET_DEGRADED' })] },
    act: (p) => send(p, 'hello'),
  },
  {
    name: 'provider unavailable',
    scenario: { replies: [{ kind: 'error', status: 503, code: 'PROVIDER_UNAVAILABLE' }] },
    act: (p) => send(p, 'hello'),
  },
  {
    name: 'closed',
    scenario: { status: 'closed', history: [{ id: 'm1', seq: 1, sender_role: 'staff', content: 'Done.' }] },
  },
];

for (const theme of ['light', 'dark'] as const) {
  for (const state of STATES) {
    test(`axe: ${state.name} (${theme})`, async ({ page }) => {
      await mockApi(page, state.scenario);
      await page.goto('/');
      if (theme === 'dark') {
        await page.locator('pdk-assistant').evaluate((el) => el.setAttribute('data-theme', 'dark'));
      }
      await page.locator('pdk-assistant .launcher').click();
      await page.locator('pdk-assistant .panel').waitFor();
      await state.act?.(page);
      await page.waitForTimeout(250);
      expect(await seriousViolations(page)).toEqual([]);
    });
  }
}

test('axe: launcher closed', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  expect(await seriousViolations(page)).toEqual([]);
});

test('axe: sample host theme keeps contrast', async ({ page }) => {
  await mockApi(page, { replies: [answer('a1', 2, 'Themed answer.')] });
  await page.goto('/');
  await page.addStyleTag({ content: 'pdk-assistant { --pdk-accent: #5B2A86; --pdk-on-accent: #FFFFFF; --pdk-radius-scale: 0.5; }' });
  await page.locator('pdk-assistant .launcher').click();
  await send(page, 'hi');
  await expect(page.locator('pdk-assistant .msg-assistant')).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test('reduced motion shows typing text instead of dots', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockApi(page);
  await openWidget(page);
  await page.route('**/v1/conversations/c1/messages', () => new Promise(() => {}));
  await send(page, 'hello');
  await expect(page.locator('pdk-assistant .typing-text')).toBeVisible();
  await expect(page.locator('pdk-assistant .typing .dot').first()).toBeHidden();
});
