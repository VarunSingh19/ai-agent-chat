/**
 * One message (Design.md §6.1 message). Model and staff output is text only: Lit escapes
 * every interpolation, and links are recognised only for `https:` URLs and rendered as
 * plain anchors with `rel="noopener noreferrer"` (Rules.md §5 LLM10).
 */
import { html, nothing, type TemplateResult } from 'lit';
import type { SourceRef } from '../api/types.ts';
import type { Strings } from '../i18n/en.ts';
import type { ChatMessage } from '../state/conversation.ts';
import { icon } from './icons.ts';
import { renderSourceChips } from './source-chip.ts';

const URL_PATTERN = /https:\/\/[^\s<>"']+/g;
const TRAILING_PUNCTUATION = /[.,;:!?)\]}]+$/;

/** Split text into plain strings and https links. Exported for unit tests. */
export function linkify(text: string): Array<string | { href: string; label: string }> {
  const parts: Array<string | { href: string; label: string }> = [];
  let last = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    const raw = match[0];
    const trail = raw.match(TRAILING_PUNCTUATION)?.[0] ?? '';
    const href = raw.slice(0, raw.length - trail.length);
    const start = match.index ?? 0;
    let valid = false;
    try {
      valid = new URL(href).protocol === 'https:';
    } catch {
      valid = false;
    }
    if (!valid) continue;
    if (start > last) parts.push(text.slice(last, start));
    parts.push({ href, label: href });
    last = start + href.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderText(text: string): TemplateResult {
  return html`${linkify(text).map((part) =>
    typeof part === 'string'
      ? part
      : html`<a href=${part.href} target="_blank" rel="noopener noreferrer">${part.label}</a>`,
  )}`;
}

function formatTime(iso: string | null, lang: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString(lang || 'en', { hour: 'numeric', minute: '2-digit' });
}

function systemText(strings: Strings, m: ChatMessage): string {
  switch (m.systemEvent) {
    case 'handoff_requested':
      return strings.eventHandoffRequested;
    case 'staff_joined':
      return strings.eventStaffJoined;
    case 'handed_back':
      return strings.eventHandedBack;
    case 'closed':
      return strings.eventClosed;
    default:
      return m.text;
  }
}

export interface MessageProps {
  strings: Strings;
  lang: string;
  message: ChatMessage;
  showLabel: boolean;
  sourcesExpanded: boolean;
  onOpenSource: (source: SourceRef) => void;
  onExpandSources: () => void;
  onAskStaff: () => void;
}

export function renderMessage(p: MessageProps): TemplateResult {
  const { strings, message: m } = p;
  if (m.role === 'event') {
    return html`<p class="system-event ${m.isNew ? 'is-new' : ''}">${systemText(strings, m)}</p>`;
  }

  const label =
    m.role === 'user'
      ? html`${strings.youLabel}`
      : m.role === 'staff'
        ? html`${icon('person')}${strings.staffLabel}`
        : html`${strings.assistantLabel}`;
  const time = formatTime(m.createdAt, p.lang);
  const classes = [
    'msg',
    `msg-${m.role}`,
    m.isNew ? 'is-new' : '',
    m.status === 'sending' ? 'is-sending' : '',
  ].join(' ');

  return html`<article class=${classes} data-key=${m.key}>
    ${p.showLabel ? html`<p class="label">${label}</p>` : html`<span class="sr-only">${label}</span>`}
    <p class="bubble">${renderText(m.text)}</p>
    ${m.status === 'cut_off' ? html`<span class="cut-off-tag">${strings.answerCutOffLabel}</span>` : nothing}
    ${time
      ? html`<time class="time" datetime=${m.createdAt ?? ''}>
          <span class="sr-only">${strings.sentAt(time)}</span><span aria-hidden="true">${time}</span>
        </time>`
      : nothing}
    ${renderSourceChips({
      strings,
      sources: m.sources,
      expanded: p.sourcesExpanded,
      onOpen: p.onOpenSource,
      onExpand: p.onExpandSources,
    })}
    ${m.noSource
      ? html`<div class="no-source">
          <p>${strings.noSource}</p>
          <button type="button" class="btn" @click=${p.onAskStaff}>${strings.askStaff}</button>
        </div>`
      : nothing}
  </article>`;
}
