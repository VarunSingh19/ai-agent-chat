/**
 * Handoff banner state (Design.md §6.1 handoff-banner, §6.2 states 10–14).
 */
import type { ConversationStatus } from '../api/types.ts';

export type BannerKind = 'none' | 'waiting' | 'timed_out' | 'staff' | 'emergency';

/** While staff may write, the widget re-reads the thread on this interval. */
export const HANDOFF_POLL_INTERVAL_MS = 5_000;

/** Map an SSE `handoff.state` value to a conversation status; unknown values are ignored. */
export function statusFromHandoffState(state: string): ConversationStatus | null {
  return state === 'ai' || state === 'waiting' || state === 'staff' || state === 'closed'
    ? state
    : null;
}

export function bannerFor(
  status: ConversationStatus,
  emergency: boolean,
  timeoutAtMs: number | null,
  nowMs: number,
): BannerKind {
  // Emergency is never dismissible while the thread is escalated (Design.md §6.1).
  if (emergency && status !== 'ai' && status !== 'closed') return 'emergency';
  if (status === 'staff') return 'staff';
  if (status === 'waiting') {
    return timeoutAtMs !== null && nowMs >= timeoutAtMs ? 'timed_out' : 'waiting';
  }
  return 'none';
}

export function shouldPoll(status: ConversationStatus): boolean {
  return status === 'waiting' || status === 'staff';
}
