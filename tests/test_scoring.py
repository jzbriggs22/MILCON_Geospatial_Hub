"""Tests for the scoring engine.

Verifies:
- Scoring determinism
- Normalization correctness
- Weight changes affect rankings
"""

from __future__ import annotations

import pytest
from app.config import AnalysisConfig
from app.analytics.scoring import score_projects, _minmax
import pandas as pd
import numpy as np


def test_scoring_determinism(db_session):
    """Same config → same scores, twice."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    r1 = score_projects(db_session, cfg)
    r2 = score_projects(db_session, cfg)

    pd.testing.assert_frame_equal(
        r1.projects_df.sort_values("project_id").reset_index(drop=True),
        r2.projects_df.sort_values("project_id").reset_index(drop=True),
    )


def test_scoring_returns_columns(db_session):
    """Scored DataFrame must include all expected columns."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    result = score_projects(db_session, cfg)
    expected = {
        "project_id", "installation_id", "category",
        "cost_estimate", "benefit_estimate",
        "readiness_score", "readiness_gap", "roi",
        "hazard_exposure", "hazard_count",
        "is_constrained", "constraint_count",
        "readiness_gap_norm", "roi_norm", "hazard_exposure_norm",
        "constraint_penalty_norm", "score",
    }
    assert expected.issubset(set(result.projects_df.columns))


def test_normalization_bounds(db_session):
    """Normalized columns should be in [0, 1]."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    result = score_projects(db_session, cfg)
    df = result.projects_df

    for col in ["readiness_gap_norm", "roi_norm", "hazard_exposure_norm"]:
        assert df[col].min() >= -1e-9, f"{col} below 0"
        assert df[col].max() <= 1.0 + 1e-9, f"{col} above 1"


def test_scenario_changes_rankings(db_session):
    """Different scenarios should produce different project rankings."""
    cfg_base = AnalysisConfig(scenario="baseline", year=2026)
    cfg_climate = AnalysisConfig(scenario="climate_stress", year=2026)

    r_base = score_projects(db_session, cfg_base)
    r_climate = score_projects(db_session, cfg_climate)

    # The top project should differ (or scores should differ)
    base_scores = r_base.ranked()["score"].values
    climate_scores = r_climate.ranked()["score"].values

    # At least one score should differ
    assert not np.allclose(base_scores, climate_scores), \
        "Baseline and climate_stress produced identical scores"


def test_minmax_constant_series():
    """A constant series should normalize to 0.5."""
    s = pd.Series([5.0, 5.0, 5.0])
    normed = _minmax(s)
    assert all(normed == 0.5)


def test_minmax_normal_series():
    """Standard min-max normalization check."""
    s = pd.Series([0.0, 5.0, 10.0])
    normed = _minmax(s)
    assert normed.iloc[0] == pytest.approx(0.0)
    assert normed.iloc[1] == pytest.approx(0.5)
    assert normed.iloc[2] == pytest.approx(1.0)


def test_audit_trail_present(db_session):
    """ScoringResult must contain all audit fields."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    result = score_projects(db_session, cfg)

    assert result.sql_query is not None
    assert "project_risk_exposure" in result.sql_query
    assert result.sql_params["year"] == 2026
    assert "w_readiness" in result.weights
    assert len(result.normalization_bounds) > 0
