"""Add materialized views for analytics performance.

Revision ID: 002
Revises: 001
Create Date: 2026-02-20

The project_risk_exposure materialized view pre-computes the spatial join
between projects and hazard buffers, avoiding repeated ST_DWithin calls
during scoring.  The view is deterministic: for the same input data, the
same rows are produced.

SQL audit note: The exact query is embedded below.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Materialized view: project_risk_exposure
#
# For each project, computes the maximum hazard severity within 0.01 degrees
# (~1 km at mid-latitudes).  Projects with no nearby hazard get severity 0.
#
# Inputs:  projects, hazards
# Spatial op: ST_DWithin(projects.geometry, hazards.geometry, 0.01)
# ---------------------------------------------------------------------------
MV_PROJECT_RISK = """
CREATE MATERIALIZED VIEW IF NOT EXISTS project_risk_exposure AS
SELECT
    p.id AS project_id,
    p.installation_id,
    p.category,
    p.cost_estimate,
    p.benefit_estimate,
    p.year,
    COALESCE(MAX(h.severity), 0) AS max_hazard_severity,
    COUNT(h.id) AS hazard_count
FROM projects p
LEFT JOIN hazards h
    ON ST_DWithin(p.geometry, h.geometry, 0.01)
GROUP BY p.id, p.installation_id, p.category, p.cost_estimate, p.benefit_estimate, p.year
"""

# ---------------------------------------------------------------------------
# Materialized view: project_constraint_flags
#
# Flags projects that intersect any constraint polygon (optionally buffered).
# ---------------------------------------------------------------------------
MV_PROJECT_CONSTRAINTS = """
CREATE MATERIALIZED VIEW IF NOT EXISTS project_constraint_flags AS
SELECT
    p.id AS project_id,
    CASE WHEN COUNT(c.id) > 0 THEN 1 ELSE 0 END AS is_constrained,
    COUNT(c.id) AS constraint_count,
    ARRAY_AGG(DISTINCT c.type) FILTER (WHERE c.id IS NOT NULL) AS constraint_types
FROM projects p
LEFT JOIN constraints c
    ON ST_Intersects(p.geometry, c.geometry)
GROUP BY p.id
"""


def upgrade() -> None:
    op.execute(MV_PROJECT_RISK)
    op.execute("CREATE UNIQUE INDEX idx_prisk_project ON project_risk_exposure (project_id)")

    op.execute(MV_PROJECT_CONSTRAINTS)
    op.execute("CREATE UNIQUE INDEX idx_pcflag_project ON project_constraint_flags (project_id)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS project_constraint_flags")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS project_risk_exposure")
