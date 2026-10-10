"""Report builder — generates markdown reports with charts and maps.

Each report run produces a directory under runs/<timestamp>/ containing:
- report.md           — main narrative with embedded chart references
- score_distribution.png
- budget_spend.png
- risk_exposure.png
- project_map.png
- audit_metadata.json — full configuration, weights, SQL, normalization bounds

Auditability
============
audit_metadata.json contains everything needed to reproduce the analysis:
- AnalysisConfig (scenario, year, hazard buffer)
- ScenarioWeights (all weight values)
- The SQL query text and the exact bind parameters passed to it —
  every recorded parameter was actually applied; there are no
  decorative entries
- Normalization bounds per factor
- Budget optimizer algorithm, limitations, and the COMPLETE
  step-by-step selection trace
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy.orm import Session

from app.analytics.optimizer import OptimizationResult
from app.analytics.scoring import ScoringResult
from app.maps.renderer import attach_project_locations, export_static_map


def _save_score_distribution(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(df["score"], bins=30, color="steelblue", edgecolor="white", alpha=0.85)
    ax.axvline(df["score"].median(), color="red", linestyle="--",
               label=f"Median: {df['score'].median():.3f}")
    ax.set_xlabel("Multi-Objective Score")
    ax.set_ylabel("Number of Projects")
    ax.set_title("Score Distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _save_budget_spend(opt: OptimizationResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    cats = ["Budget Limit", "Total Selected Cost", "Remaining"]
    remaining = max(0, opt.capex_limit - opt.total_cost)
    vals = [opt.capex_limit, opt.total_cost, remaining]
    colors = ["#2196F3", "#4CAF50", "#BDBDBD"]
    ax.barh(cats, vals, color=colors, edgecolor="white")
    for i, v in enumerate(vals):
        ax.text(v + opt.capex_limit * 0.01, i, f"${v:,.0f}", va="center", fontsize=9)
    ax.set_xlabel("USD")
    ax.set_title("Budget Utilization")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _save_risk_exposure(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(df["hazard_exposure"], bins=20, color="coral", edgecolor="white", alpha=0.85)
    ax.set_xlabel("Hazard Exposure (severity × multiplier)")
    ax.set_ylabel("Number of Projects")
    ax.set_title("Risk Exposure Distribution")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def generate_report(
    session: Session,
    scoring: ScoringResult,
    optimization: OptimizationResult,
    output_dir: Path | None = None,
) -> Path:
    """Generate a complete analysis report.

    Returns the path to the report directory.
    """
    config = scoring.config
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_dir is None:
        output_dir = Path("runs") / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    df = scoring.projects_df
    ranked = scoring.ranked()
    sel = optimization.selected_df

    # --- Charts ---
    _save_score_distribution(df, output_dir / "score_distribution.png")
    _save_budget_spend(optimization, output_dir / "budget_spend.png")
    _save_risk_exposure(df, output_dir / "risk_exposure.png")

    # --- Static map ---
    sel_with_loc = attach_project_locations(session, sel, config.year)
    export_static_map(session, sel_with_loc, output_dir / "project_map.png", year=config.year)

    # --- Audit metadata ---
    audit = {
        "generated_at": ts,
        "config": {
            "scenario": config.scenario,
            "year": config.year,
            "hazard_buffer_m": config.hazard_buffer_m,
        },
        "weights": scoring.weights,
        "sql_query": scoring.sql_query,
        "sql_params": {k: str(v) for k, v in scoring.sql_params.items()},
        "normalization_bounds": scoring.normalization_bounds,
        "optimizer": {
            "algorithm": optimization.algorithm,
            "limitations": optimization.limitations,
            "capex_limit": optimization.capex_limit,
            "total_cost": optimization.total_cost,
            "total_score": optimization.total_score,
            "projects_selected": len(optimization.selected_df),
            "projects_rejected": len(optimization.rejected_df),
        },
        "selection_trace": optimization.selection_trace,
    }
    (output_dir / "audit_metadata.json").write_text(json.dumps(audit, indent=2))

    # --- Markdown report ---
    top10 = ranked.head(10)
    n_sel = len(sel)
    n_total = len(df)
    utilization = (
        optimization.total_cost / optimization.capex_limit * 100
        if optimization.capex_limit else 0
    )

    md_lines = [
        f"# MILCON Analysis Report — {config.scenario}",
        "",
        f"**Generated:** {ts}  ",
        f"**Scenario:** {config.scenario}  ",
        f"**Year:** FY{config.year}  ",
        "",
        "## Scenario Configuration",
        "",
        "All parameters below were applied to this run (buffers are bind",
        "parameters of the SQL query; the multiplier scales exposure against",
        "the fixed [0, 10] severity domain).",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| w_readiness | {scoring.weights['w_readiness']} |",
        f"| w_roi | {scoring.weights['w_roi']} |",
        f"| w_risk | {scoring.weights['w_risk']} |",
        f"| w_constraint | {scoring.weights['w_constraint']} |",
        f"| hazard_severity_multiplier | {scoring.weights['hazard_severity_multiplier']} |",
        f"| budget_multiplier | {scoring.weights['budget_multiplier']} |",
        f"| hazard_buffer_m | {config.hazard_buffer_m} |",
        f"| constraint_buffer_m | {scoring.weights['constraint_buffer_m']} |",
        "",
        "## Summary",
        "",
        f"- **Projects evaluated:** {n_total}",
        f"- **Projects selected:** {n_sel}",
        f"- **Budget (capex limit):** ${optimization.capex_limit:,.0f}",
        f"- **Total selected cost:** ${optimization.total_cost:,.0f}",
        f"- **Budget utilization:** {utilization:.1f}%",
        f"- **Total score of selected:** {optimization.total_score:.3f}",
        f"- **Median score (all):** {df['score'].median():.3f}",
        f"- **Optimizer:** {optimization.algorithm}",
        "",
        "## Score Distribution",
        "",
        "![Score Distribution](score_distribution.png)",
        "",
        "## Budget Utilization",
        "",
        "![Budget Spend](budget_spend.png)",
        "",
        "## Risk Exposure",
        "",
        "![Risk Exposure](risk_exposure.png)",
        "",
        "## Project Map",
        "",
        "![Project Map](project_map.png)",
        "",
        "## Top 10 Projects by Score",
        "",
    ]

    if not top10.empty:
        md_lines.append("| Rank | Project ID | Category | Cost | Benefit | ROI | Score |")
        md_lines.append("|------|-----------|----------|------|---------|-----|-------|")
        for rank, (_, row) in enumerate(top10.iterrows(), 1):
            md_lines.append(
                f"| {rank} | {int(row['project_id'])} | {row['category']} "
                f"| ${row['cost_estimate']:,.0f} | ${row['benefit_estimate']:,.0f} "
                f"| {row['roi']:.2f} | {row['score']:.4f} |"
            )

    md_lines += [
        "",
        "## Optimizer Notes",
        "",
        f"**Algorithm:** {optimization.algorithm}  ",
        f"**Limitations:** {optimization.limitations}",
        "",
        "## SQL Query Reference",
        "",
        "The raw factor query executed against PostGIS:",
        "",
        "```sql",
        scoring.sql_query.strip(),
        "```",
        "",
        f"**Parameters:** `{scoring.sql_params}`",
        "",
        "## Normalization Bounds",
        "",
        "Readiness gap, hazard exposure, and constraint penalty are anchored",
        "to fixed domains; ROI is min-max normalized within this run's cohort",
        "(so ROI-derived scores are comparable only within this run).",
        "",
        "| Factor | Min | Max |",
        "|--------|-----|-----|",
    ]
    for factor, bnd in scoring.normalization_bounds.items():
        md_lines.append(f"| {factor} | {bnd['min']:.4f} | {bnd['max']:.4f} |")

    md_lines += [
        "",
        "---",
        "*Full audit metadata: [audit_metadata.json](audit_metadata.json)*",
    ]

    (output_dir / "report.md").write_text("\n".join(md_lines))
    return output_dir
