"""Database maintenance operations shared by every write path.

Any code that modifies projects, hazards, or constraints MUST call
refresh_analytics_views() afterwards — scoring reads the proximity
materialized views, and stale views silently misprice or drop projects.
Encoding that invariant here (rather than in each caller) is what keeps
future write paths honest.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import REFRESH_STATEMENTS


def refresh_analytics_views(session: Session) -> None:
    """Refresh all analytics materialized views and commit."""
    for statement in REFRESH_STATEMENTS:
        session.execute(text(statement))
    session.commit()
