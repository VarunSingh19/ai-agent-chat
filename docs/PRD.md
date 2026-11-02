# PRD.md — PropertyDek AI Assistant

## Project Name
PropertyDek Assistant (service name `pdagent`)

## 1. Problem Statement
PropertyDek tenants and staff reach the platform through screens, predefined prompts and person-to-person chat (in-app and SMS). Staff answer the same questions about house rules, request status and balances all day, and every maintenance request is read and triaged by hand. No conversational assistant exists in the product today (public sources show none; FBC to confirm).

Build an assistant that answers from each building's own documents, reads and creates PropertyDek data under the user's own permissions, and hands the conversation to staff when it cannot help.

## 2. Target Users
<user_persona id="P1">
  ROLE: Tenant
  WHO: Residents of affordable multifamily buildings. Mobile app and SMS. Many are on older phones and metered data.
  GOALS: Know the rules, see request status, report a problem fast, check their balance, reach a person.
  PAIN POINTS TODAY: Waiting for staff replies, unclear request status, predefined prompts that do not answer the question.
</user_persona>

<user_persona id="P2">
  ROLE: Property staff (manager, maintenance coordinator)
  WHO: Staff assigned to one or more properties. Management app and web.
  GOALS: Spend less time on repeat questions, triage requests quickly, take over a conversation without losing context.
  PAIN POINTS TODAY: Every request is read and categorised by hand; no summary of a long thread.
</user_persona>

<user_persona id="P3">
  ROLE: Organization admin / owner
  WHO: Person responsible for one customer organization's portfolio.
  GOALS: Control what the assistant knows and may do, see that it is safe and cost-bounded.
  PAIN POINTS TODAY: No control over automation, no visibility of spend.
</user_persona>

<user_persona id="P4">
  ROLE: FBC engineer (operator)
  WHO: The engineers who run the service.
  GOALS: See cost, errors, eval results and tool-call history without seeing tenant personal data.
  PAIN POINTS TODAY: n/a (new system).
</user_persona>

## 3. Role-Based Access Model
| Capability | Tenant | Staff | Org admin | FBC engineer |
|---|---|---|---|---|
| Ask about documents of own property | ✅ | ✅ (assigned properties) | ✅ | ✅ (support view, redacted) |
| See status of own requests | ✅ | ❌ | ❌ | ❌ |
| See requests in assigned properties | ❌ | ✅ | ✅ (all in org) | ❌ |
| Create a maintenance request (after confirmation) | ✅ own unit | ✅ | ✅ | ❌ |
| See own balance and recent payments | ✅ | ❌ | ❌ | ❌ |
| See device status | ✅ own unit | ✅ assigned properties | ✅ | ❌ |
| Unlock gate, refund, waive fee, change lease, take payment | ❌ | ❌ | ❌ | ❌ (not exposed to the agent at all) |
| Take over / release a conversation | ❌ | ✅ | ✅ | ❌ |
| Upload and delete documents | ❌ | ❌ | ✅ | ❌ |
| Change agent settings and budgets | ❌ | ❌ | ✅ | ❌ |
| Read another organization's data | ❌ | ❌ | ❌ | ❌ |
| Read transcripts | own only | assigned properties | whole org | redacted logs only |

Roles and property IDs come from the verified token (Architecture.md §6), never from the model or the client body.

## 4. Core Feature Set
<feature id="F1" name="Chat core">
  - One conversation API for the tenant app, management app, web widget and SMS.
  - Streamed answers (SSE). Thread stored per user; reconnect resumes from a message sequence number.
  - Rolling summary for long threads. Per-user and per-org rate limits.
  - Edge case: a user opens two devices at once; messages stay ordered by `seq`.
</feature>

<feature id="F2" name="Document Q&A (RAG)">
  - Admin uploads PDF/DOCX or pastes FAQ text. Each document is tagged org, property (or org-wide), type, version.
  - Hybrid retrieval (vector + full-text), filtered by org and property in SQL before ranking.
  - Answers name their source document. No source and no tool result → say so and offer staff.
  - Edge case: a document is replaced; old chunks must be gone before the new version answers.
</feature>

<feature id="F3" name="Read tools through MCP">
  - Tools: `list_my_requests`, `get_request`, `get_balance`, `list_announcements`, `get_device_status`, `search_knowledge`.
  - Each tool calls the PropertyDek API with the caller's own token.
  - Edge case: PropertyDek returns 403/404 — the agent says it cannot see that, never guesses.
</feature>

<feature id="F4" name="Write tools with confirmation">
  - Tools: `create_request`, `add_request_note`. The agent proposes; the user taps Confirm on a card; only then the call runs.
  - Confirmation is bound to the exact arguments (hash) and expires in 10 minutes.
  - Edge case: user edits the text after the card was shown — old confirmation is void.
</feature>

<feature id="F5" name="Emergency path">
  - Keyword rules run before any model call (gas, flood, fire, no heat in winter, locked in, etc., list owned by FBC).
  - A hit alerts staff immediately and starts a handoff. It does not wait on a model.
  - Edge case: LLM providers are down — emergency path still works.
</feature>

<feature id="F6" name="Human takeover">
  - Triggers: user asks for a person, two unhelpful answers, emergency, legal/dispute/payment-dispute topic, empty retrieval with no tool answer.
  - Staff see a queue, read the AI summary, take the thread; the AI stops replying until hand-back.
  - If nobody answers within the org's timeout, the user gets the request form and expected wait.
</feature>

<feature id="F7" name="Conversation management (staff inbox API)">
  - List/filter by status, property, channel; search; link to tenant, unit, work order; full transcript.
  - Edge case: a staff member opens a thread another staff member just took — second take returns 409.
</feature>

<feature id="F8" name="SMS channel">
  - Inbound webhook maps phone number to tenant and active lease; unknown numbers get a limited mode and no personal data.
  - STOP/START handling, delivery status, no sensitive data in plain SMS.
</feature>

<feature id="F9" name="Maintenance triage from photos">
  - Tenant text and photos → category, urgency, missing-information questions (max 2), draft work order.
  - Draft goes to staff for approval. Nothing is created in PropertyDek without staff approval.
</feature>

<feature id="F10" name="Staff assistant and per-org settings">
  - Staff questions: open urgent requests, device alerts, day summary. Staff tools are read-only except `create_task` (confirmed).
  - Org settings: tone, enabled tools, handoff timeout, daily token budget, retention days.
</feature>

## 5. Non-Functional Requirements
Targets are proposals; FBC confirms them in Phase 0.
- Latency: p95 time to first token ≤ 2.5 s for document questions, ≤ 4 s for tool turns.
- Availability: 99.5% monthly for chat. Emergency alert reaches staff in ≤ 5 s from message receipt.
- Isolation: zero cross-organization reads. Enforced in token check, application code and row-level security.
- Cost: ≤ $0.05 per resolved conversation at launch traffic; hard daily cap per org and overall (Architecture.md §7e).
- Data: personal data masked in logs; message retention default 90 days, configurable per org; documents kept until deleted.
- Auditability: every tool call, confirmation, handoff and staff action is stored with user, time, arguments hash and outcome.
- Security baseline: OWASP LLM Top 10 (2026 edition: Excessive Agency is #3, Unbounded Consumption #6) mapped in Rules.md §5.
- Browser support for the widget: evergreen browsers; works down to 320 px width.

## 6. Out of Scope (explicitly)
- Visual flow builder.
- Agent-controlled gate unlock, refunds, fee waivers, lease changes, payments, notices.
- Voice.
- Predictive maintenance models.
- Lead capture and tour booking for prospects.
- Multi-agent orchestration, separate vector database, reranker, semantic answer cache.
- Code-execution tool calling in tenant-facing flows (a measured spike is allowed in Phase 10 for staff tools only).
- Answers about tenant screening or eligibility decisions (route to staff).

## 7. Success Metrics
- Share of conversations resolved without handoff (baseline in week 1 of pilot; target set then).
- Staff time to first response on handoffs; time to triage a request.
- Eval suite: 100% on isolation and injection cases; tool-choice accuracy and recall@5 targets set in Phase 3/4.
- Cost per resolved conversation vs the $0.05 target.
- Zero cross-tenant incidents; zero unconfirmed writes.
