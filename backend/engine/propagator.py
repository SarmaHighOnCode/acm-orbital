"""
propagator.py — J2-Perturbed Orbital Propagation
═════════════════════════════════════════════════
Implements two-body + J2 perturbation using DOP853 integrator.
Owner: Dev 1 (Physics Engine)

Mathematical specification:
  d²r/dt² = -(μ/|r|³) · r  +  a_J2
  where a_J2 accounts for Earth's equatorial bulge.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

from config import MU_EARTH, J2, R_EARTH


class OrbitalPropagator:
    """J2-perturbed orbital propagator using DOP853 (8th-order Dormand-Prince)."""

    def __init__(self, rtol: float = 1e-10, atol: float = 1e-12):
        self.rtol = rtol
        self.atol = atol

    @staticmethod
    def _compute_acceleration(position: np.ndarray) -> np.ndarray:
        """Compute total acceleration (two-body + J2) at a given position.

        Args:
            position: [x, y, z] in km (ECI J2000)

        Returns:
            Acceleration vector [ax, ay, az] in km/s²
        """
        x, y, z = position
        r = np.linalg.norm(position)

        # Two-body gravity
        a_gravity = -MU_EARTH * position / r**3

        # J2 perturbation (strictly following problem statement formula)
        factor = 1.5 * J2 * MU_EARTH * R_EARTH**2 / r**5
        z2_r2 = (z / r) ** 2
        a_j2 = factor * np.array([
            x * (5.0 * z2_r2 - 1.0),
            y * (5.0 * z2_r2 - 1.0),
            z * (5.0 * z2_r2 - 3.0),
        ])

        return a_gravity + a_j2

    @staticmethod
    def _derivatives(t: float, state: np.ndarray) -> np.ndarray:
        """ODE right-hand side for solve_ivp.

        Args:
            t: Time variable (unused — autonomous ODE)
            state: [x, y, z, vx, vy, vz] in km and km/s

        Returns:
            [vx, vy, vz, ax, ay, az]
        """
        pos = state[:3]
        vel = state[3:]
        acc = OrbitalPropagator._compute_acceleration(pos)
        return np.concatenate([vel, acc])

    def propagate(self, state_vector: np.ndarray, dt_seconds: float) -> np.ndarray:
        """Propagate a single object forward by dt_seconds.

        Args:
            state_vector: [x, y, z, vx, vy, vz] in km and km/s
            dt_seconds: Time step in seconds

        Returns:
            New state vector [x, y, z, vx, vy, vz]
        """
        sol = solve_ivp(
            self._derivatives,
            [0.0, dt_seconds],
            state_vector,
            method="DOP853",
            rtol=self.rtol,
            atol=self.atol,
            dense_output=False,
        )
        return sol.y[:, -1]

    def propagate_batch(
        self, states: dict[str, np.ndarray], dt_seconds: float
    ) -> dict[str, np.ndarray]:
        """Propagate multiple objects forward by dt_seconds.

        Args:
            states: {object_id: state_vector} mapping
            dt_seconds: Time step in seconds

        Returns:
            {object_id: new_state_vector} mapping

        TODO: Dev 1 — optimize with vectorized integration or parallel execution.
        """
        results = {}
        for obj_id, sv in states.items():
            results[obj_id] = self.propagate(sv, dt_seconds)
        return results
