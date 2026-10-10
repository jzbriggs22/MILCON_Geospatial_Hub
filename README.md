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
3. Seed the database with ~2000 rows of synthetic data (seed=42; seeding is
   idempotent, so restarts are safe)
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

# Seed database (idempotent — clears and re-creates seeded data)
python -m app.cli seed --rows 2000 --seed 42

# Run analysis
python -m app.cli analyze --scenario baseline --year 2026

# View the latest report (or pass a run ID: python -m app.cli report 20260101_120000)
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
| `python -m app.cli seed --rows 2000 --seed 42` | Seed database (idempotent, deterministic incl. primary keys) |
| `python -m app.cli analyze --scenario baseline --year 2026` | Refresh views, score, optimize, generate report |
| `python -m app.cli report --last` | Display the most recent report (default behavior) |
| `python -m app.cli report <RUN_ID>` | Display a specific run's report |
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

All geometry columns use SRID 4326 (WGS 84), each with exactly one GIST index.

### Materialized Views

| View | Purpose |
|------|---------|
| `project_hazard_proximity` | Pairwise project↔hazard distances in **meters** (geography cast — true isotropic distances), materialized for all pairs within 10 km |
| `project_constraint_proximity` | Pairwise project↔constraint distances, same design |

Scenario-specific buffer distances are applied **at query time** as bind
parameters (`distance_m <= :buffer_m`), so one materialization serves every
scenario. A pair at distance 0 intersects, so a 0 m constraint buffer
reproduces plain-intersection semantics.

The views are refreshed by `app.db.maintenance.refresh_analytics_views()`,
which is called automatically by the seeder and at the start of every
analysis run — scoring never reads stale spatial data.

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

| Factor | Source | Computation | Direction |
|--------|--------|------------|-----------|
| Readiness Gap | `installations.readiness_score` | `100 - readiness_score` | Higher gap = more benefit from investment |
| ROI | `projects.benefit_estimate / cost_estimate` | Direct ratio | Higher ROI = better value |
| Hazard Exposure | `project_hazard_proximity` | Max severity within `hazard_buffer_m` meters × scenario `hazard_severity_multiplier` | Higher exposure = penalty |
| Constraint Penalty | `project_constraint_proximity` | Flagged when within `constraint_buffer_m` meters of a constraint; `min(count/5, 1)` | Constrained = penalty |

### Normalization

| Factor | Scheme |
|--------|--------|
| `readiness_gap_norm` | Domain-anchored: `gap / 100` (readiness is constrained to [0, 100]) |
| `hazard_exposure_norm` | Domain-anchored: `clip(severity × multiplier / 10, 0, 1)` (severity is constrained to [0, 10]) — the multiplier therefore **genuinely changes** normalized risk |
| `roi_norm` | Min-max over the run's project cohort (ROI has no natural upper bound) |
| `constraint_penalty_norm` | Domain-anchored: saturates at 5 constraint zones |

**Comparability note:** because ROI is normalized within a cohort, scores are
directly comparable only within a single run. The dashboard's comparison tab
warns when the two runs analyze different fiscal years.

### Traceability

Every score is reproducible by:
1. Running `RAW_FACTORS_QUERY` (app/analytics/queries.py) with the bind
   parameters recorded in `audit_metadata.json` — every recorded parameter
   is actually bound in the query; there are no decorative entries.
2. Applying the normalization formulas above with the recorded bounds.
3. Multiplying by the recorded scenario weights.

---

## Scenarios

| Scenario | Description | w_readiness | w_roi | w_risk | w_constraint | Special |
|----------|-------------|-------------|-------|--------|--------------|---------|
| `baseline` | Normal weights, full budget | 0.30 | 0.35 | 0.20 | 0.15 | — |
| `climate_stress` | Elevated hazard severity and risk weight | 0.20 | 0.25 | 0.40 | 0.15 | `hazard_severity_multiplier=1.5` |
| `readiness_surge` | Readiness top priority, budget at 70% | 0.50 | 0.20 | 0.15 | 0.15 | `budget_multiplier=0.70` |
| `constraint_heavy` | 500 m constraint proximity buffer, constraint weight up | 0.25 | 0.25 | 0.20 | 0.30 | `constraint_buffer_m=500` |

All scenario parameters are live: the multiplier scales normalized exposure,
the budget multiplier scales the capex limit, and the constraint buffer is a
bind parameter of the scoring query. Weight values are defined in
`app/config.py:SCENARIOS` and recorded in every report.

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
- `selection_trace`: The **complete** step-by-step log of every selection
  decision (project_id, cost, score, cumulative_cost), persisted in full to
  `audit_metadata.json`

### Limitations

- Not provably optimal (0-1 knapsack is NP-hard).
- Typically within 90-95% of optimal for typical MILCON cost distributions.
- A future enhancement could use `scipy.optimize.milp` or Google OR-Tools.

---

## Auditability

Every analytic output is traceable to specific SQL queries, input tables,
configuration values, and scenario weights. There is no hidden logic, no
opaque heuristics, and no recorded parameter that was not actually applied.

| Artifact | Contents |
|----------|----------|
| `runs/<ts>/audit_metadata.json` | Full config, weights, SQL query text + bind params, normalization bounds, complete optimizer trace |
| `runs/<ts>/report.md` | Scenario config table, SQL reference, normalization bounds, top-10 projects |
| Dashboard Explainability tab | Per-project factor breakdown: raw value, normalized value, weight, signed contribution, formula |
| `app/analytics/queries.py` | All SQL queries as named constants with documentation |
| `sql/views_and_functions.sql` | **Generated** reference copy of all SQL (`python -m app.db.generate_sql_reference`); `tests/test_sql_reference.py` fails if it drifts from the executable sources |

---

## Adding New Hazards / Constraints

Insert directly into PostgreSQL:

```sql
-- New flood hazard
INSERT INTO hazards (type, severity, geometry)
VALUES ('flood', 7.5, ST_GeomFromText('POLYGON((-80 32, -80 33, -79 33, -79 32, -80 32))', 4326));

-- New no-build constraint
INSERT INTO constraints (type, notes, geometry)
VALUES ('no-build', 'Wetland protection area',
        ST_GeomFromText('POLYGON((-81 33, -81 33.1, -80.9 33.1, -80.9 33, -81 33))', 4326));
```

No manual view refresh is required: every analysis run (CLI `analyze` and the
dashboard's Run buttons) refreshes the proximity views before scoring via
`app.db.maintenance.refresh_analytics_views()`. To refresh explicitly (e.g.
from a script), call that function or run:

```sql
REFRESH MATERIALIZED VIEW project_hazard_proximity;
REFRESH MATERIALIZED VIEW project_constraint_proximity;
```

Or extend `app/data/seed.py` and re-run `python -m app.cli seed` (safe to
re-run: the seeder truncates and rebuilds its tables deterministically).

---

## Performance Considerations

- **GIST indexes** on all geometry columns (exactly one per column).
- **Proximity materialized views** pre-compute the expensive geography
  distance joins once; scenario buffers then filter on the indexed
  `(project_id, distance_m)` columns at query time — changing a buffer never
  re-runs a spatial join.
- Views are refreshed per analysis run; the refresh cost is one spatial join
  per view, bounded by the 10 km materialization radius.
- The dashboard caches the engine and read-mostly query results
  (`st.cache_data`, 5-minute TTL) and opens a short-lived session per
  operation, so no connection is ever held idle-in-transaction.
- For datasets >100k projects, consider partitioning `projects` by year and
  raising/lowering `MAX_PROXIMITY_RADIUS_M` (app/db/migrations 002) to trade
  materialization size against maximum buffer flexibility.

---

## Project Structure

```
milcon_geospatial_hub/
├── app/
│   ├── analytics/
│   │   ├── queries.py        # All SQL queries (named constants, documented)
│   │   ├── scoring.py        # Scoring pipeline with audit trail
│   │   ├── optimizer.py      # Budget-constrained selection with trace
│   │   └── run.py            # run_analysis(): the single pipeline entry point
│   ├── data/
│   │   └── seed.py           # Synthetic data generator (deterministic, idempotent)
│   ├── db/
│   │   ├── engine.py         # SQLAlchemy engines (cached per URL)
│   │   ├── models.py         # ORM models with PostGIS geometry
│   │   ├── maintenance.py    # refresh_analytics_views()
│   │   ├── generate_sql_reference.py  # regenerates sql/views_and_functions.sql
│   │   └── migrations/       # Alembic migrations (001 schema, 002 proximity MVs)
│   ├── maps/
│   │   └── renderer.py       # Folium (interactive) + matplotlib (static)
│   ├── reports/
│   │   └── builder.py        # Markdown + charts + audit_metadata.json
│   ├── ui/
│   │   └── dashboard.py      # Streamlit (map, table, compare, explain)
│   ├── config.py             # Scenarios, weights, analysis config
│   └── cli.py                # Click CLI (seed, analyze, report, scenarios)
├── sql/
│   └── views_and_functions.sql  # GENERATED auditor reference (do not edit)
├── tests/
│   ├── conftest.py           # Migrations + deterministic reseed
│   ├── test_seed.py          # Idempotency, reproducibility, integrity
│   ├── test_scoring.py       # Determinism, normalization, multiplier/buffer effects
│   ├── test_optimizer.py     # Budget constraint, trace, metadata
│   ├── test_spatial.py       # Geography distances, SRID, single-index invariant
│   └── test_sql_reference.py # SQL reference drift guard
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
- ROI normalization is cohort-relative, so scores are comparable only within
  a single run (the UI warns on cross-year comparisons).
- Buffers are capped at the 10 km materialization radius (a `ValueError` is
  raised — never a silent truncation — if a larger buffer is requested).
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
