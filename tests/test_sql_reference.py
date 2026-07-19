"""Guard against drift between executable SQL and the auditor reference file.

sql/views_and_functions.sql is generated from the migration module and
app/analytics/queries.py.  If either changes without regenerating the
reference (python -m app.db.generate_sql_reference), this test fails.
"""

from __future__ import annotations

from pathlib import Path

from app.db.generate_sql_reference import OUTPUT_PATH, render_reference


def test_sql_reference_up_to_date():
    assert OUTPUT_PATH.exists(), (
        "sql/views_and_functions.sql missing — run "
        "python -m app.db.generate_sql_reference"
    )
    assert OUTPUT_PATH.read_text() == render_reference(), (
        "sql/views_and_functions.sql is stale — run "
        "python -m app.db.generate_sql_reference"
    )
