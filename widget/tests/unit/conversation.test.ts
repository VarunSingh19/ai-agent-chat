import { describe, expect, it } from 'vitest';
import type { MessageOut, StreamEvent } from '../../src/api/types.ts';
import {
  addUserMessage,
  applyStreamEvent,
  initialState,
  loadConversation,
  markReconnecting,
  mergeHistory,
  startsRun,
  turnRecovered,
  type ConversationState,
} from '../../src/state/conversation.ts';

const NOW = '2026-11-02T10:00:00.000Z';
let n = 0;
const ctx = () => ({ newKey: `e${++n}`, nowIso: NOW });

function apply(state: ConversationState, events: StreamEvent[]): ConversationState {
  return events.reduce((s, e) => applyStreamEvent(s, e, ctx()), state);
}

function started(): ConversationState {
  const loaded = loadConversation(
    { id: 'c1', channel: 'web', status: 'ai', property_id: null, assigned_to: null, created_at: NOW, updated_at: NOW },
    [],
  );
  return addUserMessage(loaded, 'u1', 'What are quiet hours?', 'idem-1', NOW);
}

describe('conversation state', () => {
  it('streams an answer with sources (states 2, 3, 5, 6)', () => {
    let s = started();
    expect(s.phase).toBe('sending');
    expect(s.messages[0]?.status).toBe('sending');

    s = apply(s, [{ type: 'message.start', id: 'a1', seq: 2 }]);
    expect(s.messages[0]?.status).toBe('sent');
    expect(s.phase).toBe('waiting_first_token');

    s = apply(s, [
      { type: 'source', source: { document_id: 'd1', title: 'House rules (2026)' } },
      { type: 'source', source: { document_id: 'd1', title: 'House rules (2026)' } },
      { type: 'token', text: 'Quiet hours' },
    ]);
    expect(s.phase).toBe('streaming');
    s = apply(s, [
      { type: 'token', text: ' are 10pm–7am.' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: false, emergency: false, code: null },
    ]);
    const answer = s.messages[1]!;
    expect(answer.text).toBe('Quiet hours are 10pm–7am.');
    expect(answer.sources).toHaveLength(1);
    expect(answer.noSource).toBe(false);
    expect(s.phase).toBe('idle');
    expect(s.lastSeq).toBe(2);
  });

  it('flags an answer without a source (state 7) but not a tool answer', () => {
    const plain = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'token', text: 'Not sure.' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: false, emergency: false, code: null },
    ]);
    expect(plain.messages[1]?.noSource).toBe(true);

    const tool = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'tool.start', name: 'get_request' },
      { type: 'token', text: 'Your request is open.' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: false, emergency: false, code: null },
    ]);
    expect(tool.messages[1]?.noSource).toBe(false);
  });

  it('shows the tool status line until the first token (state 4)', () => {
    let s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'tool.start', name: 'get_request' },
    ]);
    expect(s.toolName).toBe('get_request');
    s = apply(s, [{ type: 'token', text: 'Done' }]);
    expect(s.toolName).toBeNull();
  });

  it('keeps a cut-off partial answer and never splices (Architecture.md §7f)', () => {
    const s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'token', text: 'Half an ans' },
      { type: 'error', code: 'PROVIDER_UNAVAILABLE' },
    ]);
    expect(s.messages[1]?.status).toBe('cut_off');
    expect(s.messages[1]?.text).toBe('Half an ans');
    expect(s.error).toMatchObject({ kind: 'cut_off', messageKey: 'm-a1' });
  });

  it('turns an error before any text into a failed send with no empty bubble', () => {
    const s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'error', code: 'PROVIDER_UNAVAILABLE' },
    ]);
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0]?.status).toBe('failed');
    expect(s.error).toMatchObject({ kind: 'provider_unavailable', messageKey: 'u1' });
  });

  it('records degraded and emergency answers (states 14, 15)', () => {
    const s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'handoff', state: 'waiting' },
      { type: 'token', text: 'Call 911.' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: false, emergency: true, code: null },
    ]);
    expect(s.emergency).toBe(true);
    expect(s.status).toBe('waiting');
    expect(s.messages[1]?.noSource).toBe(false);

    const d = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'token', text: 'FAQ only.' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: true, emergency: false, code: 'BUDGET_DEGRADED' },
    ]);
    expect(d.degraded).toBe(true);
  });

  it('stores a message sent while staff are active without an AI answer (state 12)', () => {
    let s = started();
    s = { ...s, status: 'staff' };
    s = apply(s, [{ type: 'handoff', state: 'staff' }]);
    expect(s.messages[0]?.status).toBe('sent');
    expect(s.messages).toHaveLength(1);
  });

  it('adds a system event when handed back (state 13) and when closed (state 19)', () => {
    let s: ConversationState = { ...initialState(), conversationId: 'c1', status: 'staff' };
    s = apply(s, [{ type: 'handoff', state: 'ai' }]);
    expect(s.messages.at(-1)?.systemEvent).toBe('handed_back');
    s = apply(s, [{ type: 'handoff', state: 'closed' }]);
    expect(s.messages.at(-1)?.systemEvent).toBe('closed');
  });

  it('recovers the persisted answer after a dropped stream (state 18)', () => {
    let s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'token', text: 'Quiet' },
    ]);
    s = markReconnecting(s);
    expect(s.error?.kind).toBe('reconnecting');
    const history: MessageOut[] = [
      { id: 'u-srv', seq: 1, sender_role: 'user', content: 'What are quiet hours?', degraded: false, sources: [], created_at: NOW },
      { id: 'a1', seq: 2, sender_role: 'assistant', content: 'Quiet hours are 10pm–7am.', degraded: false, sources: [], created_at: NOW },
    ];
    s = mergeHistory(s, history);
    expect(turnRecovered(s)).toBe(true);
    expect(s.messages).toHaveLength(2);
    expect(s.messages[0]?.id).toBe('u-srv');
    expect(s.messages[1]?.text).toBe('Quiet hours are 10pm–7am.');
  });

  it('labels only the first message in a run', () => {
    const s = apply(started(), [
      { type: 'message.start', id: 'a1', seq: 2 },
      { type: 'token', text: 'Hi' },
      { type: 'message.end', id: 'a1', seq: 2, degraded: false, emergency: false, code: null },
    ]);
    const withSecond = addUserMessage(addUserMessage(s, 'u2', 'a', 'i2', NOW), 'u3', 'b', 'i3', NOW);
    expect([0, 1, 2, 3].map((i) => startsRun(withSecond.messages, i))).toEqual([true, true, true, false]);
  });
});
