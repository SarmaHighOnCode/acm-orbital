"""
kessler.py — Kessler Cascade Risk Assessment Engine
════════════════════════════════════════════════════
Real-time computation of debris cascade (Kessler Syndrome) probability
across LEO altitude shells. Uses NASA's spatial density collision model
to quantify cascade risk per orbital band.

Key formula per shell:
    P_collision = n × σ × v_rel × Δt × V_shell⁻¹
where:
    n     = number of objects in shell
    σ     = average collision cross-section (m²)
    v_rel = average relative velocity (km/s)
    Δt    = assessment window (seconds)
    V_shell = volume of the altitude shell (km³)

References:
    - Kessler, D.J. & Cour-Palais, B.G. (1978) "Collision Frequency of
      Artificial Satellites: The Creation of a Debris Belt"
    - NASA ODPO Technical Report (2023) "LEO Debris Environment Stability"
    - ESA Space Debris Mitigation Guidelines

Owner: Dev 1 (Physics Engine)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from config import (
    R_EARTH,
    KESSLER_SHELL_WIDTH_KM as SHELL_WIDTH_KM,
    KESSLER_MIN_ALT_KM as MIN_ALT_KM,
    KESSLER_MAX_ALT_KM as MAX_ALT_KM,
    KESSLER_AVG_CROSS_SECTION_M2 as AVG_CROSS_SECTION_M2,
    KESSLER_AVG_REL_VELOCITY_KMS as AVG_REL_VELOCITY_KMS,
    KESSLER_ASSESSMENT_WINDOW_S as ASSESSMENT_WINDOW_S,
    KESSLER_NASA_CRITICAL_DENSITY as NASA_CRITICAL_DENSITY,
)

logger = logging.getLogger("acm.engine.kessler")

# Derived from config
AVG_CROSS_SECTION_KM2 = AVG_CROSS_SECTION_M2 * 1e-6  # Convert m² → km²


@dataclass
class ShellRisk:
    """Risk assessment for a single altitude shell."""
    alt_min_km: float
    alt_max_km: float
    object_count: int
    volume_km3: float
    spatial_density: float      # objects/km³
    collision_prob_24h: float   # probability per 24h
    is_critical: bool           # exceeds NASA threshold
    cascade_factor: float       # multiplier: how many new fragments per collision


@dataclass
class KesslerAssessment:
    """Complete Kessler cascade risk assessment."""
    overall_risk_score: float   # 0.0 – 1.0
    risk_label: str             # LOW / MODERATE / ELEVATED / HIGH / CRITICAL
    cascade_probability: float  # probability of ≥1 cascade event in 24h
    total_objects: int
    critical_shells: int        # shells exceeding NASA density threshold
    most_crowded_alt_km: float
    most_crowded_density: float
    shell_data: list[ShellRisk]


class KesslerRiskEngine:
    """Compute real-time Kessler cascade risk from simulation state.

    This engine analyzes the current debris + satellite population
    and computes per-shell collision probabilities using NASA's
    spatial density model. It identifies altitude bands where
    debris density approaches or exceeds the critical threshold
    for self-sustaining cascade.
    """

    def __init__(self):
        self.shells = self._init_shells()

    @staticmethod
    def _init_shells() -> list[tuple[float, float]]:
        """Generate altitude shell boundaries."""
        shells = []
        alt = MIN_ALT_KM
        while alt < MAX_ALT_KM:
            shells.append((alt, alt + SHELL_WIDTH_KM))
            alt += SHELL_WIDTH_KM
        return shells

    @staticmethod
    def _shell_volume(alt_min_km: float, alt_max_km: float) -> float:
        """Compute volume of a spherical shell in km³."""
        r_inner = R_EARTH + alt_min_km
        r_outer = R_EARTH + alt_max_km
        return (4.0 / 3.0) * math.pi * (r_outer**3 - r_inner**3)

    @staticmethod
    def _cascade_fragment_count(rel_velocity_kms: float) -> float:
        """Estimate number of trackable fragments from a collision.

        Uses NASA's empirical formula from Satellite Orbital Debris
        Characterization Impact Test (SOCIT) data:
            N(>10cm) ≈ 0.1 × M_target^0.75 × v_rel^0.5
        Simplified to a velocity-dependent multiplier.
        """
        # Approximate: LEO collision at 10 km/s produces ~1000 trackable fragments
        # Scale by velocity ratio
        return max(1.0, 100.0 * (rel_velocity_kms / 10.0) ** 0.5)

    def assess(
        self,
        satellite_positions: np.ndarray,
        debris_positions: np.ndarray,
    ) -> KesslerAssessment:
        """Run full Kessler cascade risk assessment.

        Args:
            satellite_positions: (N, 3) ECI positions of satellites in km
            debris_positions: (M, 3) ECI positions of debris in km

        Returns:
            KesslerAssessment with per-shell breakdown
        """
        # Compute altitudes for all objects
        if len(satellite_positions) > 0:
            sat_alts = np.linalg.norm(satellite_positions, axis=1) - R_EARTH
        else:
            sat_alts = np.array([])

        if len(debris_positions) > 0:
            deb_alts = np.linalg.norm(debris_positions, axis=1) - R_EARTH
        else:
            deb_alts = np.array([])

        all_alts = np.concatenate([sat_alts, deb_alts]) if len(sat_alts) + len(deb_alts) > 0 else np.array([])

        shell_results: list[ShellRisk] = []
        max_density = 0.0
        max_density_alt = 0.0
        critical_count = 0
        overall_collision_prob = 0.0

        for alt_min, alt_max in self.shells:
            # Count objects in this shell
            if len(all_alts) > 0:
                mask = (all_alts >= alt_min) & (all_alts < alt_max)
                n_objects = int(np.sum(mask))
            else:
                n_objects = 0

            volume = self._shell_volume(alt_min, alt_max)
            density = n_objects / volume if volume > 0 else 0.0

            # Collision probability per object pair per 24h
            # P = n² × σ × v_rel × Δt / (2 × V)  (kinetic theory of gases analog)
            if n_objects >= 2:
                collision_prob = (
                    n_objects * (n_objects - 1) / 2  # unique pairs
                    * AVG_CROSS_SECTION_KM2
                    * AVG_REL_VELOCITY_KMS
                    * ASSESSMENT_WINDOW_S
                    / volume
                )
            else:
                collision_prob = 0.0

            is_critical = density > NASA_CRITICAL_DENSITY
            cascade_factor = self._cascade_fragment_count(AVG_REL_VELOCITY_KMS)

            if density > max_density:
                max_density = density
                max_density_alt = (alt_min + alt_max) / 2

            if is_critical:
                critical_count += 1

            # Accumulate: probability of at least one collision across all shells
            # Using P(≥1) = 1 - ∏(1 - P_i)
            overall_collision_prob = 1.0 - (1.0 - overall_collision_prob) * (1.0 - min(collision_prob, 1.0))

            shell_results.append(ShellRisk(
                alt_min_km=alt_min,
                alt_max_km=alt_max,
                object_count=n_objects,
                volume_km3=volume,
                spatial_density=density,
                collision_prob_24h=collision_prob,
                is_critical=is_critical,
                cascade_factor=cascade_factor,
            ))

        # Cascade probability: if a collision produces N fragments,
        # the cascade probability = P_collision × P(fragments cause another collision)
        # Simplified: cascade_prob = collision_prob × (density / critical_density)
        cascade_multiplier = min(max_density / NASA_CRITICAL_DENSITY, 10.0) if NASA_CRITICAL_DENSITY > 0 else 0.0
        cascade_prob = min(overall_collision_prob * cascade_multiplier * 0.1, 1.0)

        # Risk score: 0–1 based on cascade probability + density factors
        risk_score = min(1.0, cascade_prob + critical_count * 0.05)

        # Classify risk
        if risk_score < 0.1:
            label = "LOW"
        elif risk_score < 0.3:
            label = "MODERATE"
        elif risk_score < 0.5:
            label = "ELEVATED"
        elif risk_score < 0.7:
            label = "HIGH"
        else:
            label = "CRITICAL"

        total_objects = int(len(sat_alts) + len(deb_alts))

        return KesslerAssessment(
            overall_risk_score=round(risk_score, 4),
            risk_label=label,
            cascade_probability=round(cascade_prob, 6),
            total_objects=total_objects,
            critical_shells=critical_count,
            most_crowded_alt_km=round(max_density_alt, 1),
            most_crowded_density=max_density,
            shell_data=shell_results,
        )
