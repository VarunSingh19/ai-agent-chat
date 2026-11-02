import { describe, expect, it } from 'vitest';
import { SseParser, readSseFrames, toStreamEvent } from '../../src/api/sse.ts';

describe('SseParser', () => {
  it('parses frames split across arbitrary chunk boundaries', () => {
    const wire =
      'id: 4\nevent: message.start\ndata: {"id":"a","seq":4}\n\n' +
      'event: token\ndata: {"text":"Hel"}\n\nevent: token\ndata: {"text":"lo"}\n\n';
    const parser = new SseParser();
    const frames = [];
    for (let i = 0; i < wire.length; i += 7) frames.push(...parser.push(wire.slice(i, i + 7)));
    expect(frames.map((f) => f.event)).toEqual(['message.start', 'token', 'token']);
    expect(frames[0]?.id).toBe('4');
    expect(frames[2]?.data).toBe('{"text":"lo"}');
  });

  it('handles CRLF split between chunks without dropping the event name', () => {
    const parser = new SseParser();
    const frames = [
      ...parser.push('event: token\r'),
      ...parser.push('\ndata: {"text":"x"}\r\n\r\n'),
    ];
    expect(frames).toEqual([{ id: null, event: 'token', data: '{"text":"x"}' }]);
  });

  it('joins multi-line data and ignores comments', () => {
    const parser = new SseParser();
    expect(parser.push(': keepalive\ndata: a\ndata: b\n\n')).toEqual([
      { id: null, event: 'message', data: 'a\nb' },
    ]);
  });

  it('reads a ReadableStream body', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: token\ndata: {"text":"é'));
        controller.enqueue(encoder.encode('"}\n\n'));
        controller.close();
      },
    });
    const frames = [];
    for await (const f of readSseFrames(body)) frames.push(f);
    expect(frames).toHaveLength(1);
    expect(toStreamEvent(frames[0]!)).toEqual({ type: 'token', text: 'é' });
  });
});

describe('toStreamEvent', () => {
  it('validates each event type from the backend', () => {
    expect(toStreamEvent({ id: '1', event: 'message.start', data: '{"id":"m","seq":3}' })).toEqual({
      type: 'message.start',
      id: 'm',
      seq: 3,
    });
    expect(
      toStreamEvent({
        id: '1',
        event: 'source',
        data: '{"document_id":"d1","title":"House rules","section":"Pets","page":2}',
      }),
    ).toEqual({ type: 'source', source: { document_id: 'd1', title: 'House rules', section: 'Pets', page: 2 } });
    expect(
      toStreamEvent({
        id: '1',
        event: 'message.end',
        data: '{"id":"m","seq":3,"usage_public":{"degraded":true,"failover":false,"code":"BUDGET_DEGRADED"}}',
      }),
    ).toEqual({ type: 'message.end', id: 'm', seq: 3, degraded: true, emergency: false, code: 'BUDGET_DEGRADED' });
    expect(
      toStreamEvent({
        id: '1',
        event: 'confirm.card',
        data: '{"id":"c","tool":"create_request","summary":"Fix sink","args_hash":"h","expires_at":"2026-11-02T10:00:00Z"}',
      }),
    ).toEqual({
      type: 'confirm.card',
      card: { id: 'c', tool: 'create_request', summary: 'Fix sink', args_hash: 'h', expires_at: '2026-11-02T10:00:00Z' },
    });
  });

  it('drops unknown events, bad JSON and wrongly typed fields', () => {
    expect(toStreamEvent({ id: null, event: 'surprise', data: '{}' })).toBeNull();
    expect(toStreamEvent({ id: null, event: 'token', data: 'not json' })).toBeNull();
    expect(toStreamEvent({ id: null, event: 'token', data: '{"text":5}' })).toBeNull();
    expect(toStreamEvent({ id: null, event: 'message.start', data: '{"id":"x"}' })).toBeNull();
    expect(toStreamEvent({ id: null, event: 'source', data: '{"title":"no id"}' })).toBeNull();
  });
});
