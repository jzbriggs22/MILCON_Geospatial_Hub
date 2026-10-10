"""CLI entry point for MILCON Geospatial Hub.

Commands:
    seed      — populate database with synthetic data (idempotent)
    analyze   — run scoring + optimization for a scenario/year
    report    — print the latest report, or a specific run by ID
    scenarios — list available scenarios

Usage:
    python -m app.cli seed --rows 2000 --seed 42
    python -m app.cli analyze --scenario baseline --year 2026
    python -m app.cli report            # latest run
    python -m app.cli report 20260220_120000   # specific run
    python -m app.cli scenarios
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from app.config import SCENARIOS, get_database_url


@click.group()
def cli() -> None:
    """MILCON Geospatial Hub — infrastructure planning CLI."""
    pass


@cli.command()
@click.option("--rows", default=2000, help="Approximate total row count across all tables.")
@click.option("--seed", "rng_seed", default=42, help="RNG seed for reproducibility.")
def seed(rows: int, rng_seed: int) -> None:
    """Seed the database with synthetic MILCON data (clears prior seed data)."""
    from app.db.engine import get_session, ensure_postgis
    from app.data.seed import seed_database

    click.echo(f"Connecting to {get_database_url()} ...")
    session = get_session()
    ensure_postgis(session)

    click.echo(f"Seeding database (rows≈{rows}, seed={rng_seed}) ...")
    counts = seed_database(session, total_rows=rows, rng_seed=rng_seed)
    session.close()

    click.echo("Seeded:")
    for entity, count in counts.items():
        click.echo(f"  {entity}: {count}")
    click.echo("Done.")


@cli.command()
@click.option("--scenario", default="baseline", type=click.Choice(list(SCENARIOS.keys())))
@click.option("--year", default=2026, type=int)
@click.option("--output-dir", default=None, type=click.Path(), help="Custom output directory.")
def analyze(scenario: str, year: int, output_dir: str | None) -> None:
    """Run scoring + budget optimization and generate a report."""
    from app.db.engine import get_session
    from app.analytics.run import run_analysis
    from app.reports.builder import generate_report

    click.echo(f"Running analysis: scenario={scenario}, year={year}")
    click.echo(f"Weights: {json.dumps(SCENARIOS[scenario].as_dict(), indent=2)}")

    session = get_session()
    try:
        click.echo("Refreshing views and scoring projects ...")
        scoring, optimization = run_analysis(session, scenario, year)

        if scoring.projects_df.empty:
            click.echo("No projects found for the given year. Exiting.")
            sys.exit(1)

        click.echo(f"  {len(scoring.projects_df)} projects scored.")
        click.echo(f"  {len(optimization.selected_df)} projects selected")
        click.echo(f"  Total cost: ${optimization.total_cost:,.0f}")
        click.echo(f"  Budget: ${optimization.capex_limit:,.0f}")

        out = Path(output_dir) if output_dir else None
        click.echo("Generating report ...")
        report_dir = generate_report(session, scoring, optimization, output_dir=out)
    finally:
        session.close()

    click.echo(f"Report saved to: {report_dir}")
    click.echo(f"  - {report_dir / 'report.md'}")
    click.echo(f"  - {report_dir / 'audit_metadata.json'}")
    click.echo("Done.")


@cli.command()
@click.option("--last", "use_last", is_flag=True,
              help="Show the latest run (this is also the default).")
@click.argument("run_id", required=False)
def report(run_id: str | None, use_last: bool) -> None:
    """Print a report: the latest run by default, or RUN_ID if given."""
    if use_last and run_id:
        click.echo("Pass either --last or a RUN_ID, not both.")
        sys.exit(1)

    runs_dir = Path("runs")
    if not runs_dir.exists():
        click.echo("No runs directory found. Run 'analyze' first.")
        sys.exit(1)

    run_dirs = sorted((d for d in runs_dir.iterdir() if d.is_dir()), reverse=True)
    if not run_dirs:
        click.echo("No analysis runs found.")
        sys.exit(1)

    if run_id:
        target = runs_dir / run_id
        if not target.is_dir():
            available = ", ".join(d.name for d in run_dirs[:10])
            click.echo(f"Run '{run_id}' not found. Recent runs: {available}")
            sys.exit(1)
    else:
        target = run_dirs[0]

    report_path = target / "report.md"
    if report_path.exists():
        click.echo(report_path.read_text())
    else:
        click.echo(f"Report not found at {report_path}")
        sys.exit(1)


@cli.command("scenarios")
def list_scenarios() -> None:
    """List available analysis scenarios with their weights."""
    for name, sw in SCENARIOS.items():
        click.echo(f"\n{'=' * 50}")
        click.echo(f"Scenario: {name}")
        click.echo(f"Description: {sw.description}")
        click.echo(f"  w_readiness:  {sw.w_readiness}")
        click.echo(f"  w_roi:        {sw.w_roi}")
        click.echo(f"  w_risk:       {sw.w_risk}")
        click.echo(f"  w_constraint: {sw.w_constraint}")
        click.echo(f"  hazard_severity_multiplier: {sw.hazard_severity_multiplier}")
        click.echo(f"  budget_multiplier: {sw.budget_multiplier}")
        click.echo(f"  constraint_buffer_m: {sw.constraint_buffer_m}")


if __name__ == "__main__":
    cli()
