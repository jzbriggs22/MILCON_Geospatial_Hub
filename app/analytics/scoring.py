"""Project scoring engine.

Scoring pipeline
================
1. Execute RAW_FACTORS_QUERY against PostGIS to get un-normalized factors.
   Hazard and constraint proximity buffers are bind parameters (meters),
   so scenario buffers genuinely change the spatial inputs.
2. Normalize each factor to [0, 1]:

   - readiness_gap_norm      = readiness_gap / 100
       (domain-anchored: readiness_score is defined on [0, 100])
   - hazard_exposure_norm    = clip(max_hazard_severity
                                    * hazard_severity_multiplier / 10, 0, 1)
       (domain-anchored: severity is defined on [0, 10]; the scenario
        multiplier therefore genuinely shifts the normalized value)
   - roi_norm                = min-max over the project cohort
       (ROI has no natural upper bound; NOTE this makes roi_norm — and any
        score built on it — comparable only within a single run's cohort)
   - constraint_penalty_norm = is_constrained * min(constraint_count/5, 1)

3. Compute the multi-objective score using scenario weights:

       score = w_readiness  * readiness_gap_norm
             + w_roi        * roi_norm
             - w_risk       * hazard_exposure_norm
             - w_constraint * constraint_penalty_norm

Auditability
============
- The exact SQL is analytics.queries.RAW_FACTORS_QUERY; the bind parameters
  actually passed (including both buffers) are recorded in the result.
- Scenario weights come from config.SCENARIOS[scenario_name].
- Normalization bounds per factor are returned alongside results.
- Every row keeps its raw factor values so the score can be recomputed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import (
    BUDGET_QUERY,
    MAX_PROXIMITY_RADIUS_M,
    RAW_FACTORS_QUERY,
)
from app.config import AnalysisConfig, ScenarioWeights

# Severity is defined on [0, 10] (see hazards.severity CHECK constraint).
SEVERITY_DOMAIN_MAX = 10.0
# Constraint counts at or above this saturate the penalty at 1.0.
CONSTRAINT_COUNT_SATURATION = 5.0


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
        config:  Analysis configuration (scenario, year, buffers).

    Returns:
        ScoringResult with everything needed for audit.

    Raises:
        ValueError: if a buffer exceeds the materialized proximity radius.
    """
    weights: ScenarioWeights = config.weights

    hazard_buffer_m = config.hazard_buffer_m
    constraint_buffer_m = weights.constraint_buffer_m
    for name, value in (("hazard_buffer_m", hazard_buffer_m),
                        ("constraint_buffer_m", constraint_buffer_m)):
        if value > MAX_PROXIMITY_RADIUS_M:
            raise ValueError(
                f"{name}={value} exceeds materialized proximity radius "
                f"{MAX_PROXIMITY_RADIUS_M} m; widen the views in migration 002 first"
            )

    # -- Step 1: fetch raw factors from PostGIS -----------------------------
    params = {
        "year": config.year,
        "hazard_buffer_m": hazard_buffer_m,
        "constraint_buffer_m": constraint_buffer_m,
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

    # -- Step 2: normalization ----------------------------------------------
    bounds: dict[str, dict[str, float]] = {}

    # Domain-anchored: readiness gap lives on [0, 100] by table constraint.
    df["readiness_gap_norm"] = df["readiness_gap"] / 100.0
    bounds["readiness_gap"] = {"min": 0.0, "max": 100.0}

    # Domain-anchored: severity lives on [0, 10]; the scenario multiplier
    # scales exposure within (and up to saturation of) that domain.
    df["hazard_exposure"] = (
        df["max_hazard_severity"] * weights.hazard_severity_multiplier
    )
    df["hazard_exposure_norm"] = (
        df["hazard_exposure"] / SEVERITY_DOMAIN_MAX
    ).clip(0.0, 1.0)
    bounds["hazard_exposure"] = {"min": 0.0, "max": SEVERITY_DOMAIN_MAX}

    # Cohort-relative: ROI has no natural upper bound.
    bounds["roi"] = {"min": float(df["roi"].min()), "max": float(df["roi"].max())}
    df["roi_norm"] = _minmax(df["roi"])

    # Domain-anchored: penalty saturates at CONSTRAINT_COUNT_SATURATION zones.
    df["constraint_penalty_norm"] = (
        df["is_constrained"].astype(float)
        * df["constraint_count"].clip(upper=CONSTRAINT_COUNT_SATURATION)
        / CONSTRAINT_COUNT_SATURATION
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
