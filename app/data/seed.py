"""Synthetic data generator for MILCON Geospatial Hub.

Generates reproducible demo data using a fixed RNG seed.  All geometries
are in SRID 4326 (WGS 84).  The generator creates data across several
CONUS regions, placing installations, facilities, projects, hazards,
constraints, budgets, and ISR snapshots.

Usage:
    from app.data.seed import seed_database
    seed_database(session, total_rows=2000, rng_seed=42)

Audit note:
    Every random draw uses the numpy Generator seeded at entry.
    The same (total_rows, rng_seed) pair always produces identical data.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import numpy as np
from shapely.geometry import Point, Polygon, box
from geoalchemy2.shape import from_shape

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.db.models import (
    Budget,
    Constraint,
    Facility,
    Hazard,
    ISRSnapshot,
    Installation,
    Project,
)

# ---------------------------------------------------------------------------
# Region definitions (bounding boxes in lon/lat)
# ---------------------------------------------------------------------------
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "Southeast": (-88.0, 30.0, -80.0, 35.0),
    "Southwest": (-115.0, 32.0, -108.0, 37.0),
    "Mid-Atlantic": (-78.0, 37.0, -74.0, 40.0),
    "Midwest": (-95.0, 38.0, -87.0, 42.0),
    "Pacific": (-123.0, 34.0, -117.0, 39.0),
}

FACILITY_TYPES = [
    "Barracks", "Admin Building", "Motor Pool", "Warehouse",
    "Medical Clinic", "Training Facility", "Dining Hall", "Hangar",
]

PROJECT_CATEGORIES = [
    "New Construction", "Renovation", "Demolition",
    "Infrastructure Upgrade", "Energy Modernization",
    "Force Protection", "Utility Repair",
]

HAZARD_TYPES = ["flood", "fire", "wind", "earthquake", "landslide"]

CONSTRAINT_TYPES = ["no-build", "noise-zone", "protected-wetland", "historic-preservation"]


def _random_point_in_bbox(
    rng: np.random.Generator,
    minx: float, miny: float, maxx: float, maxy: float,
) -> Point:
    lon = rng.uniform(minx, maxx)
    lat = rng.uniform(miny, maxy)
    return Point(lon, lat)


def _random_polygon_near(
    rng: np.random.Generator,
    center_lon: float, center_lat: float,
    size_deg: float = 0.02,
) -> Polygon:
    """Create a roughly rectangular polygon near a center point."""
    half = size_deg / 2
    dx = rng.uniform(-0.05, 0.05)
    dy = rng.uniform(-0.05, 0.05)
    return box(
        center_lon + dx - half,
        center_lat + dy - half,
        center_lon + dx + half,
        center_lat + dy + half,
    )


def seed_database(session: Session, total_rows: int = 2000, rng_seed: int = 42) -> dict[str, int]:
    """Populate the database with synthetic MILCON data.

    Returns a dict of entity counts for logging.
    """
    rng = np.random.default_rng(rng_seed)

    # ---- Proportions (roughly) ----
    n_installations = max(10, total_rows // 40)
    n_facilities_per = max(3, total_rows // (n_installations * 4))
    n_projects_per = max(2, total_rows // (n_installations * 5))
    n_hazards = max(8, total_rows // 50)
    n_constraints = max(6, total_rows // 60)
    n_isr_per = 4  # quarterly snapshots

    region_names = list(REGIONS.keys())

    # ---- Installations ----
    installations: list[Installation] = []
    for i in range(n_installations):
        region = region_names[i % len(region_names)]
        bbox = REGIONS[region]
        pt = _random_point_in_bbox(rng, *bbox)
        inst = Installation(
            name=f"Installation {region[:3].upper()}-{i + 1:03d}",
            region=region,
            readiness_score=round(float(rng.uniform(40, 95)), 1),
            geometry=from_shape(pt, srid=4326),
        )
        installations.append(inst)
    session.add_all(installations)
    session.flush()  # get IDs

    # ---- Facilities ----
    facilities: list[Facility] = []
    for inst in installations:
        pt: Point = Point(
            float(inst.geometry.desc.split("(")[1].split()[0]) if isinstance(inst.geometry, str)
            else 0, 0
        ) if False else None  # placeholder, we use inst coords below

        # Extract coords from WKB via shapely
        from geoalchemy2.shape import to_shape
        inst_pt = to_shape(inst.geometry)

        for _ in range(rng.integers(n_facilities_per, n_facilities_per + 4)):
            fac_pt = Point(
                inst_pt.x + rng.uniform(-0.01, 0.01),
                inst_pt.y + rng.uniform(-0.01, 0.01),
            )
            fac = Facility(
                installation_id=inst.id,
                type=rng.choice(FACILITY_TYPES),
                condition_index=round(float(rng.uniform(20, 100)), 1),
                geometry=from_shape(fac_pt, srid=4326),
            )
            facilities.append(fac)
    session.add_all(facilities)

    # ---- Projects ----
    projects: list[Project] = []
    for inst in installations:
        inst_pt = to_shape(inst.geometry)
        for _ in range(rng.integers(n_projects_per, n_projects_per + 5)):
            cost = round(float(rng.uniform(500_000, 80_000_000)), -3)
            benefit = round(cost * float(rng.uniform(0.5, 3.0)), -3)
            proj_pt = Point(
                inst_pt.x + rng.uniform(-0.02, 0.02),
                inst_pt.y + rng.uniform(-0.02, 0.02),
            )
            proj = Project(
                installation_id=inst.id,
                category=rng.choice(PROJECT_CATEGORIES),
                cost_estimate=cost,
                benefit_estimate=benefit,
                priority=int(rng.integers(1, 6)),
                year=int(rng.choice([2025, 2026, 2027, 2028])),
                geometry=from_shape(proj_pt, srid=4326),
            )
            projects.append(proj)
    session.add_all(projects)

    # ---- Hazards ----
    hazards: list[Hazard] = []
    for _ in range(n_hazards):
        region = rng.choice(region_names)
        bbox = REGIONS[region]
        center_lon = float(rng.uniform(bbox[0], bbox[2]))
        center_lat = float(rng.uniform(bbox[1], bbox[3]))
        size = float(rng.uniform(0.01, 0.05))
        haz = Hazard(
            type=rng.choice(HAZARD_TYPES),
            severity=round(float(rng.uniform(1, 10)), 1),
            geometry=from_shape(
                _random_polygon_near(rng, center_lon, center_lat, size),
                srid=4326,
            ),
        )
        hazards.append(haz)
    session.add_all(hazards)

    # ---- Constraints ----
    constraints: list[Constraint] = []
    for _ in range(n_constraints):
        region = rng.choice(region_names)
        bbox = REGIONS[region]
        center_lon = float(rng.uniform(bbox[0], bbox[2]))
        center_lat = float(rng.uniform(bbox[1], bbox[3]))
        con = Constraint(
            type=rng.choice(CONSTRAINT_TYPES),
            notes=f"Synthetic {rng.choice(CONSTRAINT_TYPES)} zone",
            geometry=from_shape(
                _random_polygon_near(rng, center_lon, center_lat, float(rng.uniform(0.005, 0.03))),
                srid=4326,
            ),
        )
        constraints.append(con)
    session.add_all(constraints)

    # ---- Budgets ----
    budgets = [
        Budget(year=2025, capex_limit=500_000_000),
        Budget(year=2026, capex_limit=550_000_000),
        Budget(year=2027, capex_limit=520_000_000),
        Budget(year=2028, capex_limit=480_000_000),
    ]
    session.add_all(budgets)

    # ---- ISR Snapshots ----
    snapshots: list[ISRSnapshot] = []
    for inst in installations:
        base_readiness = inst.readiness_score
        for q in range(n_isr_per):
            snap = ISRSnapshot(
                installation_id=inst.id,
                date=datetime.date(2026, 1 + q * 3, 1),
                readiness=round(
                    max(0, min(100, base_readiness + float(rng.normal(0, 3)))),
                    1,
                ),
                notes=f"Q{q + 1} 2026 assessment",
            )
            snapshots.append(snap)
    session.add_all(snapshots)

    session.commit()

    # Refresh materialized views
    from sqlalchemy import text
    session.execute(text("REFRESH MATERIALIZED VIEW project_risk_exposure"))
    session.execute(text("REFRESH MATERIALIZED VIEW project_constraint_flags"))
    session.commit()

    counts = {
        "installations": len(installations),
        "facilities": len(facilities),
        "projects": len(projects),
        "hazards": len(hazards),
        "constraints": len(constraints),
        "budgets": len(budgets),
        "isr_snapshots": len(snapshots),
    }
    return counts
