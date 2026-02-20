"""SQL queries used by the analytics layer.

Every query is stored as a named constant so that:
1. Reports can reference the exact SQL executed.
2. Auditors can verify that scoring logic matches documentation.
3. The same queries appear in sql/views_and_functions.sql for cross-reference.

All queries use bind parameters (`:param`) — never string interpolation.
"""

# ---------------------------------------------------------------------------
# RAW_FACTORS_QUERY
# ---------------------------------------------------------------------------
# Pulls un-normalized scoring factors for all projects in a given year.
#
# Inputs:
#   :year — analysis year (integer)
#   :hazard_severity_mult — scenario multiplier for hazard severity (float)
#
# Source tables:
#   project_risk_exposure   (materialized view, from projects + hazards)
#   project_constraint_flags (materialized view, from projects + constraints)
#   installations
#
# Columns returned:
#   project_id, installation_id, category, cost_estimate, benefit_estimate,
#   readiness_score, readiness_gap, roi, hazard_exposure,
#   is_constrained, constraint_count
# ---------------------------------------------------------------------------
RAW_FACTORS_QUERY = """
SELECT
    pre.project_id,
    pre.installation_id,
    pre.category,
    pre.cost_estimate,
    pre.benefit_estimate,
    i.readiness_score,
    (100.0 - i.readiness_score)                      AS readiness_gap,
    CASE WHEN pre.cost_estimate > 0
         THEN pre.benefit_estimate / pre.cost_estimate
         ELSE 0 END                                   AS roi,
    pre.max_hazard_severity * :hazard_severity_mult    AS hazard_exposure,
    pre.hazard_count,
    pcf.is_constrained,
    pcf.constraint_count
FROM project_risk_exposure pre
JOIN installations i        ON i.id = pre.installation_id
JOIN project_constraint_flags pcf ON pcf.project_id = pre.project_id
WHERE pre.year = :year
ORDER BY pre.project_id
"""

# ---------------------------------------------------------------------------
# BUDGET_QUERY
# ---------------------------------------------------------------------------
BUDGET_QUERY = """
SELECT year, capex_limit FROM budgets WHERE year = :year
"""

# ---------------------------------------------------------------------------
# INSTALLATION_SUMMARY
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
# REFRESH_MATERIALIZED_VIEWS
# ---------------------------------------------------------------------------
REFRESH_MV_RISK = "REFRESH MATERIALIZED VIEW CONCURRENTLY project_risk_exposure"
REFRESH_MV_CONSTRAINTS = "REFRESH MATERIALIZED VIEW CONCURRENTLY project_constraint_flags"
