"""Map rendering utilities using Folium and Matplotlib.

Produces:
- Interactive Folium maps (for the Streamlit dashboard)
- Static PNG map exports (for reports)

Both renderers draw the same layers (installations, hazards, constraints,
selected projects) so the report map never silently diverges from the
dashboard map.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import folium
import pandas as pd
from shapely.geometry import shape as shapely_shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import (
    CONSTRAINT_OVERLAY_QUERY,
    HAZARD_OVERLAY_QUERY,
    INSTALLATION_SUMMARY_QUERY,
    PROJECT_LOCATIONS_QUERY,
)


def _color_for_hazard(htype: str) -> str:
    return {
        "flood": "blue",
        "fire": "red",
        "wind": "purple",
        "earthquake": "orange",
        "landslide": "brown",
    }.get(htype, "gray")


def _color_for_constraint(ctype: str) -> str:
    return {
        "no-build": "black",
        "noise-zone": "darkred",
        "protected-wetland": "green",
        "historic-preservation": "goldenrod",
    }.get(ctype, "gray")


def _load_overlay(session: Session, query: str) -> list:
    """Fetch overlay rows, parsing geojson to dicts when needed."""
    rows = []
    for row in session.execute(text(query)).fetchall():
        geojson = row.geojson
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        rows.append((row, geojson))
    return rows


def attach_project_locations(
    session: Session, selected_df: pd.DataFrame, year: int
) -> pd.DataFrame:
    """Merge lon/lat coordinates onto a selected-projects DataFrame.

    Uses an inner merge: a project without a live location row (e.g. data
    changed since scoring) is dropped rather than plotted at NaN, and the
    caller can compare row counts to detect the discrepancy.
    """
    proj_locs = pd.read_sql(
        text(PROJECT_LOCATIONS_QUERY), session.connection(), params={"year": year}
    )
    merged = selected_df.merge(
        proj_locs[["id", "lon", "lat"]],
        left_on="project_id", right_on="id", how="inner",
    )
    return merged.drop(columns=["id"])


def _iter_polygons(geom):
    """Yield individual Polygons from a Polygon or MultiPolygon."""
    if geom.geom_type == "MultiPolygon":
        yield from geom.geoms
    elif geom.geom_type == "Polygon":
        yield geom


def build_folium_map(
    session: Session,
    selected_projects: pd.DataFrame | None = None,
) -> folium.Map:
    """Build an interactive Folium map with installations, hazards,
    constraints, and optionally highlighted selected projects."""

    inst_df = pd.read_sql(text(INSTALLATION_SUMMARY_QUERY), session.connection())

    center_lat = inst_df["lat"].mean() if not inst_df.empty else 37.0
    center_lon = inst_df["lon"].mean() if not inst_df.empty else -95.0

    m = folium.Map(location=[center_lat, center_lon], zoom_start=5, tiles="CartoDB positron")

    # Installation markers
    for _, row in inst_df.iterrows():
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=6,
            color="darkblue",
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(
                f"<b>{row['name']}</b><br>"
                f"Region: {row['region']}<br>"
                f"Readiness: {row['readiness_score']}<br>"
                f"Facilities: {row['facility_count']}<br>"
                f"Avg Condition: {row['avg_condition']}",
                max_width=250,
            ),
        ).add_to(m)

    # Hazards
    hazard_group = folium.FeatureGroup(name="Hazards")
    for row, geojson in _load_overlay(session, HAZARD_OVERLAY_QUERY):
        folium.GeoJson(
            geojson,
            style_function=lambda _f, ht=row.type, sv=row.severity: {
                "fillColor": _color_for_hazard(ht),
                "color": _color_for_hazard(ht),
                "weight": 1,
                "fillOpacity": min(0.15 + sv * 0.05, 0.6),
            },
            tooltip=f"{row.type} (severity {row.severity})",
        ).add_to(hazard_group)
    hazard_group.add_to(m)

    # Constraints
    con_group = folium.FeatureGroup(name="Constraints")
    for row, geojson in _load_overlay(session, CONSTRAINT_OVERLAY_QUERY):
        folium.GeoJson(
            geojson,
            style_function=lambda _f, ct=row.type: {
                "fillColor": _color_for_constraint(ct),
                "color": _color_for_constraint(ct),
                "weight": 1,
                "dashArray": "5 3",
                "fillOpacity": 0.2,
            },
            tooltip=f"{row.type}: {row.notes or ''}",
        ).add_to(con_group)
    con_group.add_to(m)

    # Selected projects
    if selected_projects is not None and not selected_projects.empty:
        proj_group = folium.FeatureGroup(name="Selected Projects")
        for _, row in selected_projects.iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            if lat is None or lon is None or math.isnan(lat) or math.isnan(lon):
                continue
            folium.CircleMarker(
                location=[lat, lon],
                radius=8,
                color="green",
                fill=True,
                fill_color="lime",
                fill_opacity=0.8,
                popup=folium.Popup(
                    f"<b>Project {int(row['project_id'])}</b><br>"
                    f"Category: {row.get('category', 'N/A')}<br>"
                    f"Cost: ${row.get('cost_estimate', 0):,.0f}<br>"
                    f"Score: {row.get('score', 0):.3f}",
                    max_width=250,
                ),
            ).add_to(proj_group)
        proj_group.add_to(m)

    folium.LayerControl().add_to(m)
    return m


def export_static_map(
    session: Session,
    selected_projects: pd.DataFrame | None,
    output_path: Path,
    year: int | None = None,
) -> Path:
    """Export a static PNG map using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon

    fig, ax = plt.subplots(1, 1, figsize=(12, 8))

    # Installations
    inst_df = pd.read_sql(text(INSTALLATION_SUMMARY_QUERY), session.connection())
    if not inst_df.empty:
        ax.scatter(
            inst_df["lon"], inst_df["lat"],
            c="navy", s=40, zorder=5, label="Installations", alpha=0.7,
        )

    # Hazards
    for row, geojson in _load_overlay(session, HAZARD_OVERLAY_QUERY):
        color = _color_for_hazard(row.type)
        for poly in _iter_polygons(shapely_shape(geojson)):
            ax.add_patch(MplPolygon(
                list(poly.exterior.coords), closed=True,
                facecolor=color, edgecolor=color, alpha=0.3,
            ))

    # Constraints
    for row, geojson in _load_overlay(session, CONSTRAINT_OVERLAY_QUERY):
        color = _color_for_constraint(row.type)
        for poly in _iter_polygons(shapely_shape(geojson)):
            ax.add_patch(MplPolygon(
                list(poly.exterior.coords), closed=True,
                facecolor="none", edgecolor=color, alpha=0.6,
                linestyle="--",
            ))

    # Selected projects
    if (
        selected_projects is not None
        and not selected_projects.empty
        and {"lon", "lat"}.issubset(selected_projects.columns)
    ):
        plot_df = selected_projects.dropna(subset=["lon", "lat"])
        if not plot_df.empty:
            ax.scatter(
                plot_df["lon"], plot_df["lat"],
                c="lime", edgecolors="green", s=60, zorder=6,
                label="Selected Projects", alpha=0.9,
            )

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    title = "MILCON Project Selection Map"
    if year:
        title += f" — FY{year}"
    ax.set_title(title)
    ax.legend(loc="lower left")
    ax.set_aspect("equal")
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path
