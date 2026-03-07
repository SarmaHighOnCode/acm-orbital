"""
test_propagator.py — OrbitalPropagator Unit Tests
══════════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

import numpy as np
import pytest


def test_propagate_returns_correct_shape(propagator, circular_leo_state):
    """Output must be np.ndarray of shape (6,)."""
    result = propagator.propagate(circular_leo_state, 60.0)
    assert isinstance(result, np.ndarray)
    assert result.shape == (6,)


def test_circular_orbit_conserves_energy(propagator, circular_leo_state):
    """Orbital energy should be conserved to < 1e-6 relative error over one period."""
    mu = 398600.4418
    state = circular_leo_state

    def energy(sv):
        r = np.linalg.norm(sv[:3])
        v = np.linalg.norm(sv[3:])
        return 0.5 * v**2 - mu / r

    e0 = energy(state)
    # Propagate for one full orbital period (~92 min)
    period = 2.0 * np.pi * np.sqrt(np.linalg.norm(state[:3])**3 / mu)
    final_state = propagator.propagate(state, period)
    e1 = energy(final_state)

    relative_error = abs((e1 - e0) / e0)
    assert relative_error < 1e-6, f"Energy conservation violated: {relative_error:.2e}"


def test_propagate_position_changes(propagator, circular_leo_state):
    """After propagation, position should differ from initial."""
    result = propagator.propagate(circular_leo_state, 600.0)
    assert not np.allclose(result[:3], circular_leo_state[:3])


def test_propagate_batch_matches_individual(propagator, circular_leo_state):
    """Batch result for N objects must match N individual propagate() calls."""
    states = {
        "SAT-01": circular_leo_state.copy(),
        "SAT-02": circular_leo_state.copy() * 1.01,
    }
    dt = 300.0

    batch_results = propagator.propagate_batch(states, dt)
    for obj_id, sv in states.items():
        individual = propagator.propagate(sv, dt)
        np.testing.assert_allclose(
            batch_results[obj_id], individual, rtol=1e-12
        )
