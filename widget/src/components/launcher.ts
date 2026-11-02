/** Launcher button (Design.md §6.1 launcher). Hidden while the panel is open. */
import { html, nothing, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import { icon } from './icons.ts';

export interface LauncherProps {
  strings: Strings;
  badge: boolean;
  onOpen: () => void;
}

export function renderLauncher({ strings, badge, onOpen }: LauncherProps): TemplateResult {
  const name = badge ? `${strings.launcherLabel}. ${strings.launcherBadgeLabel}` : strings.launcherLabel;
  return html`<button
    type="button"
    class="launcher"
    part="launcher"
    aria-label=${name}
    aria-haspopup="dialog"
    aria-expanded="false"
    @click=${onOpen}
  >
    ${icon('chat')}${badge ? html`<span class="badge" aria-hidden="true"></span>` : nothing}
  </button>`;
}
