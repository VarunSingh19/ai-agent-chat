/**
 * Inline SVG icons (Design.md §9): 24 px grid, currentColor, 1.75 px stroke, decorative
 * (`aria-hidden`); every icon sits next to a text label or inside a named control.
 */
import { svg, type SVGTemplateResult } from 'lit';

export type IconName =
  | 'chat'
  | 'close'
  | 'send'
  | 'person'
  | 'check'
  | 'warning'
  | 'document'
  | 'phone'
  | 'refresh';

const PATHS: Record<IconName, SVGTemplateResult> = {
  chat: svg`<path d="M4 5h16v11H9l-5 4z" />`,
  close: svg`<path d="M6 6l12 12M18 6L6 18" />`,
  send: svg`<path d="M4 12l16-8-6 16-2.5-6.5z" /><path d="M11.5 13.5L20 4" />`,
  person: svg`<circle cx="12" cy="8" r="3.5" /><path d="M5 20c1-4 4-6 7-6s6 2 7 6" />`,
  check: svg`<path d="M5 12.5l4.5 4.5L19 7.5" />`,
  warning: svg`<path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17v.5" />`,
  document: svg`<path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M10 12h5M10 16h5" />`,
  phone: svg`<path d="M6 3h3l1.5 5-2 1.5a11 11 0 0 0 6 6l1.5-2 5 1.5v3a2 2 0 0 1-2 2A17 17 0 0 1 4 5a2 2 0 0 1 2-2z" />`,
  refresh: svg`<path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" />`,
};

export function icon(name: IconName, extraClass = ''): SVGTemplateResult {
  return svg`<svg class="icon ${extraClass}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
    focusable="false">${PATHS[name]}</svg>`;
}
