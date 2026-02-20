"""Project scoring engine.

Scoring pipeline
================
1. Execute RAW_FACTORS_QUERY against PostGIS to get un-normalized factors.
2. Apply min-max normalization so each factor ∈ [0, 1].
3. Compute multi-objective score using scenario weights:

       score = w_readiness * readiness_gap_norm
             + w_roi       * roi_norm
             - w_risk      * hazard_exposure_norm
             - w_constraint * constraint_penalty_norm

4. Return a DataFrame with all raw and normalized values plus the score.

Auditability
============
- The exact SQL query is stored in analytics.queries.RAW_FACTORS_QUERY.
- Scenario weights come from config.SCENARIOS[scenario_name].
- Normalization bounds (min/max per column) are returned alongside results.
- Every row includes the raw factor values so the score can be recomputed
  by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import RAW_FACTORS_QUERY, BUDGET_QUERY
from app.config import AnalysisConfig, ScenarioWeights


@dataclass
class ScoringResult:
    """Container for a single scoring run.

    Every field needed to reproduce the result is included.
    """
    config: AnalysisConfig
    weights: dict[str, Any]
    sql_query: str
    sql_params: dict[str, Any]
    normalization_bounds: dict[str, dict[str, float]]
    projects_df: pd.DataFrame  # full dataframe with raw + norm + score
    capex_limit: float | None = None

    def ranked(self) -> pd.DataFrame:
        return self.projects_df.sort_values("score", ascending=False).reset_index(drop=True)


def _minmax(series: pd.Series) -> pd.Series:
    """Min-max normalize a Series to [0, 1].  Constant series → 0.5."""
    lo, hi = series.min(), series.max()
    if hi - lo < 1e-12:
        return pd.Series(0.5, index=series.index)
    return (series - lo) / (hi - lo)


def score_projects(session: Session, config: AnalysisConfig) -> ScoringResult:
    """Run the full scoring pipeline.

    Args:
        session: Active SQLAlchemy session connected to PostGIS.
        config:  Analysis configuration (scenario, year, etc.).

    Returns:
        ScoringResult with everything needed for audit.
    """
    weights: ScenarioWeights = config.weights

    # -- Step 1: fetch raw factors from PostGIS -----------------------------
    params = {
        "year": config.year,
        "hazard_severity_mult": weights.hazard_severity_multiplier,
    }
    df = pd.read_sql(text(RAW_FACTORS_QUERY), session.connection(), params=params)

    if df.empty:
        return ScoringResult(
            config=config,
            weights=weights.as_dict(),
            sql_query=RAW_FACTORS_QUERY,
            sql_params=params,
            normalization_bounds={},
            projects_df=df,
        )

    # -- Step 2: min-max normalization --------------------------------------
    norm_cols = {
        "readiness_gap": "readiness_gap_norm",
        "roi": "roi_norm",
        "hazard_exposure": "hazard_exposure_norm",
    }
    bounds: dict[str, dict[str, float]] = {}
    for raw_col, norm_col in norm_cols.items():
        bounds[raw_col] = {"min": float(df[raw_col].min()), "max": float(df[raw_col].max())}
        df[norm_col] = _minmax(df[raw_col])

    # Constraint penalty: binary (0 or 1), weighted by count
    df["constraint_penalty_norm"] = (
        df["is_constrained"].astype(float)
        * df["constraint_count"].clip(upper=5) / 5.0
    )
    bounds["constraint_penalty"] = {"min": 0.0, "max": 1.0}

    # -- Step 3: weighted multi-objective score -----------------------------
    df["score"] = (
        weights.w_readiness  * df["readiness_gap_norm"]
        + weights.w_roi      * df["roi_norm"]
        - weights.w_risk     * df["hazard_exposure_norm"]
        - weights.w_constraint * df["constraint_penalty_norm"]
    )

    # -- Step 4: fetch budget -----------------------------------------------
    budget_row = session.execute(
        text(BUDGET_QUERY), {"year": config.year}
    ).fetchone()
    capex = None
    if budget_row:
        capex = float(budget_row.capex_limit) * weights.budget_multiplier

    return ScoringResult(
        config=config,
        weights=weights.as_dict(),
        sql_query=RAW_FACTORS_QUERY,
        sql_params=params,
        normalization_bounds=bounds,
        projects_df=df,
        capex_limit=capex,
    )
