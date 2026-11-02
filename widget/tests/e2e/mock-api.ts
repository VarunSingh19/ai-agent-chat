/**
 * Network-level stand-in for the pdagent API in browser tests. Responses follow the shapes
 * of the real routes (Architecture.md §8); the widget under test is the real bundle.
 */
import type { Page, Request } from '@playwright/test';

export const NOW = '2026-11-02T10:00:00.000Z';

export type Reply =
  | { kind: 'sse'; events: Array<[string, Record<string, unknown>]> }
  | { kind: 'error'; status: number; code: string; headers?: Record<string, string> };

export interface HistoryItem {
  id: string;
  seq: number;
  sender_role: string;
  content: string;
  degraded?: boolean;
  sources?: Array<Record<string, unknown>>;
}

export interface Scenario {
  status?: 'ai' | 'waiting' | 'staff' | 'closed';
  history?: HistoryItem[];
  /** Served by GET messages after a dropped stream (resume). */
  resumeHistory?: HistoryItem[];
  replies?: Reply[];
  confirm?: { status: number; body: Record<string, unknown> };
}

export interface Captured {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: string | null;
}

export function sse(events: Array<[string, Record<string, unknown>]>): string {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');
}

export function answer(
  id: string,
  seq: number,
  text: string,
  extra: Array<[string, Record<string, unknown>]> = [],
  usage: Record<string, unknown> = { degraded: false, failover: false },
): Reply {
  return {
    kind: 'sse',
    events: [
      ['message.start', { id, seq }],
      ...extra,
      ...text.split(' ').map((w, i): [string, Record<string, unknown>] => ['token', { text: i ? ` ${w}` : w }]),
      ['message.end', { id, seq, usage_public: usage }],
    ],
  };
}

function problem(status: number, code: string): string {
  return JSON.stringify({ type: 'about:blank', title: code, status, detail: 'x', code, request_id: 'r' });
}

function toHistory(items: HistoryItem[]): string {
  return JSON.stringify({
    items: items.map((i) => ({ degraded: false, sources: [], created_at: NOW, ...i })),
    next_cursor: null,
  });
}

export async function mockApi(page: Page, scenario: Scenario = {}): Promise<Captured[]> {
  const captured: Captured[] = [];
  const replies = [...(scenario.replies ?? [])];
  let status = scenario.status ?? 'ai';
  let resumed = false;

  await page.route('**/v1/**', async (route) => {
    const req: Request = route.request();
    const url = new URL(req.url());
    captured.push({ method: req.method(), path: url.pathname, headers: req.headers(), body: req.postData() });
    const json = (code: number, body: string, headers: Record<string, string> = {}) =>
      route.fulfill({ status: code, contentType: code >= 400 ? 'application/problem+json' : 'application/json', body, headers });

    if (req.method() === 'POST' && url.pathname === '/v1/conversations') {
      return json(201, JSON.stringify({ id: 'c1', channel: 'web', status, property_id: null, assigned_to: null, created_at: NOW, updated_at: NOW }));
    }
    if (req.method() === 'GET' && url.pathname === '/v1/conversations/c1/messages') {
      const afterSeq = Number(url.searchParams.get('after_seq') ?? '0');
      if (afterSeq > 0 && scenario.resumeHistory && !resumed) {
        resumed = true;
        return json(200, toHistory(scenario.resumeHistory));
      }
      return json(200, toHistory(afterSeq === 0 ? (scenario.history ?? []) : []));
    }
    if (req.method() === 'POST' && url.pathname === '/v1/conversations/c1/messages') {
      const reply = replies.shift();
      if (!reply) return json(500, problem(500, 'INTERNAL'));
      if (reply.kind === 'error') return json(reply.status, problem(reply.status, reply.code), reply.headers);
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse(reply.events) });
    }
    if (req.method() === 'POST' && url.pathname === '/v1/conversations/c1/handoff') {
      status = 'waiting';
      return json(200, JSON.stringify({ handoff_id: 'h1', conversation_id: 'c1', state: 'waiting', timeout_at: '2099-01-01T00:00:00Z' }));
    }
    const confirmMatch = url.pathname.match(/^\/v1\/confirmations\/([^/]+)\/(confirm|cancel)$/);
    if (req.method() === 'POST' && confirmMatch) {
      if (confirmMatch[2] === 'cancel') {
        return json(200, JSON.stringify({ confirmation_id: confirmMatch[1], status: 'cancelled' }));
      }
      const c = scenario.confirm ?? { status: 200, body: { confirmation_id: confirmMatch[1], status: 'confirmed', tool: 'create_request', result: { reference: 'WO-1042' }, idempotent_replay: false } };
      return json(c.status, c.status >= 400 ? problem(c.status, String(c.body['code'] ?? 'INTERNAL')) : JSON.stringify(c.body));
    }
    return json(404, problem(404, 'NOT_FOUND'));
  });
  return captured;
}

/** Open the widget through the launcher. */
export async function openWidget(page: Page): Promise<void> {
  await page.goto('/');
  await page.locator('pdk-assistant .launcher').click();
  await page.locator('pdk-assistant .panel').waitFor();
}
