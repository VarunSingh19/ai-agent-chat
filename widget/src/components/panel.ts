/**
 * Panel shell (Design.md §6.1 panel): header with title, status line and close button,
 * then banner, log, notice and composer regions supplied by the element.
 */
import { html, type nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import { icon } from './icons.ts';

export interface PanelProps {
  strings: Strings;
  lang: string;
  statusText: string;
  closing: boolean;
  onClose: () => void;
  onKeydown: (e: KeyboardEvent) => void;
  /** Persistent "Talk to a person" while the assistant handles the thread (Design.md §6.1). */
  headerAction: TemplateResult | typeof nothing;
  banner: TemplateResult | typeof nothing;
  body: TemplateResult;
  notice: TemplateResult | typeof nothing;
  footer: TemplateResult;
}

export function renderPanel(p: PanelProps): TemplateResult {
  return html`<section
    class="panel ${p.closing ? 'closing' : ''}"
    part="panel"
    role="dialog"
    aria-modal="false"
    aria-labelledby="pdk-title"
    lang=${p.lang}
    @keydown=${p.onKeydown}
  >
    <header class="header">
      <div class="header-text">
        <h2 class="title" id="pdk-title">${p.strings.panelTitle}</h2>
        <p class="status-text">${p.statusText}</p>
      </div>
      ${p.headerAction}
      <button
        type="button"
        class="btn btn-icon"
        data-close
        aria-label=${p.strings.closeLabel}
        @click=${p.onClose}
      >
        ${icon('close')}
      </button>
    </header>
    ${p.banner} ${p.body} ${p.notice} ${p.footer}
  </section>`;
}
