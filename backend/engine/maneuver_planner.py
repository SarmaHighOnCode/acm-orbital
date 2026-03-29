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
        r_mag = np.linalg.norm(r_eci)
        if r_mag < 1e-10:
            return dv_rtn  # Degenerate: return RTN as-is
        R_hat: np.ndarray = r_eci / r_mag
        h: np.ndarray     = np.cross(r_eci, v_eci)
        h_mag = np.linalg.norm(h)
        if h_mag < 1e-10:
            return dv_rtn  # Zero angular momentum: cannot define RTN frame
        N_hat: np.ndarray = h / h_mag
        T_hat: np.ndarray = np.cross(N_hat, R_hat)
        Q: np.ndarray     = np.column_stack([R_hat, T_hat, N_hat])
        return Q @ dv_rtn

    # ── Fleet-level coordination ────────────────────────────────────────

    @staticmethod
    def select_fleet_optimal_evasions(
        cdm_groups: dict[str, list],
        fuel_remaining: dict[str, float],
    ) -> dict[str, object]:
        """Pick the single most fuel-efficient threat to evade per satellite.

        When multiple CDMs target the same satellite simultaneously, this
        method selects the one whose evasion delta-v will be smallest —
        minimising total fleet fuel expenditure (Rubric §2: Fuel Efficiency).

        For sat-vs-sat conjunctions, the satellite with MORE remaining fuel
        is assigned the evasion; the other holds course.

        Args:
            cdm_groups: {sat_id: [CDM, ...]} grouped threats per satellite.
            fuel_remaining: {sat_id: fuel_kg} current fuel state.

        Returns:
            {sat_id: CDM} — the single CDM each satellite should evade.
        """
        assignments: dict[str, object] = {}

        for sat_id, cdms in cdm_groups.items():
            if not cdms:
                continue

            # Score each CDM: prefer the one requiring the smallest evasion
            # delta-v ≈ proportional to (threshold / miss_distance) — closer
            # misses need larger burns.  Also penalise very short TCA lead
            # times (less room for optimal timing).
            best_cdm = None
            best_score = float('inf')

            for cdm in cdms:
                miss = max(cdm.miss_distance_km, 1e-6)
                # Lower miss → higher required dv → higher score (worse)
                dv_proxy = 0.1 / miss  # km/s rough scale

                # Sat-vs-sat: only the fuel-richer satellite should evade
                if hasattr(cdm, 'debris_id') and cdm.debris_id in fuel_remaining:
                    peer_id = cdm.debris_id if cdm.satellite_id == sat_id else cdm.satellite_id
                    if peer_id in fuel_remaining:
                        peer_fuel = fuel_remaining.get(peer_id, 0)
                        my_fuel = fuel_remaining.get(sat_id, 0)
                        if peer_fuel > my_fuel + 2.0:
                            # Peer is healthier; skip — peer will handle it
                            continue

                if dv_proxy < best_score:
                    best_score = dv_proxy
                    best_cdm = cdm

            if best_cdm is not None:
                assignments[sat_id] = best_cdm

        return assignments

    # ── Evasion planning ──────────────────────────────────────────────────────

    def plan_evasion(
        self,
        satellite: 'Satellite',
        debris: 'Debris',
        tca: datetime,
        miss_distance_km: float,
        current_time: datetime,
    ) -> list[dict]:
        """Calculate an evasion + recovery burn pair for a CRITICAL conjunction.

        Optimizations (v2):
            1. Optimal burn timing: search [TCA-3h, TCA-10min] in 5-min steps,
               pick the time with lowest delta-v that has ground station LOS.
            2. Minimum-energy evasion: target 200m miss distance (2× threshold)
               using physics-based linear phasing approximation.
            3. Dynamic recovery: recover as soon as debris is 50 km away
               (typically TCA+5-10min) instead of fixed 45-min delay.

        Args:
            satellite:       Satellite data object (position, velocity, state_vector).
            debris:          Debris data object (id used for burn labelling).
            tca:             Predicted Time of Closest Approach (UTC datetime).
            miss_distance_km: Miss distance at TCA in km (from CDM).
            current_time:    Present simulation clock time (UTC datetime).

        Returns:
            List of burn dicts: [evasion_burn(s), recovery_burn], each with
            keys: burn_id, burnTime (ISO-8601), deltaV_vector {x, y, z} (km/s).
        """
        # ── 1. Optimal Burn Timing Search ────────────────────────────────────
        # Search [TCA-3h, TCA-10min] in 5-minute steps for the lowest delta-v
        # that achieves 200m miss distance while having LOS.
        TARGET_MISS_KM: float = CONJUNCTION_THRESHOLD_KM * 2.0   # 200 m
        earliest_burn_time = current_time + timedelta(seconds=SIGNAL_LATENCY_S)

        if tca <= earliest_burn_time:
            logger.warning("PLANNER | %s | TCA is before signal latency. Unresolvable.", satellite.id)
            return []

        # Import ground station network for LOS checks during planning
        from engine.ground_stations import GroundStationNetwork
        gs_network = GroundStationNetwork()

        best_burn_time = None
        best_dv_ms = float('inf')

        # Search window: from earliest possible up to 2 hours, 5-min steps
        search_start = earliest_burn_time
        search_end   = min(search_start + timedelta(seconds=7200), tca - timedelta(seconds=600))

        if search_end < search_start:
            search_end = earliest_burn_time

        t_candidate = search_start
        while t_candidate <= search_end:
            dt_lead = (tca - t_candidate).total_seconds()
            if dt_lead <= 0:
                t_candidate += timedelta(seconds=300)
                continue

            # Physics-based delta-v: ΔV = target_miss / dt_lead
            # This gives the cross-track displacement needed to achieve target miss
            # distance. Works for both co-orbital (CW phasing) and crossing
            # (head-on retrograde) encounter geometries.
            candidate_dv_ms = (TARGET_MISS_KM / dt_lead) * 1000.0

            # Ensure minimum effectiveness (1 m/s floor for very long lead times)
            candidate_dv_ms = max(1.0, candidate_dv_ms)

            # Check LOS: propagate satellite to candidate time to get position
            dt_from_now = (t_candidate - current_time).total_seconds()
            if self.propagator is not None and dt_from_now > 0:
                try:
                    pos_at_t = self.propagator.propagate(
                        satellite.state_vector, dt_from_now
                    )[:3]
                except Exception:
                    pos_at_t = satellite.position
            else:
                pos_at_t = satellite.position

            has_los = gs_network.check_line_of_sight(pos_at_t, t_candidate)

            if has_los and candidate_dv_ms < best_dv_ms:
                best_dv_ms = candidate_dv_ms
                best_burn_time = t_candidate

            t_candidate += timedelta(seconds=300)

        # Fallback: if no optimal time found, use TCA-30min or earliest possible
        if best_burn_time is None:
            best_burn_time = max(earliest_burn_time, tca - timedelta(seconds=1800))
            dt_lead = max(1.0, (tca - best_burn_time).total_seconds())
            best_dv_ms = max(2.0, (TARGET_MISS_KM / dt_lead) * 1000.0)

        burn_time = best_burn_time
        dv_mag_ms = best_dv_ms

        logger.info(
            "PLANNER | %s | Optimal burn at TCA-%.0fs (dv=%.2f m/s vs TCA-30min)",
            satellite.id, (tca - burn_time).total_seconds(), dv_mag_ms,
        )

        # ── 2. Evasion Burns: handle magnitude > 15 m/s by splitting ────────
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
                if current_burn_time >= tca - timedelta(seconds=60):
                    break

        # ── 3. Dynamic Recovery Timing ───────────────────────────────────────
        # Instead of fixed 45-min delay, recover when debris is 50km away
        # (typically TCA+5-10min). Massive uptime improvement.
        last_evasion_time = datetime.fromisoformat(
            burn_sequences[-1]["burnTime"].replace("Z", "+00:00")
        )
        recovery_base_time = tca + timedelta(seconds=300)  # TCA + 5min default

        # Try to compute when debris recedes past 50 km
        if self.propagator is not None:
            dt_tca = (tca - current_time).total_seconds()
            if dt_tca > 0:
                # Propagate both objects to TCA, then check separation at TCA+N
                for dt_after in range(60, 3600, 60):  # 1min to 60min post-TCA
                    t_check = dt_tca + dt_after
                    try:
                        sat_pos = self.propagator.propagate(
                            satellite.state_vector, t_check
                        )[:3]
                        deb_pos = self.propagator.propagate(
                            debris.state_vector, t_check
                        )[:3]
                        sep = float(np.linalg.norm(sat_pos - deb_pos))
                        if sep > 50.0:
                            recovery_base_time = tca + timedelta(seconds=dt_after + 60)
                            break
                    except Exception:
                        break

        # Ensure recovery respects cooldown from last evasion burn
        min_recovery = last_evasion_time + timedelta(seconds=THRUSTER_COOLDOWN_S + 10)
        recovery_time = max(recovery_base_time, min_recovery)

        maneuvers = []
        for evasion in burn_sequences:
            maneuvers.append({k: v for k, v in evasion.items() if k != "mag_ms"})

        # Propagate satellite vector strictly through the evasion maneuvers
        sat_state_cursor = satellite.state_vector.copy()
        t_cursor = current_time
        
        for e in burn_sequences:
            bt = datetime.fromisoformat(e["burnTime"].replace("Z", "+00:00"))
            dt = (bt - t_cursor).total_seconds()
            if self.propagator is not None and dt > 0:
                sat_state_cursor = self.propagator.propagate(sat_state_cursor, dt)
            sat_state_cursor[3:] += np.array([e["deltaV_vector"]["x"], e["deltaV_vector"]["y"], e["deltaV_vector"]["z"]])
            t_cursor = bt
            
        sat_state_after_evasion = sat_state_cursor
        
        max_attempts = 3
        recovery_shift_s = 0.0
        final_rec_burns = []
        final_recovery_time = recovery_time
        
        for attempt in range(max_attempts):
            test_recovery_time = recovery_time + timedelta(seconds=recovery_shift_s)
            
            # Propagate to test_recovery_time
            dt_final = (test_recovery_time - t_cursor).total_seconds()
            if self.propagator is not None and dt_final > 0:
                sat_state_at_rec = self.propagator.propagate(sat_state_after_evasion, dt_final)
            else:
                sat_state_at_rec = sat_state_after_evasion.copy()
                
            dt_nom = (test_recovery_time - current_time).total_seconds()
            if self.propagator is not None and dt_nom > 0:
                nom_state_at_rec = self.propagator.propagate(satellite.nominal_state, dt_nom)
            else:
                nom_state_at_rec = satellite.nominal_state.copy()
                
            rec_burns = self.plan_return_to_slot(
                satellite=satellite,
                nominal_state=satellite.nominal_state,
                current_time=test_recovery_time,
                override_state=sat_state_at_rec,
                override_nominal=nom_state_at_rec
            )
            
            # Check for secondary conjunction checking first 1hr of return transfer
            if rec_burns and self.propagator is not None:
                bt1 = test_recovery_time + timedelta(seconds=SIGNAL_LATENCY_S)
                dt_to_burn1 = (bt1 - test_recovery_time).total_seconds()
                
                sv_before_burn1 = self.propagator.propagate(sat_state_at_rec, dt_to_burn1)
                dv_vec1 = np.array([rec_burns[0]["deltaV_vector"]["x"], rec_burns[0]["deltaV_vector"]["y"], rec_burns[0]["deltaV_vector"]["z"]])
                post_burn1_sv = np.concatenate([sv_before_burn1[:3], sv_before_burn1[3:] + dv_vec1])
                
                dt_to_burn1_global = (bt1 - current_time).total_seconds()
                collision_risk = False
                for dt_fwd in range(60, 5400, 60):
                    sat_fwd = self.propagator.propagate(post_burn1_sv, dt_fwd)[:3]
                    deb_fwd = self.propagator.propagate(debris.state_vector, dt_to_burn1_global + dt_fwd)[:3]
                    if float(np.linalg.norm(sat_fwd - deb_fwd)) < 5.0:
                        collision_risk = True
                        break
                        
                if not collision_risk:
                    final_rec_burns = rec_burns
                    final_recovery_time = test_recovery_time
                    break
                else:
                    recovery_shift_s += 5400.0
            else:
                final_rec_burns = rec_burns
                final_recovery_time = test_recovery_time
                break
        else:
            final_rec_burns = rec_burns
            final_recovery_time = test_recovery_time
            
        for rb in final_rec_burns:
            maneuvers.append({k: v for k, v in rb.items() if not k.startswith('_')})

        logger.info(
            "PLANNER | %s | Evasion (ΔV=%.2f m/s, %d burns) | Recovery at TCA+%.0fs",
            satellite.id, dv_mag_ms, len(burn_sequences),
            (recovery_time - tca).total_seconds(),
        )
        return maneuvers

    # ── Return-to-Slot (Station Keeping) ──────────────────────────────────────

    def plan_return_to_slot(
        self,
        satellite,
        nominal_state: np.ndarray,
        current_time: datetime,
        override_state: np.ndarray | None = None,
        override_nominal: np.ndarray | None = None,
    ) -> list[dict]:
        """Plan a two-impulse phasing maneuver to return to the nominal slot.
        
        Uses Clohessy-Wiltshire (Hill's) equations to resolve the relative
        position and velocity offsets. PRD §4.7 requirement.
        
        Target duration: 1 orbital period (≈ 92 min for LEO).
        """
        # 1. State setup
        r_sat = override_state[:3] if override_state is not None else satellite.position
        v_sat = override_state[3:] if override_state is not None else satellite.velocity
        r_nom = override_nominal[:3] if override_nominal is not None else nominal_state[:3]
        v_nom = override_nominal[3:] if override_nominal is not None else nominal_state[3:]
        
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
        # Recompute RTN frame at the burn epoch (not planning epoch) for accuracy
        if self.propagator:
            sv_at_b1 = self.propagator.propagate(
                override_state if override_state is not None else satellite.state_vector,
                SIGNAL_LATENCY_S,
            )
            nom_at_b1 = self.propagator.propagate(nominal_state, SIGNAL_LATENCY_S)
            r_hat_b1 = nom_at_b1[:3] / np.linalg.norm(nom_at_b1[:3])
            h_b1 = np.cross(nom_at_b1[:3], nom_at_b1[3:])
            n_hat_b1 = h_b1 / np.linalg.norm(h_b1)
            t_hat_b1 = np.cross(n_hat_b1, r_hat_b1)
            Q_b1 = np.column_stack([r_hat_b1, t_hat_b1, n_hat_b1])
            dv_eci1 = Q_b1 @ delta_v1_rtn
        else:
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
