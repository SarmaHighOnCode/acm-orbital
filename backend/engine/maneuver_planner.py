"""
maneuver_planner.py — RTN-to-ECI Evasion & Recovery Burns
═════════════════════════════════════════════════════════
Calculates evasion and recovery burn sequences in the RTN (Radial-Transverse-Normal)
orbital frame, converts them to ECI for execution, and enforces all operational
constraints.
Owner: Dev 1 (Physics Engine)

RTN frame correction for future burns (F1 critical fix):
    The RTN basis vectors (R̂, T̂, N̂) are attached to the satellite and rotate
    with it. In LEO an orbital period is ≈ 92 min, so the RTN frame completes a
    full ECI rotation in 92 min.  If the evasion burn executes 30 min in the
    future (typical lead time before TCA), the satellite has travelled ≈ 117°
    around its orbit — T̂ now points in a completely different ECI direction.
    Applying a T-axis delta-v computed at the CURRENT RTN frame would inject the
    burn energy in the wrong inertial direction, defeating the evasion.

    Fix: propagate the satellite's state forward to burn_time, compute the RTN
    frame there, then convert to ECI.  Same correction is applied to the
    recovery burn (already done in the original code; extended to evasion here).

Burn priority order (PRD §4.5, fuel optimisation):
    1. Transverse (T̂) — most efficient for phasing (in-plane, changes period)
    2. Radial   (R̂)  — backup (does not change semi-major axis, less efficient)
    3. Normal   (N̂)  — LAST RESORT (out-of-plane, very expensive in fuel)
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
    """Plans evasion and recovery maneuvers for collision-avoidance operations.

    All delta-v vectors are computed in RTN frame then converted to ECI for
    application to the satellite's velocity vector.

    Args:
        propagator: OrbitalPropagator instance used to advance satellite state
                    to burn execution time to obtain the correct RTN frame.
                    If None, the planning-epoch frame is used as a fallback
                    (less accurate for burns far in the future).
    """

    def __init__(self, propagator=None) -> None:
        self.propagator = propagator

    # ── RTN ↔ ECI conversion ──────────────────────────────────────────────────

    @staticmethod
    def rtn_to_eci(
        r_eci: np.ndarray, v_eci: np.ndarray, dv_rtn: np.ndarray
    ) -> np.ndarray:
        """Rotate a delta-v vector from the RTN orbital frame to ECI.

        RTN basis construction (PRD §3.4):
            R̂ = r / |r|                 (radial, pointing away from Earth)
            N̂ = (r × v) / |r × v|      (normal to orbital plane)
            T̂ = N̂ × R̂                 (transverse, along-track)
            Q = [R̂ | T̂ | N̂]           (3×3 rotation matrix, columns)

        Args:
            r_eci:  Satellite position [x, y, z] in km (ECI).
            v_eci:  Satellite velocity [vx, vy, vz] in km/s (ECI).
            dv_rtn: Delta-v [dR, dT, dN] in km/s (RTN frame).

        Returns:
            Delta-v [dx, dy, dz] in km/s (ECI frame).
        """
        R_hat: np.ndarray = r_eci / np.linalg.norm(r_eci)
        h: np.ndarray     = np.cross(r_eci, v_eci)
        N_hat: np.ndarray = h / np.linalg.norm(h)
        T_hat: np.ndarray = np.cross(N_hat, R_hat)
        Q: np.ndarray     = np.column_stack([R_hat, T_hat, N_hat])
        return Q @ dv_rtn

    # ── Evasion planning ──────────────────────────────────────────────────────

    def plan_evasion(
        self,
        satellite,
        debris,
        tca: datetime,
        miss_distance_km: float,
        current_time: datetime,
    ) -> list[dict]:
        """Calculate an evasion + recovery burn pair for a CRITICAL conjunction.

        Strategy (PRD §4.5):
            - Evasion  burn: +T (speed-up, arrive at intersection point earlier)
              applied ≥ 30 min before TCA.  Proportional magnitude: direct collision
              (0 m miss) → 2.0 m/s; grazing threshold (≈ 100 m miss) → ≈ 0.0 m/s.
            - Recovery burn: −T applied 45 min after evasion (≈ half LEO period) to
              restore the original phasing and return to the nominal slot.

        RTN-frame accuracy (F1 fix):
            Both the evasion and recovery delta-v vectors are computed from the
            RTN frame as it will exist at the respective burn execution times,
            by propagating the satellite forward from current_time.  Using the
            current-epoch RTN frame for a future burn would give an incorrect
            ECI direction by up to ±180° depending on the lead time.

        Args:
            satellite:       Satellite data object (position, velocity, state_vector).
            debris:          Debris data object (id used for burn labelling).
            tca:             Predicted Time of Closest Approach (UTC datetime).
            miss_distance_km: Miss distance at TCA in km (from CDM).
            current_time:    Present simulation clock time (UTC datetime).

        Returns:
            List of two burn dicts: [evasion_burn, recovery_burn], each with
            keys: burn_id, burnTime (ISO-8601), deltaV_vector {x, y, z} (km/s).
        """
        # ── 1. Timing: burn 30 min before TCA (or ASAP after signal latency) ──
        BURN_LEAD_S: float   = 1800.0   # 30 minutes
        earliest_burn_time   = current_time + timedelta(seconds=SIGNAL_LATENCY_S + 60)
        burn_time            = tca - timedelta(seconds=BURN_LEAD_S)
        if burn_time < earliest_burn_time:
            burn_time = earliest_burn_time

        # ── 2. Magnitude: proportional scaling (PRD §4.5) ─────────────────────
        # At miss = 0 m   → dv = 2.0 m/s  (direct hit, maximum evasion)
        # At miss = 100 m → dv ≈ 0.0 m/s  (grazing threshold, minimal change)
        # Formula: dv_ms = 2.0 × (threshold_km − miss_km) / threshold_km
        dv_mag_ms: float = max(
            0.001,
            2.0 * (CONJUNCTION_THRESHOLD_KM - miss_distance_km) / CONJUNCTION_THRESHOLD_KM,
        )
        dv_rtn = np.array([0.0, dv_mag_ms / 1000.0, 0.0])   # convert m/s → km/s in T̂

        # ── 3. Evasion burn: propagate to burn_time for accurate RTN frame ─────
        # Critical: compute T̂ as it will be at burn execution, not at current epoch.
        # In LEO the RTN frame rotates ≈ 4°/min; a 30-min lead yields ≈ 120° rotation.
        dt_to_burn: float = (burn_time - current_time).total_seconds()
        if self.propagator is not None and dt_to_burn > 0:
            burn_sv  = self.propagator.propagate(satellite.state_vector, dt_to_burn)
            burn_pos = burn_sv[:3]
            burn_vel = burn_sv[3:]
        else:
            burn_pos = satellite.position
            burn_vel = satellite.velocity

        dv_eci = self.rtn_to_eci(burn_pos, burn_vel, dv_rtn)

        # ── 4. Recovery burn: −T applied 45 min later ─────────────────────────
        recovery_time    = burn_time + timedelta(seconds=2700.0)
        dv_rtn_recovery  = -dv_rtn

        dt_to_recovery: float = (recovery_time - current_time).total_seconds()
        if self.propagator is not None and dt_to_recovery > 0:
            recovery_sv  = self.propagator.propagate(satellite.state_vector, dt_to_recovery)
            recovery_pos = recovery_sv[:3]
            recovery_vel = recovery_sv[3:]
        else:
            recovery_pos = satellite.position
            recovery_vel = satellite.velocity

        dv_eci_recovery = self.rtn_to_eci(recovery_pos, recovery_vel, dv_rtn_recovery)

        maneuvers = [
            {
                "burn_id":     f"EVASION_{debris.id}_{burn_time.strftime('%H%M%S')}",
                "burnTime":    burn_time.isoformat(),
                "deltaV_vector": {
                    "x": float(dv_eci[0]),
                    "y": float(dv_eci[1]),
                    "z": float(dv_eci[2]),
                },
            },
            {
                "burn_id":     f"RECOVERY_{debris.id}_{recovery_time.strftime('%H%M%S')}",
                "burnTime":    recovery_time.isoformat(),
                "deltaV_vector": {
                    "x": float(dv_eci_recovery[0]),
                    "y": float(dv_eci_recovery[1]),
                    "z": float(dv_eci_recovery[2]),
                },
            },
        ]

        logger.info(
            "PLANNER | %s | Evasion ΔV=%.4f m/s | Avoidance to %s",
            satellite.id, dv_mag_ms, debris.id,
        )
        return maneuvers

    # ── Burn validation ───────────────────────────────────────────────────────

    def validate_burn(
        self,
        delta_v_magnitude_ms: float,
        burn_time: datetime,
        current_time: datetime,
        last_burn_time: datetime | None,
        has_los: bool,
    ) -> tuple[bool, str]:
        """Validate a commanded burn against all operational constraints.

        Constraint checks (in order of rejection precedence):
            1. Max ΔV per burn:   |Δv| ≤ 15 m/s        (PRD §4.5)
            2. Signal latency:    burn_time − now ≥ 10 s (PRD §4.4)
            3. Thruster cooldown: burn_time − last_burn ≥ 600 s (PRD §4.5)
            4. Ground-station LOS required at burn time (PRD §4.4)

        Fuel sufficiency is intentionally NOT checked here — it is the caller's
        responsibility to call FuelTracker.sufficient_fuel() separately, because
        FuelTracker owns the propellant state.

        Args:
            delta_v_magnitude_ms: Requested ΔV magnitude in m/s.
            burn_time:            Requested burn execution time (UTC).
            current_time:         Current simulation clock time (UTC).
            last_burn_time:       Time of last completed or queued burn, or None.
            has_los:              True if a ground station has LOS at burn_time.

        Returns:
            (is_valid, rejection_reason) — reason is "OK" if valid.
        """
        if abs(delta_v_magnitude_ms) > MAX_DV_PER_BURN:
            return False, f"Exceeds max thrust ({MAX_DV_PER_BURN} m/s)"

        time_until_burn = (burn_time - current_time).total_seconds()
        if time_until_burn < SIGNAL_LATENCY_S:
            return False, f"Violates {SIGNAL_LATENCY_S}s signal latency"

        if last_burn_time is not None:
            cooldown_elapsed = (burn_time - last_burn_time).total_seconds()
            if cooldown_elapsed <= THRUSTER_COOLDOWN_S:
                return False, f"Violates {THRUSTER_COOLDOWN_S}s thruster cooldown"

        if not has_los:
            return False, "No ground station LOS at burn time"

        return True, "OK"
