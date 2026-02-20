"""Initial schema — all core MILCON tables with PostGIS geometry.

Revision ID: 001
Revises: None
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # -- installations -------------------------------------------------------
    op.create_table(
        "installations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("readiness_score", sa.Float, nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.CheckConstraint("readiness_score >= 0 AND readiness_score <= 100"),
    )
    op.create_index("idx_installations_geom", "installations", ["geometry"], postgresql_using="gist")

    # -- facilities ----------------------------------------------------------
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("installation_id", sa.Integer, sa.ForeignKey("installations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("condition_index", sa.Float, nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.CheckConstraint("condition_index >= 0 AND condition_index <= 100"),
    )
    op.create_index("idx_facilities_geom", "facilities", ["geometry"], postgresql_using="gist")
    op.create_index("idx_facilities_installation", "facilities", ["installation_id"])

    # -- projects ------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("installation_id", sa.Integer, sa.ForeignKey("installations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("cost_estimate", sa.Float, nullable=False),
        sa.Column("benefit_estimate", sa.Float, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.CheckConstraint("cost_estimate > 0"),
        sa.CheckConstraint("benefit_estimate >= 0"),
        sa.CheckConstraint("priority >= 1 AND priority <= 5"),
    )
    op.create_index("idx_projects_geom", "projects", ["geometry"], postgresql_using="gist")
    op.create_index("idx_projects_installation", "projects", ["installation_id"])
    op.create_index("idx_projects_year", "projects", ["year"])

    # -- hazards -------------------------------------------------------------
    op.create_table(
        "hazards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("severity", sa.Float, nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=False),
        sa.CheckConstraint("severity >= 0 AND severity <= 10"),
    )
    op.create_index("idx_hazards_geom", "hazards", ["geometry"], postgresql_using="gist")

    # -- constraints ---------------------------------------------------------
    op.create_table(
        "constraints",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("geometry", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=False),
    )
    op.create_index("idx_constraints_geom", "constraints", ["geometry"], postgresql_using="gist")

    # -- budgets -------------------------------------------------------------
    op.create_table(
        "budgets",
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("capex_limit", sa.Float, nullable=False),
        sa.CheckConstraint("capex_limit > 0"),
    )

    # -- isr_snapshots -------------------------------------------------------
    op.create_table(
        "isr_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("installation_id", sa.Integer, sa.ForeignKey("installations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("readiness", sa.Float, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.CheckConstraint("readiness >= 0 AND readiness <= 100"),
        sa.UniqueConstraint("installation_id", "date", name="uq_isr_snapshot"),
    )
    op.create_index("idx_isr_installation_date", "isr_snapshots", ["installation_id", "date"])


def downgrade() -> None:
    op.drop_table("isr_snapshots")
    op.drop_table("budgets")
    op.drop_table("constraints")
    op.drop_table("hazards")
    op.drop_table("projects")
    op.drop_table("facilities")
    op.drop_table("installations")
