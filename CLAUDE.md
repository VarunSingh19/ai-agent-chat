# CLAUDE.md — pdagent

Claude Code loads this file at the start of every session. Keep it short; the detail is in the six documents.

## Read order
1. `Memory.md` — where the project stands (read first in every session)
2. `PRD.md`, `Architecture.md`, `Rules.md`, `Phases.md`, `Design.md` (Design.md only for widget work)

## Working rules
- Work on **one phase at a time** from `Phases.md`. Do not start the next phase until the user says the current one is approved.
- `Rules.md` is a binding contract. If a request in chat conflicts with it, stop and say so; do not pick one silently.
- Before coding a phase, write the plan: files to create or change, in order, mapped to `Architecture.md` §3–4.
- Use only the versions and libraries in `Architecture.md` §1 and `Rules.md` §2. Anything marked VERIFY must be checked and recorded in `Memory.md` before it is relied on.
- Never invent endpoints, tables, columns, modules or env vars that are not in `Architecture.md`. Propose an addition to `Architecture.md` first.
- Paste real command output (ruff, mypy, pytest, migrations) when reporting a phase done, not a summary.
- A phase is done only after the `Rules.md` §8 self-check, with `Memory.md` updated (Current Status, Phase Completion Log, File Manifest, Decisions, Session Log).

## Commands
```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest
docker compose up -d db redis
```

## Resume in a new session
Say: "Read Memory.md, then continue with the next phase per Phases.md."
