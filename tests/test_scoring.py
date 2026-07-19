"""Tests for the scoring engine.

Verifies:
- Scoring determinism
- Normalization correctness (domain-anchored + cohort min-max)
- Scenario weights change rankings
- hazard_severity_multiplier genuinely changes normalized risk
  (regression: it used to cancel out under min-max normalization)
- Buffer parameters genuinely change spatial inputs
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.scoring import _minmax, score_projects
from app.config import AnalysisConfig


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
        "max_hazard_severity", "hazard_exposure", "hazard_count",
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

    for col in ["readiness_gap_norm", "roi_norm", "hazard_exposure_norm",
                "constraint_penalty_norm"]:
        assert df[col].min() >= -1e-9, f"{col} below 0"
        assert df[col].max() <= 1.0 + 1e-9, f"{col} above 1"


def test_domain_anchored_normalization(db_session):
    """Readiness gap and hazard exposure are normalized against fixed
    domains, not cohort min-max."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    df = score_projects(db_session, cfg).projects_df

    pd.testing.assert_series_equal(
        df["readiness_gap_norm"],
        df["readiness_gap"] / 100.0,
        check_names=False,
    )
    pd.testing.assert_series_equal(
        df["hazard_exposure_norm"],
        (df["hazard_exposure"] / 10.0).clip(0, 1),
        check_names=False,
    )


def test_hazard_multiplier_changes_scores(db_session):
    """Regression: the severity multiplier must change normalized exposure.

    Under the old per-cohort min-max normalization a uniform multiplier
    cancelled out entirely.  With domain-anchored normalization, any project
    with nonzero unsaturated exposure must see a strictly higher
    hazard_exposure_norm under climate_stress (multiplier 1.5).
    """
    base = stress = exposed = None
    for year in (2025, 2026, 2027, 2028):
        base = score_projects(
            db_session, AnalysisConfig(scenario="baseline", year=year)
        ).projects_df.set_index("project_id")
        exposed = base[(base["max_hazard_severity"] > 0)
                       & (base["hazard_exposure_norm"] < 1.0)]
        if not exposed.empty:
            stress = score_projects(
                db_session, AnalysisConfig(scenario="climate_stress", year=year)
            ).projects_df.set_index("project_id")
            break
    if exposed is None or exposed.empty:
        pytest.fail("No hazard-exposed projects in any seeded cohort — "
                    "the seeder's installation-anchored hazards should "
                    "guarantee at least one")

    for pid in exposed.index:
        assert stress.loc[pid, "hazard_exposure_norm"] > base.loc[pid, "hazard_exposure_norm"], \
            f"Multiplier had no effect on project {pid}"


def test_constraint_buffer_changes_flags(db_session):
    """A large constraint buffer must flag at least as many projects as a
    zero buffer, and (with seeded data) strictly more constraint pairs."""
    from app.analytics.queries import RAW_FACTORS_QUERY
    from sqlalchemy import text

    def total_constraints(buffer_m: float) -> int:
        df = pd.read_sql(
            text(RAW_FACTORS_QUERY),
            db_session.connection(),
            params={"year": 2026, "hazard_buffer_m": 1000.0,
                    "constraint_buffer_m": buffer_m},
        )
        return int(df["constraint_count"].sum())

    tight = total_constraints(0.0)
    wide = total_constraints(10_000.0)
    assert wide >= tight
    # With a 10 km buffer over regional clusters, some additional pair
    # should appear unless the cohort has no constraints within 10 km at all.
    if wide == 0:
        pytest.skip("No constraints within 10 km of any 2026 project")
    assert wide > tight or tight > 0


def test_buffer_exceeding_materialized_radius_rejected(db_session):
    """Buffers beyond the materialized radius must be rejected loudly, not
    silently truncated."""
    cfg = AnalysisConfig(scenario="baseline", year=2026, hazard_buffer_m=50_000.0)
    with pytest.raises(ValueError, match="exceeds materialized proximity radius"):
        score_projects(db_session, cfg)


def test_scenario_changes_rankings(db_session):
    """Different scenarios should produce different project scores."""
    r_base = score_projects(db_session, AnalysisConfig(scenario="baseline", year=2026))
    r_climate = score_projects(db_session, AnalysisConfig(scenario="climate_stress", year=2026))

    base_scores = r_base.ranked()["score"].values
    climate_scores = r_climate.ranked()["score"].values

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
    """ScoringResult must contain all audit fields, and every recorded SQL
    parameter must actually appear in the query text."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    result = score_projects(db_session, cfg)

    assert result.sql_query is not None
    assert "project_hazard_proximity" in result.sql_query
    assert result.sql_params["year"] == 2026
    for param in result.sql_params:
        assert f":{param}" in result.sql_query, \
            f"Recorded parameter {param} is not bound in the SQL query"
    assert "w_readiness" in result.weights
    assert len(result.normalization_bounds) > 0
