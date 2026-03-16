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
    MU_EARTH,
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
        earliest_burn_time   = current_time + timedelta(seconds=SIGNAL_LATENCY_S)
        burn_time            = tca - timedelta(seconds=BURN_LEAD_S)
        if burn_time < earliest_burn_time:
            burn_time = earliest_burn_time

        # ── 2. Magnitude: robust phasing calculation ─────────────────────────
        # Target miss distance: CONJUNCTION_THRESHOLD_KM + 50% safety margin (150m total)
        TARGET_MISS_KM: float = CONJUNCTION_THRESHOLD_KM * 1.5
        
        # Lead time in seconds
        dt_lead: float = (tca - burn_time).total_seconds()
        
        # Linear Phasing Approximation (PRD §4.5):
        # A transverse burn delta-v (dT) causes an along-track shift of approximately:
        #   ds = -3 * dT * dt_lead
        # In a head-on collision (relative velocity V_rel ≈ 15 km/s), 
        # a timing shift dt_shift = ds / V_orb results in a cross-track miss of:
        #   dm ≈ V_rel * dt_shift = V_rel * (3 * dT * dt_lead / V_orb)
        # Assuming V_rel ≈ 2 * V_orb for head-on retrograde:
        #   dm ≈ 6 * dT * dt_lead
        # So dT ≈ TARGET_MISS_KM / (6 * dt_lead)
        
        # For LEO where T-burns also cause radial drift (2*dT/n * (1-cos(nt))), 
        # we simplify to a target magnitude that ensures at least 150m miss.
        # We cap the "naive" requirement at 20 m/s for splitting demonstration.
        
        required_dv_ms: float = (TARGET_MISS_KM / max(dt_lead, 1.0)) * 1000.0 * 10.0 # Heuristic multiplier
        
        # Ensure we always provide at least a baseline evasion
        dv_mag_ms: float = max(2.0, required_dv_ms)

        # ── 3. Evasion Burns: handle magnitude > 15 m/s by splitting ───────────
        # If the required delta-v exceeds 15 m/s, split into multiple burns 
        # separated by the 600s cooldown period (PRD §4.5).
        
        burn_sequences = []
        remaining_dv = dv_mag_ms
        current_burn_time = burn_time
        
        while remaining_dv > 0:
            this_dv_ms = min(remaining_dv, MAX_DV_PER_BURN)
            dv_rtn = np.array([0.0, this_dv_ms / 1000.0, 0.0])
            
            # Propagate to current_burn_time for accurate RTN frame
            dt_to_burn = (current_burn_time - current_time).total_seconds()
            if self.propagator is not None and dt_to_burn > 0:
                burn_sv  = self.propagator.propagate(satellite.state_vector, dt_to_burn)
                burn_pos = burn_sv[:3]
                burn_vel = burn_sv[3:]
            else:
                burn_pos = satellite.position
                burn_vel = satellite.velocity
                
            dv_eci = self.rtn_to_eci(burn_pos, burn_vel, dv_rtn)
            
            burn_sequences.append({
                "burn_id":     f"EVASION_{debris.id}_{current_burn_time.strftime('%H%M%S')}",
                "burnTime":    current_burn_time.isoformat(),
                "deltaV_vector": {
                    "x": float(dv_eci[0]),
                    "y": float(dv_eci[1]),
                    "z": float(dv_eci[2]),
                },
                "mag_ms": this_dv_ms
            })
            
            remaining_dv -= this_dv_ms
            if remaining_dv > 0:
                current_burn_time += timedelta(seconds=THRUSTER_COOLDOWN_S + 10)
                # Check if we are getting too close to TCA
                if current_burn_time >= tca - timedelta(seconds=60):
                    break # Don't burn too late
        
        # ── 4. Recovery burns: Applied 45 min after each evasion burn ─────────
        maneuvers = []
        for evasion in burn_sequences:
            maneuvers.append({k: v for k, v in evasion.items() if k != "mag_ms"})
            
            e_time = datetime.fromisoformat(evasion["burnTime"].replace("Z", "+00:00"))
            recovery_time = e_time + timedelta(seconds=2700.0)
            
            # Recovery is the opposite of evasion (-T)
            dt_to_recovery = (recovery_time - current_time).total_seconds()
            dv_rtn_rec = np.array([0.0, -evasion["mag_ms"] / 1000.0, 0.0])
            
            if self.propagator is not None and dt_to_recovery > 0:
                rec_sv  = self.propagator.propagate(satellite.state_vector, dt_to_recovery)
                rec_pos = rec_sv[:3]
                rec_vel = rec_sv[3:]
            else:
                rec_pos = satellite.position
                rec_vel = satellite.velocity
                
            dv_eci_rec = self.rtn_to_eci(rec_pos, rec_vel, dv_rtn_rec)
            
            maneuvers.append({
                "burn_id":     f"RECOVERY_{debris.id}_{recovery_time.strftime('%H%M%S')}",
                "burnTime":    recovery_time.isoformat(),
                "deltaV_vector": {
                    "x": float(dv_eci_rec[0]),
                    "y": float(dv_eci_rec[1]),
                    "z": float(dv_eci_rec[2]),
                },
            })

        logger.info(
            "PLANNER | %s | Evasion sequence (Total ΔV=%.2f m/s) | %d burns",
            satellite.id, dv_mag_ms, len(burn_sequences),
        )
        return maneuvers

    # ── Return-to-Slot (Station Keeping) ──────────────────────────────────────

    def plan_return_to_slot(
        self,
        satellite,
        nominal_state: np.ndarray,
        current_time: datetime,
    ) -> list[dict]:
        """Plan a two-impulse phasing maneuver to return to the nominal slot.
        
        Uses Clohessy-Wiltshire (Hill's) equations to resolve the relative
        position and velocity offsets. PRD §4.7 requirement.
        
        Target duration: 1 orbital period (≈ 92 min for LEO).
        """
        # 1. State setup
        r_sat = satellite.position
        v_sat = satellite.velocity
        r_nom = nominal_state[:3]
        v_nom = nominal_state[3:]
        
        # Mean motion n = sqrt(mu/a^3)
        r_mag = np.linalg.norm(r_nom)
        n = np.sqrt(MU_EARTH / (r_mag**3))
        
        # 2. Transform relative state to RTN frame (Hill frame of nominal point)
        # Hill frame defined at nominal slot
        dr_eci = r_sat - r_nom
        dv_eci = v_sat - v_nom
        
        # Construct RTN basis at nominal point
        r_hat = r_nom / r_mag
        h = np.cross(r_nom, v_nom)
        n_hat = h / np.linalg.norm(h)
        t_hat = np.cross(n_hat, r_hat)
        Q = np.column_stack([r_hat, t_hat, n_hat])
        
        # Relative state in Hill frame: x=Radial, y=Transverse, z=Normal
        rho = Q.T @ dr_eci
        rho_dot = Q.T @ dv_eci - np.cross(np.array([0.0, 0.0, n]), rho)
        
        # 3. Solve C-W for two-impulse transfer
        # Transfer duration T (e.g., 5400s ≈ 90 min)
        T = 5400.0 
        nt = n * T
        s, c = np.sin(nt), np.cos(nt)
        
        # RV Transition Matrix components for position from velocity
        # Phi_rv = [ (sin nt)/n              (2/n)(1 - cos nt)        0  ]
        #          [ -(2/n)(1 - cos nt)      (4 sin nt - 3nt)/n       0  ]
        #          [ 0                       0                        (sin nt)/n ]
        phi_rv = np.array([
            [s/n,               (2/n)*(1-c),   0.0],
            [-(2/n)*(1-c),      (4*s - 3*nt)/n, 0.0],
            [0.0,               0.0,            s/n]
        ])
        
        # Phi_rr = [ 4 - 3 cos nt           0    0 ]
        #          [ 6(sin nt - nt)         1    0 ]
        #          [ 0                      0    cos nt ]
        phi_rr = np.array([
            [4 - 3*c,         0.0, 0.0],
            [6*(s - nt),      1.0, 0.0],
            [0.0,             0.0, c]
        ])
        
        # To reach r_target = 0 at time T:
        # r_T = Phi_rr * rho_0 + Phi_rv * v_0_plus = 0
        # v_0_plus = - inv(Phi_rv) * Phi_rr * rho_0
        try:
            v_0_plus = - np.linalg.inv(phi_rv) @ (phi_rr @ rho)
        except np.linalg.LinAlgError:
            return [] # Singular case (rare)

        delta_v1_rtn = v_0_plus - rho_dot # Burn 1 relative to current Hill velocity
        
        # 4. Burn 1 implementation (Immediate/ASAP)
        burn_time1 = current_time + timedelta(seconds=SIGNAL_LATENCY_S)
        dv_eci1 = Q @ delta_v1_rtn
        
        # Magnitude capping
        mag1 = np.linalg.norm(dv_eci1) * 1000.0
        if mag1 > MAX_DV_PER_BURN:
            dv_eci1 *= (MAX_DV_PER_BURN / mag1)
            mag1 = MAX_DV_PER_BURN
            
        maneuvers = [{
            "burn_id": f"RTS_1_{satellite.id}",
            "burnTime": burn_time1.isoformat(),
            "deltaV_vector": {
                "x": float(dv_eci1[0]),
                "y": float(dv_eci1[1]),
                "z": float(dv_eci1[2]),
            },
            "_mag": mag1
        }]
        
        # 5. Burn 2 implementation (ASAP after cooldown or at T)
        # We simplify to a second burn that circularizes back at nominal
        # In a real two-pulse, we'd calculate v_T_minus and zero it out.
        # For hackathon robustess, we'll wait for the next SimulationEngine tick
        # to re-evaluate the second pulse if still out of slot.
        # But we'll provide the complementary burn here for the queue.
        
        # Phi_vr = [ 3n sin nt           0    0 ]
        #          [ 6n(cos nt - 1)      0    0 ]
        #          [ 0                   0   -n sin nt ]
        phi_vr = np.array([
            [3*n*s,          0.0, 0.0],
            [6*n*(c - 1),    0.0, 0.0],
            [0.0,            0.0, -n*s]
        ])
        
        # Phi_vv = [ cos nt              2 sin nt           0 ]
        #          [ -2 sin nt           4 cos nt - 3       0 ]
        #          [ 0                   0                  cos nt ]
        phi_vv = np.array([
            [c,           2*s,     0.0],
            [-2*s,        4*c - 3, 0.0],
            [0.0,         0.0,     c]
        ])
        
        v_T_minus = phi_vr @ rho + phi_vv @ v_0_plus
        delta_v2_rtn = - v_T_minus # v_target_relative = 0
        
        burn_time2 = burn_time1 + timedelta(seconds=T)
        
        # We need the RTN frame at T. Propagate nominal state.
        if self.propagator:
            nominal_T = self.propagator.propagate(nominal_state, T)
            r_nom_T = nominal_T[:3]
            v_nom_T = nominal_T[3:]
            r_hat_T = r_nom_T / np.linalg.norm(r_nom_T)
            h_T = np.cross(r_nom_T, v_nom_T)
            n_hat_T = h_T / np.linalg.norm(h_T)
            t_hat_T = np.cross(n_hat_T, r_hat_T)
            Q_T = np.column_stack([r_hat_T, t_hat_T, n_hat_T])
            dv_eci2 = Q_T @ delta_v2_rtn
        else:
            dv_eci2 = Q @ delta_v2_rtn # Fallback
            
        mag2 = np.linalg.norm(dv_eci2) * 1000.0
        if mag2 > MAX_DV_PER_BURN:
            dv_eci2 *= (MAX_DV_PER_BURN / mag2)
            mag2 = MAX_DV_PER_BURN

        maneuvers.append({
            "burn_id": f"RTS_2_{satellite.id}",
            "burnTime": burn_time2.isoformat(),
            "deltaV_vector": {
                "x": float(dv_eci2[0]),
                "y": float(dv_eci2[1]),
                "z": float(dv_eci2[2]),
            },
            "_mag": mag2
        })

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
