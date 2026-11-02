/**
 * Component styles for <pdk-assistant> (Design.md §3–§8).
 * Margins and paddings use only the --pdk-s* tokens (Rules.md §4, scripts/check-spacing.mjs).
 */
import { css } from 'lit';

export const baseCss = css`
  :host {
    font-family: var(--pdk-font);
    font-size: 1rem;
    line-height: 1.5;
    color: var(--pdk-text);
  }
  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }
  button,
  textarea {
    font: inherit;
    color: inherit;
  }
  :focus-visible {
    outline: 2px solid var(--pdk-focus);
    outline-offset: 2px;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: 0;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    border: 0;
  }
  svg.icon {
    width: 20px;
    height: 20px;
    flex: none;
  }

  /* Buttons ------------------------------------------------------------- */
  .btn {
    min-height: var(--pdk-target);
    min-width: var(--pdk-target);
    padding: var(--pdk-s2) var(--pdk-s4);
    border-radius: var(--pdk-r-sm);
    border: 1px solid var(--pdk-border);
    background: var(--pdk-bg);
    font-size: 0.875rem;
    line-height: 1.4;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--pdk-s2);
    text-decoration: none;
  }
  .btn-primary {
    background: var(--pdk-accent);
    color: var(--pdk-on-accent);
    border-color: var(--pdk-accent);
  }
  .btn:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }
  .btn-icon {
    padding: var(--pdk-s2);
    border: none;
    background: transparent;
  }
  .btn-small {
    padding: var(--pdk-s1) var(--pdk-s2);
    font-size: 0.8125rem;
    white-space: nowrap;
  }

  /* Launcher (Design.md §6.1 launcher) --------------------------------- */
  .launcher {
    position: fixed;
    right: calc(var(--pdk-s4) + env(safe-area-inset-right, 0px));
    bottom: calc(var(--pdk-s4) + env(safe-area-inset-bottom, 0px));
    width: 56px;
    height: 56px;
    border-radius: 50%;
    border: none;
    background: var(--pdk-accent);
    color: var(--pdk-on-accent);
    box-shadow: var(--pdk-shadow);
    cursor: pointer;
    display: grid;
    place-items: center;
    z-index: 2147483000;
  }
  .launcher svg.icon {
    width: 24px;
    height: 24px;
  }
  .badge {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--pdk-danger);
    border: 2px solid var(--pdk-on-accent);
  }

  /* Panel (Design.md §6.1 panel) --------------------------------------- */
  .panel {
    position: fixed;
    inset: 0;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    background: var(--pdk-bg);
    color: var(--pdk-text);
    z-index: 2147483000;
    animation: pdk-panel-in 180ms var(--pdk-ease);
  }
  .panel.closing {
    animation: pdk-panel-out 180ms var(--pdk-ease) forwards;
  }
  @media (min-width: 480px) {
    .panel {
      inset: auto;
      right: calc(var(--pdk-s4) + env(safe-area-inset-right, 0px));
      bottom: calc(var(--pdk-s4) + env(safe-area-inset-bottom, 0px));
      width: 380px;
      height: min(600px, calc(100dvh - var(--pdk-s6)));
      border-radius: var(--pdk-r-lg);
      box-shadow: var(--pdk-shadow);
      overflow: hidden;
    }
  }
  @keyframes pdk-panel-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  @keyframes pdk-panel-out {
    to {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  .header {
    display: flex;
    align-items: center;
    gap: var(--pdk-s3);
    padding: var(--pdk-s3) var(--pdk-s4);
    border-bottom: 1px solid var(--pdk-border);
    flex: none;
  }
  .header-text {
    flex: 1;
    min-width: 0;
  }
  .title {
    margin: 0;
    font-size: 1.125rem;
    line-height: 1.4;
    font-weight: 600;
  }
  .status-text {
    margin: 0;
    font-size: 0.8125rem;
    line-height: 1.4;
    color: var(--pdk-text-muted);
  }

  /* Handoff banner (Design.md §6.1 handoff-banner) --------------------- */
  .banner {
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--pdk-s2);
    padding: var(--pdk-s3) var(--pdk-s4);
    font-size: 0.875rem;
    line-height: 1.4;
  }
  .banner p {
    margin: 0;
    flex: 1 1 12rem;
  }
  .banner-waiting,
  .banner-timed_out {
    background: var(--pdk-warn-bg);
    color: var(--pdk-warn-text);
  }
  .banner-staff {
    background: var(--pdk-staff-bg);
    color: var(--pdk-text);
  }
  .banner-emergency {
    background: var(--pdk-bg);
    color: var(--pdk-text);
    border-left: 6px solid var(--pdk-danger);
    border-bottom: 1px solid var(--pdk-border);
    font-weight: 600;
  }
  .banner .btn {
    color: inherit;
    background: transparent;
    border-color: currentColor;
  }

  /* Message log (Design.md §6.1 message) ------------------------------- */
  .log {
    flex: 1;
    overflow-y: auto;
    padding: var(--pdk-s4);
    display: flex;
    flex-direction: column;
    gap: var(--pdk-s2);
    overscroll-behavior: contain;
  }
  .msg {
    display: flex;
    flex-direction: column;
    max-width: min(85%, 34rem);
    gap: var(--pdk-s1);
  }
  .msg.is-new {
    animation: pdk-fade 120ms linear;
  }
  @keyframes pdk-fade {
    from {
      opacity: 0;
    }
  }
  .msg-user {
    align-self: flex-end;
    align-items: flex-end;
  }
  .msg-assistant,
  .msg-staff {
    align-self: flex-start;
  }
  .label {
    margin: var(--pdk-s2) 0 0;
    font-size: 0.875rem;
    line-height: 1.4;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: var(--pdk-s1);
  }
  .bubble {
    margin: 0;
    padding: var(--pdk-s2) var(--pdk-s3);
    border: 1px solid transparent;
    border-radius: var(--pdk-r-md);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .msg-user .bubble {
    background: var(--pdk-accent);
    color: var(--pdk-on-accent);
    border-bottom-right-radius: var(--pdk-r-tail);
  }
  .msg-user .bubble a {
    color: inherit;
  }
  /* Muted until message.start (Design.md §6.2 state 2) without opacity, so contrast holds. */
  .msg-user.is-sending .bubble {
    background: var(--pdk-surface);
    color: var(--pdk-text);
    border-style: dashed;
    border-color: var(--pdk-accent);
  }
  .msg-assistant .bubble {
    background: var(--pdk-surface);
    border-bottom-left-radius: var(--pdk-r-tail);
  }
  .msg-staff .bubble {
    background: var(--pdk-staff-bg);
    border-bottom-left-radius: var(--pdk-r-tail);
  }
  .bubble a {
    color: var(--pdk-accent);
  }
  .msg-assistant .bubble a,
  .msg-staff .bubble a {
    color: var(--pdk-text);
    text-decoration-color: var(--pdk-accent);
  }
  .cut-off-tag {
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
  }
  .time {
    font-size: 0.8125rem;
    line-height: 1.4;
    color: var(--pdk-text-muted);
    font-variant-numeric: tabular-nums;
    visibility: hidden;
  }
  .msg:hover .time,
  .msg:focus-within .time {
    visibility: visible;
  }
  .system-event {
    align-self: center;
    margin: var(--pdk-s2) 0;
    font-size: 0.8125rem;
    line-height: 1.4;
    color: var(--pdk-text-muted);
    text-align: center;
  }
  .no-source {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--pdk-s2);
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
  }
  .no-source p {
    margin: 0;
  }

  /* Source chips (Design.md §6.1 source-chip) -------------------------- */
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--pdk-s2);
  }
  .chip {
    min-height: var(--pdk-target);
    padding: var(--pdk-s1) var(--pdk-s3);
    border: 1px solid var(--pdk-border);
    border-radius: var(--pdk-r-sm);
    background: var(--pdk-bg);
    font-size: 0.8125rem;
    line-height: 1.4;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--pdk-s1);
    text-align: left;
  }
  .chip svg.icon {
    width: 16px;
    height: 16px;
  }

  /* Status line and typing (Design.md §6.1 status-line, typing) -------- */
  .status-line {
    align-self: flex-start;
    margin: 0;
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
  }
  .typing {
    align-self: flex-start;
    display: inline-flex;
    gap: var(--pdk-s1);
    padding: var(--pdk-s3);
    border-radius: var(--pdk-r-md);
    background: var(--pdk-surface);
  }
  .typing .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--pdk-text-muted);
    animation: pdk-dot 1.2s infinite ease-in-out;
  }
  .typing .dot:nth-child(2) {
    animation-delay: 0.2s;
  }
  .typing .dot:nth-child(3) {
    animation-delay: 0.4s;
  }
  .typing .typing-text {
    display: none;
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
  }
  @keyframes pdk-dot {
    0%,
    80%,
    100% {
      opacity: 0.3;
    }
    40% {
      opacity: 1;
    }
  }

  /* Request slip (Design.md §6.1 request-slip) ------------------------- */
  .slip {
    align-self: stretch;
    margin: var(--pdk-s2) 0;
    border: 1px solid var(--pdk-border);
    border-radius: var(--pdk-r-md);
    background: var(--pdk-bg);
    transition:
      background-color 150ms linear,
      border-color 150ms linear;
    position: relative;
  }
  .slip::before {
    content: '';
    display: block;
    border-top: 2px dashed var(--pdk-border);
    margin: 0 var(--pdk-s3);
    padding-top: var(--pdk-s1);
  }
  .slip-body {
    padding: var(--pdk-s2) var(--pdk-s4) var(--pdk-s3);
  }
  .slip-heading {
    margin: 0 0 var(--pdk-s2);
    font-size: 1rem;
    font-weight: 600;
  }
  .slip-fields {
    margin: 0;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--pdk-s1) var(--pdk-s3);
  }
  .slip-fields dt {
    font-size: 0.875rem;
    font-weight: 600;
  }
  .slip-fields dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .slip-meta {
    margin: var(--pdk-s2) 0 0;
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
    font-variant-numeric: tabular-nums;
  }
  .slip-stub {
    display: flex;
    flex-wrap: wrap;
    gap: var(--pdk-s2);
    padding: var(--pdk-s3) var(--pdk-s4);
    border-top: 1px solid var(--pdk-border);
    background: var(--pdk-surface);
    border-radius: 0 0 var(--pdk-r-md) var(--pdk-r-md);
  }
  .slip textarea {
    width: 100%;
    min-height: 6rem;
    padding: var(--pdk-s2);
    border: 1px solid var(--pdk-border);
    border-radius: var(--pdk-r-sm);
    background: var(--pdk-bg);
    resize: vertical;
  }
  .slip-result {
    margin: 0;
    display: flex;
    align-items: center;
    gap: var(--pdk-s2);
    font-weight: 600;
  }
  .slip-confirmed {
    border-color: var(--pdk-ok);
  }
  .slip-confirmed .slip-result {
    color: var(--pdk-ok);
  }
  .slip-collapsed {
    padding: var(--pdk-s2) var(--pdk-s4);
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
  }
  .slip-collapsed::before {
    display: none;
  }
  .check path {
    stroke-dasharray: 24;
    stroke-dashoffset: 0;
    animation: pdk-check 200ms var(--pdk-ease);
  }
  @keyframes pdk-check {
    from {
      stroke-dashoffset: 24;
    }
  }
  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: pdk-spin 0.8s linear infinite;
  }
  @keyframes pdk-spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* Error row and notices (Design.md §6.1 error-row, degraded-notice) -- */
  .error-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--pdk-s2);
    padding: var(--pdk-s2) 0;
    font-size: 0.875rem;
    color: var(--pdk-text);
  }
  .error-row p {
    margin: 0;
    flex: 1 1 100%;
    display: flex;
    gap: var(--pdk-s2);
    align-items: flex-start;
  }
  .error-row svg.icon {
    color: var(--pdk-danger);
  }
  .notice {
    flex: none;
    margin: 0;
    padding: var(--pdk-s2) var(--pdk-s4);
    background: var(--pdk-warn-bg);
    color: var(--pdk-warn-text);
    font-size: 0.875rem;
    line-height: 1.4;
  }

  /* Empty state (Design.md §6.1 empty-state) --------------------------- */
  .empty {
    display: flex;
    flex-direction: column;
    gap: var(--pdk-s3);
    padding: var(--pdk-s2) 0;
  }
  .empty p {
    margin: 0;
  }
  .starters {
    display: flex;
    flex-direction: column;
    gap: var(--pdk-s2);
  }
  .starters .btn {
    justify-content: flex-start;
    text-align: left;
  }

  /* Composer (Design.md §6.1 composer) --------------------------------- */
  .composer {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: var(--pdk-s1);
    padding: var(--pdk-s3) var(--pdk-s4) calc(var(--pdk-s3) + env(safe-area-inset-bottom, 0px));
    background: var(--pdk-surface);
    border-top: 1px solid var(--pdk-border);
  }
  .composer-row {
    display: flex;
    align-items: flex-end;
    gap: var(--pdk-s2);
  }
  .composer textarea {
    flex: 1;
    min-height: 48px;
    max-height: calc(1.5em * 5 + var(--pdk-s3) * 2);
    padding: var(--pdk-s3);
    border: 1px solid var(--pdk-border);
    border-radius: var(--pdk-r-sm);
    background: var(--pdk-bg);
    resize: none;
    overflow-y: auto;
  }
  .composer .btn {
    min-height: 48px;
  }
  .char-count {
    margin: 0;
    font-size: 0.8125rem;
    color: var(--pdk-text-muted);
    text-align: right;
  }
  .composer-closed {
    flex: none;
    padding: var(--pdk-s3) var(--pdk-s4);
    border-top: 1px solid var(--pdk-border);
    display: flex;
    justify-content: center;
  }

  /* Reduced motion (Design.md §7) -------------------------------------- */
  @media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
    .typing .dot {
      display: none;
    }
    .typing .typing-text {
      display: inline;
    }
  }
`;
