"""
conftest.py — Shared Pytest Fixtures
═════════════════════════════════════
Provides reusable test fixtures for physics engine tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure backend/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.models import Satellite, Debris
from engine.propagator import OrbitalPropagator
from engine.fuel_tracker import FuelTracker
from engine.simulation import SimulationEngine
from config import R_EARTH


@pytest.fixture
def propagator():
    """Fresh OrbitalPropagator instance."""
    return OrbitalPropagator()


@pytest.fixture
def fuel_tracker():
    """Fresh FuelTracker with one registered satellite."""
    ft = FuelTracker()
    ft.register_satellite("SAT-TEST-01", fuel_kg=50.0)
    return ft


@pytest.fixture
def engine():
    """Fresh SimulationEngine instance."""
    return SimulationEngine()


@pytest.fixture
def circular_leo_state():
    """State vector for a circular LEO orbit at ~400 km altitude.

    Properties:
      - Altitude: 400 km above Earth's surface
      - Orbital radius: R_EARTH + 400 = 6778.137 km
      - Circular velocity: sqrt(μ/r) ≈ 7.669 km/s
      - Inclination: 51.6° (ISS-like)
      - Period: ~92.4 minutes
    """
    r = R_EARTH + 400.0  # km
    v = np.sqrt(398600.4418 / r)  # km/s — circular velocity
    inc = np.radians(51.6)
    return np.array([
        r, 0.0, 0.0,
        0.0, v * np.cos(inc), v * np.sin(inc),
    ])
