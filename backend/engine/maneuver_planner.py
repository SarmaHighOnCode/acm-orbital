"""
maneuver_planner.py — RTN-to-ECI Evasion & Recovery Burns
═════════════════════════════════════════════════════════
Calculates evasion and recovery burn sequences in RTN frame,
converts to ECI, and enforces all operational constraints.
Owner: Dev 1 (Physics Engine)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np

from config import (
    MAX_DV_PER_BURN,
    SIGNAL_LATENCY_S,
    THRUSTER_COOLDOWN_S,
)

logger = logging.getLogger("acm.engine.maneuver")


class ManeuverPlanner:
    """Plans evasion and recovery maneuvers in RTN frame.

    Burn priority order (enforced):
      1. Transverse (T-axis) — most fuel-efficient for phasing
      2. Radial (R-axis) — only if T insufficient
      3. Normal (N-axis) — LAST RESORT (expensive out-of-plane)
    """

    @staticmethod
    def rtn_to_eci(
        r_eci: np.ndarray, v_eci: np.ndarray, dv_rtn: np.ndarray
    ) -> np.ndarray:
        """Convert a delta-v vector from RTN frame to ECI frame.

        Args:
            r_eci: Satellite position [x,y,z] in km (ECI)
            v_eci: Satellite velocity [vx,vy,vz] in km/s (ECI)
            dv_rtn: Delta-v [dR, dT, dN] in km/s (RTN frame)

        Returns:
            Delta-v [dx, dy, dz] in km/s (ECI frame)
        """
        R_hat = r_eci / np.linalg.norm(r_eci)
        h = np.cross(r_eci, v_eci)
        N_hat = h / np.linalg.norm(h)
        T_hat = np.cross(N_hat, R_hat)
        Q = np.column_stack([R_hat, T_hat, N_hat])
        return Q @ dv_rtn

    def plan_evasion(
        self,
        satellite,
        debris,
        tca: datetime,
        miss_distance_km: float,
        current_time: datetime,
    ) -> list[dict]:
        """Calculate evasion + recovery burn pair for a critical conjunction.

        Args:
            satellite: Satellite object with position, velocity, fuel
            debris: Debris object at predicted TCA
            tca: Time of Closest Approach
            miss_distance_km: Predicted miss distance at TCA
            current_time: Current simulation time

        Returns:
            List of burn command dicts [{burn_id, burnTime, deltaV}, ...]

        TODO: Dev 1 — implement T-axis evasion, validate constraints, plan recovery.
        """
        logger.info(
            "Planning evasion: %s vs %s | TCA: %s | Miss: %.3f km",
            satellite.id,
            debris.id,
            tca.isoformat(),
            miss_distance_km,
        )
        return []

    def validate_burn(
        self,
        delta_v_magnitude_ms: float,
        burn_time: datetime,
        current_time: datetime,
        last_burn_time: datetime | None,
        has_los: bool,
        fuel_kg: float,
    ) -> tuple[bool, str]:
        """Validate a burn command against all operational constraints.

        Returns:
            (is_valid, rejection_reason)
        """
        if abs(delta_v_magnitude_ms) > MAX_DV_PER_BURN:
            return False, f"Exceeds max thrust ({MAX_DV_PER_BURN} m/s)"

        time_until_burn = (burn_time - current_time).total_seconds()
        if time_until_burn < SIGNAL_LATENCY_S:
            return False, f"Violates {SIGNAL_LATENCY_S}s signal latency"

        if last_burn_time is not None:
            cooldown_elapsed = (burn_time - last_burn_time).total_seconds()
            if cooldown_elapsed < THRUSTER_COOLDOWN_S:
                return False, f"Violates {THRUSTER_COOLDOWN_S}s thruster cooldown"

        if not has_los:
            return False, "No ground station LOS at burn time"

        # Fuel check delegated to FuelTracker
        return True, "OK"
