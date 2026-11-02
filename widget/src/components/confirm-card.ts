/**
 * Request slip, the confirm card (Design.md §6.1 request-slip, §8). `role="group"` named by
 * its heading; focus moves to the heading when it appears, and Send is one Tab away.
 * The Send button disables on first activation (double-tap safe).
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import { isNoteTool, minutesLeft, type Slip } from '../state/confirm.ts';
import { icon } from './icons.ts';

export interface SlipHandlers {
  onSend: (slip: Slip) => void;
  onEdit: (slip: Slip) => void;
  onCancel: (slip: Slip) => void;
  onDraftInput: (slip: Slip, value: string) => void;
  onSaveEdit: (slip: Slip) => void;
  onCancelEdit: (slip: Slip) => void;
}

export function renderSlip(
  strings: Strings,
  slip: Slip,
  nowMs: number,
  h: SlipHandlers,
): TemplateResult {
  const note = isNoteTool(slip.tool);
  const headingId = `slip-h-${slip.id}`;

  if (slip.status === 'replaced') {
    return html`<div class="slip slip-collapsed" data-slip=${slip.id}>${strings.slipReplaced}</div>`;
  }

  const heading = html`<h3 class="slip-heading" id=${headingId} tabindex="-1" data-slip-heading=${slip.id}>
    ${note ? strings.slipHeadingNote : strings.slipHeadingRequest}
  </h3>`;

  const what =
    slip.status === 'editing'
      ? html`<label class="sr-only" for="slip-edit-${slip.id}">${strings.slipEditLabel}</label>
          <textarea
            id="slip-edit-${slip.id}"
            .value=${slip.draft}
            maxlength="4000"
            @input=${(e: Event) => h.onDraftInput(slip, (e.target as HTMLTextAreaElement).value)}
          ></textarea>`
      : html`${slip.summary}`;

  const fields = html`<dl class="slip-fields">
    <dt>${strings.slipWhat}</dt>
    <dd>${what}</dd>
  </dl>`;

  let footer: TemplateResult | typeof nothing = nothing;
  let meta: TemplateResult | typeof nothing = nothing;
  switch (slip.status) {
    case 'pending':
      meta = html`<p class="slip-meta">${strings.slipExpiresIn(minutesLeft(slip, nowMs))}</p>`;
      footer = html`<div class="slip-stub">
        <button type="button" class="btn btn-primary" data-slip-send @click=${() => h.onSend(slip)}>
          ${note ? strings.slipSendNote : strings.slipSend}
        </button>
        ${note
          ? nothing
          : html`<button type="button" class="btn" @click=${() => h.onEdit(slip)}>${strings.slipEdit}</button>`}
        <button type="button" class="btn" @click=${() => h.onCancel(slip)}>${strings.slipCancel}</button>
      </div>`;
      break;
    case 'editing':
      meta = html`<p class="slip-meta">${strings.slipExpiresIn(minutesLeft(slip, nowMs))}</p>`;
      footer = html`<div class="slip-stub">
        <button
          type="button"
          class="btn btn-primary"
          ?disabled=${slip.draft.trim() === ''}
          @click=${() => h.onSaveEdit(slip)}
        >
          ${strings.slipSave}
        </button>
        <button type="button" class="btn" @click=${() => h.onCancelEdit(slip)}>${strings.slipKeep}</button>
      </div>`;
      break;
    case 'sending':
      footer = html`<div class="slip-stub">
        <button type="button" class="btn btn-primary" disabled aria-disabled="true">
          <span class="spinner" aria-hidden="true"></span>${strings.slipSending}
        </button>
      </div>`;
      break;
    case 'confirmed':
      footer = html`<div class="slip-stub">
        <p class="slip-result" role="status">
          ${icon('check', 'check')}${note ? strings.slipNoteSent : strings.slipSent}
          ${slip.reference ? html`<span>· ${strings.slipReference(slip.reference)}</span>` : nothing}
        </p>
      </div>`;
      break;
    case 'expired':
      footer = html`<div class="slip-stub"><p class="slip-result">${strings.slipExpired}</p></div>`;
      break;
    case 'cancelled':
      footer = html`<div class="slip-stub"><p class="slip-result">${strings.slipCancelled}</p></div>`;
      break;
    case 'failed':
      footer = html`<div class="slip-stub">
        <p class="slip-result" role="alert">${icon('warning')}${strings.slipFailed}</p>
        <button type="button" class="btn btn-primary" data-slip-send @click=${() => h.onSend(slip)}>
          ${icon('refresh')}${strings.tryAgain}
        </button>
      </div>`;
      break;
  }

  return html`<div
    class="slip slip-${slip.status}"
    role="group"
    aria-labelledby=${headingId}
    data-slip=${slip.id}
  >
    <div class="slip-body">${heading}${fields}${meta}</div>
    ${footer}
  </div>`;
}
