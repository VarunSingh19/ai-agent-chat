/**
 * Design tokens for <pdk-assistant> (Design.md §2–§5).
 *
 * PALETTE is the single source for colours: the CSS below is generated from it and
 * `scripts/check-contrast.mjs` reads it to enforce the §2 contrast minimums in CI.
 * Host-overridable: --pdk-accent, --pdk-on-accent, --pdk-font, --pdk-radius-scale.
 */
import { css, unsafeCSS } from 'lit';

export const PALETTE = {
  light: {
    '--pdk-bg': '#FFFFFF',
    '--pdk-surface': '#F3F5F7',
    '--pdk-text': '#18222D',
    '--pdk-text-muted': '#4A5968',
    '--pdk-border': '#7A8896',
    '--pdk-accent': '#0A5A66',
    '--pdk-on-accent': '#FFFFFF',
    '--pdk-staff-bg': '#E4EEF7',
    '--pdk-warn-bg': '#FFF1CF',
    '--pdk-warn-text': '#5A3800',
    '--pdk-danger': '#A12027',
    '--pdk-ok': '#1A6A38',
    '--pdk-focus': '#1550C0',
  },
  dark: {
    '--pdk-bg': '#10171E',
    '--pdk-surface': '#1A2430',
    '--pdk-text': '#E9EEF3',
    '--pdk-text-muted': '#A9B5C1',
    '--pdk-border': '#6B7A89',
    '--pdk-accent': '#63C3CF',
    '--pdk-on-accent': '#082024',
    '--pdk-staff-bg': '#1D3144',
    '--pdk-warn-bg': '#3A2D0B',
    '--pdk-warn-text': '#FFDFA0',
    '--pdk-danger': '#FF8D92',
    '--pdk-ok': '#7FD39A',
    '--pdk-focus': '#8FB4FF',
  },
} as const;

type Scheme = keyof typeof PALETTE;

// Declared on :host, so a host rule on the element (e.g. `pdk-assistant { --pdk-accent: … }`)
// wins over these defaults in both schemes. Only the tokens marked in Design.md are supported.
function declarations(scheme: Scheme): string {
  return Object.entries(PALETTE[scheme])
    .map(([name, value]) => `${name}: ${value};`)
    .join('\n');
}

export const tokensCss = css`
  :host {
    ${unsafeCSS(declarations('light'))}
    --pdk-font: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    --pdk-s1: 0.25rem;
    --pdk-s2: 0.5rem;
    --pdk-s3: 0.75rem;
    --pdk-s4: 1rem;
    --pdk-s5: 1.5rem;
    --pdk-s6: 2rem;
    --pdk-r-sm: calc(6px * var(--pdk-radius-scale, 1));
    --pdk-r-md: calc(12px * var(--pdk-radius-scale, 1));
    --pdk-r-lg: calc(16px * var(--pdk-radius-scale, 1));
    --pdk-r-tail: 4px;
    --pdk-target: 2.75rem;
    --pdk-shadow: 0 8px 24px rgb(0 0 0 / 0.18);
    --pdk-ease: cubic-bezier(0.2, 0, 0, 1);
    color-scheme: light;
  }
  :host([data-theme='dark']) {
    ${unsafeCSS(declarations('dark'))}
    color-scheme: dark;
  }
  @media (prefers-color-scheme: dark) {
    :host(:not([data-theme='light'])) {
      ${unsafeCSS(declarations('dark'))}
      color-scheme: dark;
    }
  }
`;
