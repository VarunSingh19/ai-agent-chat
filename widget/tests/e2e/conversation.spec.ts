/**
 * Phase 7 exit criteria (Phases.md): a full conversation by keyboard alone, XSS rendered as
 * text, layout at 320 px and 1280 px, and the error/handoff/emergency/closed states.
 */
import { expect, test } from '@playwright/test';
import { NOW, answer, mockApi, openWidget } from './mock-api.ts';

const SOURCES: Array<[string, Record<string, unknown>]> = [
  ['source', { document_id: 'd1', title: 'House rules (2026)', section: 'Quiet hours', page: 3 }],
  ['source', { document_id: 'd2', title: 'Lease addendum' }],
  ['source', { document_id: 'd3', title: 'Move-in guide' }],
  ['source', { document_id: 'd4', title: 'Parking policy' }],
];

const CARD: Array<[string, Record<string, unknown>]> = [
  ['tool.start', { name: 'create_request' }],
  ['confirm.card', { id: 'conf-1', tool: 'create_request', summary: 'Kitchen sink is leaking under the cabinet', args_hash: 'abc123', expires_at: '2099-01-01T00:00:00Z' }],
];

test('full conversation by keyboard: question, source, request slip, ask for a person', async ({ page }) => {
  const captured = await mockApi(page, {
    replies: [
      answer('a1', 2, 'Quiet hours are 10pm to 7am.', SOURCES),
      answer('a2', 4, 'I can send this request for you.', CARD),
    ],
  });
  await page.goto('/');

  // Open by keyboard; focus moves into the panel.
  await page.locator('pdk-assistant .launcher').focus();
  await page.keyboard.press('Enter');
  const composer = page.locator('pdk-assistant #pdk-composer');
  await expect(composer).toBeFocused();

  // Ask a question; Enter sends on desktop pointers.
  await page.keyboard.type('What are quiet hours?');
  await page.keyboard.press('Enter');
  await expect(page.locator('pdk-assistant .msg-assistant .bubble').first()).toHaveText('Quiet hours are 10pm to 7am.');
  await expect(page.locator('pdk-assistant .chip', { hasText: 'From: House rules (2026)' })).toBeVisible();
  await expect(page.locator('pdk-assistant .chip', { hasText: '+1 more' })).toBeVisible();

  // Reach a source chip by keyboard and open it in the host.
  const chip = page.locator('pdk-assistant .chip', { hasText: 'House rules (2026)' });
  for (let i = 0; i < 12 && !(await chip.evaluate((el) => el.matches(':focus'))); i++) {
    await page.keyboard.press('Shift+Tab');
  }
  await expect(chip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#last-event')).toHaveText(/pdk-open-source .*"document_id":"d1"/);

  // Report a problem; the slip takes focus and Send request is one Tab away.
  await composer.focus();
  await page.keyboard.type('My kitchen sink is leaking');
  await page.keyboard.press('Enter');
  const heading = page.locator('pdk-assistant [data-slip-heading="conf-1"]');
  await expect(heading).toBeFocused();
  await expect(page.locator('pdk-assistant .slip')).toContainText('Kitchen sink is leaking under the cabinet');
  await page.keyboard.press('Tab');
  await expect(page.locator('pdk-assistant [data-slip-send]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('pdk-assistant .slip-result')).toContainText('Request sent');
  await expect(page.locator('pdk-assistant .slip-result')).toContainText('Reference WO-1042');

  const confirmCall = captured.find((c) => c.path === '/v1/confirmations/conf-1/confirm');
  expect(confirmCall?.headers['idempotency-key']).toBeTruthy();
  expect(confirmCall?.body).toBe('{"args_hash":"abc123"}');
  const sends = captured.filter((c) => c.method === 'POST' && c.path.endsWith('/messages'));
  expect(new Set(sends.map((c) => c.headers['idempotency-key'])).size).toBe(2);
  expect(sends.every((c) => c.headers['authorization']?.startsWith('Bearer '))).toBe(true);

  // Ask for a person from the header button.
  const talk = page.locator('pdk-assistant .header .btn', { hasText: 'Talk to a person' });
  await talk.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('pdk-assistant .banner-waiting')).toContainText('A staff member will reply here.');
  await expect(page.locator('pdk-assistant .system-event').last()).toHaveText('You asked for a person. A staff member will reply here.');

  // Esc closes and focus returns to the launcher.
  await composer.focus();
  await page.keyboard.press('Escape');
  await expect(page.locator('pdk-assistant .launcher')).toBeFocused();
});

test('model output with HTML renders as inert text (LLM10)', async ({ page }) => {
  const payload = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>';
  await mockApi(page, {
    replies: [{ kind: 'sse', events: [
      ['message.start', { id: 'a1', seq: 2 }],
      ['token', { text: payload }],
      ['message.end', { id: 'a1', seq: 2, usage_public: { degraded: false } }],
    ] }],
  });
  await openWidget(page);
  await page.locator('pdk-assistant #pdk-composer').fill('hi');
  await page.locator('pdk-assistant .composer button[type=submit]').click();
  await expect(page.locator('pdk-assistant .msg-assistant .bubble')).toHaveText(payload);
  await expect(page.locator('pdk-assistant .bubble img, pdk-assistant .bubble script')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
});

test('layout fits the viewport with no horizontal scroll', async ({ page }, info) => {
  await mockApi(page, { replies: [answer('a1', 2, 'A long answer '.repeat(40).trim(), SOURCES)] });
  await openWidget(page);
  await page.locator('pdk-assistant #pdk-composer').fill('hello');
  await page.locator('pdk-assistant .composer button[type=submit]').click();
  await expect(page.locator('pdk-assistant .msg-assistant')).toBeVisible();

  const box = await page.locator('pdk-assistant .panel').boundingBox();
  const scrollFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(scrollFits).toBe(true);
  if (info.project.name === 'desktop-1280') {
    expect(box?.width).toBe(380);
    expect(box?.height).toBe(600);
  } else {
    expect(box?.width).toBe(320);
    const panelOverflow = await page.locator('pdk-assistant .log').evaluate((el) => el.scrollWidth <= el.clientWidth);
    expect(panelOverflow).toBe(true);
  }
});

test('rate limit and provider outage show plain error rows (states 16, 17)', async ({ page }) => {
  await mockApi(page, {
    replies: [
      { kind: 'error', status: 429, code: 'RATE_LIMITED', headers: { 'Retry-After': '9' } },
      { kind: 'error', status: 503, code: 'PROVIDER_UNAVAILABLE' },
    ],
  });
  await openWidget(page);
  const composer = page.locator('pdk-assistant #pdk-composer');
  await composer.fill('one');
  await page.keyboard.press('Enter');
  await expect(page.locator('pdk-assistant .error-row')).toContainText(/You’re sending messages quickly\. Try again in \d seconds\./);

  await composer.fill('two');
  await page.keyboard.press('Enter');
  const row = page.locator('pdk-assistant .error-row').last();
  await expect(row).toContainText('The assistant isn’t available right now.');
  await expect(row.locator('.btn', { hasText: 'Open the request form' })).toBeVisible();
  await expect(row.locator('.btn', { hasText: 'Ask staff' })).toBeVisible();
});

test('a stream that drops mid-answer resumes from history (state 18)', async ({ page }) => {
  await mockApi(page, {
    replies: [{ kind: 'sse', events: [
      ['message.start', { id: 'a1', seq: 2 }],
      ['token', { text: 'Quiet hours' }],
    ] }],
    resumeHistory: [
      { id: 'u1', seq: 1, sender_role: 'user', content: 'quiet hours?' },
      { id: 'a1', seq: 2, sender_role: 'assistant', content: 'Quiet hours are 10pm to 7am.' },
    ],
  });
  await openWidget(page);
  await page.locator('pdk-assistant #pdk-composer').fill('quiet hours?');
  await page.keyboard.press('Enter');
  await expect(page.locator('pdk-assistant .msg-assistant .bubble')).toHaveText('Quiet hours are 10pm to 7am.');
  await expect(page.locator('pdk-assistant .msg-user')).toHaveCount(1);
  await expect(page.locator('pdk-assistant .error-row')).toHaveCount(0);
});

test('emergency answer pins a non-dismissible alert banner (state 14)', async ({ page }) => {
  await mockApi(page, {
    replies: [answer('a1', 2, 'If you smell gas, leave now and call 911.', [['handoff', { state: 'waiting', reason: 'emergency' }]], { degraded: false, emergency: true })],
  });
  await openWidget(page);
  await page.locator('pdk-assistant #pdk-composer').fill('I smell gas');
  await page.keyboard.press('Enter');
  const banner = page.locator('pdk-assistant .banner-emergency');
  await expect(banner).toHaveAttribute('role', 'alert');
  await expect(banner.locator('a[href="tel:911"]')).toBeVisible();
  await expect(banner.locator('button')).toHaveCount(0);
});

test('closed thread offers a new chat (state 19)', async ({ page }) => {
  await mockApi(page, {
    status: 'closed',
    history: [{ id: 'm1', seq: 1, sender_role: 'staff', content: 'All fixed, closing this chat.' }],
  });
  await openWidget(page);
  await expect(page.locator('pdk-assistant .msg-staff .label')).toContainText('Staff');
  await expect(page.locator('pdk-assistant .system-event')).toHaveText('This chat was closed.');
  await expect(page.locator('pdk-assistant .composer-closed .btn')).toHaveText('Start a new chat');
  await expect(page.locator('pdk-assistant #pdk-composer')).toHaveCount(0);
  void NOW;
});
