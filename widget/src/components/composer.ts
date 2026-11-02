/**
 * Composer (Design.md §6.1 composer): a growing textarea (up to 5 lines) and Send.
 * Enter sends on desktop and inserts a newline on touch devices; Send always works.
 * The character count appears only within 100 of the limit. The attach-photo button is
 * not rendered: the conversation API exposes no per-org triage flag to the widget yet.
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import { icon } from './icons.ts';

export const MAX_MESSAGE_LENGTH = 4000;
const COUNT_THRESHOLD = 100;

export interface ComposerProps {
  strings: Strings;
  value: string;
  /** While a message is being posted. */
  disabled: boolean;
  /** While an answer streams: typing stays possible, sending waits. */
  sendBlocked: boolean;
  coarsePointer: boolean;
  onInput: (value: string) => void;
  onSend: () => void;
}

function grow(el: HTMLTextAreaElement): void {
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

export function renderComposer(p: ComposerProps): TemplateResult {
  const left = MAX_MESSAGE_LENGTH - p.value.length;
  const onKeydown = (e: KeyboardEvent): void => {
    if (e.key === 'Enter' && !e.shiftKey && !p.coarsePointer && !e.isComposing) {
      e.preventDefault();
      if (!p.sendBlocked) p.onSend();
    }
  };
  return html`<form
    class="composer"
    @submit=${(e: Event) => {
      e.preventDefault();
      p.onSend();
    }}
  >
    <div class="composer-row">
      <label class="sr-only" for="pdk-composer">${p.strings.composerLabel}</label>
      <textarea
        id="pdk-composer"
        rows="1"
        maxlength=${MAX_MESSAGE_LENGTH}
        placeholder=${p.strings.composerPlaceholder}
        aria-describedby=${left <= COUNT_THRESHOLD ? 'pdk-count' : nothing}
        .value=${p.value}
        ?disabled=${p.disabled}
        @input=${(e: Event) => {
          const el = e.target as HTMLTextAreaElement;
          grow(el);
          p.onInput(el.value);
        }}
        @keydown=${onKeydown}
      ></textarea>
      <button
        type="submit"
        class="btn btn-primary"
        ?disabled=${p.disabled || p.sendBlocked || p.value.trim() === ''}
      >
        ${icon('send')}<span>${p.strings.sendButton}</span>
      </button>
    </div>
    ${left <= COUNT_THRESHOLD
      ? html`<p class="char-count" id="pdk-count">${p.strings.charactersLeft(left)}</p>`
      : nothing}
  </form>`;
}
