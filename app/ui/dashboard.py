"""Streamlit dashboard for MILCON Geospatial Hub.

Required views:
1. Map view — installations + hazards + selected projects
2. Project ranking table — filters by region/category/year
3. Scenario comparison — side-by-side metrics + project diff
4. Explainability panel — factor contributions for a selected project

Session handling: the engine is cached for the process, but every database
operation opens a short-lived Session (context-managed).  A failed query
therefore never leaves a poisoned transaction behind, and no connection is
held idle-in-transaction between reruns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.analytics.queries import INSTALLATION_SUMMARY_QUERY
from app.analytics.run import run_analysis
from app.config import SCENARIOS
from app.db.engine import get_engine
from app.maps.renderer import attach_project_locations, build_folium_map
from streamlit_folium import st_folium

YEARS = [2025, 2026, 2027, 2028]

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="MILCON Geospatial Hub",
    page_icon="🏗️",
    layout="wide",
)

st.title("MILCON Geospatial Hub")
st.caption("Infrastructure planning decision-support system — synthetic demo data")


# ---------------------------------------------------------------------------
# DB access — cached engine, short-lived sessions
# ---------------------------------------------------------------------------
@st.cache_resource
def _engine():
    return get_engine()


@st.cache_data(ttl=300)
def load_installations() -> pd.DataFrame:
    with Session(_engine()) as session:
        return pd.read_sql(text(INSTALLATION_SUMMARY_QUERY), session.connection())


def _run(scenario: str, year: int):
    """Run a full analysis in its own session; returns (scoring, optimization)."""
    with Session(_engine()) as session:
        scoring, optimization = run_analysis(session, scenario, year)
        selected_with_loc = attach_project_locations(
            session, optimization.selected_df, year
        )
    return scoring, optimization, selected_with_loc


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.header("Analysis Controls")
scenario_name = st.sidebar.selectbox("Scenario", list(SCENARIOS.keys()))
year = st.sidebar.selectbox("Fiscal Year", YEARS, index=1)
run_btn = st.sidebar.button("Run Analysis", type="primary")

if "scoring" not in st.session_state:
    st.session_state.scoring = None
    st.session_state.optimization = None
    st.session_state.selected_with_loc = None

if run_btn:
    try:
        with st.spinner("Refreshing views, scoring, and optimizing ..."):
            scoring, optimization, selected_with_loc = _run(scenario_name, year)
        st.session_state.scoring = scoring
        st.session_state.optimization = optimization
        st.session_state.selected_with_loc = selected_with_loc
    except Exception as exc:  # surface, don't poison future reruns
        st.error(f"Analysis failed: {exc}")

scoring = st.session_state.scoring
optimization = st.session_state.optimization
selected_with_loc = st.session_state.selected_with_loc

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------
tab_map, tab_table, tab_compare, tab_explain = st.tabs([
    "Map View", "Project Rankings", "Scenario Comparison", "Explainability",
])

# ===== TAB 1: MAP VIEW =====================================================
with tab_map:
    st.subheader("Installation & Project Map")
    if scoring is None:
        st.info("Run an analysis to overlay selected projects on the map.")

    with Session(_engine()) as session:
        m = build_folium_map(session, selected_with_loc)
    st_folium(m, width=1000, height=600)

    if optimization is not None:
        col1, col2 = st.columns(2)
        col1.metric("Selected Projects", len(optimization.selected_df))
        col2.metric(
            "Budget Utilization",
            f"{optimization.total_cost / optimization.capex_limit * 100:.1f}%"
            if optimization.capex_limit else "N/A",
        )

# ===== TAB 2: PROJECT RANKINGS =============================================
with tab_table:
    st.subheader("Ranked Projects")
    if scoring is not None and not scoring.projects_df.empty:
        ranked = scoring.ranked()

        inst_df = load_installations()
        inst_names = inst_df.set_index("id")["name"].to_dict()
        ranked["installation"] = ranked["installation_id"].map(inst_names)

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            regions = ["All"] + sorted(inst_df["region"].unique().tolist())
            region_filter = st.selectbox("Region", regions)
        with col2:
            categories = ["All"] + sorted(ranked["category"].unique().tolist())
            cat_filter = st.selectbox("Category", categories)
        with col3:
            show_selected = st.checkbox("Show only selected projects", value=False)

        display = ranked.copy()
        if region_filter != "All":
            region_inst_ids = set(inst_df[inst_df["region"] == region_filter]["id"])
            display = display[display["installation_id"].isin(region_inst_ids)]
        if cat_filter != "All":
            display = display[display["category"] == cat_filter]
        if show_selected and optimization is not None:
            sel_ids = set(optimization.selected_df["project_id"])
            display = display[display["project_id"].isin(sel_ids)]

        display_cols = [
            "project_id", "installation", "category",
            "cost_estimate", "benefit_estimate", "roi",
            "readiness_gap", "hazard_exposure",
            "is_constrained", "score",
        ]
        available_cols = [c for c in display_cols if c in display.columns]
        st.dataframe(
            display[available_cols].reset_index(drop=True),
            use_container_width=True,
            height=500,
        )
        st.caption(f"Showing {len(display)} of {len(ranked)} projects")
    else:
        st.info("Run an analysis to see project rankings.")

# ===== TAB 3: SCENARIO COMPARISON ==========================================
with tab_compare:
    st.subheader("Scenario Comparison")
    st.markdown(
        "Run the analysis for two different scenarios to compare results side by side."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        sc_a = st.selectbox("Scenario A", list(SCENARIOS.keys()), key="sc_a")
        yr_a = st.selectbox("Year A", YEARS, index=1, key="yr_a")
        run_a = st.button("Run A", key="run_a_btn")
    with col_b:
        sc_b = st.selectbox("Scenario B", list(SCENARIOS.keys()), index=1, key="sc_b")
        yr_b = st.selectbox("Year B", YEARS, index=1, key="yr_b")
        run_b = st.button("Run B", key="run_b_btn")

    if "cmp_a" not in st.session_state:
        st.session_state.cmp_a = None
        st.session_state.cmp_b = None

    try:
        if run_a:
            s, o, _ = _run(sc_a, yr_a)
            st.session_state.cmp_a = (s, o)
        if run_b:
            s, o, _ = _run(sc_b, yr_b)
            st.session_state.cmp_b = (s, o)
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")

    if st.session_state.cmp_a and st.session_state.cmp_b:
        sa, oa = st.session_state.cmp_a
        sb, ob = st.session_state.cmp_b

        if sa.config.year != sb.config.year:
            st.warning(
                "The two runs analyze different fiscal years, i.e. different "
                "project cohorts. ROI is normalized within each cohort, so "
                "Total/Median Score are NOT directly comparable across the "
                "columns — compare selection diffs, costs, and utilization "
                "instead."
            )

        metrics = pd.DataFrame({
            "Metric": [
                "Projects Evaluated",
                "Projects Selected",
                "Budget Limit",
                "Total Selected Cost",
                "Budget Utilization %",
                "Total Score",
                "Median Score",
                "Mean Hazard Exposure",
            ],
            f"{sa.config.scenario} FY{sa.config.year}": [
                len(sa.projects_df),
                len(oa.selected_df),
                f"${oa.capex_limit:,.0f}",
                f"${oa.total_cost:,.0f}",
                f"{oa.total_cost / oa.capex_limit * 100:.1f}%" if oa.capex_limit else "N/A",
                f"{oa.total_score:.3f}",
                f"{sa.projects_df['score'].median():.3f}",
                f"{sa.projects_df['hazard_exposure'].mean():.2f}",
            ],
            f"{sb.config.scenario} FY{sb.config.year}": [
                len(sb.projects_df),
                len(ob.selected_df),
                f"${ob.capex_limit:,.0f}",
                f"${ob.total_cost:,.0f}",
                f"{ob.total_cost / ob.capex_limit * 100:.1f}%" if ob.capex_limit else "N/A",
                f"{ob.total_score:.3f}",
                f"{sb.projects_df['score'].median():.3f}",
                f"{sb.projects_df['hazard_exposure'].mean():.2f}",
            ],
        })
        st.dataframe(metrics, use_container_width=True, hide_index=True)

        # Project diff
        ids_a = set(oa.selected_df["project_id"])
        ids_b = set(ob.selected_df["project_id"])
        st.markdown(f"**Common selected:** {len(ids_a & ids_b)} projects")
        st.markdown(f"**Only in {sa.config.scenario}:** {len(ids_a - ids_b)} projects")
        st.markdown(f"**Only in {sb.config.scenario}:** {len(ids_b - ids_a)} projects")

        # Weight comparison
        wa, wb = sa.weights, sb.weights
        weight_keys = ["w_readiness", "w_roi", "w_risk", "w_constraint",
                       "hazard_severity_multiplier", "budget_multiplier",
                       "constraint_buffer_m"]
        wdf = pd.DataFrame({
            "Weight": weight_keys,
            sa.config.scenario: [wa[k] for k in weight_keys],
            sb.config.scenario: [wb[k] for k in weight_keys],
        })
        st.subheader("Weight Comparison")
        st.dataframe(wdf, use_container_width=True, hide_index=True)
    else:
        st.info("Run both scenarios to see the comparison.")

# ===== TAB 4: EXPLAINABILITY ================================================
with tab_explain:
    st.subheader("Score Explainability")
    st.markdown(
        "Select a project to see the breakdown of its multi-objective score. "
        "Every factor, its raw value, normalized value, weight, and contribution "
        "to the final score is shown."
    )

    if scoring is not None and not scoring.projects_df.empty:
        project_ids = sorted(scoring.projects_df["project_id"].tolist())
        selected_pid = st.selectbox("Project ID", project_ids)

        row = scoring.projects_df[scoring.projects_df["project_id"] == selected_pid].iloc[0]
        weights = scoring.weights

        factors = [
            {
                "Factor": "Readiness Gap",
                "Raw Value": f"{row['readiness_gap']:.1f}",
                "Normalized": f"{row['readiness_gap_norm']:.4f}",
                "Weight": f"+{weights['w_readiness']}",
                "Contribution": f"{weights['w_readiness'] * row['readiness_gap_norm']:+.4f}",
                "Direction": "↑ benefit",
            },
            {
                "Factor": "ROI (benefit/cost)",
                "Raw Value": f"{row['roi']:.3f}",
                "Normalized": f"{row['roi_norm']:.4f}",
                "Weight": f"+{weights['w_roi']}",
                "Contribution": f"{weights['w_roi'] * row['roi_norm']:+.4f}",
                "Direction": "↑ benefit",
            },
            {
                "Factor": "Hazard Exposure",
                "Raw Value": f"{row['hazard_exposure']:.2f}",
                "Normalized": f"{row['hazard_exposure_norm']:.4f}",
                "Weight": f"-{weights['w_risk']}",
                "Contribution": f"{-weights['w_risk'] * row['hazard_exposure_norm']:+.4f}",
                "Direction": "↓ penalty",
            },
            {
                "Factor": "Constraint Penalty",
                "Raw Value": f"{row['is_constrained']} ({int(row['constraint_count'])} zones)",
                "Normalized": f"{row['constraint_penalty_norm']:.4f}",
                "Weight": f"-{weights['w_constraint']}",
                "Contribution": f"{-weights['w_constraint'] * row['constraint_penalty_norm']:+.4f}",
                "Direction": "↓ penalty",
            },
        ]
        st.dataframe(pd.DataFrame(factors), use_container_width=True, hide_index=True)

        st.metric("Final Score", f"{row['score']:.4f}")
        st.markdown("**Formula:**")
        st.code(
            f"score = {weights['w_readiness']} × {row['readiness_gap_norm']:.4f}  (readiness)\n"
            f"      + {weights['w_roi']} × {row['roi_norm']:.4f}  (ROI)\n"
            f"      - {weights['w_risk']} × {row['hazard_exposure_norm']:.4f}  (risk)\n"
            f"      - {weights['w_constraint']} × {row['constraint_penalty_norm']:.4f}  (constraint)\n"
            f"      = {row['score']:.4f}",
            language=None,
        )

        st.markdown("**Normalization Bounds:**")
        bounds_df = pd.DataFrame([
            {"Factor": k, "Min": f"{v['min']:.4f}", "Max": f"{v['max']:.4f}"}
            for k, v in scoring.normalization_bounds.items()
        ])
        st.dataframe(bounds_df, use_container_width=True, hide_index=True)

        st.markdown("**SQL Query Used:**")
        st.code(scoring.sql_query.strip(), language="sql")
        st.markdown(f"**Parameters:** `{scoring.sql_params}`")
        st.markdown(f"**Scenario:** `{json.dumps(scoring.weights, indent=2)}`")
    else:
        st.info("Run an analysis to explore project score explainability.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**MILCON Geospatial Hub** v0.1.0  \n"
    "Synthetic demo data only.  \n"
    "All outputs are auditable — see Explainability tab."
)
