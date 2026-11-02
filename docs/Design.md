# Design.md — Visual Design System (`<pdk-assistant>` widget)

Scope: the web widget in `/widget` (Architecture.md §4). The tenant and management mobile apps do not use the widget; they call the same conversation API and must render the same states (§6.2). Backend has no UI.

PropertyDek's brand tokens were not available when this file was written (Memory.md Q11). The palette below is a neutral default. A host page may override the tokens marked **host-overridable**; everything else is fixed.

## 1. Design principles

1. **Residents first.** Many tenants use older phones on metered data and are not tech-fluent. So: system fonts only (no font download), one small JS bundle, plain words, large tap targets, works at 320 px.
2. **Always clear who is talking.** The assistant, a staff member and the system each look different and carry a text label. Colour is never the only signal.
3. **Quiet by default, one distinctive element.** Chat is flat and calm. The one designed object is the **request slip** (the confirm card, §6.1), because it is the only place the assistant changes anything. It looks like a work-order slip the user signs off.
4. **Show what happened, not how.** Show "Checking your requests" and the source document. Never show raw reasoning, tool names, JSON or ids.
5. **Model output is text.** Never rendered as HTML (Rules.md §5, LLM10).

## 2. Colour system

Tokens are CSS custom properties on `:host`, defined in `src/styles/tokens.css.ts`. Dark values apply under `@media (prefers-color-scheme: dark)` and when the host sets `data-theme="dark"` on the element. Contrast ratios were calculated, not estimated; CI re-checks them (§8).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--pdk-bg` | `#FFFFFF` | `#10171E` | panel background |
| `--pdk-surface` | `#F3F5F7` | `#1A2430` | assistant bubble, composer area |
| `--pdk-text` | `#18222D` | `#E9EEF3` | body text |
| `--pdk-text-muted` | `#4A5968` | `#A9B5C1` | timestamps, hints |
| `--pdk-border` | `#7A8896` | `#6B7A89` | input borders, dividers that carry meaning |
| `--pdk-accent` **host-overridable** | `#0A5A66` | `#63C3CF` | user bubble, primary button, links |
| `--pdk-on-accent` **host-overridable** | `#FFFFFF` | `#082024` | text on accent |
| `--pdk-staff-bg` | `#E4EEF7` | `#1D3144` | staff message bubble |
| `--pdk-warn-bg` / `--pdk-warn-text` | `#FFF1CF` / `#5A3800` | `#3A2D0B` / `#FFDFA0` | handoff waiting, degraded mode |
| `--pdk-danger` | `#A12027` | `#FF8D92` | errors, emergency banner accent |
| `--pdk-ok` | `#1A6A38` | `#7FD39A` | confirmed state |
| `--pdk-focus` | `#1550C0` | `#8FB4FF` | focus ring |

Minimums enforced: body text ≥ 4.5:1 on its background; large text and UI boundaries (inputs, focus ring) ≥ 3:1. A host that overrides `--pdk-accent` must keep `--pdk-on-accent` at ≥ 4.5:1 against it. The e2e suite runs once with a sample host theme to prove this.

## 3. Typography

Font: `--pdk-font: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` (**host-overridable**). No webfont, because each font file is a download on a metered connection.
Numbers in request ids, dates and money use `font-variant-numeric: tabular-nums`.
All sizes in `rem`, so the user's system font size is respected; layout must still work at 200% text.

| Level | Size | Line height | Weight | Use |
|---|---|---|---|---|
| `title` | 1.125rem | 1.4 | 600 | panel header |
| `body` | 1rem | 1.5 | 400 | messages, composer |
| `label` | 0.875rem | 1.4 | 600 | sender label, card field names, buttons |
| `small` | 0.8125rem | 1.4 | 400 | timestamps, source chips, hints |

Messages: max line length about 65 characters (bubbles cap at `min(85%, 34rem)`). No all-caps. Sentence case everywhere.

## 4. Spacing scale

Base unit 4 px. Allowed values: `--pdk-s1` 4, `s2` 8, `s3` 12, `s4` 16, `s5` 24, `s6` 32. **No arbitrary spacing values in component CSS** (proposed Rules.md §4 addition: a grep check in CI fails on raw `px` margins and paddings outside these tokens; no new linter).

## 5. Shape, elevation

- Radius: `--pdk-r-sm` 6 (chips, inputs), `--pdk-r-md` 12 (bubbles), `--pdk-r-lg` 16 (panel). Radius is **host-overridable** as one multiplier.
- Bubble tail corner: 4 px on the corner nearest the sender.
- Elevation: one shadow, on the floating panel and launcher only: `0 8px 24px rgb(0 0 0 / 0.18)`. Nothing inside the panel has a shadow.

## 6. Components

### 6.1 Component specs

<component id="launcher">
  Round button, 56 px, bottom-right with `env(safe-area-inset-*)` offset. Icon plus accessible name "Chat with building assistant". Badge dot when staff replied while closed (also announced). Hidden while the panel is open.
</component>

<component id="panel">
  Desktop (≥ 480 px wide viewport): 380 × 600 px, anchored to the launcher. Narrow screens: full-screen sheet using `100dvh`, with header and composer pinned. Header: title, a status line ("Assistant" or "Staff: first name"), close button. Focus moves into the panel on open and returns to the launcher on close. Esc closes.
</component>

<component id="message">
  Three kinds, each with a text label above the first message in a run:
  - **You**: right-aligned, accent background.
  - **Assistant**: left-aligned, surface background, label "Assistant".
  - **Staff**: left-aligned, staff background, label with the staff member's first name and the word "Staff". A small person icon, not just colour.
  - **System event** (handoff started, handed back, thread closed): centred, `small`, muted, no bubble.
  Text only. Links in answers are plain anchors with `rel="noopener noreferrer"`, allow-listed to `https:`. Timestamps on hover/focus and in the accessible name.
</component>

<component id="source-chip">
  Under an assistant answer: "From: House rules (2026)". `small`, border, 44 px tap target. Opens the document title in the host (event `pdk-open-source`), never fetches the file inside the widget. Maximum 3 chips; the rest collapse into "+2 more".
</component>

<component id="status-line">
  Shows one plain sentence while a tool runs, from the `tool.start` event: "Checking your requests…", "Looking up your balance…". Replaced by the answer. Tool names are mapped to sentences in `i18n/en.ts`; unknown tools show "Looking that up…". Announced politely once, not per token.
</component>

<component id="request-slip">
  The confirm card (the one distinctive element). A slip with a dashed tear line along its top edge and a stub area for the buttons.
  - Heading: "Review this request" (for `create_request`) or "Review this note".
  - Fields as label/value rows: Where (property and unit), What (the user's description, editable), Photos (thumbnail count), Urgency if set.
  - Buttons: **Send request** (primary), **Edit**, **Cancel**. Button text states the exact action; the confirmed state says "Request sent", matching the button.
  - **Edit** turns the What field into a textarea; saving voids the old card and shows a new slip (Architecture.md §7c). The old slip collapses to "Replaced".
  - Expiry: a line "Expires in 9 min", updated every minute (not announced every minute; announced once at 1 minute left).
  - States: `pending`, `sending` (buttons disabled, spinner), `confirmed` (green check, reference number once PropertyDek returns it), `expired` ("This request expired. Ask me again to start a new one."), `cancelled`, `replaced`, `failed` (error row with a **Try again** button that reuses the same `Idempotency-Key`).
  - Double-tap safe: the Send button disables on first activation.
</component>

<component id="handoff-banner">
  Pinned under the header while `status` is not `ai`.
  - `waiting`: warn colours. "A staff member will reply here. Usual wait: {time}." The user can keep typing; messages are stored and shown to staff.
  - After timeout: "Nobody is available right now." with a **Open the request form** link button and the expected response time.
  - `staff`: staff colours, "{First name} from {building} is helping you."
  - Emergency: `role="alert"`, danger accent bar, text is the fixed safety wording owned by FBC (Memory.md Q9). Includes the emergency number as a tel: link. Never dismissible while the thread is in emergency state.
</component>

<component id="composer">
  Multi-line textarea (grows to 5 lines), Send button, and an attach-photo button only when the org has triage enabled. Min height 48 px. Enter sends on desktop, inserts a newline on touch devices (Send button always works). Character limit shown only within 100 of the limit. Disabled while `sending`; stays enabled while the assistant streams so the user can type the next message.
</component>

<component id="typing">
  Three dots, shown only between send and first token. Replaced by streamed text. Under `prefers-reduced-motion` the dots do not animate; the text "Assistant is typing" is shown instead.
</component>

<component id="error-row">
  Inline under the failed message. Says what happened and what to do, no apology, no provider text, no codes shown to the user:
  - Rate limited: "You're sending messages quickly. Try again in {n} seconds."
  - Provider unavailable: "The assistant isn't available right now. You can use the request form or ask for staff." with two buttons.
  - Connection lost: "Connection lost. Reconnecting…" then resumes with `after_seq`. After 30 s: **Try again**.
  - Stream broke mid-answer: "This answer was cut off." with **Try again**. The partial text stays visible and labelled; it is never spliced with a new answer (Architecture.md §7f).
</component>

<component id="empty-state">
  First open, no history. One sentence of what it can do and three starter buttons, all real actions: "Check my request status", "Report a problem", "Ask about building rules". Starter labels come from enabled tools in `org_settings`; a disabled tool's starter is not shown. Plus a persistent "Talk to a person" button.
</component>

<component id="degraded-notice">
  Shown when the response carries `degraded=true`: "I can only answer common questions right now. For anything else, use the request form or ask for staff." Warn colours. Not shown for `degraded_retrieval`, which the user cannot act on.
</component>

### 6.2 States every client must render (widget and mobile apps)

| # | State | Trigger | Required UI |
|---|---|---|---|
| 1 | Empty | no messages | empty-state |
| 2 | Sending | user message posted | message appears at once, muted until the server returns `message.start` |
| 3 | Waiting for first token | after send | typing |
| 4 | Using a tool | `tool.start` | status-line |
| 5 | Streaming | `token` | text grows in place; source chips appear on `source` |
| 6 | Answered with sources | `message.end` | chips under the answer |
| 7 | Answered without a source | `message.end`, no sources | answer plus the line "I couldn't find this in your building's documents." and **Ask staff** button |
| 8 | Confirm card pending | `confirm.card` | request-slip `pending` |
| 9 | Confirmed / expired / replaced / failed | confirm endpoint result | request-slip states |
| 10 | Handoff waiting | `handoff {state: waiting}` | handoff-banner `waiting` |
| 11 | Handoff timed out | timeout job event | banner with request form link |
| 12 | Staff active | `handoff {state: staff}` | banner `staff`; staff messages; AI silent |
| 13 | Handed back | `handoff {state: ai}` | system event, banner removed |
| 14 | Emergency | emergency rules hit | emergency banner and fixed reply |
| 15 | Degraded | `degraded=true` | degraded-notice |
| 16 | Rate limited | 429 | error-row with seconds |
| 17 | Provider unavailable | 503 | error-row with form and staff buttons |
| 18 | Offline / reconnecting | network loss | error-row, then resume |
| 19 | Closed | `status=closed` | system event, composer replaced by "Start a new chat" |

## 7. Motion

- Panel open/close: 180 ms, `cubic-bezier(0.2, 0, 0, 1)`, opacity and 8 px translate.
- Message appear: none for history; 120 ms opacity fade only for new messages.
- Request-slip state change: 150 ms background and border colour change; the check mark draws once over 200 ms.
- Typing dots: 1.2 s loop, only while waiting.
- No other motion. No entrance animations on load, no hover animations.
- `@media (prefers-reduced-motion: reduce)`: all of the above become instant, typing dots become text.

## 8. Accessibility

Targets WCAG 2.2 AA. Checked by axe in every component state and by manual screen-reader passes (Phases.md Phase 7).

- Message list: `role="log"`, `aria-live="polite"`, `aria-relevant="additions"`. Streaming text is announced when the message ends, not per token.
- Emergency banner and send failures: `role="alert"`.
- Request-slip: `role="group"` with an accessible name; on appearance, focus moves to its heading and the card is announced; Send request is reachable in two Tab presses.
- Every interactive target ≥ 44 × 44 px (stricter than WCAG 2.2's 24 px minimum, because of older phones and shaky hands).
- Visible focus ring: 2 px `--pdk-focus` with 2 px offset, never removed.
- Full keyboard path: open launcher, type, send, Tab to a source chip, Tab to the slip, confirm, ask for a person.
- Text resizes to 200% and reflows at 320 px width with no horizontal scroll (Phase 7 e2e at 320 and 1280).
- Colour is never the only signal: sender labels, icons and text accompany every colour.
- Icons always have a text label or an accessible name. Decorative icons are `aria-hidden`.
- Language: `lang` attribute follows the `lang` attribute of the element; all strings come from `i18n/`; no copy inside components.
- Contrast check script runs in CI against the token table and fails if a pair drops below the minimums in §2.

## 9. Iconography

Inline SVG, 24 px grid, drawn at 20 px inside buttons and 24 px alone, `currentColor`, 1.75 px stroke. Only the icons in use are included (about 10: chat, close, send, attach, person, check, warning, document, phone, refresh). No icon font, no icon library import, to keep the bundle under budget (starting target ≤ 60 KB gzipped, Phases.md Phase 7).

## 10. Embedding contract (implemented in Phase 7; still to agree with FBC, Memory.md K-007)

`<pdk-assistant>` public surface, kept small:

- Attributes: `api-base` (HTTPS URL; plain `http:` only for `localhost`/`127.0.0.1`), `channel` (`web`), `lang`, `open`, `data-theme` (`light`/`dark`).
- Property: `tokenProvider: () => Promise<string>`. The host supplies a fresh chat token; the widget keeps it in memory only and calls the provider again when the token is within 60 s of expiry, and once more after a 401. No `localStorage`/`sessionStorage` (Rules.md §2).
- Method: `signOut()` drops the token and the conversation from memory.
- Events (all `CustomEvent`, bubbling, composed): `pdk-open-source {document_id, title}`, `pdk-handoff {state}`, `pdk-error {code}`, `pdk-open-request-form {}` (added in Phase 7: the request form lives in the host, so the widget asks the host to open it instead of holding a URL). No message text in event details.
- Host theming: only the tokens marked host-overridable in §2, §3, §5. Shadow DOM keeps host CSS from leaking in.
