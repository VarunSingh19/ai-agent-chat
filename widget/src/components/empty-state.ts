/**
 * Empty state on first open (Design.md §6.1 empty-state): one sentence, three starters
 * that send real messages, and a persistent "Talk to a person".
 *
 * Design.md asks for starters filtered by `org_settings.enabled_tools`; the conversation
 * API does not expose that to tenants yet (Memory.md K-008), so all three are shown.
 */
import { html, type TemplateResult } from 'lit';
import type { Strings } from '../i18n/en.ts';
import { icon } from './icons.ts';

export interface EmptyStateProps {
  strings: Strings;
  disabled: boolean;
  onStarter: (message: string) => void;
  onTalkToPerson: () => void;
}

export function renderEmptyState(p: EmptyStateProps): TemplateResult {
  const s = p.strings;
  const starters: Array<[string, string]> = [
    [s.starterStatus, s.starterStatusMessage],
    [s.starterReport, s.starterReportMessage],
    [s.starterRules, s.starterRulesMessage],
  ];
  return html`<div class="empty">
    <p>${s.emptyIntro}</p>
    <div class="starters">
      ${starters.map(
        ([label, message]) =>
          html`<button type="button" class="btn" ?disabled=${p.disabled} @click=${() => p.onStarter(message)}>
            ${label}
          </button>`,
      )}
      <button type="button" class="btn" ?disabled=${p.disabled} @click=${p.onTalkToPerson}>
        ${icon('person')}${s.talkToPerson}
      </button>
    </div>
  </div>`;
}
