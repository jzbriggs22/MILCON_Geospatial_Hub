"""Tests for spatial / PostGIS logic.

Verifies:
- Proximity materialized views store true meter distances
- Distance-0 pairs correspond to intersections
- Geometry types and SRIDs are correct
- No duplicate spatial indexes (regression: geoalchemy2 used to
  auto-create a second GiST index per geometry column)
"""

from __future__ import annotations

from sqlalchemy import text


def test_proximity_distances_within_radius(db_session):
    """All materialized pairs must be within the 10 km cap."""
    from app.analytics.queries import MAX_PROXIMITY_RADIUS_M

    max_dist = db_session.execute(text(
        "SELECT MAX(distance_m) FROM project_hazard_proximity"
    )).scalar()
    if max_dist is not None:
        assert max_dist <= MAX_PROXIMITY_RADIUS_M


def test_zero_distance_means_intersection(db_session):
    """Pairs at distance 0 must actually intersect (geography semantics)."""
    mismatches = db_session.execute(text(
        "SELECT COUNT(*) FROM project_hazard_proximity phz "
        "JOIN projects p ON p.id = phz.project_id "
        "JOIN hazards h ON h.id = phz.hazard_id "
        "WHERE phz.distance_m = 0 "
        "AND NOT ST_Intersects(p.geometry, h.geometry)"
    )).scalar()
    assert mismatches == 0


def test_installation_geometry_is_point(db_session):
    """All installation geometries should be POINT type."""
    result = db_session.execute(text(
        "SELECT DISTINCT ST_GeometryType(geometry) FROM installations"
    )).fetchall()
    types = {row[0] for row in result}
    assert types == {"ST_Point"}


def test_hazard_geometry_is_polygon(db_session):
    """All hazard geometries should be POLYGON type."""
    result = db_session.execute(text(
        "SELECT DISTINCT ST_GeometryType(geometry) FROM hazards"
    )).fetchall()
    types = {row[0] for row in result}
    assert types == {"ST_Polygon"}


def test_srid_consistency(db_session):
    """All geometries should use SRID 4326."""
    tables = ["installations", "facilities", "projects", "hazards", "constraints"]
    for table in tables:
        srid = db_session.execute(text(
            f"SELECT DISTINCT ST_SRID(geometry) FROM {table}"
        )).scalar()
        assert srid == 4326, f"Table {table} has SRID {srid}, expected 4326"


def test_single_spatial_index_per_geometry_column(db_session):
    """Each geometry column must carry exactly one GiST index."""
    tables = ["installations", "facilities", "projects", "hazards", "constraints"]
    for table in tables:
        count = db_session.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = :t AND indexdef ILIKE '%USING gist%'"
        ), {"t": table}).scalar()
        assert count == 1, f"Table {table} has {count} GiST indexes, expected 1"


def test_stale_view_detection(db_session):
    """After refresh, every 2026 project appears in the factors query even
    if it has no nearby hazard or constraint (LEFT JOIN semantics)."""
    import pandas as pd
    from app.analytics.queries import RAW_FACTORS_QUERY

    n_projects = db_session.execute(text(
        "SELECT COUNT(*) FROM projects WHERE year = 2026"
    )).scalar()
    df = pd.read_sql(
        text(RAW_FACTORS_QUERY),
        db_session.connection(),
        params={"year": 2026, "hazard_buffer_m": 1000.0, "constraint_buffer_m": 0.0},
    )
    assert len(df) == n_projects
