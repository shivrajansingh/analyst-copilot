"""
Engine and session plumbing.

The database is optional by design: the QA pipeline never needs it, and a
deployment that only asks questions should not be forced to run Postgres. When
`DATABASE_URL` is unset the API serves answers normally and simply does not
record them — the conversations endpoints answer 503 `database_unavailable`
instead of failing with a stack trace.
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> Optional[str]:
    """The configured Postgres URL, or None when persistence is disabled."""
    return os.getenv("DATABASE_URL") or os.getenv("API_DATABASE_URL") or None


def _create_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_create_engine(url), expire_on_commit=False, future=True)


def check_database(session: Session) -> bool:
    """True when the configured database answers. Never raises."""
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
