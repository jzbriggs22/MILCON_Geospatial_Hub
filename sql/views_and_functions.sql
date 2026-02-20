-- ==========================================================================
-- MILCON Geospatial Hub — SQL views and utility functions
-- ==========================================================================
-- These are reference copies of the SQL used by the Python analytics layer.
-- They are also created via Alembic migrations (002).  Auditors can compare
-- these files to verify consistency.
-- ==========================================================================

-- Materialized view: project_risk_exposure
-- Inputs: projects, hazards
-- Spatial op: ST_DWithin(projects.geometry, hazards.geometry, 0.01)
-- Join type: LEFT JOIN (projects with no nearby hazard get severity 0)
CREATE MATERIALIZED VIEW IF NOT EXISTS project_risk_exposure AS
SELECT
    p.id              AS project_id,
    p.installation_id,
    p.category,
    p.cost_estimate,
    p.benefit_estimate,
    p.year,
    COALESCE(MAX(h.severity), 0) AS max_hazard_severity,
    COUNT(h.id)       AS hazard_count
FROM projects p
LEFT JOIN hazards h
    ON ST_DWithin(p.geometry, h.geometry, 0.01)
GROUP BY p.id, p.installation_id, p.category,
         p.cost_estimate, p.benefit_estimate, p.year;

CREATE UNIQUE INDEX IF NOT EXISTS idx_prisk_project
    ON project_risk_exposure (project_id);

-- Materialized view: project_constraint_flags
-- Inputs: projects, constraints
-- Spatial op: ST_Intersects(projects.geometry, constraints.geometry)
CREATE MATERIALIZED VIEW IF NOT EXISTS project_constraint_flags AS
SELECT
    p.id AS project_id,
    CASE WHEN COUNT(c.id) > 0 THEN 1 ELSE 0 END AS is_constrained,
    COUNT(c.id)            AS constraint_count,
    ARRAY_AGG(DISTINCT c.type) FILTER (WHERE c.id IS NOT NULL) AS constraint_types
FROM projects p
LEFT JOIN constraints c
    ON ST_Intersects(p.geometry, c.geometry)
GROUP BY p.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_pcflag_project
    ON project_constraint_flags (project_id);

-- Refresh both materialized views (call after data changes)
-- REFRESH MATERIALIZED VIEW CONCURRENTLY project_risk_exposure;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY project_constraint_flags;

-- ==========================================================================
-- Scoring query (parameterized, used by Python analytics layer)
-- ==========================================================================
-- This query is the backbone of project scoring.  Python passes scenario
-- weights and buffer distances as bind parameters.
--
-- Parameters:
--   :year                       — analysis year
--   :hazard_severity_mult       — scenario hazard severity multiplier
--   :constraint_buffer_m        — extra buffer in meters for constraints
--
-- The Python layer applies min-max normalization on the raw columns and
-- then computes the weighted score.  See app/analytics/scoring.py.
-- ==========================================================================

-- Raw factor query (un-normalized)
-- SELECT
--     pre.project_id,
--     pre.installation_id,
--     pre.category,
--     pre.cost_estimate,
--     pre.benefit_estimate,
--     i.readiness_score,
--     (100 - i.readiness_score) AS readiness_gap,
--     CASE WHEN pre.cost_estimate > 0
--          THEN pre.benefit_estimate / pre.cost_estimate
--          ELSE 0 END AS roi,
--     pre.max_hazard_severity * :hazard_severity_mult AS hazard_exposure,
--     pcf.is_constrained,
--     pcf.constraint_count
-- FROM project_risk_exposure pre
-- JOIN installations i ON i.id = pre.installation_id
-- JOIN project_constraint_flags pcf ON pcf.project_id = pre.project_id
-- WHERE pre.year = :year;
