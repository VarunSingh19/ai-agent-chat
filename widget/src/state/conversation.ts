/**
 * Conversation state for the widget (Design.md §6.2 states 1–7, 15–19).
 *
 * Pure functions over an immutable state object, so every transition is unit-testable.
 * A cut-off partial answer stays as its own message; a new answer is never spliced into
 * it (Architecture.md §7f). Replaying the same persisted message (same id) from history
 * after a dropped stream replaces the partial copy, because it is the same answer.
 */
import type {
  ConversationOut,
  ConversationStatus,
  MessageOut,
  SenderRole,
  SourceRef,
  StreamEvent,
} from '../api/types.ts';
import { statusFromHandoffState } from './handoff.ts';

export type MessageStatus = 'sending' | 'sent' | 'streaming' | 'done' | 'cut_off' | 'failed';
export type TurnPhase = 'idle' | 'sending' | 'waiting_first_token' | 'streaming';
export type SystemEventKind = 'handoff_requested' | 'staff_joined' | 'handed_back' | 'closed';

export interface ChatMessage {
  key: string;
  id: string | null;
  seq: number | null;
  role: SenderRole;
  text: string;
  sources: SourceRef[];
  createdAt: string | null;
  status: MessageStatus;
  /** For user messages: reused when the user retries a failed send. */
  idempotencyKey: string | null;
  noSource: boolean;
  degraded: boolean;
  emergency: boolean;
  /** Added live (fades in), as opposed to loaded from history. */
  isNew: boolean;
  systemEvent: SystemEventKind | null;
}

export type ErrorKind =
  | 'rate_limited'
  | 'provider_unavailable'
  | 'reconnecting'
  | 'connection_lost'
  | 'cut_off'
  | 'send_failed';

export interface ErrorRow {
  kind: ErrorKind;
  /** The message the row sits under. */
  messageKey: string;
  retryAfterS: number | null;
}

export interface ConversationState {
  conversationId: string | null;
  status: ConversationStatus;
  lastSeq: number;
  messages: ChatMessage[];
  phase: TurnPhase;
  toolName: string | null;
  usedToolThisTurn: boolean;
  /** Key of the user message the in-flight turn answers. */
  turnUserKey: string | null;
  /** Key of the assistant message being streamed. */
  streamingKey: string | null;
  error: ErrorRow | null;
  degraded: boolean;
  emergency: boolean;
}

export function initialState(): ConversationState {
  return {
    conversationId: null,
    status: 'ai',
    lastSeq: 0,
    messages: [],
    phase: 'idle',
    toolName: null,
    usedToolThisTurn: false,
    turnUserKey: null,
    streamingKey: null,
    error: null,
    degraded: false,
    emergency: false,
  };
}

function roleOf(raw: string): SenderRole {
  return raw === 'user' || raw === 'assistant' || raw === 'staff' ? raw : 'event';
}

function fromHistory(item: MessageOut, isNew: boolean): ChatMessage {
  return {
    key: `m-${item.id}`,
    id: item.id,
    seq: item.seq,
    role: roleOf(item.sender_role),
    text: item.content,
    sources: item.sources ?? [],
    createdAt: item.created_at,
    status: 'done',
    idempotencyKey: null,
    noSource: false,
    degraded: item.degraded,
    emergency: false,
    isNew,
    systemEvent: null,
  };
}

function systemMessage(key: string, kind: SystemEventKind, nowIso: string): ChatMessage {
  return {
    key,
    id: null,
    seq: null,
    role: 'event',
    text: '',
    sources: [],
    createdAt: nowIso,
    status: 'done',
    idempotencyKey: null,
    noSource: false,
    degraded: false,
    emergency: false,
    isNew: true,
    systemEvent: kind,
  };
}

function patchMessage(
  state: ConversationState,
  key: string | null,
  patch: (m: ChatMessage) => ChatMessage,
): ConversationState {
  if (key === null) return state;
  return { ...state, messages: state.messages.map((m) => (m.key === key ? patch(m) : m)) };
}

/** Load a thread for the first time (history is not animated). */
export function loadConversation(conv: ConversationOut, items: MessageOut[]): ConversationState {
  const messages = items.map((i) => fromHistory(i, false));
  const lastSeq = items.reduce((max, i) => Math.max(max, i.seq), 0);
  const next: ConversationState = {
    ...initialState(),
    conversationId: conv.id,
    status: conv.status,
    lastSeq,
    messages,
  };
  return conv.status === 'closed'
    ? { ...next, messages: [...messages, { ...systemMessage('sys-closed', 'closed', conv.updated_at), isNew: false }] }
    : next;
}

/**
 * Merge messages read from history (resume after a dropped stream, or handoff polling).
 * Known ids are replaced in place; a pending local user message is matched by text;
 * everything else is appended in seq order.
 */
export function mergeHistory(state: ConversationState, items: MessageOut[]): ConversationState {
  let messages = [...state.messages];
  let lastSeq = state.lastSeq;
  for (const item of [...items].sort((a, b) => a.seq - b.seq)) {
    lastSeq = Math.max(lastSeq, item.seq);
    const byId = messages.findIndex((m) => m.id === item.id);
    if (byId !== -1) {
      const existing = messages[byId]!;
      messages[byId] = { ...fromHistory(item, existing.isNew), key: existing.key };
      continue;
    }
    if (roleOf(item.sender_role) === 'user') {
      const pending = messages.findIndex(
        (m) => m.role === 'user' && m.id === null && m.text === item.content,
      );
      if (pending !== -1) {
        const existing = messages[pending]!;
        messages[pending] = { ...existing, id: item.id, seq: item.seq, status: 'done', createdAt: item.created_at };
        continue;
      }
    }
    messages = [...messages, fromHistory(item, true)];
  }
  return { ...state, messages, lastSeq };
}

export function addUserMessage(
  state: ConversationState,
  key: string,
  text: string,
  idempotencyKey: string,
  nowIso: string,
): ConversationState {
  const message: ChatMessage = {
    key,
    id: null,
    seq: null,
    role: 'user',
    text,
    sources: [],
    createdAt: nowIso,
    status: 'sending',
    idempotencyKey,
    noSource: false,
    degraded: false,
    emergency: false,
    isNew: true,
    systemEvent: null,
  };
  return beginTurn({ ...state, messages: [...state.messages, message] }, key);
}

/** Start (or restart, on Try again) the turn that answers `userKey`. */
export function beginTurn(state: ConversationState, userKey: string): ConversationState {
  const next = patchMessage(state, userKey, (m) => ({ ...m, status: 'sending' }));
  return {
    ...next,
    phase: 'sending',
    toolName: null,
    usedToolThisTurn: false,
    turnUserKey: userKey,
    streamingKey: null,
    error: null,
  };
}

export function addSystemEvent(
  state: ConversationState,
  key: string,
  kind: SystemEventKind,
  nowIso: string,
): ConversationState {
  return { ...state, messages: [...state.messages, systemMessage(key, kind, nowIso)] };
}

/** Apply a status change, adding the matching system event (Design.md §6.2 states 12, 13, 19). */
export function applyStatus(
  state: ConversationState,
  status: ConversationStatus,
  key: string,
  nowIso: string,
): ConversationState {
  if (status === state.status) return state;
  let next: ConversationState = { ...state, status };
  if (status === 'staff') next = addSystemEvent(next, key, 'staff_joined', nowIso);
  else if (status === 'closed') next = addSystemEvent(next, key, 'closed', nowIso);
  else if (status === 'ai' && (state.status === 'waiting' || state.status === 'staff')) {
    next = addSystemEvent({ ...next, emergency: false }, key, 'handed_back', nowIso);
  }
  return next;
}

export interface EventContext {
  /** Fresh key for any message or system event this event creates. */
  newKey: string;
  nowIso: string;
}

export function applyStreamEvent(
  state: ConversationState,
  event: StreamEvent,
  ctx: EventContext,
): ConversationState {
  switch (event.type) {
    case 'message.start': {
      const userDone = patchMessage(state, state.turnUserKey, (m) => ({ ...m, status: 'sent' }));
      const assistant: ChatMessage = {
        key: `m-${event.id}`,
        id: event.id,
        seq: event.seq,
        role: 'assistant',
        text: '',
        sources: [],
        createdAt: ctx.nowIso,
        status: 'streaming',
        idempotencyKey: null,
        noSource: false,
        degraded: false,
        emergency: false,
        isNew: true,
        systemEvent: null,
      };
      return {
        ...userDone,
        messages: [...userDone.messages, assistant],
        streamingKey: assistant.key,
        phase: 'waiting_first_token',
        lastSeq: Math.max(state.lastSeq, event.seq),
      };
    }
    case 'token': {
      const next = patchMessage(state, state.streamingKey, (m) => ({ ...m, text: m.text + event.text }));
      return { ...next, phase: state.streamingKey ? 'streaming' : state.phase, toolName: null };
    }
    case 'source': {
      return patchMessage(state, state.streamingKey, (m) =>
        m.sources.some((s) => s.document_id === event.source.document_id)
          ? m
          : { ...m, sources: [...m.sources, event.source] },
      );
    }
    case 'tool.start':
      return { ...state, toolName: event.name, usedToolThisTurn: true };
    case 'confirm.card':
      return { ...state, usedToolThisTurn: true };
    case 'handoff': {
      const status = statusFromHandoffState(event.state);
      // A message sent while staff are active is stored without an AI answer.
      const userDone = patchMessage(state, state.turnUserKey, (m) =>
        m.status === 'sending' ? { ...m, status: 'sent' } : m,
      );
      return status ? applyStatus(userDone, status, ctx.newKey, ctx.nowIso) : userDone;
    }
    case 'message.end': {
      const current = state.messages.find((m) => m.key === state.streamingKey);
      const noSource =
        current !== undefined &&
        current.text.trim() !== '' &&
        current.sources.length === 0 &&
        !state.usedToolThisTurn &&
        !event.emergency &&
        !event.degraded &&
        event.code === null &&
        state.status === 'ai';
      const next = patchMessage(state, state.streamingKey, (m) => ({
        ...m,
        status: 'done',
        degraded: event.degraded,
        emergency: event.emergency,
        noSource,
      }));
      const providerDown = event.code === 'PROVIDER_UNAVAILABLE' && state.streamingKey !== null;
      return {
        ...next,
        phase: 'idle',
        toolName: null,
        streamingKey: null,
        lastSeq: Math.max(state.lastSeq, event.seq),
        degraded: event.degraded,
        emergency: state.emergency || event.emergency,
        error: providerDown
          ? { kind: 'provider_unavailable', messageKey: state.streamingKey!, retryAfterS: null }
          : null,
      };
    }
    case 'error':
      return streamError(state, event.code);
  }
}

/** An `error` event, or a failure after the answer started streaming. */
export function streamError(state: ConversationState, code: string): ConversationState {
  const current = state.messages.find((m) => m.key === state.streamingKey);
  if (current && current.text.trim() !== '') {
    const next = patchMessage(state, current.key, (m) => ({ ...m, status: 'cut_off' }));
    return {
      ...next,
      phase: 'idle',
      toolName: null,
      streamingKey: null,
      error: { kind: 'cut_off', messageKey: current.key, retryAfterS: null },
    };
  }
  // Nothing visible yet: drop the empty assistant placeholder and flag the user message.
  const withoutEmpty = current
    ? { ...state, messages: state.messages.filter((m) => m.key !== current.key) }
    : state;
  return failTurn(withoutEmpty, code === 'PROVIDER_UNAVAILABLE' ? 'provider_unavailable' : 'send_failed', null);
}

/** The turn failed before any answer text arrived. */
export function failTurn(
  state: ConversationState,
  kind: ErrorKind,
  retryAfterS: number | null,
): ConversationState {
  const key = state.turnUserKey;
  const next = patchMessage(state, key, (m) => ({ ...m, status: 'failed' }));
  return {
    ...next,
    phase: 'idle',
    toolName: null,
    streamingKey: null,
    error: key ? { kind, messageKey: key, retryAfterS } : null,
  };
}

/** The stream dropped after `message.start`: keep the partial text, try to resume. */
export function markReconnecting(state: ConversationState): ConversationState {
  const key = state.streamingKey ?? state.turnUserKey;
  return {
    ...state,
    phase: 'idle',
    toolName: null,
    error: key ? { kind: 'reconnecting', messageKey: key, retryAfterS: null } : null,
  };
}

/** Resume gave up after 30 s: offer Try again (Design.md §6.1 error-row). */
export function markConnectionLost(state: ConversationState): ConversationState {
  const key = state.error?.messageKey ?? state.streamingKey ?? state.turnUserKey;
  return { ...state, error: key ? { kind: 'connection_lost', messageKey: key, retryAfterS: null } : null };
}

/** Whether the persisted answer for the in-flight turn has been recovered from history. */
export function turnRecovered(state: ConversationState): boolean {
  if (state.streamingKey === null) return false;
  const m = state.messages.find((x) => x.key === state.streamingKey);
  return m !== undefined && m.status === 'done';
}

/** Finish a turn recovered from history. */
export function finishRecovered(state: ConversationState): ConversationState {
  return { ...state, streamingKey: null, phase: 'idle', error: null };
}

export function clearError(state: ConversationState): ConversationState {
  return { ...state, error: null };
}

/** Whether a label should precede this message (first in a run of the same sender). */
export function startsRun(messages: ChatMessage[], index: number): boolean {
  const current = messages[index];
  const previous = messages[index - 1];
  if (!current || current.role === 'event') return false;
  return !previous || previous.role !== current.role;
}
