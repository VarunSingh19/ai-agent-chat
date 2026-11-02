/**
 * Inline error row under the failed message (Design.md §6.1 error-row). Says what happened
 * and what to do; no codes, no provider text. Send failures use `role="alert"`.
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import type { ErrorRow } from '../state/conversation.ts';
import { icon } from './icons.ts';

export interface ErrorRowHandlers {
  onRetry: () => void;
  onOpenRequestForm: () => void;
  onAskStaff: () => void;
}

export function renderErrorRow(
  strings: Strings,
  error: ErrorRow,
  retryWaitS: number,
  h: ErrorRowHandlers,
): TemplateResult {
  const retry = (disabled = false): TemplateResult =>
    html`<button type="button" class="btn" ?disabled=${disabled} @click=${h.onRetry}>
      ${icon('refresh')}${strings.tryAgain}
    </button>`;

  let text: string;
  let actions: TemplateResult | typeof nothing = nothing;
  let role: 'alert' | 'status' = 'alert';
  switch (error.kind) {
    case 'rate_limited':
      text = strings.errorRateLimited(Math.max(retryWaitS, 1));
      actions = retry(retryWaitS > 0);
      break;
    case 'provider_unavailable':
      text = strings.errorProviderUnavailable;
      actions = html`<button type="button" class="btn" @click=${h.onOpenRequestForm}>
          ${strings.openRequestForm}
        </button>
        <button type="button" class="btn" @click=${h.onAskStaff}>${strings.askStaff}</button>`;
      break;
    case 'reconnecting':
      text = strings.errorReconnecting;
      role = 'status';
      break;
    case 'connection_lost':
      text = strings.errorConnectionLost;
      actions = retry();
      break;
    case 'cut_off':
      text = strings.errorCutOff;
      actions = retry();
      break;
    case 'send_failed':
      text = strings.errorSendFailed;
      actions = retry();
      break;
  }

  return html`<div class="error-row" role=${role}>
    <p>${icon('warning')}<span>${text}</span></p>
    ${actions}
  </div>`;
}
