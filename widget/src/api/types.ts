/**
 * Wire types for the pdagent API used by the widget (Architecture.md §8).
 *
 * Mirrors the OpenAPI schema of `conversations/schemas.py`, `tools/confirm.py` and
 * `handoff/router.py`. Keep in sync when those response models change.
 */

export type ConversationStatus = 'ai' | 'waiting' | 'staff' | 'closed';

export interface ConversationOut {
  id: string;
  channel: string;
  status: ConversationStatus;
  property_id: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

export type SenderRole = 'user' | 'assistant' | 'staff' | 'event';

export interface SourceRef {
  document_id: string;
  title: string;
  section?: string | null;
  page?: number | null;
}

export interface MessageOut {
  id: string;
  seq: number;
  sender_role: string;
  content: string;
  degraded: boolean;
  sources: SourceRef[];
  created_at: string;
}

export interface MessagePage {
  items: MessageOut[];
  next_cursor: string | null;
}

export interface ConfirmCardPayload {
  id: string;
  tool: string;
  summary: string;
  args_hash?: string;
  expires_at: string;
}

export interface ConfirmResult {
  confirmation_id: string;
  status: 'confirmed';
  tool: string;
  result: Record<string, unknown> | null;
  idempotent_replay: boolean;
}

export interface CancelResult {
  confirmation_id: string;
  status: 'cancelled';
}

export interface HandoffResult {
  handoff_id: string;
  conversation_id: string;
  state: string;
  timeout_at: string;
}

/** `application/problem+json` body (Architecture.md §8). */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  request_id?: string;
}

/** SSE events of `POST /v1/conversations/{id}/messages`, after validation. */
export type StreamEvent =
  | { type: 'message.start'; id: string; seq: number }
  | { type: 'token'; text: string }
  | { type: 'source'; source: SourceRef }
  | { type: 'tool.start'; name: string }
  | { type: 'confirm.card'; card: ConfirmCardPayload }
  | { type: 'handoff'; state: string }
  | {
      type: 'message.end';
      id: string;
      seq: number;
      degraded: boolean;
      emergency: boolean;
      code: string | null;
    }
  | { type: 'error'; code: string };
