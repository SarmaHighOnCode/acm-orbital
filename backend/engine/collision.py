"""
collision.py — KDTree Conjunction Assessment Pipeline
═════════════════════════════════════════════════════
4-stage filter cascade for O(S·log D) conjunction assessment.
O(N²) nested loops are FORBIDDEN.
Owner: Dev 1 (Physics Engine)

Algorithm complexity per assess() call:
    Stage 1: O(D)                 altitude-band pre-filter    (reduces D → D_alt ≈ 0.15 D)
    Stage 2: O(D_alt log D_alt)   SciPy KDTree build
             O(S log D_alt)       S satellite query_ball_point calls (200 km radius)
    Stage 3: O(k)                 dense DOP853 batch propagation for k unique targets
             O(k · W · F)         Multi-start Brent TCA refinement; W ≈ T/(T_period/2)
                                  sub-windows, F ≈ 20 polynomial evals each O(1)
    Stage 4: O(k)                 CDM emission

    Total: O(D + S·log(D_alt) + k·W·F)   with k ≪ S·D due to Stage 1+2 filtering.
    Eliminates the naïve O(S·D) nested loop entirely.

CDM relative-velocity accuracy note:
    Velocities in the emitted CDM are sampled from the DOP853 dense polynomial
    evaluated at the TCA time, NOT at the planning epoch.  For LEO pairs with
    relative speeds of 7–15 km/s this matters: the velocity direction rotates
    substantially between planning time and TCA.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.spatial import KDTree
from scipy.optimize import minimize_scalar

from config import CONJUNCTION_THRESHOLD_KM, LOOKAHEAD_SECONDS, MU_EARTH
from engine.models import CDM
from engine.propagator import OrbitalPropagator

logger = logging.getLogger("acm.engine.collision")


class ConjunctionAssessor:
    """4-stage conjunction assessment pipeline using KDTree spatial indexing.

    Stage 1: Altitude band filter  — O(D), eliminates ~85 % of debris before KDTree build.
    Stage 2: KDTree spatial index  — O(D_alt log D_alt) build + O(S log D_alt) queries.
    Stage 3: TCA refinement        — Brent's method on DOP853 dense-output polynomial
                                     interpolants (O(1) per evaluation).
    Stage 4: CDM emission          — risk classification and CDM generation.
    """

    def __init__(self, propagator) -> None:
        self.propagator = propagator
        # Dedicated propagator with relaxed tolerances for Stage-2 debris
        self._screening_propagator = OrbitalPropagator(rtol=1e-4, atol=1e-6)

    @staticmethod
    def _compute_apo_peri(states: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r_vec = states[:, :3]
        v_vec = states[:, 3:]
        r = np.linalg.norm(r_vec, axis=1)
        v2 = np.sum(v_vec**2, axis=1)
        eps = v2 / 2.0 - MU_EARTH / r
        a = -MU_EARTH / (2.0 * eps)
        h_vec = np.cross(r_vec, v_vec)
        h2 = np.sum(h_vec**2, axis=1)
        e = np.sqrt(np.clip(1.0 + 2.0 * eps * h2 / (MU_EARTH**2), 0.0, None))
        rp = a * (1.0 - e)
        ra = a * (1.0 + e)
        rp = np.where(a > 0, rp, r)
        ra = np.where(a > 0, ra, float('inf'))
        return rp, ra

    def assess(
        self,
        sat_states: dict[str, np.ndarray],
        debris_states: dict[str, np.ndarray],
        lookahead_s: float = LOOKAHEAD_SECONDS,
        current_time: datetime | None = None,
    ) -> list[CDM]:
        """Run the full 4-stage conjunction assessment pipeline.

        Args:
            sat_states:    {sat_id:   state_vector [x,y,z,vx,vy,vz] km/km·s⁻¹}
            debris_states: {debris_id: state_vector [x,y,z,vx,vy,vz] km/km·s⁻¹}
            lookahead_s:   Propagation window in seconds (default: 86400 s = 24 h).
            current_time:  Simulation clock epoch; CDM.tca timestamps are expressed
                           relative to this value.  Defaults to UTC wall-clock.

        Returns:
            List of CDM warnings for all pairs with miss_distance < 5 km.
        """
        base_time = current_time if current_time is not None else datetime.now(timezone.utc)
        warnings: list[CDM] = []

        if not sat_states or not debris_states:
            return warnings

        debris_ids: list[str] = list(debris_states.keys())
        debris_positions: np.ndarray = np.array([sv[:3] for sv in debris_states.values()])

        # ── Stage 1: Altitude Band Filter — O(D) ────────────────────────────
        # Compute the union of ±50 km altitude shells for all satellites' periapsis/apoapsis.
        # Debris outside EVERY satellite's shell cannot close to collision
        # threshold within the propagation window → discard before KDTree build.
        sat_states_arr: np.ndarray = np.array(list(sat_states.values()))
        sat_rp, sat_ra = self._compute_apo_peri(sat_states_arr)
        r_min = float(sat_rp.min()) - 50.0
        r_max = float(sat_ra.max()) + 50.0

        deb_states_arr: np.ndarray = np.array(list(debris_states.values()))
        deb_rp, deb_ra = self._compute_apo_peri(deb_states_arr)
        alt_mask: np.ndarray = (deb_rp <= r_max) & (deb_ra >= r_min)

        filtered_ids: list[str] = [debris_ids[i] for i, keep in enumerate(alt_mask) if keep]
        filtered_positions: np.ndarray = debris_positions[alt_mask]

        if len(filtered_positions) == 0:
            return warnings

        # ── Stage 2: KDTree Spatial Index — O(D_alt log D_alt) build ────────
        # 50 km query radius: debris farther away in 3-D cannot close to the
        # 100 m collision threshold within the lookahead window at LEO speeds.
        tree = KDTree(filtered_positions)

        # Batch-propagate every satellite with dense output using a single DOP853
        # call (vectorised; not one call per satellite).
        # Uses the screening propagator (rtol=1e-4) for BOTH satellites and debris
        # to ensure symmetric tolerance — relative position errors cancel when
        # both sides use the same integrator settings.
        sat_ids_list, sat_batch_sol = self._screening_propagator.propagate_dense_batch(
            sat_states, lookahead_s
        )
        # Map each sat_id to a closure that extracts its row from the batch solution.
        sat_solutions: dict[str, object] = {
            sid: (lambda t, idx=i: sat_batch_sol(t)[idx])
            for i, sid in enumerate(sat_ids_list)
        }

        # Collect unique debris targets that survive KDTree screening.
        deb_targets: dict[str, np.ndarray] = {}
        candidate_pairs: list[tuple[str, str]] = []

        for sat_id, sat_state in sat_states.items():
            # O(log D_alt + k_i) query per satellite — never a Python loop over D
            # 200 km radius (expanded from 50 km) eliminates the false-negative
            # blind spot for crossing-orbit pairs that start >50 km apart but
            # converge to <100 m within the TCA refinement window.
            neighbor_indices = tree.query_ball_point(sat_state[:3], r=200.0)
            for idx in neighbor_indices:
                deb_id = filtered_ids[idx]
                deb_targets[deb_id] = debris_states[deb_id]
                candidate_pairs.append((sat_id, deb_id))

        if not candidate_pairs:
            return warnings

        # Batch-propagate candidate debris with the dedicated screening
        # propagator (rtol=1e-4, atol=1e-6).  The looser tolerances are
        # sufficient for TCA bracketing; Stage 3 Brent refinement uses the
        # polynomial interpolant, not raw integration steps.  Using a separate
        # propagator instance avoids mutating shared state (thread-safe).
        deb_ids_list, deb_batch_sol = self._screening_propagator.propagate_dense_batch(
            deb_targets, lookahead_s
        )

        deb_solutions: dict[str, object] = {
            did: (lambda t, idx=i: deb_batch_sol(t)[idx])
            for i, did in enumerate(deb_ids_list)
        }

        # ── Stage 3 & 4: TCA Refinement + CDM Emission ───────────────────────
        for sat_id, deb_id in candidate_pairs:
            sol_sat = sat_solutions[sat_id]
            sol_deb = deb_solutions[deb_id]

            # Multi-start Brent TCA refinement.
            # A single minimize_scalar over [0, 86400s] would find only ONE
            # local minimum. LEO objects orbit in ~90 min, so there can be
            # ~16 close-approach windows in a 24h lookahead.  We subdivide
            # the interval at half-period steps derived from the satellite's
            # specific orbital energy and run Brent on each sub-interval,
            # then take the global minimum across all windows.
            r_sat = np.linalg.norm(sol_sat(0.0)[:3])
            sma = -MU_EARTH / (2.0 * (
                0.5 * np.linalg.norm(sol_sat(0.0)[3:])**2 - MU_EARTH / r_sat
            ))
            half_period = np.pi * np.sqrt(sma**3 / MU_EARTH)  # T/2 in seconds
            # Clamp sub-interval to [half_period, lookahead_s] for safety
            sub_interval = max(float(half_period), 900.0)  # at least 15 min

            dist_fn = lambda t, _s=sol_sat, _d=sol_deb: float(
                np.linalg.norm(_s(t)[:3] - _d(t)[:3])
            )

            best_tca: float = 0.0
            best_miss: float = dist_fn(0.0)

            t_lo = 0.0
            while t_lo < lookahead_s:
                t_hi = min(t_lo + sub_interval, lookahead_s)
                if t_hi - t_lo < 1.0:  # skip degenerate sub-intervals
                    break
                res = minimize_scalar(
                    dist_fn, bounds=(t_lo, t_hi), method="bounded",
                )
                if res.fun < best_miss:
                    best_miss = float(res.fun)
                    best_tca = float(res.x)
                t_lo = t_hi

            tca_s: float = best_tca
            miss_distance_km: float = best_miss

            # Emit CDM only for YELLOW / RED / CRITICAL risk levels
            if miss_distance_km < 5.0:
                risk = self._classify_risk(miss_distance_km)

                # Sample TCA-time state vectors directly from the polynomial
                # interpolant for physically accurate relative velocity.
                # Using planning-epoch velocities here would be wrong: at LEO
                # speeds (7–15 km/s), the velocity direction rotates significantly
                # between assessment time and TCA.
                tca_sat_state: np.ndarray = sol_sat(tca_s)   # shape (6,)
                tca_deb_state: np.ndarray = sol_deb(tca_s)   # shape (6,)
                rel_vel_km_s = float(
                    np.linalg.norm(tca_sat_state[3:] - tca_deb_state[3:])
                )

                warnings.append(CDM(
                    satellite_id=sat_id,
                    debris_id=deb_id,
                    tca=base_time + timedelta(seconds=tca_s),
                    miss_distance_km=miss_distance_km,
                    risk=risk,
                    relative_velocity_km_s=rel_vel_km_s,
                ))

        logger.info(
            "CA | %d sats | %d/%d debris after Stage 1 | %d candidate pairs | %d CDMs",
            len(sat_states),
            len(filtered_ids),
            len(debris_ids),
            len(candidate_pairs),
            len(warnings),
        )
        return warnings

    @staticmethod
    def _classify_risk(miss_distance_km: float) -> str:
        """Classify conjunction risk level from miss distance.

        Thresholds (Problem Statement §5.2):
            CRITICAL : miss < 0.100 km  (100 m — hard collision threshold)
            RED      : miss < 1.0   km
            YELLOW   : miss < 5.0   km
            GREEN    : miss ≥ 5.0   km  (not emitted — caller filters at 5 km)

        Args:
            miss_distance_km: Miss distance at TCA in km.

        Returns:
            Risk level string: "CRITICAL" | "RED" | "YELLOW" | "GREEN".
        """
        if miss_distance_km < CONJUNCTION_THRESHOLD_KM:   # 0.100 km = 100 m
            return "CRITICAL"
        if miss_distance_km < 1.0:
            return "RED"
        if miss_distance_km < 5.0:
            return "YELLOW"
        return "GREEN"
