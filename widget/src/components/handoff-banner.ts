/**
 * Handoff banner, pinned under the header while the thread is not with the AI
 * (Design.md §6.1 handoff-banner). The emergency banner is `role="alert"` and is never
 * dismissible while the thread is in the emergency state.
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import type { BannerKind } from '../state/handoff.ts';
import { icon } from './icons.ts';

export interface BannerProps {
  strings: Strings;
  kind: BannerKind;
  onOpenRequestForm: () => void;
}

export function renderHandoffBanner(p: BannerProps): TemplateResult | typeof nothing {
  const s = p.strings;
  switch (p.kind) {
    case 'none':
      return nothing;
    case 'waiting':
      return html`<div class="banner banner-waiting" role="status"><p>${s.handoffWaiting}</p></div>`;
    case 'timed_out':
      return html`<div class="banner banner-timed_out" role="status">
        <p>${s.handoffTimedOut}</p>
        <button type="button" class="btn" @click=${p.onOpenRequestForm}>${s.openRequestForm}</button>
      </div>`;
    case 'staff':
      return html`<div class="banner banner-staff" role="status">
        ${icon('person')}
        <p>${s.handoffStaff}</p>
      </div>`;
    case 'emergency':
      return html`<div class="banner banner-emergency" role="alert">
        <p>${s.emergencyBanner}</p>
        <a class="btn" href="tel:${s.emergencyNumber}">${icon('phone')}${s.emergencyCall}</a>
      </div>`;
  }
}
