/**
 * Degraded-mode notice (Design.md §6.1 degraded-notice), shown when the last answer
 * carried `degraded=true`. Not shown for `degraded_retrieval`, which the user cannot act on.
 */
import { html, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';

export function renderDegradedNotice(strings: Strings): TemplateResult {
  return html`<p class="notice" role="status">${strings.degradedNotice}</p>`;
}
