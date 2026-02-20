# MILCON Geospatial Hub

A geospatial decision-support system for MILCON-style infrastructure planning.
Stores installations, facilities, projects, hazards, and constraints in PostGIS;
runs automated scoring, cost-benefit analysis, and budget optimization; and
produces auditable reports with full traceability.

**This is a planning/analytics tool using synthetic demo data only.**

---

## Quickstart

### One-command setup (Docker Compose)

```bash
docker compose up --build
```

This will:
1. Start a PostGIS 16 database
2. Run Alembic migrations
3. Seed the database with ~2000 rows of synthetic data (seed=42)
4. Launch the Streamlit dashboard at http://localhost:8501

### Manual setup (local Python)

```bash
# Start PostGIS (or use your own)
docker run -d --name milcon-db \
  -e POSTGRES_DB=milcon -e POSTGRES_USER=milcon -e POSTGRES_PASSWORD=milcon \
  -p 5432:5432 postgis/postgis:16-3.4

# Install dependencies
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Seed database
python -m app.cli seed --rows 2000 --seed 42

# Run analysis
python -m app.cli analyze --scenario baseline --year 2026

# View report
python -m app.cli report --last

# Run tests
pytest -q

# Launch dashboard
streamlit run app/ui/dashboard.py
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m app.cli seed --rows 2000 --seed 42` | Seed database with synthetic data |
| `python -m app.cli analyze --scenario baseline --year 2026` | Run scoring + budget optimization |
| `python -m app.cli report --last` | Display the most recent report |
| `python -m app.cli scenarios` | List available scenarios with weights |
| `pytest -q` | Run all unit tests |

---

## Schema Overview (ERD)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ installations│────<│  facilities  │     │   hazards    │
│──────────────│     │──────────────│     │──────────────│
│ id       PK  │     │ id       PK  │     │ id       PK  │
│ name         │     │ install_id FK│     │ type         │
│ region       │     │ type         │     │ severity 0-10│
│ readiness    │     │ condition    │     │ geometry POLY│
│   0-100      │     │   0-100      │     └──────────────┘
│ geometry PT  │     │ geometry PT  │
└──────┬───────┘     └──────────────┘     ┌──────────────┐
       │                                   │ constraints  │
       │         ┌──────────────┐          │──────────────│
       └────────<│   projects   │          │ id       PK  │
                 │──────────────│          │ type         │
                 │ id       PK  │          │ notes        │
                 │ install_id FK│          │ geometry POLY│
                 │ category     │          └──────────────┘
                 │ cost_estimate│
                 │ benefit_est  │   ┌──────────────┐
                 │ priority 1-5 │   │   budgets    │
                 │ year         │   │──────────────│
                 │ geometry PT  │   │ year     PK  │
                 └──────────────┘   │ capex_limit  │
                                    └──────────────┘
┌──────────────────┐
│  isr_snapshots   │
│──────────────────│
│ id           PK  │
│ install_id   FK  │
│ date             │
│ readiness  0-100 │
│ notes            │
│ UQ(install, date)│
└──────────────────┘
```

All geometry columns use SRID 4326 (WGS 84) with GIST indexes.

### Materialized Views

| View | Purpose | Key spatial op |
|------|---------|---------------|
| `project_risk_exposure` | Pre-computes max hazard severity within 0.01 degrees (~1 km) of each project | `ST_DWithin` |
| `project_constraint_flags` | Flags projects intersecting constraint polygons | `ST_Intersects` |

Both views have unique indexes on `project_id` and support `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

---

## Scoring Factors & Weights

The multi-objective score for each project is:

```
score = w_readiness  * readiness_gap_norm
      + w_roi        * roi_norm
      - w_risk       * hazard_exposure_norm
      - w_constraint * constraint_penalty_norm
```

### Factor Definitions

| Factor | Source Table(s) | Computation | Direction |
|--------|----------------|------------|-----------|
| Readiness Gap | `installations.readiness_score` | `100 - readiness_score` | Higher gap = more benefit from investment |
| ROI | `projects.benefit_estimate / cost_estimate` | Direct ratio | Higher ROI = better value |
| Hazard Exposure | `project_risk_exposure.max_hazard_severity` | Max severity within ~1km, multiplied by scenario `hazard_severity_multiplier` | Higher exposure = penalty |
| Constraint Penalty | `project_constraint_flags` | `is_constrained * min(constraint_count / 5, 1)` | Constrained = penalty |

### Normalization

All factors are min-max normalized to [0, 1] over the project set for the given year.
Constant columns normalize to 0.5. Normalization bounds are recorded in every report's
`audit_metadata.json` and displayed in the Explainability panel.

### Traceability

Every score is reproducible by:
1. Running the SQL query from `app/analytics/queries.py:RAW_FACTORS_QUERY` with the stated parameters.
2. Applying min-max normalization with the stated bounds from `audit_metadata.json`.
3. Multiplying by the stated scenario weights from `app/config.py:SCENARIOS`.

---

## Scenarios

| Scenario | Description | w_readiness | w_roi | w_risk | w_constraint | Special |
|----------|-------------|-------------|-------|--------|--------------|---------|
| `baseline` | Normal weights, full budget | 0.30 | 0.35 | 0.20 | 0.15 | — |
| `climate_stress` | Elevated hazard severity and risk weight | 0.20 | 0.25 | 0.40 | 0.15 | `hazard_severity_multiplier=1.5` |
| `readiness_surge` | Readiness top priority, budget at 70% | 0.50 | 0.20 | 0.15 | 0.15 | `budget_multiplier=0.70` |
| `constraint_heavy` | Expanded no-build zones, constraint weight up | 0.25 | 0.25 | 0.20 | 0.30 | `constraint_buffer_m=500` |

All weight values are defined in `app/config.py:SCENARIOS` and stored in every report.

---

## Budget Optimizer

Uses a **greedy approximation** to the 0-1 knapsack problem:

1. Compute `score_per_cost = score / cost_estimate` for each project.
2. Sort descending by `score_per_cost`.
3. Select projects while cumulative cost <= `capex_limit` and `score > 0`.

### Algorithm Audit Trail

The `OptimizationResult` includes:
- `algorithm`: Name of the algorithm used (e.g., `"greedy-score-per-cost"`)
- `limitations`: Human-readable description of known limitations
- `selection_trace`: Step-by-step log of every selection decision (project_id, cost, score, cumulative_cost)

### Limitations

- Not provably optimal (0-1 knapsack is NP-hard).
- Typically within 90-95% of optimal for typical MILCON cost distributions.
- A future enhancement could use `scipy.optimize.milp` or Google OR-Tools.

---

## Auditability

Every analytic output is traceable to specific SQL queries, input tables,
configuration values, and scenario weights. There is no hidden logic or
opaque heuristics.

| Artifact | Contents |
|----------|----------|
| `runs/<ts>/audit_metadata.json` | Full config, weights, SQL query text + bind params, normalization bounds, optimizer algorithm + trace |
| `runs/<ts>/report.md` | Scenario config table, SQL reference, normalization bounds, top-10 projects |
| Dashboard Explainability tab | Per-project factor breakdown: raw value, normalized value, weight, signed contribution, formula |
| `app/analytics/queries.py` | All SQL queries as named string constants with documentation |
| `sql/views_and_functions.sql` | Reference copy of all SQL for independent cross-verification |
| `app/config.py` | All scenario weight definitions |

---

## Adding New Hazards / Constraints

Insert directly into PostgreSQL:

```sql
-- New flood hazard
INSERT INTO hazards (type, severity, geometry)
VALUES ('flood', 7.5, ST_GeomFromText('POLYGON((-80 32, -80 33, -79 33, -79 32, -80 32))', 4326));

-- New no-build constraint
INSERT INTO constraints (type, notes, geometry)
VALUES ('no-build', 'Wetland protection area', ST_GeomFromText('POLYGON((...)))', 4326));

-- IMPORTANT: Refresh materialized views after data changes
REFRESH MATERIALIZED VIEW CONCURRENTLY project_risk_exposure;
REFRESH MATERIALIZED VIEW CONCURRENTLY project_constraint_flags;
```

Or extend `app/data/seed.py` and re-run `python -m app.cli seed`.

---

## Performance Considerations

- **GIST indexes** on all geometry columns for spatial query acceleration.
- **Materialized views** (`project_risk_exposure`, `project_constraint_flags`) pre-compute spatial joins, avoiding repeated `ST_DWithin`/`ST_Intersects` during scoring.
- `REFRESH MATERIALIZED VIEW CONCURRENTLY` allows non-blocking refreshes with the unique indexes.
- For datasets >100k projects, consider partitioning `projects` by year and adding composite covering indexes on `(installation_id, year)`.
- The scoring query reads from materialized views (not base tables), keeping read latency stable as base data grows.

---

## Project Structure

```
milcon_geospatial_hub/
├── app/
│   ├── analytics/
│   │   ├── queries.py        # All SQL queries (named constants, documented)
│   │   ├── scoring.py        # Scoring pipeline with audit trail
│   │   └── optimizer.py      # Budget-constrained selection with trace
│   ├── data/
│   │   └── seed.py           # Synthetic data generator (deterministic)
│   ├── db/
│   │   ├── engine.py         # SQLAlchemy engine/session
│   │   ├── models.py         # ORM models with PostGIS geometry
│   │   └── migrations/       # Alembic migrations (001 schema, 002 MVs)
│   ├── maps/
│   │   └── renderer.py       # Folium (interactive) + matplotlib (static)
│   ├── reports/
│   │   └── builder.py        # Markdown + charts + audit_metadata.json
│   ├── ui/
│   │   └── dashboard.py      # Streamlit (map, table, compare, explain)
│   ├── config.py             # Scenarios, weights, analysis config
│   └── cli.py                # Click CLI (seed, analyze, report, scenarios)
├── sql/
│   └── views_and_functions.sql  # Reference SQL for auditor cross-check
├── tests/
│   ├── conftest.py           # DB fixtures, migration, seeding
│   ├── test_seed.py          # Reproducibility, data integrity
│   ├── test_scoring.py       # Determinism, normalization, audit trail
│   ├── test_optimizer.py     # Budget constraint, trace, metadata
│   └── test_spatial.py       # PostGIS ops, SRID, geometry types
├── runs/                     # Analysis output directories
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
└── README.md
```

---

## Limitations & Next Steps

### Current Limitations
- Synthetic data only — no real ISR ingestion pipeline.
- Greedy optimizer is approximate, not provably optimal.
- `constraint_buffer_m` scenario parameter is defined but not yet wired into the materialized view refresh (constraints use direct `ST_Intersects`).
- No uncertainty/confidence intervals on scores.
- Single-year analysis; no multi-year planning horizon.

### Potential Enhancements
- **Real ISR data ingestion** from CSV/shapefile/API sources.
- **Integer programming** optimizer via `scipy.optimize.milp` or OR-Tools.
- **Multi-year planning** with discount rates and phased construction.
- **Uncertainty modeling** using Monte Carlo simulation on cost/benefit estimates.
- **User-defined scenarios** via the dashboard (custom weight sliders).
- **Authentication and role-based access** for multi-user deployments.
- **CI/CD pipeline** with automated migration testing.

---

## License

This project is for demonstration and educational purposes.
