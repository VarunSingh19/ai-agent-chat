# Phases.md — Build Roadmap

Rules of the road: nothing from a later phase is built early; nothing in an earlier phase is left half-done "to come back to". Every phase ends in a working, tested slice, a green CI run, and an updated Memory.md. One engineer, ~64 working days (~13 weeks) in total — an estimate, revised after Phase 0. (The build plan already sent to FBC says Node and TypeScript, BullMQ and 10 weeks for a smaller scope; this pack builds Python. Reconcile before kickoff — Memory.md Q10 and K-001.)

Each phase maps to the folders it creates in Architecture.md §3–4.

## Phase 0 — Scaffolding & Discovery (4 days)
**Goal:** a repository that builds, tests and deploys an empty service, and every VERIFY item in Architecture.md answered.
- Repo from SETUP.md: uv project, Docker, docker-compose (Postgres 18 + pgvector, Redis), CI (lint, types, tests, migration check, advisory check), pre-commit.
- `core/` (settings, db, errors, logging with masking filter, telemetry configured explicitly), `main.py`, `/healthz`, `/readyz`, Alembic baseline, test fixtures with a Postgres testcontainer.
- Run every VERIFY item: Redis engine in FBC's AWS, small fallback model, `httpx2` TestClient setup, Procrastinate extras and version, minimum cacheable prompt length per model, MCP authorization wording on token passthrough (Architecture.md §6.6), CI advisory tool. Record answers in Memory.md Decisions.
- Eval set v0: 50 redacted conversations from FBC (or synthetic if not yet delivered) in `tests/evals/cases/`.
- Send FBC the open questions (Memory.md Q1–Q11); confirm the PRD §5 targets.
**Exit criteria:** `docker compose up` then `curl /readyz` returns 200 with DB and Redis checked; CI green on an empty PR; a migration applies and rolls back; a deliberately failing lint, type, test and migration each fail CI; every VERIFY line is resolved or has an owner in Memory.md.

## Phase 1 — Identity, Tenancy, Audit, Limits (5 days) — `auth/`, `limits/`, `audit/`, `core/rls.py`
**Goal:** nothing can be read or spent without a verified principal, and tenant isolation is provable.
- JWKS verification, `Principal`, revocation list, dependency that sets `app.org_id` per transaction; DB roles (owner, migrator, app) with RLS; token minting helper for tests.
- Redis rate limiter, spend guard skeleton with reservations, `org_settings` table and defaults, `audit_log` (append-only grants).
- The two-org isolation fixture and the generator that creates an isolation test per route from the OpenAPI schema.
- Decide the FBC engineer access path (Memory.md K-002): a separate operator identity for dashboards, or a new token role. Record it as a decision.
**Exit criteria:** a token for org A cannot read, list, guess an id of, or write to anything of org B through any route (tested, 404s); a forged, expired, wrong-audience and revoked token each return 401; the app DB role cannot `UPDATE` or `DELETE` `audit_log`; 100 parallel spend reservations never exceed a small cap in a test; adding a route without an isolation test fails CI.

## Phase 2 — Chat Core & Provider Layer (6 days) — `conversations/`, `agent/`
**Goal:** a streamed, persisted, resumable conversation with a model, with cost recorded on every turn.
- `conversations` and `messages` with `seq`, SSE streaming through FastAPI's SSE support, reconnect with `after_seq`, idempotency keys, two-device ordering test.
- Canonical types, `LLMProvider`, Anthropic adapter, OpenAI adapter, fake provider; breaker, retry, failover rules from Architecture.md §7f; prompt assembly in cache-stable order; `config/models.yaml` with dated prices; usage and cost per message; rolling summary job.
- Verify caching actually works: log `cache_read_tokens` and assert in an integration test (real call, run manually and gated) that the second turn reads from cache for each model in use; record the minimum-length result for Haiku.
**Exit criteria:** a conversation survives a disconnect and resumes without loss or duplicates; killing the primary provider mid-test fails over before the first token and does not splice after it; every assistant message has tokens, cost and latency; a prompt change that breaks a golden case fails the eval job; no per-request value appears before the cache breakpoint (test inspects the built prompt).

## Phase 3 — Knowledge Base (RAG) (7 days) — `knowledge/`
**Goal:** document Q&A that is filtered by org and property and names its sources.
- Upload API, S3 storage, Procrastinate ingestion (extract, chunk by headings, embed, store), replace/delete lifecycle, hybrid retrieval with RRF, "no source ⇒ say so and offer staff" rule, source events in the stream.
- Labelled retrieval set (≥ 50 questions); chunk-size experiment (256 / 512 / 1024) and top-k experiment; **set the recall@5 floor** and record it in Memory.md.
- Degraded mode when embeddings are down (full-text only).
**Exit criteria:** recall@5 meets the floor on the labelled set; a replaced document's old chunks never appear in an answer; a tenant at property X never sees property Y's documents or another org's; embedding outage test returns full-text results with the degraded flag; ingestion is idempotent (re-running a job creates no duplicates); a 50-page PDF ingests within the agreed time.

## Phase 4 — Read Tools through MCP (5 days) — `mcp_server/`, `tools/`
**Goal:** the agent answers about requests, balances, announcements and devices using the user's own permissions.
- One-hour spike: in-process versus loopback transport for the SDK `Client`; record the decision.
- `MCPServer` (stateless Streamable HTTP, spec 2026-07-28) with `list_my_requests`, `get_request`, `get_balance`, `list_announcements`, `get_device_status`, `search_knowledge`; PropertyDek API client with the token exchange from Architecture.md §6.6; per-role tool registry; `not_visible` handling.
- Tool-choice eval cases; **set the tool-choice accuracy floor**.
- Prerequisite: Memory.md Q1 (token exchange) answered by FBC. If not, build against a recorded fake PropertyDek API and mark the phase "conditionally done".
**Exit criteria:** tool-choice accuracy meets the floor; a tenant cannot obtain another tenant's request through any prompt (injection cases pass 100%); a 403/404 from PropertyDek yields "I can't see that" and no invented data; tool arguments never contain identity fields (schema test); the MCP server serves both a 2026-07-28 client and a 2025-11-25 client in a contract test.

## Phase 5 — Write Tools with Confirmation (4 days) — `tools/confirm.py`
**Goal:** `create_request` and `add_request_note` work only after an explicit, argument-bound confirmation.
- `confirmations` lifecycle, card payloads, confirm/cancel endpoints, void-on-edit, expiry job, audit rows, idempotent execution.
**Exit criteria:** tampered arguments, replayed confirmation, expired confirmation, other user's confirmation and double-tap each fail with the right code and create nothing in PropertyDek; exactly one work order exists after a successful confirm even if the request is retried; zero code path executes a write without a confirmed row (a test greps the registry and the loop).

## Phase 6 — Emergency Path, Human Takeover, Staff Inbox API (8 days) — `handoff/`, `inbox/`
**Goal:** a person can always be reached, and emergencies bypass the model.
- Emergency rules loader and matcher (`config/emergency_rules.yaml`, owned by FBC), staff alert fan-out (push + inbox + pub/sub), canned safety reply.
- Handoff triggers (user request, two unhelpful, emergency, legal/dispute topics, no answer), state machine, takeover with 409, release, timeout job with request form, AI silent while `status='staff'`, summary for staff.
- Staff inbox API (list/filter/search, transcript, link to tenant/unit/work order), WebSocket stream, staff reply to web/app/SMS channels.
**Exit criteria:** with both providers faked as down, an emergency phrase produces a staff alert in ≤ 5 s and the safety reply; two staff members taking the same thread yield exactly one winner and one 409; the AI never replies while a thread is `staff`; timeout produces the request form exactly once; staff cannot read threads outside their properties; transcripts are unreachable for anyone except tenant (own), staff (assigned properties) and org_admin (own org); the FBC engineer access path is settled per Memory.md K-002.

## Phase 7 — Web Widget (5 days) — `/widget`
**Goal:** the embeddable `<pdk-assistant>` component implementing Design.md against the live API.
- Custom element, tokens, components, SSE client with resume, confirm card, handoff banner, source chips, error and empty states, host theming through CSS custom properties, in-memory token handling.
- Axe checks, keyboard path, 320 px and 1280 px Playwright runs, bundle size budget (set in Phase 0 CI; starting target ≤ 60 KB gzipped).
**Exit criteria:** axe reports no serious or critical issues in all component states; a full conversation (question, source, tool answer, confirm card, handoff) works by keyboard alone and with a screen reader's live-region output verified manually and recorded; an XSS payload in a model answer renders as text; the bundle is within budget.

## Phase 8 — SMS Channel (4 days) — `channels/sms/`
**Goal:** the same assistant over SMS with compliance behaviour.
- Provider adapter (provider chosen per Memory.md Q3), signed webhook verification, replay protection, phone-to-tenant resolution, limited anonymous mode, STOP/START, delivery status, SMS-safe answer templates (no sensitive data), staff replies by SMS.
**Exit criteria:** STOP prevents every later outbound message until START; an unknown number never receives personal data and can reach only public FAQ and the request form; a replayed webhook creates no duplicate message; a tenant's SMS and app conversations stay separate but link to the same user.

## Phase 9 — Maintenance Triage from Photos (5 days) — `triage/`
**Goal:** text plus photos become a staff-approved draft work order.
- Upload with signed URLs, size/type limits, image tokens counted in cost, Sonnet route for triage, category and urgency output validated by schema, at most two follow-up questions, draft stored for staff approval (nothing created in PropertyDek without approval).
- Triage eval set (category, urgency, missing-information questions); set its floor.
**Exit criteria:** triage eval meets its floor; an emergency-looking photo description still goes through the emergency rules first; draft appears in the staff inbox with the photos; approval creates exactly one work order; image cost per triage is measured and written to Memory.md.

## Phase 10 — Staff Assistant, Org Settings, Optional Code-Mode Spike (5 days) — `settings_org/`, staff tool set
**Goal:** staff get day summaries and urgent lists; org admins control behaviour and budgets.
- Staff tools (`list_open_urgent`, device alerts, `summarize_day`, `create_task` with confirmation), settings API (tone, enabled tools, handoff timeout, daily budgets, retention days), usage endpoint.
- **Spike (time-boxed to 1 day, staff tools only):** measure the staff tool schema's token cost and a deferred-loading or code-execution variant. Adopt it only if it saves ≥ 30% of staff-turn cost with no drop on the staff eval cases; otherwise record the numbers and close the question.
**Exit criteria:** an org admin's budget change takes effect on the next turn; disabled tools disappear from the model's tool list; staff tools never appear for tenants; spike result recorded with numbers.

## Phase 11 — Hardening, Load Test, Rollout (6 days)
**Goal:** safe to run for real customers.
- Load test to 10× expected peak (and a looping-prompt abuse test); chaos tests (provider down, Redis down, DB failover); security pass against Rules.md §5 with the OWASP Agentic and MCP lists; privacy review (masking, retention, deletion); restore test; runbooks; dashboards and alerts live; per-org flag and rollback rehearsed.
- Rollout: staff-only shadow (AI drafts, staff see it) ▸ one building ▸ all, behind the per-org flag. Final Memory.md update with the post-launch backlog taken from PRD §6 and Architecture.md §10.
**Exit criteria:** p95 time-to-first-token and availability targets from PRD §5 met in the load test; no cross-tenant read in any test; cost per resolved conversation measured on pilot traffic and compared with the $0.05 target; every runbook exercised once; FBC signs off the pilot.
