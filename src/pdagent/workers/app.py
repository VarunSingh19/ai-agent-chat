"""Procrastinate PostgreSQL-backed worker application (`procrastinate >=3.10,<4`, Architecture.md
§1, §3).
"""

from __future__ import annotations

import procrastinate

procrastinate_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(),
)
