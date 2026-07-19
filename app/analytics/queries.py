"""SQL queries used by the analytics layer.

Every query is stored as a named constant so that:
1. Reports can reference the exact SQL executed.
2. Auditors can verify that scoring logic matches documentation.
3. sql/views_and_functions.sql mirrors the view definitions for
   cross-reference (consistency enforced by tests/test_sql_reference.py).

All queries use bind parameters (`:param`) — never string interpolation.
"""

# Materialized views only contain pairs within this radius (see migration 002).
# Query-time buffers must not exceed it.
MAX_PROXIMITY_RADIUS_M = 10_000

# ---------------------------------------------------------------------------
# RAW_FACTORS_QUERY
# ---------------------------------------------------------------------------
# Pulls un-normalized scoring factors for all projects in a given year.
#
# Bind parameters:
#   :year                — analysis year (integer)
#   :hazard_buffer_m     — hazard proximity radius in meters (float)
#   :constraint_buffer_m — constraint proximity radius in meters (float);
#                          0 reproduces plain-intersection semantics
#
# Source tables/views:
#   projects, installations (base tables — new projects always appear)
#   project_hazard_proximity, project_constraint_proximity
#     (materialized views of pairwise distances in meters; migration 002)
#
# Columns returned:
#   project_id, installation_id, category, cost_estimate, benefit_estimate,
#   year, readiness_score, readiness_gap, roi, max_hazard_severity,
#   hazard_count, is_constrained, constraint_count
# ---------------------------------------------------------------------------
RAW_FACTORS_QUERY = """
SELECT
    p.id AS project_id,
    p.installation_id,
    p.category,
    p.cost_estimate,
    p.benefit_estimate,
    p.year,
    i.readiness_score,
    (100.0 - i.readiness_score)                      AS readiness_gap,
    CASE WHEN p.cost_estimate > 0
         THEN p.benefit_estimate / p.cost_estimate
         ELSE 0 END                                   AS roi,
    COALESCE(hz.max_severity, 0)                      AS max_hazard_severity,
    COALESCE(hz.hazard_count, 0)                      AS hazard_count,
    CASE WHEN COALESCE(cz.constraint_count, 0) > 0
         THEN 1 ELSE 0 END                            AS is_constrained,
    COALESCE(cz.constraint_count, 0)                  AS constraint_count
FROM projects p
JOIN installations i ON i.id = p.installation_id
LEFT JOIN (
    SELECT project_id,
           MAX(severity) AS max_severity,
           COUNT(*)      AS hazard_count
    FROM project_hazard_proximity
    WHERE distance_m <= :hazard_buffer_m
    GROUP BY project_id
) hz ON hz.project_id = p.id
LEFT JOIN (
    SELECT project_id,
           COUNT(*) AS constraint_count
    FROM project_constraint_proximity
    WHERE distance_m <= :constraint_buffer_m
    GROUP BY project_id
) cz ON cz.project_id = p.id
WHERE p.year = :year
ORDER BY p.id
"""

# ---------------------------------------------------------------------------
# BUDGET_QUERY
# ---------------------------------------------------------------------------
BUDGET_QUERY = """
SELECT year, capex_limit FROM budgets WHERE year = :year
"""

# ---------------------------------------------------------------------------
# INSTALLATION_SUMMARY_QUERY
# ---------------------------------------------------------------------------
INSTALLATION_SUMMARY_QUERY = """
SELECT
    i.id,
    i.name,
    i.region,
    i.readiness_score,
    ST_X(i.geometry::geometry) AS lon,
    ST_Y(i.geometry::geometry) AS lat,
    COUNT(DISTINCT f.id) AS facility_count,
    ROUND(AVG(f.condition_index)::numeric, 1) AS avg_condition
FROM installations i
LEFT JOIN facilities f ON f.installation_id = i.id
GROUP BY i.id, i.name, i.region, i.readiness_score, i.geometry
ORDER BY i.id
"""

# ---------------------------------------------------------------------------
# HAZARD_OVERLAY_QUERY — for map rendering
# ---------------------------------------------------------------------------
HAZARD_OVERLAY_QUERY = """
SELECT
    id, type, severity,
    ST_AsGeoJSON(geometry)::json AS geojson
FROM hazards
"""

# ---------------------------------------------------------------------------
# CONSTRAINT_OVERLAY_QUERY — for map rendering
# ---------------------------------------------------------------------------
CONSTRAINT_OVERLAY_QUERY = """
SELECT
    id, type, notes,
    ST_AsGeoJSON(geometry)::json AS geojson
FROM constraints
"""

# ---------------------------------------------------------------------------
# PROJECT_LOCATIONS_QUERY — for map rendering with scores
# ---------------------------------------------------------------------------
PROJECT_LOCATIONS_QUERY = """
SELECT
    p.id,
    p.category,
    p.cost_estimate,
    p.benefit_estimate,
    p.year,
    ST_X(p.geometry::geometry) AS lon,
    ST_Y(p.geometry::geometry) AS lat,
    i.name AS installation_name
FROM projects p
JOIN installations i ON i.id = p.installation_id
WHERE p.year = :year
ORDER BY p.id
"""

# ---------------------------------------------------------------------------
# Materialized view refresh — single source of truth.
# Plain (non-CONCURRENT) refresh: correct on both populated and fresh views,
# and faster for full reloads.  Called via
# app.db.maintenance.refresh_analytics_views().
# ---------------------------------------------------------------------------
REFRESH_STATEMENTS = (
    "REFRESH MATERIALIZED VIEW project_hazard_proximity",
    "REFRESH MATERIALIZED VIEW project_constraint_proximity",
)
