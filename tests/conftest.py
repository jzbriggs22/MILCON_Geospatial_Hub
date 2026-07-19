"""Shared test fixtures.

Tests use a real PostgreSQL/PostGIS database (via Docker Compose or local).
Set DATABASE_URL env var to override.  The test suite:

1. Applies all Alembic migrations.
2. Reseeds with a small deterministic dataset (seed_database truncates
   and restarts identity sequences, so the state is identical every run
   regardless of what was in the database before).

The seeded data is intentionally left in place after the run so failures
can be inspected; re-running the suite (or the app's own seed command)
resets it.
"""

from __future__ import annotations

import os

import pytest

from app.db.engine import get_engine, get_session

TEST_ROWS = 200
TEST_SEED = 42


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://milcon:milcon@localhost:5432/milcon",
    )


@pytest.fixture(scope="session")
def db_engine():
    return get_engine(_db_url())


@pytest.fixture(scope="session")
def db_session(db_engine):
    """Session-scoped DB session.  Applies migrations and reseeds once."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", _db_url())
    command.upgrade(alembic_cfg, "head")

    session = get_session(_db_url())

    from app.data.seed import seed_database

    seed_database(session, total_rows=TEST_ROWS, rng_seed=TEST_SEED)

    yield session
    session.close()
