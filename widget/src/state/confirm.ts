/**
 * Request-slip (confirm card) state (Design.md §6.1 request-slip, Architecture.md §7c).
 */
import type { ConfirmCardPayload, ConfirmResult } from '../api/types.ts';

export type SlipStatus =
  | 'pending'
  | 'editing'
  | 'sending'
  | 'confirmed'
  | 'expired'
  | 'cancelled'
  | 'replaced'
  | 'failed';

export interface Slip {
  id: string;
  tool: string;
  summary: string;
  argsHash: string | null;
  expiresAtMs: number;
  status: SlipStatus;
  reference: string | null;
  /** Reused by Try again so a retried confirm cannot run the write twice. */
  idempotencyKey: string;
  draft: string;
  /** Render key of the assistant message the slip belongs under. */
  afterMessageKey: string | null;
  finalMinuteAnnounced: boolean;
}

export function slipFromCard(
  card: ConfirmCardPayload,
  afterMessageKey: string | null,
  idempotencyKey: string,
): Slip {
  const expires = Date.parse(card.expires_at);
  return {
    id: card.id,
    tool: card.tool,
    summary: card.summary,
    argsHash: card.args_hash ?? null,
    expiresAtMs: Number.isNaN(expires) ? 0 : expires,
    status: 'pending',
    reference: null,
    idempotencyKey,
    draft: card.summary,
    afterMessageKey,
    finalMinuteAnnounced: false,
  };
}

export function isActionable(slip: Slip): boolean {
  return slip.status === 'pending' || slip.status === 'editing' || slip.status === 'failed';
}

/** Whole minutes left, rounded up; 0 once expired. */
export function minutesLeft(slip: Slip, nowMs: number): number {
  return Math.max(0, Math.ceil((slip.expiresAtMs - nowMs) / 60_000));
}

export function expireIfDue(slip: Slip, nowMs: number): Slip {
  return isActionable(slip) && nowMs >= slip.expiresAtMs ? { ...slip, status: 'expired' } : slip;
}

/** The PropertyDek reference from a confirm result, if the write returned one. */
export function referenceFrom(result: ConfirmResult): string | null {
  const body = result.result;
  if (!body) return null;
  for (const key of ['reference', 'reference_number', 'request_number', 'request_id', 'id']) {
    const value = body[key];
    if (typeof value === 'string' && value) return value;
    if (typeof value === 'number') return String(value);
  }
  return null;
}

export function isNoteTool(tool: string): boolean {
  return tool === 'add_request_note';
}
