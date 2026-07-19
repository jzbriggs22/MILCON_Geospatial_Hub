"""SQLAlchemy ORM models with PostGIS geometry columns.

All geometry columns use SRID 4326 (WGS 84) for consistency.
GIST indexes are created on every geometry column.
"""

from __future__ import annotations

from datetime import date

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    readiness_score: Mapped[float] = mapped_column(
        Float,
        CheckConstraint("readiness_score >= 0 AND readiness_score <= 100"),
        nullable=False,
    )
    geometry = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)

    facilities: Mapped[list[Facility]] = relationship(back_populates="installation")
    projects: Mapped[list[Project]] = relationship(back_populates="installation")
    isr_snapshots: Mapped[list[ISRSnapshot]] = relationship(back_populates="installation")

    __table_args__ = (
        Index("idx_installations_geom", "geometry", postgresql_using="gist"),
    )


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("installations.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    condition_index: Mapped[float] = mapped_column(
        Float,
        CheckConstraint("condition_index >= 0 AND condition_index <= 100"),
        nullable=False,
    )
    geometry = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)

    installation: Mapped[Installation] = relationship(back_populates="facilities")

    __table_args__ = (
        Index("idx_facilities_geom", "geometry", postgresql_using="gist"),
        Index("idx_facilities_installation", "installation_id"),
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("installations.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_estimate: Mapped[float] = mapped_column(
        Float, CheckConstraint("cost_estimate > 0"), nullable=False
    )
    benefit_estimate: Mapped[float] = mapped_column(
        Float, CheckConstraint("benefit_estimate >= 0"), nullable=False
    )
    priority: Mapped[int] = mapped_column(
        Integer, CheckConstraint("priority >= 1 AND priority <= 5"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)

    installation: Mapped[Installation] = relationship(back_populates="projects")

    __table_args__ = (
        Index("idx_projects_geom", "geometry", postgresql_using="gist"),
        Index("idx_projects_installation", "installation_id"),
        Index("idx_projects_year", "year"),
    )


class Hazard(Base):
    __tablename__ = "hazards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[float] = mapped_column(
        Float,
        CheckConstraint("severity >= 0 AND severity <= 10"),
        nullable=False,
    )
    geometry = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=False), nullable=False)

    __table_args__ = (
        Index("idx_hazards_geom", "geometry", postgresql_using="gist"),
    )


class Constraint(Base):
    __tablename__ = "constraints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=False), nullable=False)

    __table_args__ = (
        Index("idx_constraints_geom", "geometry", postgresql_using="gist"),
    )


class Budget(Base):
    __tablename__ = "budgets"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    capex_limit: Mapped[float] = mapped_column(
        Float, CheckConstraint("capex_limit > 0"), nullable=False
    )


class ISRSnapshot(Base):
    __tablename__ = "isr_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("installations.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    readiness: Mapped[float] = mapped_column(
        Float,
        CheckConstraint("readiness >= 0 AND readiness <= 100"),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    installation: Mapped[Installation] = relationship(back_populates="isr_snapshots")

    __table_args__ = (
        UniqueConstraint("installation_id", "date", name="uq_isr_snapshot"),
        Index("idx_isr_installation_date", "installation_id", "date"),
    )
