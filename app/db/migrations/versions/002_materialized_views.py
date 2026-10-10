"""Add materialized views for analytics performance.

Revision ID: 002
Revises: 001
Create Date: 2026-02-20

Design
======
The proximity views pre-compute pairwise project↔hazard and
project↔constraint distances in METERS (geography cast, so distances are
true meters and isotropic — no degrees/latitude distortion) for all pairs
within MAX_PROXIMITY_RADIUS_M.  Scenario-specific buffer distances are then
applied at query time as bind parameters (`distance_m <= :buffer_m`),
so the same materialized data serves every scenario without re-computation.

A pair at distance 0 intersects (geography distance 0 ⇔ ST_Intersects),
so a constraint buffer of 0 m reproduces plain intersection semantics.

Auditability: the exact SQL is embedded below and mirrored in
sql/views_and_functions.sql (consistency enforced by tests/test_sql_reference.py).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pairs beyond this distance are not materialized; query-time buffers must
# not exceed it (enforced in app/analytics/scoring.py).
MAX_PROXIMITY_RADIUS_M = 10_000

MV_HAZARD_PROXIMITY = f"""
CREATE MATERIALIZED VIEW project_hazard_proximity AS
SELECT
    p.id AS project_id,
    h.id AS hazard_id,
    h.type AS hazard_type,
    h.severity,
    ST_Distance(p.geometry::geography, h.geometry::geography) AS distance_m
FROM projects p
JOIN hazards h
    ON ST_DWithin(p.geometry::geography, h.geometry::geography, {MAX_PROXIMITY_RADIUS_M})
"""

MV_CONSTRAINT_PROXIMITY = f"""
CREATE MATERIALIZED VIEW project_constraint_proximity AS
SELECT
    p.id AS project_id,
    c.id AS constraint_id,
    c.type AS constraint_type,
    ST_Distance(p.geometry::geography, c.geometry::geography) AS distance_m
FROM projects p
JOIN constraints c
    ON ST_DWithin(p.geometry::geography, c.geometry::geography, {MAX_PROXIMITY_RADIUS_M})
"""


def upgrade() -> None:
    op.execute(MV_HAZARD_PROXIMITY)
    op.execute(
        "CREATE UNIQUE INDEX idx_phaz_pair ON project_hazard_proximity (project_id, hazard_id)"
    )
    op.execute(
        "CREATE INDEX idx_phaz_project_dist ON project_hazard_proximity (project_id, distance_m)"
    )

    op.execute(MV_CONSTRAINT_PROXIMITY)
    op.execute(
        "CREATE UNIQUE INDEX idx_pcon_pair ON project_constraint_proximity (project_id, constraint_id)"
    )
    op.execute(
        "CREATE INDEX idx_pcon_project_dist ON project_constraint_proximity (project_id, distance_m)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS project_constraint_proximity")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS project_hazard_proximity")
