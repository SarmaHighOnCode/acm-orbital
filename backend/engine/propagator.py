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

    def __init__(self, rtol: float = 1e-6, atol: float = 1e-8):
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

    def propagate_dense(self, state_vector: np.ndarray, dt_seconds: float):
        """Propagate with dense output for efficient multi-point trajectory sampling."""
        sol = solve_ivp(
            self._derivatives,
            [0.0, dt_seconds],
            state_vector,
            method="DOP853",
            rtol=self.rtol,
            atol=self.atol,
            dense_output=True,
        )
        return sol.sol

    def propagate_dense_batch(self, states: dict[str, np.ndarray], dt_seconds: float):
        """Propagate multiple objects with dense output.
        Returns a callable sol(t) that yields shape (N, 6).
        """
        if not states:
            return lambda t: np.array([])
            
        object_ids = list(states.keys())
        n_objects = len(object_ids)
        states_array = np.array(list(states.values()))
        state_flat = states_array.flatten()
        
        sol = solve_ivp(
            self._vectorized_derivatives,
            [0.0, dt_seconds],
            state_flat,
            args=(n_objects,),
            method="DOP853",
            rtol=self.rtol,
            atol=self.atol,
            dense_output=True,
        )
        
        dense_ode = sol.sol
        
        def batch_sol(t):
            res_flat = dense_ode(t)
            # handle case where t is an array (e.g. solving for multiple times)
            if np.isscalar(t):
                return res_flat.reshape(n_objects, 6)
            else:
                return res_flat.reshape(n_objects, 6, len(t))
                
        return object_ids, batch_sol

    @staticmethod
    def _vectorized_derivatives(t: float, state_flat: np.ndarray, n_objects: int) -> np.ndarray:
        """Vectorized ODE right-hand side for a batch of objects."""
        state = state_flat.reshape(n_objects, 6)
        pos = state[:, :3]
        vel = state[:, 3:]
        
        x = pos[:, 0]
        y = pos[:, 1]
        z = pos[:, 2]
        r = np.linalg.norm(pos, axis=1)
        
        # Two-body gravity
        a_gravity = -MU_EARTH * pos / (r[:, np.newaxis]**3)
        
        # J2 perturbation
        factor = 1.5 * J2 * MU_EARTH * R_EARTH**2 / (r**5)
        z2_r2 = (z / r)**2
        
        a_j2_x = factor * x * (5.0 * z2_r2 - 1.0)
        a_j2_y = factor * y * (5.0 * z2_r2 - 1.0)
        a_j2_z = factor * z * (5.0 * z2_r2 - 3.0)
        
        a_j2 = np.column_stack([a_j2_x, a_j2_y, a_j2_z])
        acc = a_gravity + a_j2
        
        derivs = np.column_stack([vel, acc])
        return derivs.flatten()

    def propagate_batch(
        self, states: dict[str, np.ndarray], dt_seconds: float
    ) -> dict[str, np.ndarray]:
        """Propagate multiple objects forward by dt_seconds using vectorized solve_ivp.

        Args:
            states: {object_id: state_vector} mapping
            dt_seconds: Time step in seconds

        Returns:
            {object_id: new_state_vector} mapping
        """
        if not states:
            return {}

        object_ids = list(states.keys())
        n_objects = len(object_ids)
        
        # Flatten all state vectors into a 1D array
        states_array = np.array(list(states.values()))
        state_flat = states_array.flatten()
        
        # Use slightly relaxed tolerances for batch to maintain high speed
        # while keeping sufficient accuracy for CA.
        sol = solve_ivp(
            self._vectorized_derivatives,
            [0.0, dt_seconds],
            state_flat,
            args=(n_objects,),
            method="DOP853",
            rtol=self.rtol,
            atol=self.atol,
            dense_output=False,
        )
        
        res_flat = sol.y[:, -1]
        res_array = res_flat.reshape(n_objects, 6)
        
        results = {}
        for i, obj_id in enumerate(object_ids):
            results[obj_id] = res_array[i]
            
        return results
