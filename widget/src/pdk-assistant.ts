/**
 * <pdk-assistant> embeddable chat widget (Phase 7; Design.md; Architecture.md §4, §8).
 *
 * Public surface (Design.md §10):
 * - Attributes: `api-base` (HTTPS URL), `channel` (`web`), `lang`, `open`, `data-theme`.
 * - Property: `tokenProvider: () => Promise<string>`; the token stays in memory only.
 * - Events (bubbling, composed; no message text in details): `pdk-open-source
 *   {document_id, title}`, `pdk-handoff {state}`, `pdk-error {code}`,
 *   `pdk-open-request-form {}`.
 * - Method: `signOut()` drops the token and the conversation from memory.
 */
import { LitElement, html, nothing, type PropertyValues, type TemplateResult } from 'lit';
import { ApiClient, ApiError, NetworkError, isAllowedApiBase, type TokenProvider } from './api/client.ts';
import type { SourceRef, StreamEvent } from './api/types.ts';
import { renderSlip, type SlipHandlers } from './components/confirm-card.ts';
import { renderComposer } from './components/composer.ts';
import { renderDegradedNotice } from './components/degraded-notice.ts';
import { renderEmptyState } from './components/empty-state.ts';
import { renderErrorRow } from './components/error-row.ts';
import { renderHandoffBanner } from './components/handoff-banner.ts';
import { renderLauncher } from './components/launcher.ts';
import { renderMessage } from './components/message.ts';
import { renderPanel } from './components/panel.ts';
import { renderToolStatus, renderTyping } from './components/typing.ts';
import { EN_STRINGS } from './i18n/en.ts';
import {
  expireIfDue,
  isActionable,
  minutesLeft,
  referenceFrom,
  slipFromCard,
  type Slip,
} from './state/confirm.ts';
import {
  addSystemEvent,
  addUserMessage,
  applyStatus,
  applyStreamEvent,
  beginTurn,
  failTurn,
  finishRecovered,
  initialState,
  loadConversation,
  markConnectionLost,
  markReconnecting,
  mergeHistory,
  startsRun,
  turnRecovered,
  type ConversationState,
  type ErrorKind,
} from './state/conversation.ts';
import { HANDOFF_POLL_INTERVAL_MS, bannerFor, shouldPoll } from './state/handoff.ts';
import { baseCss } from './styles/base.css.ts';
import { tokensCss } from './styles/tokens.css.ts';

const STRINGS = EN_STRINGS;
const RESUME_WINDOW_MS = 30_000;
const CLOSE_ANIMATION_MS = 180;
const DEFAULT_RETRY_AFTER_S = 30;

function nowIso(): string {
  return new Date().toISOString();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function isCoarsePointer(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
}

export class PdkAssistantElement extends LitElement {
  static override styles = [tokensCss, baseCss];

  static override properties = {
    apiBase: { type: String, attribute: 'api-base' },
    channel: { type: String },
    open: { type: Boolean, reflect: true },
    _conv: { state: true },
    _slips: { state: true },
    _draft: { state: true },
    _closing: { state: true },
    _badge: { state: true },
    _now: { state: true },
    _expanded: { state: true },
    _announcement: { state: true },
    _loadFailed: { state: true },
    _timeoutAtMs: { state: true },
  };

  declare apiBase: string;
  declare channel: string;
  declare open: boolean;
  declare _conv: ConversationState;
  declare _slips: Slip[];
  declare _draft: string;
  declare _closing: boolean;
  declare _badge: boolean;
  declare _now: number;
  declare _expanded: ReadonlySet<string>;
  declare _announcement: string;
  declare _loadFailed: boolean;
  declare _timeoutAtMs: number | null;

  #tokenProvider: TokenProvider | null = null;
  #client: ApiClient | null = null;
  #clientBase = '';
  #loading: Promise<boolean> | null = null;
  #abort: AbortController | null = null;
  #pollTimer: ReturnType<typeof setInterval> | null = null;
  #polling = false;
  #clock: ReturnType<typeof setInterval> | null = null;
  #rateLimitedUntil = 0;
  #slipsInFlight = new Set<string>();
  #focusSlipId: string | null = null;
  #focusAfterOpen = false;
  #focusLauncher = false;
  #stickToBottom = true;
  #keySeq = 0;

  constructor() {
    super();
    this.apiBase = '';
    this.channel = 'web';
    this.open = false;
    this._conv = initialState();
    this._slips = [];
    this._draft = '';
    this._closing = false;
    this._badge = false;
    this._now = Date.now();
    this._expanded = new Set();
    this._announcement = '';
    this._loadFailed = false;
    this._timeoutAtMs = null;
  }

  /** Host-supplied source of fresh chat tokens. Never stored outside memory. */
  get tokenProvider(): TokenProvider | null {
    return this.#tokenProvider;
  }

  set tokenProvider(provider: TokenProvider | null) {
    this.#tokenProvider = provider;
    this.#client = null;
  }

  /** Drop the token and the conversation from memory (host sign-out). */
  signOut(): void {
    this.#abort?.abort();
    this.#client?.clearToken();
    this.#client = null;
    this.#stopPolling();
    this._conv = initialState();
    this._slips = [];
    this._draft = '';
    this._badge = false;
    this._timeoutAtMs = null;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.#clock = setInterval(() => this.#tick(), 1_000);
    this.#syncPolling();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this.#clock) clearInterval(this.#clock);
    this.#clock = null;
    this.#abort?.abort();
    this.#stopPolling();
  }

  // ---- lifecycle -------------------------------------------------------

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has('open') && this.open) {
      this._badge = false;
      this.#focusAfterOpen = true;
      void this.#ensureConversation();
    }
  }

  protected override updated(changed: PropertyValues<this>): void {
    const root = this.renderRoot;
    if (this.#focusAfterOpen && this.open) {
      this.#focusAfterOpen = false;
      // In priority order (a selector list would pick the first match in document order).
      const target = ['#pdk-composer', '.composer-closed .btn', '[data-close]']
        .map((selector) => root.querySelector<HTMLElement>(selector))
        .find((el) => el !== null);
      target?.focus();
    }
    if (this.#focusLauncher && !this.open) {
      this.#focusLauncher = false;
      root.querySelector<HTMLElement>('.launcher')?.focus();
    }
    if (this.#focusSlipId) {
      const heading = root.querySelector<HTMLElement>(`[data-slip-heading="${this.#focusSlipId}"]`);
      if (heading) {
        this.#focusSlipId = null;
        heading.focus();
      }
    }
    if (changed.has('_conv') || changed.has('_slips')) {
      const log = root.querySelector<HTMLElement>('.log');
      if (log && this.#stickToBottom) log.scrollTop = log.scrollHeight;
    }
  }

  // ---- helpers ---------------------------------------------------------

  #key(): string {
    this.#keySeq += 1;
    return `k${this.#keySeq}`;
  }

  #emit(name: string, detail: Record<string, unknown>): void {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  #emitError(err: unknown): void {
    const code = err instanceof ApiError ? err.code : err instanceof NetworkError ? 'NETWORK' : 'INTERNAL';
    this.#emit('pdk-error', { code });
  }

  #api(): ApiClient | null {
    if (!this.#tokenProvider || !isAllowedApiBase(this.apiBase)) return null;
    if (!this.#client || this.#clientBase !== this.apiBase) {
      this.#client = new ApiClient(this.apiBase, this.#tokenProvider);
      this.#clientBase = this.apiBase;
    }
    return this.#client;
  }

  #tick(): void {
    const now = Date.now();
    let slipsChanged = false;
    const slips = this._slips.map((slip) => {
      let next = expireIfDue(slip, now);
      if (isActionable(next) && !next.finalMinuteAnnounced && minutesLeft(next, now) <= 1) {
        next = { ...next, finalMinuteAnnounced: true };
        this._announcement = STRINGS.slipOneMinuteLeft;
      }
      if (next !== slip) slipsChanged = true;
      return next;
    });
    if (slipsChanged) this._slips = slips;
    const timeDependent =
      this.#rateLimitedUntil > now - 1_000 ||
      this._slips.some(isActionable) ||
      (this._conv.status === 'waiting' && this._timeoutAtMs !== null);
    if (timeDependent) this._now = now;
  }

  // ---- conversation loading and polling --------------------------------

  #ensureConversation(): Promise<boolean> {
    if (this._conv.conversationId) return Promise.resolve(true);
    if (this.#loading) return this.#loading;
    const client = this.#api();
    if (!client) {
      this._loadFailed = true;
      this.#emit('pdk-error', { code: 'CONFIGURATION' });
      return Promise.resolve(false);
    }
    this.#loading = (async () => {
      try {
        const conv = await client.openConversation(this.channel || 'web');
        const page = await client.listMessages(conv.id, 0);
        this._conv = loadConversation(conv, page.items);
        this._loadFailed = false;
        this.#syncPolling();
        return true;
      } catch (err) {
        this._loadFailed = true;
        this.#emitError(err);
        return false;
      } finally {
        this.#loading = null;
      }
    })();
    return this.#loading;
  }

  #syncPolling(): void {
    const want = this.isConnected && this._conv.conversationId !== null && shouldPoll(this._conv.status);
    if (want && !this.#pollTimer) {
      this.#pollTimer = setInterval(() => void this.#poll(), HANDOFF_POLL_INTERVAL_MS);
    } else if (!want) {
      this.#stopPolling();
    }
  }

  #stopPolling(): void {
    if (this.#pollTimer) clearInterval(this.#pollTimer);
    this.#pollTimer = null;
  }

  /** While staff may write, re-read status and new messages (no tenant push channel yet). */
  async #poll(): Promise<void> {
    const client = this.#api();
    const convId = this._conv.conversationId;
    if (!client || !convId || this.#polling || this._conv.phase !== 'idle') return;
    this.#polling = true;
    const before = new Set(this._conv.messages.map((m) => m.key));
    const prevStatus = this._conv.status;
    try {
      const conv = await client.openConversation(this.channel || 'web');
      if (conv.id !== convId) {
        // The thread was closed; the server opened a new one for the next chat.
        this._conv = applyStatus(this._conv, 'closed', this.#key(), nowIso());
      } else {
        const page = await client.listMessages(convId, this._conv.lastSeq);
        this._conv = applyStatus(mergeHistory(this._conv, page.items), conv.status, this.#key(), nowIso());
      }
      const staffReplied = this._conv.messages.some((m) => !before.has(m.key) && m.role === 'staff');
      if (staffReplied && !this.open) {
        this._badge = true;
        this._announcement = STRINGS.newStaffReply;
      }
      this.#statusChanged(prevStatus);
    } catch {
      // Transient: the next poll retries.
    } finally {
      this.#polling = false;
    }
  }

  #statusChanged(prev: ConversationState['status']): void {
    if (this._conv.status === prev) return;
    if (this._conv.status !== 'waiting') this._timeoutAtMs = null;
    this.#emit('pdk-handoff', { state: this._conv.status });
    this.#syncPolling();
  }

  // ---- turns -----------------------------------------------------------

  async #send(text: string): Promise<void> {
    const content = text.trim();
    if (!content || this._conv.phase !== 'idle') return;
    if (!(await this.#ensureConversation())) return;
    const key = this.#key();
    const idempotencyKey = crypto.randomUUID();
    this._conv = addUserMessage(this._conv, key, content, idempotencyKey, nowIso());
    this._draft = '';
    this.#stickToBottom = true;
    await this.#runTurn(key, content, idempotencyKey);
  }

  async #runTurn(userKey: string, content: string, idempotencyKey: string): Promise<void> {
    const client = this.#api();
    const convId = this._conv.conversationId;
    if (!client || !convId) return;
    this.#abort?.abort();
    const abort = new AbortController();
    this.#abort = abort;
    let started = false;
    try {
      for await (const event of client.sendMessage(convId, content, idempotencyKey, abort.signal)) {
        if (event.type === 'message.start') started = true;
        this.#applyEvent(event);
      }
      // The body ended after `message.start` but before `message.end`.
      if (started && this._conv.streamingKey !== null) throw new NetworkError();
    } catch (err) {
      if (abort.signal.aborted) return;
      if (err instanceof NetworkError && started) {
        await this.#resume();
        return;
      }
      this.#turnFailed(err);
    } finally {
      if (this.#abort === abort) this.#abort = null;
    }
  }

  #applyEvent(event: StreamEvent): void {
    const prevStatus = this._conv.status;
    if (event.type === 'confirm.card') {
      this._slips = [...this._slips, slipFromCard(event.card, this._conv.streamingKey, crypto.randomUUID())];
      this.#focusSlipId = event.card.id;
    }
    this._conv = applyStreamEvent(this._conv, event, { newKey: this.#key(), nowIso: nowIso() });
    if (event.type === 'message.end' && this._conv.error?.kind === 'provider_unavailable') {
      this.#emit('pdk-error', { code: 'PROVIDER_UNAVAILABLE' });
    }
    if (event.type === 'error') this.#emit('pdk-error', { code: event.code });
    this.#statusChanged(prevStatus);
  }

  #turnFailed(err: unknown): void {
    let kind: ErrorKind = 'send_failed';
    let retryAfter: number | null = null;
    if (err instanceof ApiError) {
      if (err.status === 429) {
        kind = 'rate_limited';
        retryAfter = err.retryAfterS ?? DEFAULT_RETRY_AFTER_S;
        this.#rateLimitedUntil = Date.now() + retryAfter * 1_000;
        this._now = Date.now();
      } else if (err.status === 503 || err.code === 'PROVIDER_UNAVAILABLE') {
        kind = 'provider_unavailable';
      }
    }
    this.#emitError(err);
    this._conv = failTurn(this._conv, kind, retryAfter);
  }

  /** The stream broke mid-answer: the server already persisted it, so read it back. */
  async #resume(): Promise<void> {
    const client = this.#api();
    const convId = this._conv.conversationId;
    if (!client || !convId) return;
    this._conv = markReconnecting(this._conv);
    const streaming = this._conv.messages.find((m) => m.key === this._conv.streamingKey);
    const afterSeq = Math.max(0, (streaming?.seq ?? this._conv.lastSeq) - 1);
    const deadline = Date.now() + RESUME_WINDOW_MS;
    let delay = 1_000;
    while (Date.now() < deadline && this.isConnected) {
      try {
        const page = await client.listMessages(convId, afterSeq);
        this._conv = mergeHistory(this._conv, page.items);
        if (turnRecovered(this._conv)) {
          this._conv = finishRecovered(this._conv);
          return;
        }
      } catch {
        // Still offline; keep trying until the window closes.
      }
      await sleep(delay);
      delay = Math.min(delay * 2, 8_000);
    }
    this._conv = markConnectionLost(this._conv);
  }

  #retry = (): void => {
    const error = this._conv.error;
    if (!error) return;
    if (error.kind === 'connection_lost') {
      void this.#resume();
      return;
    }
    const index = this._conv.messages.findIndex((m) => m.key === error.messageKey);
    const target = this._conv.messages[index];
    if (!target) return;
    if (error.kind === 'cut_off') {
      // Ask again as a new turn; the cut-off answer stays as it was (never spliced).
      const question = this._conv.messages
        .slice(0, index)
        .reverse()
        .find((m) => m.role === 'user');
      if (question) void this.#send(question.text);
      return;
    }
    if (target.role === 'user' && target.idempotencyKey) {
      // Same Idempotency-Key: if the first attempt reached the server, it is not repeated.
      this._conv = beginTurn(this._conv, target.key);
      void this.#runTurn(target.key, target.text, target.idempotencyKey);
    }
  };

  // ---- handoff ---------------------------------------------------------

  #requestHandoff = async (): Promise<void> => {
    if (!(await this.#ensureConversation())) return;
    const client = this.#api();
    const convId = this._conv.conversationId;
    if (!client || !convId || this._conv.status === 'waiting' || this._conv.status === 'staff') return;
    const prev = this._conv.status;
    try {
      const result = await client.requestHandoff(convId);
      const timeout = Date.parse(result.timeout_at);
      this._conv = addSystemEvent(
        { ...applyStatus(this._conv, 'waiting', this.#key(), nowIso()), error: null },
        this.#key(),
        'handoff_requested',
        nowIso(),
      );
      this.#statusChanged(prev);
      this._timeoutAtMs = Number.isNaN(timeout) ? null : timeout;
      this._now = Date.now();
    } catch (err) {
      this._announcement = STRINGS.errorSendFailed;
      this.#emitError(err);
    }
  };

  #openRequestForm = (): void => {
    this.#emit('pdk-open-request-form', {});
  };

  #openSource = (source: SourceRef): void => {
    this.#emit('pdk-open-source', { document_id: source.document_id, title: source.title });
  };

  #startNewChat = async (): Promise<void> => {
    this.#stopPolling();
    this._conv = initialState();
    this._slips = [];
    this._timeoutAtMs = null;
    this.#focusAfterOpen = true;
    await this.#ensureConversation();
  };

  // ---- request slips ---------------------------------------------------

  #patchSlip(id: string, patch: Partial<Slip>): void {
    this._slips = this._slips.map((s) => (s.id === id ? { ...s, ...patch } : s));
  }

  #slipHandlers: SlipHandlers = {
    onSend: async (slip) => {
      const client = this.#api();
      if (!client || this.#slipsInFlight.has(slip.id)) return;
      this.#slipsInFlight.add(slip.id);
      this.#patchSlip(slip.id, { status: 'sending' });
      try {
        const result = await client.confirm(slip.id, slip.idempotencyKey, slip.argsHash);
        this.#patchSlip(slip.id, { status: 'confirmed', reference: referenceFrom(result) });
      } catch (err) {
        const gone =
          err instanceof ApiError &&
          (err.status === 410 || err.status === 404 || err.code === 'CONFIRMATION_EXPIRED');
        this.#patchSlip(slip.id, { status: gone ? 'expired' : 'failed' });
        this.#emitError(err);
      } finally {
        this.#slipsInFlight.delete(slip.id);
      }
    },
    onEdit: (slip) => {
      this.#patchSlip(slip.id, { status: 'editing', draft: slip.summary });
    },
    onCancel: async (slip) => {
      const client = this.#api();
      if (!client || this.#slipsInFlight.has(slip.id)) return;
      this.#slipsInFlight.add(slip.id);
      try {
        await client.cancel(slip.id);
        this.#patchSlip(slip.id, { status: 'cancelled' });
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
          this.#patchSlip(slip.id, { status: 'expired' });
        }
        this.#emitError(err);
      } finally {
        this.#slipsInFlight.delete(slip.id);
      }
    },
    onDraftInput: (slip, value) => {
      this.#patchSlip(slip.id, { draft: value });
    },
    onSaveEdit: async (slip) => {
      const text = slip.draft.trim();
      const client = this.#api();
      if (!text || !client) return;
      // Saving voids the old card; the assistant prepares a new slip (Architecture.md §7c).
      try {
        await client.cancel(slip.id);
      } catch {
        // Already expired or used: the corrected request is still sent below.
      }
      this.#patchSlip(slip.id, { status: 'replaced' });
      await this.#send(STRINGS.editRequestMessage(text));
    },
    onCancelEdit: (slip) => {
      this.#patchSlip(slip.id, { status: 'pending', draft: slip.summary });
    },
  };

  // ---- panel -----------------------------------------------------------

  #openPanel = (): void => {
    this.open = true;
  };

  #closePanel = (): void => {
    this.#focusLauncher = true;
    if (prefersReducedMotion()) {
      this.open = false;
      return;
    }
    this._closing = true;
    setTimeout(() => {
      this._closing = false;
      this.open = false;
    }, CLOSE_ANIMATION_MS);
  };

  #onPanelKeydown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      this.#closePanel();
    }
  };

  #onLogScroll = (e: Event): void => {
    const log = e.currentTarget as HTMLElement;
    this.#stickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 48;
  };

  // ---- render ----------------------------------------------------------

  #renderTimeline(): TemplateResult {
    const conv = this._conv;
    const items: TemplateResult[] = [];
    const retryWaitS = Math.max(0, Math.ceil((this.#rateLimitedUntil - this._now) / 1_000));
    const errorHandlers = {
      onRetry: this.#retry,
      onOpenRequestForm: this.#openRequestForm,
      onAskStaff: () => void this.#requestHandoff(),
    };
    const slipsAfter = (key: string | null): void => {
      for (const slip of this._slips.filter((s) => s.afterMessageKey === key)) {
        items.push(renderSlip(STRINGS, slip, this._now, this.#slipHandlers));
      }
    };

    conv.messages.forEach((message, index) => {
      items.push(
        renderMessage({
          strings: STRINGS,
          lang: this.lang || 'en',
          message,
          showLabel: startsRun(conv.messages, index),
          sourcesExpanded: this._expanded.has(message.key),
          onOpenSource: this.#openSource,
          onExpandSources: () => {
            this._expanded = new Set([...this._expanded, message.key]);
          },
          onAskStaff: () => void this.#requestHandoff(),
        }),
      );
      slipsAfter(message.key);
      if (conv.error?.messageKey === message.key) {
        items.push(renderErrorRow(STRINGS, conv.error, retryWaitS, errorHandlers));
      }
    });
    slipsAfter(null);

    if (conv.toolName) items.push(renderToolStatus(STRINGS, conv.toolName));
    else if (conv.phase === 'sending' || conv.phase === 'waiting_first_token') items.push(renderTyping(STRINGS));
    return html`${items}`;
  }

  #renderBody(): TemplateResult {
    const conv = this._conv;
    let content: TemplateResult;
    if (this._loadFailed && !conv.conversationId) {
      content = html`<div class="error-row" role="alert">
        <p><span>${STRINGS.errorUnavailable}</span></p>
        <button type="button" class="btn" @click=${() => void this.#ensureConversation()}>
          ${STRINGS.tryAgain}
        </button>
      </div>`;
    } else if (conv.messages.length === 0) {
      content = renderEmptyState({
        strings: STRINGS,
        disabled: conv.phase !== 'idle',
        onStarter: (message) => void this.#send(message),
        onTalkToPerson: () => void this.#requestHandoff(),
      });
    } else {
      content = this.#renderTimeline();
    }
    return html`<div
      class="log"
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      aria-label=${STRINGS.logLabel}
      aria-busy=${conv.phase === 'streaming' ? 'true' : 'false'}
      tabindex="0"
      @scroll=${this.#onLogScroll}
    >
      ${content}
    </div>`;
  }

  #renderFooter(): TemplateResult {
    if (this._conv.status === 'closed') {
      return html`<div class="composer-closed">
        <button type="button" class="btn btn-primary" @click=${() => void this.#startNewChat()}>
          ${STRINGS.startNewChat}
        </button>
      </div>`;
    }
    return renderComposer({
      strings: STRINGS,
      value: this._draft,
      disabled: this._conv.phase === 'sending',
      sendBlocked: this._conv.phase !== 'idle',
      coarsePointer: isCoarsePointer(),
      onInput: (value) => {
        this._draft = value;
      },
      onSend: () => void this.#send(this._draft),
    });
  }

  protected override render(): TemplateResult {
    const conv = this._conv;
    const announcer = html`<div class="sr-only" role="status" aria-live="polite">${this._announcement}</div>`;
    if (!this.open) {
      return html`${renderLauncher({ strings: STRINGS, badge: this._badge, onOpen: this.#openPanel })}${announcer}`;
    }
    const banner = renderHandoffBanner({
      strings: STRINGS,
      kind: bannerFor(conv.status, conv.emergency, this._timeoutAtMs, this._now),
      onOpenRequestForm: this.#openRequestForm,
    });
    return html`${renderPanel({
      strings: STRINGS,
      lang: this.lang || 'en',
      statusText: conv.status === 'staff' ? STRINGS.statusStaff : STRINGS.statusAssistant,
      closing: this._closing,
      onClose: this.#closePanel,
      onKeydown: this.#onPanelKeydown,
      headerAction:
        conv.status === 'ai' && conv.messages.length > 0
          ? html`<button type="button" class="btn btn-small" @click=${() => void this.#requestHandoff()}>
              ${STRINGS.talkToPerson}
            </button>`
          : nothing,
      banner,
      body: this.#renderBody(),
      notice: conv.degraded ? renderDegradedNotice(STRINGS) : nothing,
      footer: this.#renderFooter(),
    })}${announcer}`;
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('pdk-assistant')) {
  customElements.define('pdk-assistant', PdkAssistantElement);
}

declare global {
  interface HTMLElementTagNameMap {
    'pdk-assistant': PdkAssistantElement;
  }
}
