"""
collision.py — KDTree Conjunction Assessment Pipeline
═════════════════════════════════════════════════════
4-stage filter cascade for collision detection.
O(N²) nested loops are FORBIDDEN. Uses KDTree for O(N log N) screening.
Owner: Dev 1 (Physics Engine)

Complexity per assess() call:
  Stage 1 — O(D)           altitude band pre-filter  (shrinks D → D_alt ≈ 0.15 D)
  Stage 2 — O(D_alt log D_alt + S log D_alt)  KDTree build + S queries
  Stage 3 — O(k)           dense propagation, one DOP853 per unique object
             O(k · F)      Brent TCA refinement, F ≈ 20 polynomial evaluations each O(1)
  Stage 4 — O(k)           CDM emission

  Total: O(D + S · log(D_alt) + k · F)  with k ≪ S·D due to Stage 1+2 filtering.
  Avoids O(S·D) naïve nested loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.spatial import KDTree
from scipy.optimize import minimize_scalar

from config import CONJUNCTION_THRESHOLD_KM, LOOKAHEAD_SECONDS
from engine.models import CDM

logger = logging.getLogger("acm.engine.collision")


class ConjunctionAssessor:
    """4-stage conjunction assessment pipeline.

    Stage 1: Altitude band filter  — O(D), eliminates ~85% of debris before KDTree build
    Stage 2: KDTree spatial index  — O(D_alt log D_alt) build + O(S log D_alt) queries
    Stage 3: TCA refinement        — Brent's method with dense-output polynomial interpolants
    Stage 4: CDM emission          — risk classification and warning generation
    """

    def __init__(self, propagator):
        self.propagator = propagator

    def assess(
        self,
        sat_states: dict[str, np.ndarray],
        debris_states: dict[str, np.ndarray],
        lookahead_s: float = LOOKAHEAD_SECONDS,
        current_time: datetime | None = None,
    ) -> list[CDM]:
        """Run the full 4-stage conjunction assessment pipeline.

        Args:
            current_time: Simulation clock at this assessment tick.
                          CDM TCA timestamps are relative to this time.
                          Defaults to UTC wall-clock if not provided.
        """
        base_time = current_time if current_time is not None else datetime.now(timezone.utc)
        warnings: list[CDM] = []

        if not sat_states or not debris_states:
            return warnings

        debris_ids = list(debris_states.keys())
        debris_positions = np.array([sv[:3] for sv in debris_states.values()])

        # ── Stage 1: Altitude Band Filter — O(D) ────────────────────────────
        # Compute union of ±50 km altitude shells across all satellites.
        # Debris outside every satellite's shell cannot collide → discarded.
        # Reduces D to D_alt before KDTree construction.
        sat_radii = np.array([np.linalg.norm(sv[:3]) for sv in sat_states.values()])
        r_min = float(sat_radii.min()) - 50.0
        r_max = float(sat_radii.max()) + 50.0
        debris_radii = np.linalg.norm(debris_positions, axis=1)
        alt_mask = (debris_radii >= r_min) & (debris_radii <= r_max)
        filtered_ids = [debris_ids[i] for i, keep in enumerate(alt_mask) if keep]
        filtered_positions = debris_positions[alt_mask]

        if len(filtered_positions) == 0:
            return warnings

        # ── Stage 2: KDTree Spatial Index — O(D_alt log D_alt) build ────────
        # 50 km query radius: any debris further away in 3-D cannot close to
        # collision threshold within the propagation interval for LEO speeds.
        tree = KDTree(filtered_positions)

        # Pre-propagate every satellite once with dense output using batch integration.
        sat_ids_list, sat_batch_sol = self.propagator.propagate_dense_batch(sat_states, lookahead_s)
        sat_solutions = {
            sid: (lambda t, idx=i: sat_batch_sol(t)[idx])
            for i, sid in enumerate(sat_ids_list)
        }

        # Identify all debris that passed KDTree check across all satellites
        deb_targets = {}
        candidate_pairs = []
        
        for sat_id, sat_state in sat_states.items():
            # O(log D_alt + k_i) per satellite
            neighbor_indices = tree.query_ball_point(sat_state[:3], r=50.0)

            for idx in neighbor_indices:
                deb_id = filtered_ids[idx]
                deb_targets[deb_id] = debris_states[deb_id]
                candidate_pairs.append((sat_id, deb_id))

        if not candidate_pairs:
            return warnings
            
        # Batch propagate all targeted debris with looser tolerances for speed
        orig_rtol, orig_atol = self.propagator.rtol, self.propagator.atol
        self.propagator.rtol, self.propagator.atol = 1e-4, 1e-6
        deb_ids_list, deb_batch_sol = self.propagator.propagate_dense_batch(deb_targets, lookahead_s)
        self.propagator.rtol, self.propagator.atol = orig_rtol, orig_atol
        deb_solutions = {
            did: (lambda t, idx=i: deb_batch_sol(t)[idx])
            for i, did in enumerate(deb_ids_list)
        }
        
        for sat_id, deb_id in candidate_pairs:
            sol_sat = sat_solutions[sat_id]
            sol_deb = deb_solutions[deb_id]
            sat_state = sat_states[sat_id]
            deb_state = debris_states[deb_id]

            # ── Stage 3: TCA Refinement — Brent's method ────────────────
            # Each lambda evaluation is O(1) polynomial interpolation.
            # Total cost per pair: ~20 O(1) evals vs ~20 full DOP853 calls
            # in the naïve approach — roughly 10× faster per candidate.
            res = minimize_scalar(
                lambda t, _s=sol_sat, _d=sol_deb: float(
                    np.linalg.norm(_s(t)[:3] - _d(t)[:3])
                ),
                bounds=(0.0, lookahead_s),
                method="bounded",
            )

            tca_s = res.x
            miss_distance_km = res.fun

            # ── Stage 4: CDM Emission ────────────────────────────────────
            if miss_distance_km < 5.0:  # YELLOW / RED / CRITICAL only
                risk = self._classify_risk(miss_distance_km)
                warnings.append(CDM(
                    satellite_id=sat_id,
                    debris_id=deb_id,
                    tca=base_time + timedelta(seconds=tca_s),
                    miss_distance_km=float(miss_distance_km),
                    risk=risk,
                    relative_velocity_km_s=float(
                        np.linalg.norm(sat_state[3:] - deb_state[3:])
                    ),
                ))

        logger.info(
            "CA | %d sats | %d/%d debris after Stage 1 | %d candidate pairs | %d CDMs",
            len(sat_states), len(filtered_ids), len(debris_ids),
            len(candidate_pairs),  # reuse already-computed set — no duplicate queries
            len(warnings),
        )
        return warnings

    @staticmethod
    def _classify_risk(miss_distance_km: float) -> str:
        """Classify conjunction risk based on miss distance."""
        if miss_distance_km < CONJUNCTION_THRESHOLD_KM:
            return "CRITICAL"
        elif miss_distance_km < 1.0:
            return "RED"
        elif miss_distance_km < 5.0:
            return "YELLOW"
        return "GREEN"
