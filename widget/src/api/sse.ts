/**
 * Server-Sent Events parsing for the streamed answer (Architecture.md §8).
 *
 * `fetch` is used instead of `EventSource` because the turn is a POST with an
 * Authorization header. Frames are validated into typed `StreamEvent`s; unknown or
 * malformed frames are dropped, never rendered.
 */
import type { ConfirmCardPayload, SourceRef, StreamEvent } from './types.ts';

export interface SseFrame {
  id: string | null;
  event: string;
  data: string;
}

/** Incremental parser; feed it decoded text chunks in order. */
export class SseParser {
  #buffer = '';
  #id: string | null = null;
  #event = '';
  #data: string[] = [];

  push(chunk: string): SseFrame[] {
    this.#buffer += chunk;
    // A trailing CR may be the first half of a CRLF split across chunks; keep it.
    const heldCR = this.#buffer.endsWith('\r');
    const work = heldCR ? this.#buffer.slice(0, -1) : this.#buffer;
    const lines = work.split(/\r\n|\r|\n/);
    this.#buffer = (lines.pop() ?? '') + (heldCR ? '\r' : '');

    const frames: SseFrame[] = [];
    for (const line of lines) {
      if (line === '') {
        if (this.#data.length > 0) {
          frames.push({ id: this.#id, event: this.#event || 'message', data: this.#data.join('\n') });
        }
        this.#event = '';
        this.#data = [];
        continue;
      }
      if (line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'data') this.#data.push(value);
      else if (field === 'event') this.#event = value;
      else if (field === 'id') this.#id = value;
    }
    return frames;
  }
}

/** Read a response body as SSE frames. Network failures surface as thrown errors. */
export async function* readSseFrames(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode() + '\n\n');
  } finally {
    reader.releaseLock();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function toSource(data: Record<string, unknown>): SourceRef | null {
  const documentId = str(data['document_id']);
  const title = str(data['title']);
  if (!documentId || !title) return null;
  const page = typeof data['page'] === 'number' ? data['page'] : null;
  return { document_id: documentId, title, section: str(data['section']), page };
}

function toCard(data: Record<string, unknown>): ConfirmCardPayload | null {
  const id = str(data['id']);
  const tool = str(data['tool']);
  const summary = str(data['summary']);
  const expiresAt = str(data['expires_at']);
  if (!id || !tool || summary === null || !expiresAt) return null;
  const argsHash = str(data['args_hash']);
  return argsHash
    ? { id, tool, summary, expires_at: expiresAt, args_hash: argsHash }
    : { id, tool, summary, expires_at: expiresAt };
}

/** Validate one frame into a typed event, or `null` if it is unknown or malformed. */
export function toStreamEvent(frame: SseFrame): StreamEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(frame.data);
  } catch {
    return null;
  }
  if (!isRecord(data)) return null;

  switch (frame.event) {
    case 'message.start': {
      const id = str(data['id']);
      return id && typeof data['seq'] === 'number'
        ? { type: 'message.start', id, seq: data['seq'] }
        : null;
    }
    case 'token': {
      const text = str(data['text']);
      return text === null ? null : { type: 'token', text };
    }
    case 'source': {
      const source = toSource(data);
      return source ? { type: 'source', source } : null;
    }
    case 'tool.start': {
      const name = str(data['name']);
      return name ? { type: 'tool.start', name } : null;
    }
    case 'confirm.card': {
      const card = toCard(data);
      return card ? { type: 'confirm.card', card } : null;
    }
    case 'handoff': {
      const state = str(data['state']);
      return state ? { type: 'handoff', state } : null;
    }
    case 'message.end': {
      const id = str(data['id']);
      const usage = isRecord(data['usage_public']) ? data['usage_public'] : {};
      return id
        ? {
            type: 'message.end',
            id,
            seq: typeof data['seq'] === 'number' ? data['seq'] : -1,
            degraded: usage['degraded'] === true,
            emergency: usage['emergency'] === true,
            code: str(usage['code']),
          }
        : null;
    }
    case 'error': {
      const code = str(data['code']);
      return code ? { type: 'error', code } : null;
    }
    default:
      return null;
  }
}
