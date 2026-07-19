"""Single entry point for running an analysis.

Every caller (CLI, dashboard, tests) goes through run_analysis() so the
pipeline — refresh materialized views, score, optimize — cannot drift
between call sites.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.analytics.optimizer import OptimizationResult, optimize_budget
from app.analytics.scoring import ScoringResult, score_projects
from app.config import AnalysisConfig
from app.db.maintenance import refresh_analytics_views


def run_analysis(
    session: Session,
    scenario: str,
    year: int,
    *,
    refresh_views: bool = True,
) -> tuple[ScoringResult, OptimizationResult]:
    """Score and budget-optimize all projects for a scenario/year.

    Args:
        session: Active SQLAlchemy session connected to PostGIS.
        scenario: Name of a scenario in config.SCENARIOS.
        year: Fiscal year to analyze.
        refresh_views: Refresh the proximity materialized views first so
            scoring never reads stale spatial data.  Callers may disable
            this only when they have just refreshed (e.g. batch runs).
    """
    if refresh_views:
        refresh_analytics_views(session)
    config = AnalysisConfig(scenario=scenario, year=year)
    scoring = score_projects(session, config)
    optimization = optimize_budget(scoring)
    return scoring, optimization
