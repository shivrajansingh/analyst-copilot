"""
Demo users, mirrored from the frontend's `auth.store.ts`.

Real auth (R3) has not landed: the browser still checks credentials against a
hardcoded table and sends a `demo.<base64(user_id)>.<timestamp>` token. The
conversations API scopes history per user, so the same two demo identities must
exist as rows. `ensure_demo_users` upserts them so a fresh database is usable
the moment it is migrated — no separate seeding step.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from analyst_copilot.api.db.models import User

DEMO_USERS: list[tuple[str, str, str, str]] = [
    ("u_demo", "demo", "Demo Analyst", "analyst"),
    ("u_analyst", "analyst", "Analyst", "analyst"),
]


def ensure_demo_users(session: Session) -> None:
    existing = {row.id for row in session.scalars(select(User)).all()}
    for user_id, username, display_name, role in DEMO_USERS:
        if user_id in existing:
            continue
        session.add(
            User(id=user_id, username=username, display_name=display_name, role=role)
        )
    session.commit()
