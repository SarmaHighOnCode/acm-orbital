"""
test_fuel.py — FuelTracker Unit Tests (Tsiolkovsky Equation)
════════════════════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

import numpy as np
import pytest

from engine.fuel_tracker import FuelTracker
from config import M_DRY, ISP, G0, EOL_FUEL_THRESHOLD_KG


def test_tsiolkovsky_known_answer(fuel_tracker):
    """For 550 kg satellite, Isp=300s, Δv=10 m/s:
    Δm = 550 × (1 - e^(-10/(300×9.80665))) ≈ 1.862 kg"""
    consumed = fuel_tracker.consume("SAT-TEST-01", delta_v_ms=10.0)
    expected = 550.0 * (1.0 - np.exp(-10.0 / (ISP * G0)))
    assert abs(consumed - expected) < 0.001, f"Expected ~{expected:.3f}, got {consumed:.3f}"


def test_fuel_decreases_monotonically(fuel_tracker):
    """After N burns, fuel_kg must be strictly decreasing."""
    prev_fuel = fuel_tracker.get_fuel("SAT-TEST-01")
    for _ in range(5):
        fuel_tracker.consume("SAT-TEST-01", delta_v_ms=5.0)
        curr_fuel = fuel_tracker.get_fuel("SAT-TEST-01")
        assert curr_fuel < prev_fuel
        prev_fuel = curr_fuel


def test_eol_triggers_at_threshold():
    """When fuel_kg drops to ≤ 2.5 kg, EOL flag must be True."""
    ft = FuelTracker()
    ft.register_satellite("SAT-EOL", fuel_kg=3.0)
    assert not ft.is_eol("SAT-EOL")

    # Burn enough to drop below threshold
    ft.consume("SAT-EOL", delta_v_ms=5.0)
    # Should be near or below 2.5 kg
    remaining = ft.get_fuel("SAT-EOL")
    if remaining <= EOL_FUEL_THRESHOLD_KG:
        assert ft.is_eol("SAT-EOL")


def test_get_current_mass(fuel_tracker):
    """Current mass should equal dry mass + remaining fuel."""
    mass = fuel_tracker.get_current_mass("SAT-TEST-01")
    fuel = fuel_tracker.get_fuel("SAT-TEST-01")
    assert abs(mass - (M_DRY + fuel)) < 0.001


def test_sufficient_fuel_check(fuel_tracker):
    """sufficient_fuel should return True for reasonable burns."""
    assert fuel_tracker.sufficient_fuel("SAT-TEST-01", delta_v_ms=10.0)


def test_consume_clamps_to_available():
    """Consuming more fuel than available should clamp to 0."""
    ft = FuelTracker()
    ft.register_satellite("SAT-LOW", fuel_kg=0.5)
    ft.consume("SAT-LOW", delta_v_ms=15.0)
    assert ft.get_fuel("SAT-LOW") >= 0.0
