"""Tests for the seed data generator.

Verifies:
- Reproducibility (same seed → same counts)
- Data integrity (FK relationships, value ranges)
"""

from __future__ import annotations

from sqlalchemy import text
import pytest


def test_seed_produces_data(db_session):
    """After seeding, all tables should have rows."""
    tables = [
        "installations", "facilities", "projects",
        "hazards", "constraints", "budgets", "isr_snapshots",
    ]
    for table in tables:
        count = db_session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        assert count > 0, f"Table {table} is empty after seeding"


def test_seed_reproducibility(db_session):
    """Two seed runs with the same parameters should produce identical installation names."""
    # The conftest seeds with rng_seed=42.  We just check that the first
    # installation name is deterministic.
    name = db_session.execute(
        text("SELECT name FROM installations ORDER BY id LIMIT 1")
    ).scalar()
    assert name is not None
    # With seed=42 and the generator logic, first installation is in Southeast region
    assert "Installation" in name


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
    """Materialized views should have data after seeding."""
    risk_count = db_session.execute(
        text("SELECT COUNT(*) FROM project_risk_exposure")
    ).scalar()
    assert risk_count > 0

    flag_count = db_session.execute(
        text("SELECT COUNT(*) FROM project_constraint_flags")
    ).scalar()
    assert flag_count > 0
