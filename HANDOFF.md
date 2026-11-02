# Handoff: pdagent, 2 November 2026

For the next engineer or Claude Code session picking this up. Read this first, then `docs/Memory.md` (CLAUDE.md read order). Memory.md has the full decision log (D-024 to D-027) and known issues (K-008 to K-012) referenced below.

## 1. Where things stand

- **Phase 7 (Web Widget):** rebuilt and **awaiting the engineer's approval**. It is not approved. The earlier "Completed" entry was a 138-line stub with no API client.
- **Phase 1 auth:** fixed with the engineer's approval (D-024). Tokens are now verified against `PDAGENT_JWKS_URL`.
- **Not production-grade yet.** Four simulations remain in production code paths (section 4), so earlier "Phases 0–11 complete / 50/50 evals APPROVED" claims in Memory.md do not hold for the real system.
- **Open proposal, not started:** a separate PropertyDek sandbox service (section 5). The engineer has not decided yet.
- **The engineer's standing instruction:** do nothing without telling them first. Propose, wait for a yes, then act.

## 2. What changed this session

### Repo root clean-up
- Removed the Google AI Studio leftovers: `.aistudio/`, `public/`, `index.html`, `metadata.json`, root `package.json`, `tsconfig.json`, `vite.config.ts`, `README.md`, root `.nvmrc`, and `src/{App.tsx,main.tsx,index.css,data/,utils/}`.
- They were moved, not deleted, to the session scratchpad: `C:\Users\Dell\AppData\Local\Temp\claude\c--Users-Dell-Desktop-test-chat-ai-agent-chat\d580d80a-4311-4575-8262-ef417e59536f\scratchpad\removed-aistudio`. This is a temp folder; copy anything you want to keep.
- `pyproject.toml`: `readme = "docs/PRD.md"` (was `PRD.md`, which made `uv sync` fail).

### Backend
- `src/pdagent/auth/token.py`: new `JwksKeySource` (PyJWKClient, cached; refetch on an unknown `kid` at most every 30 s; fetch runs off the event loop) and `build_token_verifier(settings)`.
  - The in-process test key is used only when `PDAGENT_ENVIRONMENT=test`.
  - Startup fails if `PDAGENT_JWKS_URL` is blank, or is not `https://` outside `development`.
- `src/pdagent/main.py`: uses `build_token_verifier`.
- `tests/unit/test_jwks_verifier.py`: 5 new tests.
- `.github/workflows/ci.yml`: `PDAGENT_ENVIRONMENT: test` in the backend job env, plus a new `widget` job (npm ci, audit, `npm run check`, Playwright with Chromium).

### Widget (`widget/`), Phase 7
- Lit 3.3.3 `<pdk-assistant>` built to Design.md and Architecture.md §4. File list is in Memory.md's File Manifest.
- Covers: SSE client with resume, request slip (confirm/edit/cancel/expiry), handoff banner with 5 s polling while `waiting`/`staff`, source chips, error/empty/degraded/closed states, dark theme, in-memory token only.
- `widget/dev/dev-issuer.ts`: local-only JWKS and token issuer inside the Vite dev server (`/dev/jwks.json`, `/dev/token`). Its key and dev identity live in the git-ignored `widget/.dev/`.
- Pinned dependencies, all at least 14 days old: lit 3.3.3, typescript 7.0.2, vite 8.3.4, vitest 5.0.5, @playwright/test 1.64.1, axe-core 4.14.0. `npm audit`: 0 vulnerabilities.
- Built and tested on **Node 24.21.0**. Node 26 is not installed on this machine; the engineer chose to continue on 24 (D-025). CI uses Node 26.

### Docs
- `docs/Architecture.md`: §4 widget tree (new files) and §6.9 (local development tokens).
- `docs/Design.md`: §10 embedding contract, now implemented. Adds the `pdk-open-request-form` event, `signOut()`, and `data-theme`.
- `docs/Memory.md`: Current Status, Phase log row 7, D-024 to D-027, K-008 to K-012, File Manifest, Session Log.

### Local environment
- `.env`: only three lines changed. A backup of the original is at `...\scratchpad\env.backup` (same scratchpad folder as above).
  ```
  PDAGENT_ENVIRONMENT=development
  PDAGENT_JWKS_URL=http://127.0.0.1:5173/dev/jwks.json
  PDAGENT_TOKEN_ISSUER=http://127.0.0.1:5173/dev
  ```
  Database, Redis and API key lines are untouched. Only `PDAGENT_GEMINI_API_KEY` is set; the Anthropic and OpenAI keys are empty.
- **Docker:** the original `pdagent-db-1`/`pdagent-redis-1` containers (from the sibling `../pdagent` compose) were removed outside the session. The stack now runs from this repo's `docker-compose.yml` as `chat-db-1` (pgvector 0.8.1-pg18) and `chat-redis-1` (valkey 8.0). There is **no named volume**, so `docker compose down` loses the data.
- **Database roles:** login roles `app` (no superuser, no BYPASSRLS, member of `pdagent_app`) and `migrator` (database owner, CREATEROLE) were created by hand with the passwords from `.env`. The script is `...\scratchpad\local_db_roles.py`. It's in the temp folder; move it into the repo or replace it with a proper Phase 1 setup step (K-012).
- Migrations are applied to head (`0002_phase1_to_9_schema`). A `pdagent_test` database also exists.

## 3. Verification status (real results)

| Check | Result |
|---|---|
| `ruff check` (changed files) | All checks passed |
| `ruff check .` (whole repo) | 3 errors, all pre-existing E402 in `tests/conftest.py` |
| `mypy src` | Success: no issues found in 91 source files |
| `pytest tests/unit` | 17 passed |
| DB-backed pytest suites (15 tests) | **Cannot run on this machine.** testcontainers' Postgres connection times out (pre-existing, K-010) |
| Widget `tsc --noEmit` (strict) | Clean |
| Widget vitest | 31 passed |
| `check:spacing`, `check:contrast` | OK (all pairs pass in light and dark) |
| Bundle | 22.3 KB gzipped (budget 60 KB) |
| Playwright + axe (Edge, 320 px and 1280 px) | 60 passed, but **one run showed a flaky axe failure** (see below) |
| Live end-to-end | Dev token → `POST /v1/conversations` 201 → streamed SSE answer; forged token → 401 |

**Unverified last change.** The flaky failure was real: the "sending" user bubble used `opacity: 0.7`, which dropped contrast to 3.45:1 in dark mode. Two fixes are in place but unverified:
- `widget/src/styles/base.css.ts`: the sending state now uses the surface colour with a dashed accent border, no opacity.
- `widget/tests/a11y/axe.spec.ts`: waits for finite animations to finish before running axe (100 ms polling, 5 s timeout).

The final `--repeat-each=3` run exited with code 4 and no output, so these fixes are **not yet confirmed**. Run this first:
```bash
cd widget && npx tsc --noEmit && npm run check && npx playwright test --repeat-each=3
```

The API and Vite dev servers are **not running**; they stopped when the session ended.

## 4. Simulations still in production code (blocks "production-grade")

| # | Where | What it does now | Fix | Phase |
|---|---|---|---|---|
| 1 | `main.py` `build_default_provider_gateway` | A missing Anthropic or OpenAI key is replaced by `FakeLLMProvider` labelled "anthropic", first in the chain, so answers are canned and Gemini is never reached (K-008) | Outside `test`, register only providers with keys; fail startup if none | 2 |
| 2 | `knowledge/ingest/embed.py` `EmbeddingClient` | Hashes words into vectors; never calls an embedding API | Call OpenAI `text-embedding-3-small` (Architecture.md §1); keep the hash version for tests only | 3 |
| 3 | `mcp_server/pdapi_client.py` + `auth/exchange.py` | PropertyDek data is an in-memory dict that empties on restart; token exchange is signed and verified with the in-process test key | Real HTTP client to `PDAGENT_PDAPI_BASE_URL`; real RFC 8693 exchange call | 4 |
| 4 | `evals/runner.py:83` | The reply being graded is the canned string `"Verified response with no leaked tenant IDs."` | Grade real gateway output | 11 |

All four are outside Phase 7. Rules.md §1.12 requires the engineer's OK before touching them.

## 5. Proposed, not decided: PropertyDek sandbox

The engineer asked for a backend that holds seeded data and acts as the PropertyDek API, which would also supply a real token issuer and JWKS. The recommendation given:

- **Shape:** a separate small FastAPI service (`sandbox/propertydek/` or its own repo) with its own database (`propertydek_sandbox`) and seeded **synthetic** data: 2 orgs, properties, units, about 10 tenants, staff, and work orders in various states.
- **Endpoints:** `/.well-known/jwks.json`, a sandbox login that issues chat tokens, a token-exchange endpoint, and only the data endpoints the agent's tools call.
- **pdagent side:** gets a real HTTP client and exchange call (fixes item 3). `.env` points JWKS, issuer and API URLs at the sandbox. The Vite dev issuer is then removed so there is one issuer.
- **Guardrails:**
  - Contract first: write the assumed API and token contract and send it to FBC (Q1), or build from FBC's spec if one exists.
  - Never deployed to production; pdagent refuses the sandbox issuer when `environment=production`.
- **Size and process:** about 1–2 days. This is a new item outside Phases.md, so add it to Architecture.md first and get approval.

Decisions the engineer still owes:
1. Contract source: FBC's spec, or write an assumed one.
2. Location: this repo or a separate one.
3. Go-ahead to write the Architecture.md addition and the contract for review.

## 6. Waiting on the engineer

- An **OpenAI API key** for embeddings, or a documented decision to use Gemini embeddings instead.
- **LLM keys:** add an Anthropic key (the designed primary), or decide on Gemini-only for now. Rules.md requires evals to pass before a model serves a route, and the evals are currently fake (item 4).
- **Real building documents** (PDF, DOCX or text) to seed the knowledge base. They are customer data, so they must stay out of git.
- **Approval** to fix the section 4 items, and the section 5 decisions.
- **Phase 7:** review, plus the manual screen-reader pass with NVDA or VoiceOver that Phases.md requires (K-011).
- **FBC questions:** Q1 (PropertyDek token exchange and sandbox access) and K-007 (embedding contract) are still open.

## 7. How to run locally

```bash
# Backing services (this repo's compose)
docker compose up -d db redis

# Backend (reads .env; development mode, /docs enabled)
uv sync
uv run alembic upgrade head
uv run uvicorn pdagent.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir src

# Widget dev harness (proxies /v1 to :8000 and serves the dev JWKS and tokens)
cd widget && npm install && npx vite
# open http://127.0.0.1:5173
```

Start Vite before the first API call. The API fetches the JWKS from it on first token verification.

If the database container is recreated, run in this order:
1. The roles script.
2. `uv run alembic upgrade head`.
3. `docker exec chat-db-1 psql -U postgres -d pdagent -c "GRANT pdagent_app TO app;"`

## 8. Other things to know

- **This folder is untracked in git.** The git root is `C:\Users\Dell\Desktop\test`, and its status shows a large set of deleted files from an older Java/Spring project. Nothing from this session has been committed. Commit only when the engineer asks.
- **Widget gaps where the API exposes nothing yet (K-009):**
  - Starters are not filtered by enabled tools.
  - No photo attach button.
  - No staff first name or building name in the banner.
  - The slip shows only the summary.
  - Edit is cancel plus a new message.

  Propose additions to Architecture.md §8 before changing the API.
- **No push channel for tenants:** staff replies reach the widget by polling (D-027).
