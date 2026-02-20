"""Configuration for MILCON Geospatial Hub.

Every configuration value that affects analytic outputs is defined here,
with defaults documented. Scenario weights and thresholds are explicit
so that any scoring result can be traced back to these values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def get_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://milcon:milcon@localhost:5432/milcon",
    )


# ---------------------------------------------------------------------------
# Scenario weight configurations
# ---------------------------------------------------------------------------
# Each scenario defines multiplicative weights applied to the scoring
# factors.  The multi-objective score formula is:
#
#   score = w_readiness * readiness_gap_norm
#         + w_roi       * roi_norm
#         - w_risk      * hazard_exposure_norm
#         - w_constraint * constraint_penalty_norm
#
# Normalization is min-max over the project set so all factors ∈ [0, 1].
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioWeights:
    """Immutable weight vector for a single scenario.

    Attributes are the *names* of the scoring factors.  The sign convention
    (positive = benefit, negative = penalty) is applied in the scoring
    function, NOT here — all weights are positive magnitudes.
    """
    name: str
    description: str
    w_readiness: float
    w_roi: float
    w_risk: float
    w_constraint: float
    hazard_severity_multiplier: float = 1.0
    budget_multiplier: float = 1.0
    constraint_buffer_m: float = 0.0  # extra meters added to constraint polys

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict for auditability / serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "w_readiness": self.w_readiness,
            "w_roi": self.w_roi,
            "w_risk": self.w_risk,
            "w_constraint": self.w_constraint,
            "hazard_severity_multiplier": self.hazard_severity_multiplier,
            "budget_multiplier": self.budget_multiplier,
            "constraint_buffer_m": self.constraint_buffer_m,
        }


SCENARIOS: dict[str, ScenarioWeights] = {
    "baseline": ScenarioWeights(
        name="baseline",
        description="Normal weights, full budget",
        w_readiness=0.30,
        w_roi=0.35,
        w_risk=0.20,
        w_constraint=0.15,
    ),
    "climate_stress": ScenarioWeights(
        name="climate_stress",
        description="Hazard severity increased; risk weight elevated",
        w_readiness=0.20,
        w_roi=0.25,
        w_risk=0.40,
        w_constraint=0.15,
        hazard_severity_multiplier=1.5,
    ),
    "readiness_surge": ScenarioWeights(
        name="readiness_surge",
        description="Readiness is top priority; budget constrained to 70%",
        w_readiness=0.50,
        w_roi=0.20,
        w_risk=0.15,
        w_constraint=0.15,
        budget_multiplier=0.70,
    ),
    "constraint_heavy": ScenarioWeights(
        name="constraint_heavy",
        description="Expanded no-build zones (+500 m buffer); constraint weight up",
        w_readiness=0.25,
        w_roi=0.25,
        w_risk=0.20,
        w_constraint=0.30,
        constraint_buffer_m=500.0,
    ),
}


@dataclass(frozen=True)
class AnalysisConfig:
    """Top-level knobs for a single analysis run.

    Stored verbatim in every report so auditors can reproduce results.
    """
    scenario: str
    year: int
    hazard_buffer_m: float = 1000.0  # meters — proximity threshold
    srid: int = 4326
    seed: int = 42

    @property
    def weights(self) -> ScenarioWeights:
        return SCENARIOS[self.scenario]
