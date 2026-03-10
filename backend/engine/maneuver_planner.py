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
    CONJUNCTION_THRESHOLD_KM,
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

    def __init__(self, propagator=None):
        """
        Args:
            propagator: OrbitalPropagator instance used to predict satellite state
                        at recovery burn time for correct RTN frame conversion.
                        If None, falls back to planning-time frame (less accurate).
        """
        self.propagator = propagator

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
        """Calculate evasion + recovery burn pair for a critical conjunction."""
        # 1. Timing: Burn at least 30 mins before TCA (if possible) or ASAP
        # Phasing (T-axis) maneuvers work best with time.
        burn_lead_time_s = 1800.0  # 30 minutes
        earliest_burn_time = current_time + timedelta(seconds=SIGNAL_LATENCY_S + 60)
        
        burn_time = tca - timedelta(seconds=burn_lead_time_s)
        if burn_time < earliest_burn_time:
            burn_time = earliest_burn_time
            
        # 2. Magnitude: Scale proportionally. Direct hit (0m) -> 2m/s. Edge hit -> ~0.02m/s
        # We'll use a positive T burn (speed up) to arrive EARLIER at the intersection.
        dv_mag_ms = max(0.001, 2.0 * (CONJUNCTION_THRESHOLD_KM - miss_distance_km) / CONJUNCTION_THRESHOLD_KM)
        dv_rtn = np.array([0.0, dv_mag_ms / 1000.0, 0.0])  # km/s
        
        # 3. Rotation: Convert to ECI
        dv_eci = self.rtn_to_eci(satellite.position, satellite.velocity, dv_rtn)
        
        # 4. Recovery: Apply opposite burn ~45 mins later (half orbit for LEO is ~46 mins)
        recovery_time = burn_time + timedelta(seconds=2700.0)
        dv_rtn_recovery = -dv_rtn

        # Propagate satellite state to recovery_time to get the correct RTN frame.
        # Without this, the ECI vector would be computed in the planning-time frame,
        # but the burn executes ~45 min later when the satellite has rotated ~180°,
        # so the T-axis direction in ECI would be completely wrong.
        dt_to_recovery = (recovery_time - current_time).total_seconds()
        if self.propagator is not None and dt_to_recovery > 0:
            recovery_sv = self.propagator.propagate(satellite.state_vector, dt_to_recovery)
            recovery_pos = recovery_sv[:3]
            recovery_vel = recovery_sv[3:]
        else:
            recovery_pos = satellite.position
            recovery_vel = satellite.velocity
        dv_eci_recovery = self.rtn_to_eci(recovery_pos, recovery_vel, dv_rtn_recovery)

        maneuvers = [
            {
                "burn_id": f"EVASION_{debris.id}_{burn_time.strftime('%H%M%S')}",
                "burnTime": burn_time.isoformat(),
                "deltaV_vector": {"x": dv_eci[0], "y": dv_eci[1], "z": dv_eci[2]}
            },
            {
                "burn_id": f"RECOVERY_{debris.id}_{recovery_time.strftime('%H%M%S')}",
                "burnTime": recovery_time.isoformat(),
                "deltaV_vector": {"x": dv_eci_recovery[0], "y": dv_eci_recovery[1], "z": dv_eci_recovery[2]}
            }
        ]
        
        logger.info(
            "Maneuver scheduled: %s evasion burns for %s", len(maneuvers), satellite.id
        )
        return maneuvers

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
