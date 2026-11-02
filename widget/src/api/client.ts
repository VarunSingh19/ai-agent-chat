/**
 * HTTP client for the pdagent conversation API (Architecture.md §8).
 *
 * The chat token comes from the host's `tokenProvider` and lives only in this object's
 * private fields (Rules.md §2: never Web Storage). It is refreshed when within 60 s of
 * expiry (Design.md §10) and once on a 401.
 */
import { readSseFrames, toStreamEvent } from './sse.ts';
import type {
  CancelResult,
  ConfirmResult,
  ConversationOut,
  HandoffResult,
  MessagePage,
  ProblemDetails,
  StreamEvent,
} from './types.ts';

export type TokenProvider = () => Promise<string>;

/** A non-2xx response, reduced to what the UI may act on. Never carries server text. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly retryAfterS: number | null,
  ) {
    super(code);
    this.name = 'ApiError';
  }
}

/** The request or the stream failed below HTTP (offline, reset, aborted mid-body). */
export class NetworkError extends Error {
  constructor(message = 'NETWORK') {
    super(message);
    this.name = 'NetworkError';
  }
}

const REFRESH_MARGIN_MS = 60_000;

const STATUS_CODES: Record<number, string> = {
  401: 'AUTH_INVALID_TOKEN',
  403: 'AUTH_FORBIDDEN',
  404: 'NOT_FOUND',
  409: 'CONFLICT_TAKEN',
  410: 'CONFIRMATION_EXPIRED',
  422: 'VALIDATION',
  429: 'RATE_LIMITED',
  503: 'PROVIDER_UNAVAILABLE',
};

/** Read `exp` from a JWT payload without verifying it (the server verifies). */
export function tokenExpiryMs(token: string): number | null {
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'));
    const exp: unknown = (JSON.parse(json) as Record<string, unknown>)['exp'];
    return typeof exp === 'number' ? exp * 1000 : null;
  } catch {
    return null;
  }
}

/** `api-base` must be HTTPS; plain HTTP is allowed only for loopback development hosts. */
export function isAllowedApiBase(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:') return true;
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  } catch {
    return false;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = STATUS_CODES[res.status] ?? 'INTERNAL';
  try {
    const body = (await res.json()) as ProblemDetails;
    if (typeof body.code === 'string' && body.code) code = body.code;
  } catch {
    // Non-JSON error body: keep the status-derived code.
  }
  const retryHeader = res.headers.get('Retry-After');
  const retryAfter = retryHeader !== null && /^\d+$/.test(retryHeader) ? Number(retryHeader) : null;
  return new ApiError(res.status, code, retryAfter);
}

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiClient {
  readonly #base: string;
  readonly #tokenProvider: TokenProvider;
  readonly #now: () => number;
  #token: string | null = null;
  #tokenExpiresAt = 0;

  constructor(base: string, tokenProvider: TokenProvider, now: () => number = Date.now) {
    this.#base = base.replace(/\/+$/, '');
    this.#tokenProvider = tokenProvider;
    this.#now = now;
  }

  /** Drop the in-memory token (host sign-out). */
  clearToken(): void {
    this.#token = null;
    this.#tokenExpiresAt = 0;
  }

  async #bearer(forceRefresh: boolean): Promise<string> {
    if (!forceRefresh && this.#token && this.#tokenExpiresAt - this.#now() > REFRESH_MARGIN_MS) {
      return this.#token;
    }
    const token = (await this.#tokenProvider()).trim();
    if (!token) throw new ApiError(401, 'AUTH_INVALID_TOKEN', null);
    this.#token = token;
    // Unknown expiry: treat as short-lived so the next call asks the host again.
    this.#tokenExpiresAt = tokenExpiryMs(token) ?? this.#now() + REFRESH_MARGIN_MS;
    return token;
  }

  async #send(method: string, path: string, token: string, opts: RequestOptions): Promise<Response> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
      ...opts.headers,
    };
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    try {
      return await fetch(`${this.#base}${path}`, {
        method,
        headers,
        body: opts.body === undefined ? null : JSON.stringify(opts.body),
        signal: opts.signal ?? null,
        credentials: 'omit',
        cache: 'no-store',
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      throw new NetworkError();
    }
  }

  async #request(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
    let res = await this.#send(method, path, await this.#bearer(false), opts);
    if (res.status === 401) {
      res = await this.#send(method, path, await this.#bearer(true), opts);
    }
    if (!res.ok) throw await toApiError(res);
    return res;
  }

  async #json<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const res = await this.#request(method, path, opts);
    try {
      return (await res.json()) as T;
    } catch {
      throw new NetworkError();
    }
  }

  openConversation(channel: string): Promise<ConversationOut> {
    return this.#json('POST', '/v1/conversations', { body: { channel } });
  }

  listMessages(conversationId: string, afterSeq: number): Promise<MessagePage> {
    const id = encodeURIComponent(conversationId);
    return this.#json('GET', `/v1/conversations/${id}/messages?after_seq=${afterSeq}`);
  }

  /** Send a message and yield the validated SSE events of the answer. */
  async *sendMessage(
    conversationId: string,
    content: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): AsyncGenerator<StreamEvent> {
    const id = encodeURIComponent(conversationId);
    const opts: RequestOptions = {
      body: { content },
      headers: { 'Idempotency-Key': idempotencyKey, Accept: 'text/event-stream' },
    };
    if (signal) opts.signal = signal;
    const res = await this.#request('POST', `/v1/conversations/${id}/messages`, opts);
    if (!res.body) throw new NetworkError();
    try {
      for await (const frame of readSseFrames(res.body)) {
        const event = toStreamEvent(frame);
        if (event) yield event;
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      throw new NetworkError();
    }
  }

  confirm(confirmationId: string, idempotencyKey: string, argsHash: string | null): Promise<ConfirmResult> {
    const id = encodeURIComponent(confirmationId);
    return this.#json('POST', `/v1/confirmations/${id}/confirm`, {
      body: argsHash ? { args_hash: argsHash } : {},
      headers: { 'Idempotency-Key': idempotencyKey },
    });
  }

  cancel(confirmationId: string): Promise<CancelResult> {
    return this.#json('POST', `/v1/confirmations/${encodeURIComponent(confirmationId)}/cancel`);
  }

  requestHandoff(conversationId: string): Promise<HandoffResult> {
    // No body: the server records its default user-request reason.
    return this.#json('POST', `/v1/conversations/${encodeURIComponent(conversationId)}/handoff`);
  }
}
