# Draft Message to FBC — Open Questions (Q1–Q11) & PRD §5 Target Confirmation

> **Status:** Drafted in Phase 0 for review. Not sent.

**Subject:** PropertyDek Assistant (`pdagent`) — Phase 0 Discovery Questions, Architecture Alignment & NFR Targets

Hi team,

We have completed Phase 0 scaffolding for `pdagent` (PropertyDek AI Assistant) and locked our baseline architecture, security controls, and evaluation harness. Before we proceed into Phase 1 (Identity & Tenancy) and Phase 4 (PropertyDek API integrations), could you confirm the items below?

---

### 1. Stack & Timeline Alignment (Q10 / K-001)
- **Q10 (Stack & Scope):** We have standardized the `pdagent` service on **Python 3.14 + FastAPI 0.162**, **PostgreSQL 18 + pgvector 0.8.1** (with Row-Level Security on every tenant table), and **Procrastinate** (PostgreSQL-backed transactional job queue) so we can use the first-party Anthropic, OpenAI, MCP v2, and pgvector SDKs directly. With the full production scope (including the deterministic emergency bypass path, SMS compliance, photo maintenance triage, spend guard reservations, and 100+ case eval suite), the roadmap is estimated at **~64 working days (~13 weeks)** across 12 sequential phases (vs. the 10-week Node/BullMQ estimate on the earlier smaller scope). Please confirm you are aligned with this stack and schedule.

---

### 2. Authentication & PropertyDek API Integration (Q1 — Blocks Phase 4)
- **Q1 (Per-User Token Exchange):** Every tool call (`list_my_requests`, `get_request`, `get_balance`, `create_request`, etc.) must execute under the signed-in user's own PropertyDek permissions, and MCP 2026-07-28 security rules forbid forwarding the `aud=pdagent` chat token directly to upstream APIs.
  - **Preferred:** Can PropertyDek provide an RFC 8693-style token exchange endpoint that swaps a valid `aud=pdagent` chat token for a short-lived token with `aud=propertydek-api`, identical `sub`, and `act=pdagent`?
  - **Fallback:** Alternatively, can PropertyDek issue both short-lived tokens together when the user starts a session?

---

### 3. Product, Channels & Operations (Q2–Q9, Q11)
- **Q2 (Mobile App Architecture):** Are the PropertyDek tenant and management mobile apps native (iOS/Android) or hybrid? (They will call the `/v1/conversations` SSE API directly and render the 19 required conversation states.)
- **Q3 (SMS Provider — Blocks Phase 8):** Which outbound/inbound SMS provider (e.g., Twilio, AWS End User Messaging / Pinpoint, Telnyx) is currently in use so we can build the signed webhook verifier and adapter?
- **Q4 (LLM Providers & Data Governance):** Our architecture uses **Anthropic** (`claude-haiku-5-5` and `claude-sonnet-5-5`) as primary and **OpenAI** (`/v1/responses`) as automatic failover, plus `text-embedding-3-small` for document chunks. Are both providers approved under your data processing agreements, and are there any restrictions on sending tenant message text or maintenance photos to them?
- **Q5 (Rollout Order):** Who is the target user for the initial pilot after our staff-shadow phase: tenants, property staff, or both simultaneously?
- **Q6 (Knowledge Base Source Formats):** Where do building house rules, lease templates, and FAQs live today, and in what file formats? *(Note: embedded-text PDFs, DOCX, and pasted FAQ text are supported in v1; scanned image-only PDFs requiring OCR are out of scope.)*
- **Q7 (AWS & CI Infrastructure):** Please confirm your target AWS account setup for ECS Fargate, RDS PostgreSQL 18 (`pgvector 0.8.1`), S3, and ElastiCache (specifically whether we should target **ElastiCache for Valkey 8.0** or **Redis OSS 7.1**), as well as whether GitHub Actions is your standard CI runner.
- **Q8 (Unrecognized SMS Numbers):** When an inbound SMS arrives from a phone number that does not match an active tenant lease, our design places the thread in a restricted `anonymous` role that can access only public org-wide FAQ documents and the maintenance request form link—never personal data. Please confirm this behaviour.
- **Q9 (Emergency Keyword List & Canned Safety Reply — Needed before Phase 6 Exit):** Who on the FBC side will own and sign off on `config/emergency_rules.yaml` (gas leak, flood, fire, no heat in winter, locked in, carbon monoxide) and the exact fixed safety reply wording ("If this is an emergency call 911…")?
- **Q11 (Web Widget Brand Tokens — Needed before Phase 7):** Could you share PropertyDek's brand tokens (`--pdk-accent`, `--pdk-on-accent`, `--pdk-font`, corner radius multiplier) for the `<pdk-assistant>` web component, or confirm we should launch with the WCAG 2.2 AA neutral teal default (`#0A5A66`)?

---

### 4. Confirmation of Non-Functional Targets (PRD §5)
Please also confirm these proposed launch targets:
1. **Latency:** p95 time-to-first-token (TTFT) ≤ **2.5 s** for document Q&A, ≤ **4.0 s** for tool turns.
2. **Availability & Emergency SLA:** **99.5%** monthly chat availability; emergency keyword hit alerts staff in ≤ **5.0 s** even if both LLM providers and Redis are unreachable.
3. **Unit Cost:** ≤ **$0.05** per resolved conversation (achieved via Haiku-first routing + prompt caching, enforced by per-user, per-org, and global daily spend reservations).
4. **Retention:** Default **90 days** for conversation messages (configurable per org); audit logs append-only.

Best regards,
Varun
