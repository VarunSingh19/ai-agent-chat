# SETUP.md — Scaffold `pdagent`

Run once, in Phase 0. Versions come from Architecture.md §1 (researched 1 Nov 2026). This file was written without network access to the package registries, so every line marked **VERIFY** (a tag, an extra or a flag) must be checked in Phase 0 and the result recorded in Memory.md. Do not paste a VERIFY line blindly.

Prerequisites on your machine: Git, Docker with Compose, `uv`, Node.js 26 (via nvm or fnm). No cloud login is needed in Phase 0. Cloud CLI auth (AWS) comes later and is interactive.

## 1. Repo and Python project

```bash
mkdir pdagent && cd pdagent
git init -b main
uv init --package --name pdagent --python 3.14 .     # VERIFY flags with `uv init --help`
echo "3.14" > .python-version
```

Dependencies (runtime). Pins follow Rules.md §2:

```bash
uv add "fastapi[standard]~=0.162.0"                  # VERIFY: which extra gives `fastapi run` and httpx2
uv add pydantic pydantic-settings "pyjwt[crypto]"
uv add "sqlalchemy>=2.1,<2.2" "psycopg[binary,pool]" alembic pgvector
uv add procrastinate                                  # VERIFY: version 3.x and the psycopg 3 extra
uv add redis
uv add "mcp>=2,<3"
uv add "anthropic>=1,<2" "openai>=3,<4"
uv add pypdf python-docx pyyaml jinja2
uv add opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

Dev tools:

```bash
uv add --dev ruff mypy "pytest>=9,<9.2" pytest-asyncio pytest-cov "testcontainers[postgres]" types-PyYAML
```

Release-age rule (Rules.md §2): after `uv lock`, check that no resolved package was released in the last 14 days; if one was, pin the previous version or document the security advisory. VERIFY whether the installed `uv` supports an exclude-newer setting for this.

## 2. Folder structure (matches Architecture.md §3)

```bash
mkdir -p config/prompts migrations docs/runbooks \
  src/pdagent/{core,auth,limits,audit,conversations,agent/providers,knowledge/ingest,tools,mcp_server,handoff,inbox,channels/sms,channels/web,triage,settings_org,evals/cases,workers} \
  tests/{unit,integration,isolation,injection,emergency,evals}

touch src/pdagent/main.py
touch src/pdagent/core/{settings,db,rls,errors,logging,telemetry,ids}.py
touch src/pdagent/auth/{token,principal,deps,exchange}.py
touch src/pdagent/limits/{ratelimit,spend,breaker}.py
touch src/pdagent/audit/{service,models}.py
touch src/pdagent/conversations/{router,service,repo,schemas,stream,summary}.py
touch src/pdagent/agent/{loop,router,context,canonical}.py
touch src/pdagent/agent/providers/{base,anthropic,openai,fake}.py
touch src/pdagent/knowledge/{router,service,repo,retrieve}.py
touch src/pdagent/knowledge/ingest/{extract,chunk,embed,jobs}.py
touch src/pdagent/tools/{registry,schemas,confirm}.py
touch src/pdagent/mcp_server/{server,tools_read,tools_write,pdapi_client}.py
touch src/pdagent/handoff/{router,service,states,emergency,notify}.py
touch src/pdagent/inbox/{router,service,repo,ws}.py
touch src/pdagent/channels/sms/{webhook,adapter,parse}.py
touch src/pdagent/triage/{service,schemas,photos}.py
touch src/pdagent/settings_org/{router,service,repo}.py
touch src/pdagent/evals/{runner,graders,report}.py
touch src/pdagent/workers/{app,periodic}.py
touch config/{models.yaml,emergency_rules.yaml}
touch config/prompts/{system.md,triage.md,org_block.md.j2}
touch tests/conftest.py
# every package directory also needs __init__.py
find src/pdagent -type d -exec sh -c 'test -f "$1/__init__.py" || touch "$1/__init__.py"' _ {} \;
```

`src/pdagent/evals/cases/` holds YAML only (no `__init__.py` needed there; remove the one the last command created).

Phase 0 creates these files empty on purpose so the tree matches Architecture.md. Rules.md rule 11 (no stubs reported as done) applies to what each phase reports as done, not to untouched later-phase files. Phase 0 must not put code in later-phase modules.

## 3. Tooling config

Append to `pyproject.toml` (strict settings required by Rules.md §4):

```toml
[tool.ruff]
line-length = 100
target-version = "py314"          # VERIFY ruff accepts py314

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "S", "SIM", "RUF"]

[tool.mypy]
strict = true
python_version = "3.14"
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--strict-markers --cov=src/pdagent --cov-report=term-missing"
```

## 4. Local services (docker-compose.yml)

```yaml
services:
  db:
    image: pgvector/pgvector:pg18 # VERIFY this tag exists and ships pgvector 0.8.1
    environment:
      POSTGRES_PASSWORD: postgres # local development only
      POSTGRES_DB: pdagent
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 10
  redis:
    image: redis:8 # VERIFY engine and version match FBC's ElastiCache (Memory.md Q7)
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10
```

The `postgres` password above is local only (Rules.md §7 forbids placeholder config on production paths; `.env.example` documents `PDAGENT_*` variables, never real keys).

```bash
cat > .env.example <<'EOF'
PDAGENT_DATABASE_URL=postgresql://app:CHANGE_ME@localhost:5432/pdagent
PDAGENT_MIGRATOR_DATABASE_URL=postgresql://migrator:CHANGE_ME@localhost:5432/pdagent
PDAGENT_REDIS_URL=redis://localhost:6379/0
PDAGENT_JWKS_URL=
PDAGENT_TOKEN_ISSUER=
PDAGENT_TOKEN_AUDIENCE=pdagent
PDAGENT_ANTHROPIC_API_KEY=
PDAGENT_OPENAI_API_KEY=
EOF
printf ".env\n.venv/\n__pycache__/\n.mypy_cache/\n.ruff_cache/\n.pytest_cache/\n.coverage\nnode_modules/\ndist/\n" > .gitignore
docker compose up -d db redis
uv sync
```

The three database roles (owner, migrator, app) and RLS policies are created in Phase 1, not here.

## 5. Widget project (`/widget`, created in Phase 7, not Phase 0)

Run only when Phase 7 starts. Interactive prompts: the Vite scaffolder may ask questions; answer with TypeScript, no framework.

```bash
node --version                              # must print v26.x
npm create vite@latest widget -- --template vanilla-ts   # VERIFY template name and flags
cd widget
echo "26" > .nvmrc
npm install lit                             # 3.3.x
npm install -D vitest @playwright/test axe-core
npx playwright install --with-deps          # downloads browsers; needs network
mkdir -p src/{api,state,components,styles,i18n} tests
touch src/pdk-assistant.ts src/api/{client,sse,types}.ts src/state/{conversation,confirm,handoff}.ts \
  src/components/{launcher,panel,message,source-chip,confirm-card,handoff-banner,composer,typing,error-row,empty-state}.ts \
  src/styles/{tokens.css,base.css}.ts src/i18n/en.ts
```

Set `"strict": true` in `widget/tsconfig.json`. Design.md names `confirm-card.ts` for the request slip component (spec id `request-slip`).

## 6. Smoke check (Phase 0 exit)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest
docker compose up -d db redis
uv run fastapi run src/pdagent/main.py --port 8000 &   # VERIFY command form; needs core/ and main.py implemented
curl -fsS localhost:8000/readyz
```

CI (GitHub Actions) runs the same commands plus the migration up/down check and the dependency advisory check; the workflow file is a Phase 0 deliverable, not pre-written here.
