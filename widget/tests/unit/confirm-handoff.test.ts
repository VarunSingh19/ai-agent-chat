import { describe, expect, it } from 'vitest';
import { expireIfDue, minutesLeft, referenceFrom, slipFromCard } from '../../src/state/confirm.ts';
import { bannerFor, shouldPoll, statusFromHandoffState } from '../../src/state/handoff.ts';

const card = { id: 'c1', tool: 'create_request', summary: 'Fix sink', args_hash: 'h1', expires_at: '2026-11-02T10:10:00Z' };
const T0 = Date.parse('2026-11-02T10:00:00Z');

describe('request slip', () => {
  it('counts down whole minutes and expires once', () => {
    const slip = slipFromCard(card, 'm-a1', 'idem');
    expect(slip.argsHash).toBe('h1');
    expect(minutesLeft(slip, T0)).toBe(10);
    expect(minutesLeft(slip, T0 + 9 * 60_000 + 1)).toBe(1);
    expect(expireIfDue(slip, T0 + 5 * 60_000).status).toBe('pending');
    expect(expireIfDue(slip, T0 + 10 * 60_000).status).toBe('expired');
  });

  it('does not expire a confirmed slip', () => {
    const slip = { ...slipFromCard(card, null, 'idem'), status: 'confirmed' as const };
    expect(expireIfDue(slip, T0 + 60 * 60_000).status).toBe('confirmed');
  });

  it('reads a reference from the write result when present', () => {
    const base = { confirmation_id: 'c1', status: 'confirmed' as const, tool: 'create_request', idempotent_replay: false };
    expect(referenceFrom({ ...base, result: { reference: 'WO-1042' } })).toBe('WO-1042');
    expect(referenceFrom({ ...base, result: { request_id: 77 } })).toBe('77');
    expect(referenceFrom({ ...base, result: null })).toBeNull();
  });
});

describe('handoff banner', () => {
  it('maps status, emergency and timeout to the banner (states 10–14)', () => {
    expect(bannerFor('ai', false, null, T0)).toBe('none');
    expect(bannerFor('waiting', false, T0 + 1, T0)).toBe('waiting');
    expect(bannerFor('waiting', false, T0, T0)).toBe('timed_out');
    expect(bannerFor('staff', false, null, T0)).toBe('staff');
    expect(bannerFor('waiting', true, null, T0)).toBe('emergency');
    expect(bannerFor('staff', true, null, T0)).toBe('emergency');
    expect(bannerFor('ai', true, null, T0)).toBe('none');
  });

  it('polls only while staff may write', () => {
    expect(shouldPoll('waiting')).toBe(true);
    expect(shouldPoll('staff')).toBe(true);
    expect(shouldPoll('ai')).toBe(false);
    expect(shouldPoll('closed')).toBe(false);
  });

  it('ignores unknown handoff states', () => {
    expect(statusFromHandoffState('staff')).toBe('staff');
    expect(statusFromHandoffState('weird')).toBeNull();
  });
});
