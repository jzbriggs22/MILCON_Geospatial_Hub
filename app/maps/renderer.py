"""Map rendering utilities using Folium and Matplotlib.

Produces:
- Interactive Folium maps (for the Streamlit dashboard)
- Static PNG map exports (for reports)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import folium
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import (
    HAZARD_OVERLAY_QUERY,
    CONSTRAINT_OVERLAY_QUERY,
    INSTALLATION_SUMMARY_QUERY,
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


def build_folium_map(
    session: Session,
    selected_projects: pd.DataFrame | None = None,
    year: int | None = None,
) -> folium.Map:
    """Build an interactive Folium map with installations, hazards, constraints,
    and optionally highlighted selected projects."""

    # Installations
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
    hazard_rows = session.execute(text(HAZARD_OVERLAY_QUERY)).fetchall()
    hazard_group = folium.FeatureGroup(name="Hazards")
    for row in hazard_rows:
        geojson = row.geojson
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
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
    con_rows = session.execute(text(CONSTRAINT_OVERLAY_QUERY)).fetchall()
    con_group = folium.FeatureGroup(name="Constraints")
    for row in con_rows:
        geojson = row.geojson
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
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
            if "lon" in row and "lat" in row:
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
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
    import matplotlib.patches as mpatches

    fig, ax = plt.subplots(1, 1, figsize=(12, 8))

    # Installations
    inst_df = pd.read_sql(text(INSTALLATION_SUMMARY_QUERY), session.connection())
    if not inst_df.empty:
        ax.scatter(
            inst_df["lon"], inst_df["lat"],
            c="navy", s=40, zorder=5, label="Installations", alpha=0.7,
        )

    # Hazards
    hazard_rows = session.execute(text(HAZARD_OVERLAY_QUERY)).fetchall()
    from shapely.geometry import shape as shapely_shape
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.collections import PatchCollection

    hazard_patches = []
    hazard_colors = []
    for row in hazard_rows:
        geojson = row.geojson
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        poly = shapely_shape(geojson)
        coords = list(poly.exterior.coords)
        hazard_patches.append(MplPolygon(coords, closed=True))
        hazard_colors.append(_color_for_hazard(row.type))

    if hazard_patches:
        for patch, color in zip(hazard_patches, hazard_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.3)
            patch.set_edgecolor(color)
            ax.add_patch(patch)

    # Selected projects
    if selected_projects is not None and not selected_projects.empty and "lon" in selected_projects.columns:
        ax.scatter(
            selected_projects["lon"], selected_projects["lat"],
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
