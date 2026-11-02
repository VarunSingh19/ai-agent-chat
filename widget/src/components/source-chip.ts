/**
 * Source chips under an answer (Design.md §6.1 source-chip). At most 3, the rest collapse
 * into "+N more". Activating a chip asks the host to open the document; the widget never
 * fetches the file itself.
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { SourceRef } from '../api/types.ts';
import type { Strings } from '../i18n/en.ts';
import { icon } from './icons.ts';

const MAX_VISIBLE = 3;

export interface SourceChipsProps {
  strings: Strings;
  sources: SourceRef[];
  expanded: boolean;
  onOpen: (source: SourceRef) => void;
  onExpand: () => void;
}

export function renderSourceChips(p: SourceChipsProps): TemplateResult | typeof nothing {
  if (p.sources.length === 0) return nothing;
  const visible = p.expanded ? p.sources : p.sources.slice(0, MAX_VISIBLE);
  const hidden = p.sources.length - visible.length;
  return html`<div class="chips">
    ${visible.map(
      (s) => html`<button type="button" class="chip" @click=${() => p.onOpen(s)}>
        ${icon('document')}<span>${p.strings.sourcePrefix} ${s.title}</span>
      </button>`,
    )}
    ${hidden > 0
      ? html`<button type="button" class="chip" @click=${p.onExpand}>
          ${p.strings.sourceMore(hidden)}
        </button>`
      : nothing}
  </div>`;
}
