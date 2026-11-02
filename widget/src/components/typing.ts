/**
 * Typing indicator (Design.md §6.1 typing): three dots between send and first token.
 * Under prefers-reduced-motion the dots are hidden and the text is shown (base.css.ts).
 */
import { html, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';

export function renderTyping(strings: Strings): TemplateResult {
  return html`<div class="typing" role="status" aria-label=${strings.typing}>
    <span class="dot" aria-hidden="true"></span><span class="dot" aria-hidden="true"></span
    ><span class="dot" aria-hidden="true"></span>
    <span class="typing-text" aria-hidden="true">${strings.typing}</span>
  </div>`;
}

/** Status line while a tool runs (Design.md §6.1 status-line). */
export function renderToolStatus(strings: Strings, toolName: string): TemplateResult {
  const sentence = strings.toolSentences[toolName] ?? strings.toolDefault;
  return html`<p class="status-line" role="status">${sentence}</p>`;
}
