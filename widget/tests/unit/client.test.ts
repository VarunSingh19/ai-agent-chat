import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, NetworkError, isAllowedApiBase, tokenExpiryMs } from '../../src/api/client.ts';

function jwt(expSeconds: number): string {
  const enc = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
  return `${enc({ alg: 'RS256' })}.${enc({ exp: expSeconds })}.sig`;
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ApiClient token handling', () => {
  it('reuses the token until it is within 60 s of expiry, then asks the host again', async () => {
    let now = 1_000_000_000_000;
    const provider = vi.fn(async () => jwt(now / 1000 + 120));
    const fetchMock = vi.fn(async () => jsonResponse(200, { items: [], next_cursor: null }));
    vi.stubGlobal('fetch', fetchMock);
    const client = new ApiClient('https://api.example.com/', provider, () => now);

    await client.listMessages('c1', 0);
    await client.listMessages('c1', 0);
    expect(provider).toHaveBeenCalledTimes(1);

    now += 61_000; // 59 s left: refresh
    await client.listMessages('c1', 0);
    expect(provider).toHaveBeenCalledTimes(2);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example.com/v1/conversations/c1/messages?after_seq=0');
    expect((init.headers as Record<string, string>)['Authorization']).toMatch(/^Bearer /);
    expect(init.credentials).toBe('omit');
  });

  it('refreshes once on 401 and retries', async () => {
    const provider = vi.fn(async () => jwt(Date.now() / 1000 + 900));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { code: 'AUTH_INVALID_TOKEN' }))
      .mockResolvedValueOnce(jsonResponse(201, { id: 'c1', status: 'ai' }));
    vi.stubGlobal('fetch', fetchMock);
    const client = new ApiClient('https://api.example.com', provider);
    await expect(client.openConversation('web')).resolves.toMatchObject({ id: 'c1' });
    expect(provider).toHaveBeenCalledTimes(2);
  });
});

describe('ApiClient errors', () => {
  it('maps problem+json and Retry-After without exposing server text', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      jsonResponse(429, { code: 'RATE_LIMITED', detail: 'internal detail' }, { 'Retry-After': '12' }),
    ));
    const client = new ApiClient('https://api.example.com', async () => jwt(Date.now() / 1000 + 900));
    const err = await client.openConversation('web').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: 'RATE_LIMITED', retryAfterS: 12 });
    expect((err as Error).message).toBe('RATE_LIMITED');
  });

  it('turns fetch failures into NetworkError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    const client = new ApiClient('https://api.example.com', async () => jwt(Date.now() / 1000 + 900));
    await expect(client.listMessages('c1', 0)).rejects.toBeInstanceOf(NetworkError);
  });

  it('streams SSE events from sendMessage with the Idempotency-Key header', async () => {
    const body = 'event: message.start\ndata: {"id":"a","seq":2}\n\nevent: token\ndata: {"text":"Hi"}\n\n';
    const fetchMock = vi.fn(async () => new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    const client = new ApiClient('https://api.example.com', async () => jwt(Date.now() / 1000 + 900));
    const events = [];
    for await (const e of client.sendMessage('c1', 'hello', 'idem-9')) events.push(e);
    expect(events).toEqual([
      { type: 'message.start', id: 'a', seq: 2 },
      { type: 'token', text: 'Hi' },
    ]);
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBe('idem-9');
    expect(init.body).toBe('{"content":"hello"}');
  });
});

describe('helpers', () => {
  it('reads JWT expiry and rejects non-HTTPS api-base outside loopback', () => {
    expect(tokenExpiryMs(jwt(1_700_000_000))).toBe(1_700_000_000_000);
    expect(tokenExpiryMs('garbage')).toBeNull();
    expect(isAllowedApiBase('https://api.example.com')).toBe(true);
    expect(isAllowedApiBase('http://127.0.0.1:5173')).toBe(true);
    expect(isAllowedApiBase('http://api.example.com')).toBe(false);
    expect(isAllowedApiBase('javascript:alert(1)')).toBe(false);
  });
});
