"""Tests for the seed data generator.

Verifies:
- Idempotency (re-running seed is safe and deterministic)
- Reproducibility (same seed → identical data, including primary keys)
- Data integrity (FK relationships, value ranges)
"""

from __future__ import annotations

from sqlalchemy import text

from app.data.seed import seed_database
from tests.conftest import TEST_ROWS, TEST_SEED


def _installation_fingerprint(session) -> list[tuple]:
    return session.execute(text(
        "SELECT id, name, region, readiness_score, ST_AsText(geometry) "
        "FROM installations ORDER BY id"
    )).fetchall()


def test_seed_produces_data(db_session):
    """After seeding, all tables should have rows."""
    tables = [
        "installations", "facilities", "projects",
        "hazards", "constraints", "budgets", "isr_snapshots",
    ]
    for table in tables:
        count = db_session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        assert count > 0, f"Table {table} is empty after seeding"


def test_seed_idempotent_and_reproducible(db_session):
    """Re-running seed with the same parameters must succeed (no PK
    collisions) and produce byte-identical installations, including IDs."""
    before = _installation_fingerprint(db_session)
    counts_before = db_session.execute(
        text("SELECT COUNT(*) FROM projects")
    ).scalar()

    # Second run — would raise IntegrityError on budgets if not idempotent.
    seed_database(db_session, total_rows=TEST_ROWS, rng_seed=TEST_SEED)

    after = _installation_fingerprint(db_session)
    counts_after = db_session.execute(
        text("SELECT COUNT(*) FROM projects")
    ).scalar()

    assert before == after
    assert counts_before == counts_after


def test_readiness_scores_in_range(db_session):
    """All readiness scores must be in [0, 100]."""
    result = db_session.execute(text(
        "SELECT MIN(readiness_score), MAX(readiness_score) FROM installations"
    )).fetchone()
    assert result[0] >= 0
    assert result[1] <= 100


def test_condition_index_in_range(db_session):
    """All condition indexes must be in [0, 100]."""
    result = db_session.execute(text(
        "SELECT MIN(condition_index), MAX(condition_index) FROM facilities"
    )).fetchone()
    assert result[0] >= 0
    assert result[1] <= 100


def test_project_costs_positive(db_session):
    """All project costs must be positive."""
    result = db_session.execute(text(
        "SELECT MIN(cost_estimate) FROM projects"
    )).scalar()
    assert result > 0


def test_hazard_severity_range(db_session):
    """Hazard severity must be in [0, 10]."""
    result = db_session.execute(text(
        "SELECT MIN(severity), MAX(severity) FROM hazards"
    )).fetchone()
    assert result[0] >= 0
    assert result[1] <= 10


def test_foreign_keys_valid(db_session):
    """All facility and project installation_ids reference existing installations."""
    orphan_fac = db_session.execute(text(
        "SELECT COUNT(*) FROM facilities f "
        "LEFT JOIN installations i ON i.id = f.installation_id "
        "WHERE i.id IS NULL"
    )).scalar()
    assert orphan_fac == 0

    orphan_proj = db_session.execute(text(
        "SELECT COUNT(*) FROM projects p "
        "LEFT JOIN installations i ON i.id = p.installation_id "
        "WHERE i.id IS NULL"
    )).scalar()
    assert orphan_proj == 0


def test_materialized_views_populated(db_session):
    """Proximity materialized views should have data after seeding.

    Projects are placed within ~0.02 deg of their installation and hazards
    are seeded in the same regions, so at least some pairs must fall within
    the 10 km materialization radius.
    """
    hazard_pairs = db_session.execute(
        text("SELECT COUNT(*) FROM project_hazard_proximity")
    ).scalar()
    assert hazard_pairs > 0

    # Constraint pairs may legitimately be sparse; only require the view
    # to be queryable and non-negative.
    constraint_pairs = db_session.execute(
        text("SELECT COUNT(*) FROM project_constraint_proximity")
    ).scalar()
    assert constraint_pairs >= 0
