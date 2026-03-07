"""
test_maneuver.py — ManeuverPlanner Unit Tests
═════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

import numpy as np
import pytest
from datetime import datetime, timedelta

from engine.maneuver_planner import ManeuverPlanner


def test_rtn_to_eci_identity():
    """Pure radial delta-v should map to position direction in ECI."""
    planner = ManeuverPlanner()
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    dv_rtn = np.array([1.0, 0.0, 0.0])  # Pure radial

    dv_eci = planner.rtn_to_eci(r, v, dv_rtn)

    # Radial is along r direction → should be [1, 0, 0] (ish)
    r_hat = r / np.linalg.norm(r)
    np.testing.assert_allclose(dv_eci / np.linalg.norm(dv_eci), r_hat, atol=1e-10)


def test_rtn_to_eci_preserves_magnitude():
    """RTN-to-ECI rotation should preserve the delta-v magnitude."""
    planner = ManeuverPlanner()
    r = np.array([6778.0, 0.0, 0.0])
    v = np.array([0.0, 7.67, 0.0])
    dv_rtn = np.array([0.5, 1.0, 0.3])

    dv_eci = planner.rtn_to_eci(r, v, dv_rtn)

    assert abs(np.linalg.norm(dv_eci) - np.linalg.norm(dv_rtn)) < 1e-10


def test_validate_burn_exceeds_max_thrust():
    """Burns exceeding 15 m/s should be rejected."""
    planner = ManeuverPlanner()
    now = datetime.utcnow()
    valid, reason = planner.validate_burn(
        delta_v_magnitude_ms=20.0,
        burn_time=now + timedelta(seconds=60),
        current_time=now,
        last_burn_time=None,
        has_los=True,
        fuel_kg=50.0,
    )
    assert not valid
    assert "max thrust" in reason.lower()


def test_validate_burn_violates_signal_latency():
    """Burns within 10s of current time should be rejected."""
    planner = ManeuverPlanner()
    now = datetime.utcnow()
    valid, reason = planner.validate_burn(
        delta_v_magnitude_ms=5.0,
        burn_time=now + timedelta(seconds=5),
        current_time=now,
        last_burn_time=None,
        has_los=True,
        fuel_kg=50.0,
    )
    assert not valid
    assert "latency" in reason.lower()


def test_validate_burn_violates_cooldown():
    """Burns within 600s of last burn should be rejected."""
    planner = ManeuverPlanner()
    now = datetime.utcnow()
    valid, reason = planner.validate_burn(
        delta_v_magnitude_ms=5.0,
        burn_time=now + timedelta(seconds=60),
        current_time=now,
        last_burn_time=now - timedelta(seconds=300),
        has_los=True,
        fuel_kg=50.0,
    )
    assert not valid
    assert "cooldown" in reason.lower()
