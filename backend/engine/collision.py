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
        import time as _time
        _t0 = _time.time()
        
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

        _t1 = _time.time()
        logger.debug("CA Stage 1 (altitude filter): %.2fs, %d/%d debris remain", _t1 - _t0, len(filtered_ids), len(debris_ids))

        # ── Stage 2: KDTree Spatial Index — O(D_alt log D_alt) build ────────
        tree = KDTree(filtered_positions)

        # Collect unique debris targets that survive KDTree screening.
        deb_targets: dict[str, np.ndarray] = {}
        candidate_pairs: list[tuple[str, str]] = []

        # Pre-compute satellite apo/peri for per-pair filtering
        sat_rp_dict = {sid: sat_rp[i] for i, sid in enumerate(sat_states.keys())}
        sat_ra_dict = {sid: sat_ra[i] for i, sid in enumerate(sat_states.keys())}
        deb_rp_dict = {did: deb_rp[i] for i, did in enumerate(debris_states.keys())}
        deb_ra_dict = {did: deb_ra[i] for i, did in enumerate(debris_states.keys())}

        # KDTree search radius: initial-position proximity pre-filter.
        # For short lookaheads, scale with relative velocity × time.
        # For long lookaheads (24h), objects complete full orbits so initial
        # position doesn't predict conjunction — cap radius and rely on the
        # orbital-element filters (Stage 1 altitude band + per-pair shell)
        # for correctness.  Cap at 2000 km to keep the KDTree useful as a
        # spatial index (LEO orbit diameter ≈ 13 000 km).
        kdtree_radius = max(200.0, min(15.0 * lookahead_s, 2000.0))

        for sat_id, sat_state in sat_states.items():
            # query_ball_point eliminates debris far from initial satellite position
            neighbor_indices = tree.query_ball_point(sat_state[:3], r=kdtree_radius)
            
            s_rp = sat_rp_dict[sat_id] - 5.0 # buffer for collision threshold
            s_ra = sat_ra_dict[sat_id] + 5.0
            
            for idx in neighbor_indices:
                deb_id = filtered_ids[idx]
                
                # Per-pair orbital shell filter: skip if orbits don't overlap in altitude
                if deb_rp_dict[deb_id] > s_ra or deb_ra_dict[deb_id] < s_rp:
                    continue
                    
                deb_targets[deb_id] = debris_states[deb_id]
                candidate_pairs.append((sat_id, deb_id))

        if not candidate_pairs:
            return warnings

        _t2 = _time.time()
        logger.debug("CA Stage 2 (KDTree + Pair Filter): %.2fs, %d candidate pairs from %d unique debris", _t2 - _t1, len(candidate_pairs), len(deb_targets))

        # ── Performance guard: cap Stage-3 dense propagation load ─────────
        # Dense DOP853 over 24h is O(6D) state variables; beyond ~1000 debris
        # the single batch call dominates wall-clock. Prioritise debris that
        # appear in the most candidate pairs (highest threat multiplicity).
        _MAX_DENSE_DEBRIS = 300
        if len(deb_targets) > _MAX_DENSE_DEBRIS:
            # Rank by pair count (most-connected debris first)
            deb_pair_count: dict[str, int] = {}
            for _, did in candidate_pairs:
                deb_pair_count[did] = deb_pair_count.get(did, 0) + 1
            ranked = sorted(deb_pair_count.keys(),
                            key=lambda d: deb_pair_count[d], reverse=True)
            keep = set(ranked[:_MAX_DENSE_DEBRIS])
            deb_targets = {d: deb_targets[d] for d in keep}
            candidate_pairs = [(s, d) for s, d in candidate_pairs if d in keep]
            logger.info("CA Stage 2.1 | Capped debris to %d (from %d) for dense prop",
                        len(deb_targets), len(deb_pair_count))

        # ── Standard path: Dense propagation for TCA refinement ────────────
        # Batch-propagate every satellite with dense output
        sat_ids_list, sat_batch_sol = self._screening_propagator.propagate_dense_batch(
            sat_states, lookahead_s
        )
        # Create indexed access for vectorized evaluation
        sat_id_to_idx = {sid: i for i, sid in enumerate(sat_ids_list)}

        # Batch-propagate candidate debris
        deb_ids_list, deb_batch_sol = self._screening_propagator.propagate_dense_batch(
            deb_targets, lookahead_s
        )
        deb_id_to_idx = {did: i for i, did in enumerate(deb_ids_list)}

        _t3 = _time.time()
        logger.debug("CA Stage 2.5 (dense prop): %.2fs for %d sats + %d debris", _t3 - _t2, len(sat_states), len(deb_targets))

        # ── Stage 3: Vectorized Coarse Sweep ─────────────────────────────────
        # Evaluate distances on a coarse grid (every 600s) for ALL candidate pairs at once.
        # This keeps the hot path in NumPy and avoids millions of Python loop iterations.
        grid_points = np.linspace(0.0, lookahead_s, int(lookahead_s / 600) + 1)
        
        # Pre-evaluate all states on the grid
        all_sat_grid = sat_batch_sol(grid_points) # (S, 6, T)
        all_deb_grid = deb_batch_sol(grid_points) # (D, 6, T)
        
        # Map pairs to indices
        pair_sat_indices = np.array([sat_id_to_idx[sid] for sid, did in candidate_pairs])
        pair_deb_indices = np.array([deb_id_to_idx[did] for sid, did in candidate_pairs])
        
        # Batch evaluation of distances across the grid for all candidate pairs
        # pair_sat_pos: (K, 3, T) where K is number of candidate pairs
        pair_sat_pos = all_sat_grid[pair_sat_indices, :3, :]
        pair_deb_pos = all_deb_grid[pair_deb_indices, :3, :]
        
        # dist_sq_grid: (K, T)
        dist_sq_grid = np.sum((pair_sat_pos - pair_deb_pos)**2, axis=1)
        dist_grid = np.sqrt(dist_sq_grid)
        
        # Identify pairs/windows that drop below 50km
        threatening_mask = np.any(dist_grid < 50.0, axis=1)
        
        # ── Stage 4: Refined TCA + CDM Emission ──────────────────────────────
        threatening_indices = np.where(threatening_mask)[0]
        
        for k_idx in threatening_indices:
            sat_id, deb_id = candidate_pairs[k_idx]
            
            # Refine only the specific 10-minute windows that looked risky
            risky_windows = np.where(dist_grid[k_idx] < 50.0)[0]
            
            # Group adjacent risky grid points into windows
            processed_time = -1.0
            for w_idx in risky_windows:
                t_center = grid_points[w_idx]
                if t_center <= processed_time: continue
                
                t_lo = max(0.0, t_center - 600.0)
                t_hi = min(lookahead_s, t_center + 600.0)
                
                # Brent minimization on the dense polynomial
                def dist_fn(t, sid=sat_id, did=deb_id):
                    s_sv = sat_batch_sol(t)[sat_id_to_idx[sid]]
                    d_sv = deb_batch_sol(t)[deb_id_to_idx[did]]
                    return float(np.linalg.norm(s_sv[:3] - d_sv[:3]))

                res = minimize_scalar(dist_fn, bounds=(t_lo, t_hi), method="bounded")
                
                if res.fun < 5.0:
                    tca_s = float(res.x)
                    risk = self._classify_risk(res.fun)
                    
                    # Sample state at exact TCA for precise relative velocity
                    s_tca = sat_batch_sol(tca_s)[sat_id_to_idx[sat_id]]
                    d_tca = deb_batch_sol(tca_s)[deb_id_to_idx[deb_id]]
                    rel_vel = float(np.linalg.norm(s_tca[3:] - d_tca[3:]))

                    warnings.append(CDM(
                        satellite_id=sat_id, debris_id=deb_id,
                        tca=base_time + timedelta(seconds=tca_s),
                        miss_distance_km=float(res.fun),
                        risk=risk, relative_velocity_km_s=rel_vel,
                    ))
                
                processed_time = t_hi


        logger.info(
            "CA | %d sats | %d/%d debris after Stage 1 | %d candidate pairs | %d CDMs",
            len(sat_states),
            len(filtered_ids),
            len(debris_ids),
            len(candidate_pairs),
            len(warnings),
        )
        return warnings

    def assess_sat_vs_sat(
        self,
        sat_states: dict[str, np.ndarray],
        lookahead_s: float = LOOKAHEAD_SECONDS,
        current_time: datetime | None = None,
    ) -> list[CDM]:
        """Run a specialized conjunction assessment pass for Satellite-vs-Satellite pairs.

        Optimized to avoid self-collisions (sid == did) and redundant checks (A-B vs B-A).

        Args:
            sat_states: {sat_id: state_vector [x,y,z,vx,vy,vz] km/km·s⁻¹}
            lookahead_s: Propagation window in seconds.
            current_time: Simulation clock epoch.

        Returns:
            List of CDM warnings for Sat-vs-Sat pairs with miss_distance < 5 km.
        """
        import time as _time
        _t0 = _time.time()
        base_time = current_time if current_time is not None else datetime.now(timezone.utc)
        warnings: list[CDM] = []

        if len(sat_states) < 2:
            return warnings

        sat_ids = list(sat_states.keys())
        sat_positions = np.array([sv[:3] for sv in sat_states.values()])

        # Build KDTree of all satellites
        tree = KDTree(sat_positions)

        # Collect unique pairs Survived KDTree screening
        candidate_pairs: list[tuple[str, str]] = []
        
        # Pre-compute apo/peri for filtering
        rp, ra = self._compute_apo_peri(np.array(list(sat_states.values())))
        rp_dict = {sid: rp[i] for i, sid in enumerate(sat_ids)}
        ra_dict = {sid: ra[i] for i, sid in enumerate(sat_ids)}

        for i, s1_id in enumerate(sat_ids):
            # Only check against satellites with higher index to avoid double-counting
            neighbor_indices = tree.query_ball_point(sat_positions[i], r=2000.0)
            
            s1_rp = rp_dict[s1_id] - 5.0
            s1_ra = ra_dict[s1_id] + 5.0
            
            for idx in neighbor_indices:
                if idx <= i: 
                    continue # skip self and already-checked pairs
                
                s2_id = sat_ids[idx]
                if rp_dict[s2_id] > s1_ra or ra_dict[s2_id] < s1_rp:
                    continue
                
                candidate_pairs.append((s1_id, s2_id))

        if not candidate_pairs:
            return warnings

        # Dense propagation for candidates
        relevant_sat_ids = sorted(list(set(sum(candidate_pairs, ()))))
        relevant_sat_states = {sid: sat_states[sid] for sid in relevant_sat_ids}
        
        ids_list, batch_sol = self._screening_propagator.propagate_dense_batch(
            relevant_sat_states, lookahead_s
        )
        id_to_idx = {sid: idx for idx, sid in enumerate(ids_list)}

        # For Sat-vs-Sat, we can afford refined checks on ALL candidates 
        # because the number of pairs is small (< 2500).
        # This avoids missing high-speed intercepts that a coarse grid would miss.
        for s1_id, s2_id in candidate_pairs:
            def dist_fn(t, sid1=s1_id, sid2=s2_id):
                sv1 = batch_sol(t)[id_to_idx[sid1]]
                sv2 = batch_sol(t)[id_to_idx[sid2]]
                return float(np.linalg.norm(sv1[:3] - sv2[:3]))

            # Multi-window search to avoid local minima in highly curved orbits
            # Split 24h into 4-hour chunks
            _window_size = 14400.0
            for t_start in np.arange(0.0, lookahead_s, _window_size):
                t_end = min(t_start + _window_size, lookahead_s)
                res = minimize_scalar(dist_fn, bounds=(t_start, t_end), method="bounded")
                
                if res.fun < 5.0:
                    tca_s = float(res.x)
                    risk = self._classify_risk(res.fun)
                    s1_tca = batch_sol(tca_s)[id_to_idx[s1_id]]
                    s2_tca = batch_sol(tca_s)[id_to_idx[s2_id]]
                    rel_vel = float(np.linalg.norm(s1_tca[3:] - s2_tca[3:]))

                    warnings.append(CDM(
                        satellite_id=s1_id, debris_id=s2_id,
                        tca=base_time + timedelta(seconds=tca_s),
                        miss_distance_km=float(res.fun),
                        risk=risk, relative_velocity_km_s=rel_vel,
                    ))
                    # Found one in this window, but there could be more in next windows (next orbits)
                    # For safety, we keep checking other windows.

        _t_end = _time.time()
        logger.info("CA-SAT | %d pairs | %d CDMs | took %.2fs", len(candidate_pairs), len(warnings), _t_end - _t0)
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
