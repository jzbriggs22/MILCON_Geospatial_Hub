"""Tests for the budget optimizer.

Verifies:
- Budget constraint is respected
- Greedy selection trace is consistent
- No-budget case handles correctly
"""

from __future__ import annotations

import pytest
from app.config import AnalysisConfig
from app.analytics.scoring import score_projects
from app.analytics.optimizer import optimize_budget


def test_budget_respected(db_session):
    """Total selected cost must not exceed capex_limit."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    scoring = score_projects(db_session, cfg)
    opt = optimize_budget(scoring)

    if opt.capex_limit > 0:
        assert opt.total_cost <= opt.capex_limit, \
            f"Total cost {opt.total_cost} exceeds budget {opt.capex_limit}"


def test_selection_trace_cumulative(db_session):
    """The selection trace must have monotonically increasing cumulative cost."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    scoring = score_projects(db_session, cfg)
    opt = optimize_budget(scoring)

    prev = 0.0
    for entry in opt.selection_trace:
        assert entry["cumulative_cost"] >= prev
        prev = entry["cumulative_cost"]


def test_all_selected_have_positive_score(db_session):
    """Every selected project must have score > 0."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    scoring = score_projects(db_session, cfg)
    opt = optimize_budget(scoring)

    if not opt.selected_df.empty:
        assert opt.selected_df["score"].min() > 0


def test_readiness_surge_budget_lower(db_session):
    """readiness_surge scenario has budget_multiplier=0.70, so capex < baseline."""
    cfg_base = AnalysisConfig(scenario="baseline", year=2026)
    cfg_surge = AnalysisConfig(scenario="readiness_surge", year=2026)

    s_base = score_projects(db_session, cfg_base)
    s_surge = score_projects(db_session, cfg_surge)

    o_base = optimize_budget(s_base)
    o_surge = optimize_budget(s_surge)

    if o_base.capex_limit > 0 and o_surge.capex_limit > 0:
        assert o_surge.capex_limit < o_base.capex_limit


def test_optimizer_metadata(db_session):
    """OptimizationResult must include algorithm and limitations."""
    cfg = AnalysisConfig(scenario="baseline", year=2026)
    scoring = score_projects(db_session, cfg)
    opt = optimize_budget(scoring)

    assert opt.algorithm is not None
    assert len(opt.algorithm) > 0
    assert opt.limitations is not None
    assert "greedy" in opt.limitations.lower() or "no-budget" in opt.algorithm.lower()
