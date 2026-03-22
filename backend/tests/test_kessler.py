"""
test_kessler.py — Unit tests for Kessler Cascade Risk Engine
═════════════════════════════════════════════════════════════
Tests the KesslerRiskEngine against known physical scenarios:
  - Empty space should report zero risk
  - A single shell with objects should compute correct density
  - Dense shells should exceed NASA critical threshold
  - Risk labels should be assigned correctly
  - Shell volume calculation should be physically correct
  - Cascade fragment count should scale with velocity
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from config import R_EARTH
from engine.kessler import (
    KesslerRiskEngine,
    ShellRisk,
    KesslerAssessment,
    SHELL_WIDTH_KM,
    MIN_ALT_KM,
    MAX_ALT_KM,
    AVG_CROSS_SECTION_KM2,
    AVG_REL_VELOCITY_KMS,
    ASSESSMENT_WINDOW_S,
    NASA_CRITICAL_DENSITY,
)


@pytest.fixture
def engine():
    return KesslerRiskEngine()


# ── Shell Initialization ─────────────────────────────────────────────

class TestShellInit:
    def test_shell_count(self, engine):
        """Should create (MAX_ALT - MIN_ALT) / WIDTH shells."""
        expected = int((MAX_ALT_KM - MIN_ALT_KM) / SHELL_WIDTH_KM)
        assert len(engine.shells) == expected

    def test_shell_boundaries(self, engine):
        """First shell starts at MIN_ALT, last ends at MAX_ALT."""
        assert engine.shells[0][0] == MIN_ALT_KM
        assert engine.shells[-1][1] == MAX_ALT_KM

    def test_shell_contiguous(self, engine):
        """Shells should be contiguous with no gaps."""
        for i in range(len(engine.shells) - 1):
            assert engine.shells[i][1] == engine.shells[i + 1][0]


# ── Shell Volume ─────────────────────────────────────────────────────

class TestShellVolume:
    def test_positive_volume(self, engine):
        """Shell volume must be positive."""
        vol = engine._shell_volume(400, 450)
        assert vol > 0

    def test_volume_formula(self, engine):
        """Volume should follow 4/3 π (r_outer³ - r_inner³)."""
        alt_min, alt_max = 400.0, 450.0
        r_inner = R_EARTH + alt_min
        r_outer = R_EARTH + alt_max
        expected = (4.0 / 3.0) * math.pi * (r_outer**3 - r_inner**3)
        assert abs(engine._shell_volume(alt_min, alt_max) - expected) < 1.0

    def test_volume_increases_with_altitude(self, engine):
        """Shells at higher altitude have larger volume (bigger radius)."""
        vol_low = engine._shell_volume(200, 250)
        vol_high = engine._shell_volume(1500, 1550)
        assert vol_high > vol_low


# ── Cascade Fragment Count ───────────────────────────────────────────

class TestCascadeFragments:
    def test_minimum_one_fragment(self, engine):
        """Even at very low velocity, at least 1 fragment."""
        assert engine._cascade_fragment_count(0.001) >= 1.0

    def test_scales_with_velocity(self, engine):
        """More fragments at higher relative velocity."""
        n_slow = engine._cascade_fragment_count(5.0)
        n_fast = engine._cascade_fragment_count(15.0)
        assert n_fast > n_slow

    def test_reference_value(self, engine):
        """At 10 km/s → ~100 fragments (reference point)."""
        n_ref = engine._cascade_fragment_count(10.0)
        assert abs(n_ref - 100.0) < 1.0


# ── Assessment: Empty Space ──────────────────────────────────────────

class TestEmptySpace:
    def test_no_objects(self, engine):
        """Zero objects should yield zero risk."""
        result = engine.assess(
            np.empty((0, 3)),
            np.empty((0, 3)),
        )
        assert result.overall_risk_score == 0.0
        assert result.risk_label == "LOW"
        assert result.cascade_probability == 0.0
        assert result.total_objects == 0
        assert result.critical_shells == 0

    def test_single_object_no_collision(self, engine):
        """A single satellite should yield zero collision probability."""
        # Place 1 satellite at 400 km altitude
        pos = np.array([[R_EARTH + 400.0, 0.0, 0.0]])
        result = engine.assess(pos, np.empty((0, 3)))
        assert result.total_objects == 1
        # Collision requires ≥ 2 objects per shell
        for shell in result.shell_data:
            assert shell.collision_prob_24h == 0.0


# ── Assessment: Populated Shells ─────────────────────────────────────

class TestPopulatedShells:
    def test_two_objects_same_shell(self, engine):
        """Two objects in the same shell should produce nonzero collision probability."""
        alt_km = 400.0
        pos = np.array([
            [R_EARTH + alt_km, 0.0, 0.0],
            [0.0, R_EARTH + alt_km, 0.0],
        ])
        result = engine.assess(pos, np.empty((0, 3)))
        assert result.total_objects == 2
        # At least one shell should have nonzero probability
        populated = [s for s in result.shell_data if s.object_count >= 2]
        assert len(populated) > 0
        assert populated[0].collision_prob_24h > 0.0

    def test_density_calculation(self, engine):
        """Spatial density should equal object_count / volume."""
        alt_km = 600.0
        n_objects = 50
        # All objects at ~600 km in various directions
        rng = np.random.default_rng(42)
        positions = rng.normal(0, 1, (n_objects, 3))
        norms = np.linalg.norm(positions, axis=1, keepdims=True)
        positions = positions / norms * (R_EARTH + alt_km)

        result = engine.assess(positions, np.empty((0, 3)))
        # Find the shell containing 600 km
        target_shell = None
        for s in result.shell_data:
            if s.alt_min_km <= alt_km < s.alt_max_km:
                target_shell = s
                break
        assert target_shell is not None
        # Density = count / volume
        expected_density = target_shell.object_count / target_shell.volume_km3
        assert abs(target_shell.spatial_density - expected_density) < 1e-20

    def test_many_objects_higher_risk(self, engine):
        """More objects should produce higher risk score."""
        alt_km = 500.0
        # 10 objects
        rng = np.random.default_rng(7)
        pos_10 = rng.normal(0, 1, (10, 3))
        pos_10 = pos_10 / np.linalg.norm(pos_10, axis=1, keepdims=True) * (R_EARTH + alt_km)

        # 500 objects
        pos_500 = rng.normal(0, 1, (500, 3))
        pos_500 = pos_500 / np.linalg.norm(pos_500, axis=1, keepdims=True) * (R_EARTH + alt_km)

        r10 = engine.assess(np.empty((0, 3)), pos_10)
        r500 = engine.assess(np.empty((0, 3)), pos_500)
        assert r500.overall_risk_score >= r10.overall_risk_score


# ── Risk Classification ──────────────────────────────────────────────

class TestRiskLabels:
    def test_low_risk(self, engine):
        """Very sparse population should be LOW."""
        pos = np.array([
            [R_EARTH + 400, 0, 0],
            [R_EARTH + 800, 0, 0],
        ])
        result = engine.assess(pos, np.empty((0, 3)))
        assert result.risk_label == "LOW"

    def test_assessment_return_type(self, engine):
        """Assessment should return KesslerAssessment dataclass."""
        result = engine.assess(np.empty((0, 3)), np.empty((0, 3)))
        assert isinstance(result, KesslerAssessment)
        assert isinstance(result.shell_data, list)
        assert all(isinstance(s, ShellRisk) for s in result.shell_data)


# ── Mixed Satellites + Debris ────────────────────────────────────────

class TestMixedPopulation:
    def test_satellites_and_debris_counted(self, engine):
        """Both satellites and debris should count as objects."""
        sats = np.array([[R_EARTH + 400, 0, 0]])
        debs = np.array([[0, R_EARTH + 400, 0], [0, 0, R_EARTH + 400]])
        result = engine.assess(sats, debs)
        assert result.total_objects == 3

    def test_critical_density_detection(self, engine):
        """A hyper-dense shell should be flagged critical."""
        # Pack 10000 objects into a single 50km shell at 400 km
        alt_km = 425.0   # center of 400-450 shell
        rng = np.random.default_rng(1)
        positions = rng.normal(0, 1, (10000, 3))
        positions = positions / np.linalg.norm(positions, axis=1, keepdims=True) * (R_EARTH + alt_km)

        result = engine.assess(np.empty((0, 3)), positions)
        assert result.critical_shells >= 1
        assert result.most_crowded_density > NASA_CRITICAL_DENSITY
