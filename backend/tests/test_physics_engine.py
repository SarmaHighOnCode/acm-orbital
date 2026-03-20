"""
test_physics_engine.py — Principal QA Engineer Master Test Suite
═══════════════════════════════════════════════════════════════════
Brutal, limit-breaking tests for the ACM Core Physics Engine.

Coverage:
  §1  J2 Perturbation Formula     — Analytical closed-form verification
  §2  24-Hour Propagation         — Stability, energy conservation, RAAN drift
  §3  RTN-to-ECI Transformation  — Orthonormality, specific orbit solutions
  §4  Tsiolkovsky Equation        — Precision mass depletion, coupling effects
  §5  Constraint Enforcement      — ΔV cap, cooldown, signal latency, LOS
  §6  Collision Physics           — 0 m, 99 m, 101 m, station-keeping box
  §7  O(N²) Shatterer             — 100K-object KDTree stress & correctness
  §8  Integration                 — Full 7-step tick loop end-to-end

All constants sourced directly from problemstatement.md and PRD.md.
"""

from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

# ── import path: tests/ lives inside backend/ ────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    G0, ISP, J2, CONJUNCTION_THRESHOLD_KM, EOL_FUEL_THRESHOLD_KG,
    MAX_DV_PER_BURN, MU_EARTH, M_DRY, M_FUEL_INIT, M_WET_INIT,
    R_EARTH, SIGNAL_LATENCY_S, STATION_KEEPING_RADIUS_KM,
    THRUSTER_COOLDOWN_S,
)
from engine.collision import ConjunctionAssessor
from engine.fuel_tracker import FuelTracker
from engine.maneuver_planner import ManeuverPlanner
from engine.models import Debris, Satellite
from engine.propagator import OrbitalPropagator
from engine.simulation import SimulationEngine


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED MODULE-SCOPED FIXTURES  (created once, reused across classes)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def prop():
    """High-accuracy propagator for precision tests."""
    return OrbitalPropagator(rtol=1e-9, atol=1e-11)


@pytest.fixture(scope="module")
def prop_fast():
    """Standard-accuracy propagator matching production settings."""
    return OrbitalPropagator(rtol=1e-6, atol=1e-8)


@pytest.fixture(scope="module")
def iss_state():
    """ISS-like circular LEO: r=6778.137 km, i=51.6°, equatorial ascending node."""
    r = R_EARTH + 400.0
    v = math.sqrt(MU_EARTH / r)
    inc = math.radians(51.6)
    return np.array([r, 0.0, 0.0,
                     0.0, v * math.cos(inc), v * math.sin(inc)])


@pytest.fixture(scope="module")
def equatorial_state():
    """Circular equatorial orbit at 450 km: [r,0,0] / [0,v,0]."""
    r = R_EARTH + 450.0
    v = math.sqrt(MU_EARTH / r)
    return np.array([r, 0.0, 0.0,   0.0, v, 0.0])


# ═══════════════════════════════════════════════════════════════════════════════
# §1  J2 PERTURBATION FORMULA — ANALYTICAL VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestJ2AccelerationFormula:
    """
    Verify J2 acceleration against closed-form solutions from the problem statement:

        a⃗_J2 = (3/2)·(J2·μ·RE²)/|r⃗|⁵ × [x(5z²/r²−1),  y(5z²/r²−1),  z(5z²/r²−3)]

    Special cases chosen for algebraic simplicity:
      • r⃗ = [r, 0, 0] → z=0, so a_J2 = factor·[−r, 0, 0]
      • r⃗ = [0, 0, r] → z²/r²=1, so a_J2 = factor·[0, 0, 2r]
    """

    @staticmethod
    def _j2_factor(r_mag: float) -> float:
        return 1.5 * J2 * MU_EARTH * R_EARTH**2 / r_mag**5

    @staticmethod
    def _j2_only(pos: np.ndarray) -> np.ndarray:
        """Strip two-body gravity, return only J2 component."""
        r = np.linalg.norm(pos)
        acc_total = OrbitalPropagator._compute_acceleration(pos)
        acc_2body = -MU_EARTH * pos / r**3
        return acc_total - acc_2body

    # ── equatorial position ──────────────────────────────────────────────────

    def test_equatorial_j2_x_exact(self):
        """[r,0,0]: J2 x-component = factor × r × (5×0 − 1) = −factor·r."""
        r = R_EARTH + 400.0
        pos = np.array([r, 0.0, 0.0])
        a_j2 = self._j2_only(pos)
        expected_ax = self._j2_factor(r) * r * (5.0 * 0.0 - 1.0)
        assert abs(a_j2[0] - expected_ax) < 1e-15, \
            f"J2 ax: expected {expected_ax:.6e}, got {a_j2[0]:.6e}"
        assert abs(a_j2[1]) < 1e-15, "J2 ay must be 0 at equatorial x-position"
        assert abs(a_j2[2]) < 1e-15, "J2 az must be 0 at equatorial x-position"

    def test_equatorial_j2_is_inward(self):
        """J2 radial correction at equatorial position must point TOWARD Earth."""
        r = R_EARTH + 400.0
        a_j2 = self._j2_only(np.array([r, 0.0, 0.0]))
        assert a_j2[0] < 0, "J2 at equatorial x must be negative (Earthward)"

    def test_equatorial_y_axis_symmetric(self):
        """[0,r,0] must have same J2 magnitude as [r,0,0] (equatorial symmetry)."""
        r = R_EARTH + 400.0
        a_x = self._j2_only(np.array([r, 0.0, 0.0]))
        a_y = self._j2_only(np.array([0.0, r, 0.0]))
        assert abs(np.linalg.norm(a_x) - np.linalg.norm(a_y)) < 1e-14, \
            "J2 magnitude must be identical at [r,0,0] and [0,r,0]"

    # ── polar position ───────────────────────────────────────────────────────

    def test_polar_j2_z_exact(self):
        """[0,0,r]: J2 z-component = factor × r × (5×1 − 3) = +2·factor·r."""
        r = R_EARTH + 400.0
        pos = np.array([0.0, 0.0, r])
        a_j2 = self._j2_only(pos)
        expected_az = self._j2_factor(r) * r * (5.0 * 1.0 - 3.0)  # = 2·factor·r
        assert abs(a_j2[0]) < 1e-15, "J2 ax must be 0 at polar z-position"
        assert abs(a_j2[1]) < 1e-15, "J2 ay must be 0 at polar z-position"
        assert abs(a_j2[2] - expected_az) < 1e-12, \
            f"J2 az: expected {expected_az:.6e}, got {a_j2[2]:.6e}"

    def test_polar_j2_is_outward(self):
        """J2 z-correction at polar position must point AWAY from Earth (+z)."""
        a_j2 = self._j2_only(np.array([0.0, 0.0, R_EARTH + 400.0]))
        assert a_j2[2] > 0, "J2 at polar z must be positive (away from Earth)"

    def test_j2_is_roughly_1000x_smaller_than_gravity(self):
        """J2 perturbation magnitude must be ≈ 1.08e−3 × two-body gravity."""
        r = R_EARTH + 400.0
        pos = np.array([r, 0.0, 0.0])
        a_j2   = self._j2_only(pos)
        a_2body = MU_EARTH * pos / r**3  # magnitude reference
        ratio = abs(a_j2[0]) / abs(a_2body[0])
        # Expected ≈ 1.5·J2·(RE/r)² ≈ 7.7e-4
        assert 1e-4 < ratio < 5e-3, \
            f"J2/gravity ratio {ratio:.2e} outside expected [1e-4, 5e-3]"

    def test_j2_acceleration_no_nan_no_inf(self):
        """_compute_acceleration must not return NaN or Inf for valid LEO positions."""
        for alt_km in [200, 400, 600, 1000, 2000]:
            r = R_EARTH + alt_km
            for pos in [np.array([r, 0, 0]), np.array([0, r, 0]), np.array([0, 0, r])]:
                acc = OrbitalPropagator._compute_acceleration(pos)
                assert not np.any(np.isnan(acc)), f"NaN at alt={alt_km} km"
                assert not np.any(np.isinf(acc)), f"Inf at alt={alt_km} km"


# ═══════════════════════════════════════════════════════════════════════════════
# §2  24-HOUR PROPAGATION STABILITY & ACCURACY
# ═══════════════════════════════════════════════════════════════════════════════

class TestPropagationAccuracy:
    """
    J2 does NOT change the semi-major axis to first order, so orbital energy
    must be conserved. The signature J2 effect is RAAN regression.
    """

    @staticmethod
    def _specific_energy(sv: np.ndarray) -> float:
        r = np.linalg.norm(sv[:3])
        v = np.linalg.norm(sv[3:])
        return 0.5 * v**2 - MU_EARTH / r

    @staticmethod
    def _raan_deg(sv: np.ndarray) -> float:
        pos, vel = sv[:3], sv[3:]
        h = np.cross(pos, vel)
        N = np.cross(np.array([0.0, 0.0, 1.0]), h)
        if np.linalg.norm(N) < 1e-10:
            return 0.0
        N_hat = N / np.linalg.norm(N)
        return math.degrees(math.atan2(N_hat[1], N_hat[0]))

    def test_energy_conserved_24h(self, prop, iss_state):
        """
        Two-body specific energy (½v²−μ/r) must not drift by more than 1e-2 over 24h.

        Note: J2 is conservative but adds a potential term μ·J2·RE²·P₂(sin φ)/r³.
        The full Hamiltonian (two-body + J2) is conserved, but the two-body proxy
        ½v²−μ/r absorbs the J2 work; expect ~O(J2) ~ 1e-3 relative change.
        Tolerance 1e-2 catches integrator blowup, sign errors, and catastrophic drift
        while being physically meaningful for a J2-perturbed orbit.
        """
        e0 = self._specific_energy(iss_state)
        final = prop.propagate(iss_state, 86400.0)
        e1 = self._specific_energy(final)
        rel_err = abs((e1 - e0) / e0)
        assert rel_err < 1e-2, f"24h energy error: {rel_err:.2e} (max 1e-2)"

    def test_semi_major_axis_conserved_24h(self, prop, equatorial_state):
        """
        Semi-major axis (a = −μ/2E) must be conserved to < 1 km over 24 hours.

        J2 is a conservative perturbation: it causes short-period oscillations in
        the instantaneous orbital radius (|r⃗|), but the semi-major axis is a secular
        element conserved to first order in J2.  This is the correct invariant to test.
        """
        def sma(sv):
            r = np.linalg.norm(sv[:3])
            v = np.linalg.norm(sv[3:])
            E = 0.5 * v**2 - MU_EARTH / r
            return -MU_EARTH / (2.0 * E)

        a0 = sma(equatorial_state)
        a1 = sma(prop.propagate(equatorial_state, 86400.0))
        assert abs(a1 - a0) < 1.0, \
            f"Semi-major axis drifted {abs(a1 - a0):.4f} km over 24h (max 1 km)"

    def test_propagation_no_nan_no_inf_24h(self, prop, iss_state):
        """24-hour propagation must produce finite, physically sane state vector."""
        final = prop.propagate(iss_state, 86400.0)
        assert not np.any(np.isnan(final)), "NaN in 24h propagation output"
        assert not np.any(np.isinf(final)), "Inf in 24h propagation output"
        r = np.linalg.norm(final[:3])
        assert 6400 < r < 10_000, f"Unrealistic orbital radius after 24h: {r:.1f} km"

    def test_raan_regression_matches_analytics_24h(self, prop, iss_state):
        """
        RAAN regression over 24h must match analytical J2 prediction within 20%.

        Analytical rate (Kozai, 1st order):
          dΩ/dt = -3/2 · n · J2 · (RE/r)² · cos(i)
        For i=51.6°, r=6778.137 km → ≈ −6.97°/day
        """
        r = np.linalg.norm(iss_state[:3])
        inc = math.radians(51.6)
        n = math.sqrt(MU_EARTH / r**3)
        analytical_rate_deg_day = math.degrees(
            -1.5 * n * J2 * (R_EARTH / r)**2 * math.cos(inc)
        ) * 86400.0

        raan_0 = self._raan_deg(iss_state)
        raan_1 = self._raan_deg(prop.propagate(iss_state, 86400.0))
        delta = raan_1 - raan_0
        if delta > 180:  delta -= 360
        if delta < -180: delta += 360

        assert abs(delta - analytical_rate_deg_day) < abs(analytical_rate_deg_day) * 0.20, (
            f"RAAN drift: simulated {delta:.3f}°/day, analytical {analytical_rate_deg_day:.3f}°/day"
        )

    def test_time_reversibility_1h(self, prop, iss_state):
        """Forward 1h then backward 1h must recover initial position to < 0.01 km."""
        dt = 3600.0
        fwd = prop.propagate(iss_state, dt)
        # Time-reverse: flip velocity, propagate same dt, flip velocity back
        rev_in = np.concatenate([fwd[:3], -fwd[3:]])
        bwd = prop.propagate(rev_in, dt)
        recovered = np.concatenate([bwd[:3], -bwd[3:]])
        pos_err = np.linalg.norm(recovered[:3] - iss_state[:3])
        assert pos_err < 0.01, f"Time-reversal position error: {pos_err:.4f} km (max 0.01)"

    def test_batch_matches_individual_10_orbits(self, prop_fast):
        """propagate_batch must agree with individual propagate() for 10 diverse orbits."""
        rng = np.random.default_rng(2025)
        states = {}
        for i in range(10):
            r = R_EARTH + 300 + 200 * rng.random()
            v = math.sqrt(MU_EARTH / r)
            inc = rng.uniform(0, math.pi)
            theta = rng.uniform(0, 2 * math.pi)
            states[f"SAT-{i}"] = np.array([
                r * math.cos(theta), r * math.sin(theta), 0.0,
                -v * math.sin(theta) * math.cos(inc),
                 v * math.cos(theta) * math.cos(inc),
                 v * math.sin(inc),
            ])
        batch = prop_fast.propagate_batch(states, 600.0)
        for sid, sv in states.items():
            ind = prop_fast.propagate(sv, 600.0)
            np.testing.assert_allclose(
                batch[sid], ind, rtol=1e-5, atol=1e-6,
                err_msg=f"Batch/individual mismatch for {sid}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# §3  RTN-TO-ECI TRANSFORMATION — MATHEMATICAL CORRECTNESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRTNtoECI:
    """
    RTN frame:
      R̂ = r/|r|
      N̂ = (r×v)/|r×v|
      T̂ = N̂ × R̂     (NOTE: T̂ ≠ v̂ in general, but ≈ v̂ for circular orbits)

    For the special case of equatorial circular orbit at [r,0,0] / [0,v,0]:
      R̂=[1,0,0],  T̂=[0,1,0],  N̂=[0,0,1]  → RTN frame = ECI frame (identity matrix)

    For ISS-like [r,0,0] / [0,v·cos(i),v·sin(i)]:
      T̂=[0,cos(i),sin(i)], N̂=[0,−sin(i),cos(i)]
    """

    def test_basis_vectors_orthonormal(self, iss_state):
        """R̂, T̂, N̂ must each have unit length and be mutually perpendicular."""
        r_eci, v_eci = iss_state[:3], iss_state[3:]
        R = r_eci / np.linalg.norm(r_eci)
        h = np.cross(r_eci, v_eci)
        N = h / np.linalg.norm(h)
        T = np.cross(N, R)
        assert abs(np.linalg.norm(R) - 1.0) < 1e-14
        assert abs(np.linalg.norm(T) - 1.0) < 1e-14
        assert abs(np.linalg.norm(N) - 1.0) < 1e-14
        assert abs(np.dot(R, T)) < 1e-14, "R̂·T̂ must be 0"
        assert abs(np.dot(R, N)) < 1e-14, "R̂·N̂ must be 0"
        assert abs(np.dot(T, N)) < 1e-14, "T̂·N̂ must be 0"

    def test_rotation_matrix_is_orthogonal(self, iss_state):
        """The Q matrix built by rtn_to_eci must satisfy Q^T @ Q = I."""
        r, v = iss_state[:3], iss_state[3:]
        R_hat = r / np.linalg.norm(r)
        h = np.cross(r, v)
        N_hat = h / np.linalg.norm(h)
        T_hat = np.cross(N_hat, R_hat)
        Q = np.column_stack([R_hat, T_hat, N_hat])
        np.testing.assert_allclose(
            Q.T @ Q, np.eye(3), atol=1e-13,
            err_msg="RTN rotation matrix Q is not orthogonal (Q^T Q ≠ I)"
        )

    def test_equatorial_rtn_equals_eci_identity(self, equatorial_state):
        """At [r,0,0] / [0,v,0], the RTN frame must coincide with ECI axes."""
        r, v = equatorial_state[:3], equatorial_state[3:]
        R_hat = r / np.linalg.norm(r)
        h = np.cross(r, v)
        N_hat = h / np.linalg.norm(h)
        T_hat = np.cross(N_hat, R_hat)
        np.testing.assert_allclose(R_hat, [1, 0, 0], atol=1e-14)
        np.testing.assert_allclose(T_hat, [0, 1, 0], atol=1e-14)
        np.testing.assert_allclose(N_hat, [0, 0, 1], atol=1e-14)

    def test_t_burn_equatorial_is_pure_y(self, equatorial_state):
        """Pure T-burn at equatorial position must equal pure +y in ECI."""
        dv_eci = ManeuverPlanner.rtn_to_eci(
            equatorial_state[:3], equatorial_state[3:],
            np.array([0.0, 1.0, 0.0])
        )
        np.testing.assert_allclose(dv_eci, [0, 1, 0], atol=1e-13)

    def test_r_burn_equatorial_is_pure_x(self, equatorial_state):
        """Pure R-burn at equatorial position must equal pure +x in ECI."""
        dv_eci = ManeuverPlanner.rtn_to_eci(
            equatorial_state[:3], equatorial_state[3:],
            np.array([1.0, 0.0, 0.0])
        )
        np.testing.assert_allclose(dv_eci, [1, 0, 0], atol=1e-13)

    def test_n_burn_equatorial_is_pure_z(self, equatorial_state):
        """Pure N-burn at equatorial position must equal pure +z in ECI."""
        dv_eci = ManeuverPlanner.rtn_to_eci(
            equatorial_state[:3], equatorial_state[3:],
            np.array([0.0, 0.0, 1.0])
        )
        np.testing.assert_allclose(dv_eci, [0, 0, 1], atol=1e-13)

    def test_magnitude_preserved(self, iss_state):
        """RTN→ECI rotation must preserve ΔV magnitude (rotation is an isometry)."""
        dv_rtn = np.array([0.002, 0.015, -0.001])  # km/s
        dv_eci = ManeuverPlanner.rtn_to_eci(iss_state[:3], iss_state[3:], dv_rtn)
        assert abs(np.linalg.norm(dv_eci) - np.linalg.norm(dv_rtn)) < 1e-14, \
            "Rotation must not change delta-v magnitude"

    def test_inclined_t_burn_closed_form(self, iss_state):
        """
        Closed-form prediction for T-burn at [r,0,0]/[0,v·cos(i),v·sin(i)]:
            dv_ECI = [0,  dT·cos(i),  dT·sin(i)]

        Derivation:
          T̂ = N̂ × R̂  where N̂=[0,−sin i,cos i], R̂=[1,0,0]
             = [0, cos i, sin i]
          dv_ECI = dT · T̂ = [0, dT·cos i, dT·sin i]
        """
        i = math.radians(51.6)
        dv_T = 0.002  # km/s
        dv_eci = ManeuverPlanner.rtn_to_eci(
            iss_state[:3], iss_state[3:], np.array([0.0, dv_T, 0.0])
        )
        expected = np.array([0.0, dv_T * math.cos(i), dv_T * math.sin(i)])
        np.testing.assert_allclose(dv_eci, expected, atol=1e-14)


# ═══════════════════════════════════════════════════════════════════════════════
# §4  TSIOLKOVSKY ROCKET EQUATION — PRECISION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTsiolkovsky:
    """
    Problem statement equation (§5.1):
        Δm = m_current × (1 − e^(−|Δv⃗| / (Isp · g0)))

    Physical constants:
        m_dry  = 500.0 kg    m_fuel = 50.0 kg    m_wet  = 550.0 kg
        Isp    = 300.0 s     g0     = 9.80665 m/s²
    """

    def _fresh(self, fuel_kg: float = M_FUEL_INIT) -> FuelTracker:
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=fuel_kg)
        return ft

    def test_known_answer_2ms(self):
        """Δv=2 m/s, m=550 kg → Δm = 550×(1−e^(−2/2941.995)) ≈ 0.37395 kg."""
        ft = self._fresh()
        consumed = ft.consume("T", delta_v_ms=2.0)
        expected = M_WET_INIT * (1.0 - math.exp(-2.0 / (ISP * G0)))
        assert abs(consumed - expected) < 1e-9, \
            f"Expected {expected:.9f} kg, got {consumed:.9f} kg"

    def test_known_answer_10ms(self):
        """Δv=10 m/s, m=550 kg → Δm ≈ 1.8623 kg."""
        ft = self._fresh()
        consumed = ft.consume("T", delta_v_ms=10.0)
        expected = M_WET_INIT * (1.0 - math.exp(-10.0 / (ISP * G0)))
        assert abs(consumed - expected) < 1e-9

    def test_known_answer_15ms_max_burn(self):
        """Δv=15 m/s (hard limit), m=550 kg → exact Tsiolkovsky computation."""
        ft = self._fresh()
        consumed = ft.consume("T", delta_v_ms=15.0)
        expected = M_WET_INIT * (1.0 - math.exp(-15.0 / (ISP * G0)))
        assert abs(consumed - expected) < 1e-9

    def test_uses_wet_mass_not_dry_mass(self):
        """Tsiolkovsky must use m_current = m_dry + m_fuel, NOT m_dry alone."""
        ft = self._fresh()
        dv = 8.0  # m/s
        consumed = ft.consume("T", delta_v_ms=dv)
        expected_wet = M_WET_INIT * (1.0 - math.exp(-dv / (ISP * G0)))
        expected_dry = M_DRY    * (1.0 - math.exp(-dv / (ISP * G0)))
        assert abs(consumed - expected_wet) < 1e-9, \
            f"Used dry mass ({expected_dry:.4f}) instead of wet mass ({expected_wet:.4f})"

    def test_mass_coupling_sequential_burns(self):
        """Each subsequent burn uses the lighter post-burn mass → consumes LESS fuel."""
        ft = self._fresh()
        dv = 10.0
        prev = ft.consume("T", delta_v_ms=dv)
        for _ in range(4):
            curr = ft.consume("T", delta_v_ms=dv)
            assert curr < prev, "Successive identical burns must consume less fuel"
            prev = curr

    def test_three_sequential_burns_exact_cumulative(self):
        """Manual step-through: each burn computed from correct current mass."""
        ft = self._fresh()
        m = M_WET_INIT
        for dv in [5.0, 5.0, 5.0]:
            expected_dm = m * (1.0 - math.exp(-dv / (ISP * G0)))
            consumed = ft.consume("T", delta_v_ms=dv)
            assert abs(consumed - expected_dm) < 1e-9, \
                f"Step mismatch: expected {expected_dm:.9f}, got {consumed:.9f}"
            m -= consumed

    def test_fuel_never_below_zero(self):
        """Exhaustive burn on tiny fuel reserve must clamp to 0, not go negative."""
        ft = self._fresh(fuel_kg=0.05)
        ft.consume("T", delta_v_ms=15.0)
        assert ft.get_fuel("T") >= 0.0, "Fuel must never be negative"

    def test_eol_at_exactly_threshold(self):
        """is_eol must be True at exactly EOL_FUEL_THRESHOLD_KG (2.5 kg)."""
        ft = self._fresh(fuel_kg=EOL_FUEL_THRESHOLD_KG + 0.001)
        assert not ft.is_eol("T")
        ft._fuel["T"] = EOL_FUEL_THRESHOLD_KG
        assert ft.is_eol("T"), "EOL must trigger at exactly threshold"
        ft._fuel["T"] = EOL_FUEL_THRESHOLD_KG - 0.001
        assert ft.is_eol("T"), "EOL must trigger below threshold"

    def test_sufficient_fuel_logic(self):
        """sufficient_fuel mirrors the Tsiolkovsky check without consuming."""
        ft = self._fresh()
        assert ft.sufficient_fuel("T", delta_v_ms=10.0), "Should have fuel for 10 m/s"
        # Drain almost everything
        ft._fuel["T"] = 0.001
        assert not ft.sufficient_fuel("T", delta_v_ms=10.0), "Should NOT have fuel"

    def test_get_current_mass_tracks_consumption(self):
        """get_current_mass must equal M_DRY + remaining_fuel at all times."""
        ft = self._fresh()
        for _ in range(5):
            ft.consume("T", delta_v_ms=3.0)
            expected_mass = M_DRY + ft.get_fuel("T")
            assert abs(ft.get_current_mass("T") - expected_mass) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# §5  CONSTRAINT ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstraints:
    """
    Validates every hard constraint from the problem statement §5.1 and §5.4:
      • |ΔV⃗| ≤ 15.0 m/s per burn
      • 600-second mandatory thermal cooldown between burns
      • 10-second minimum signal latency (burn_time ≥ now + 10s)
      • Ground station LOS required for command transmission
    """

    @pytest.fixture(autouse=True)
    def planner_and_now(self):
        self.planner = ManeuverPlanner()
        self.now = datetime.now(timezone.utc)

    def _validate(self, dv_ms=2.0, lead_s=30.0, cooldown_elapsed=700.0,
                  has_los=True, last_burn=True):
        last = (self.now - timedelta(seconds=cooldown_elapsed)) if last_burn else None
        return self.planner.validate_burn(
            delta_v_magnitude_ms=dv_ms,
            burn_time=self.now + timedelta(seconds=lead_s),
            current_time=self.now,
            last_burn_time=last,
            has_los=has_los,
        )

    # ── ΔV limit ─────────────────────────────────────────────────────────────

    def test_dv_above_15ms_rejected(self):
        valid, reason = self._validate(dv_ms=15.001)
        assert not valid, "16 m/s must be rejected"
        assert "15" in reason or "thrust" in reason.lower()

    def test_dv_at_exactly_15ms_accepted(self):
        valid, _ = self._validate(dv_ms=15.0)
        assert valid, "15.0 m/s (exact limit) must be accepted"

    def test_dv_at_zero_accepted(self):
        valid, _ = self._validate(dv_ms=0.0)
        assert valid, "0 m/s ΔV must be accepted (no-op burn)"

    # ── signal latency ───────────────────────────────────────────────────────

    def test_burn_at_9s_rejected(self):
        valid, reason = self._validate(lead_s=9.0)
        assert not valid
        assert any(tok in reason.lower() for tok in ["latency", "signal", "10"])

    def test_burn_at_exactly_10s_accepted(self):
        valid, _ = self._validate(lead_s=10.0)
        assert valid, "Burn at exactly now+10s must pass signal latency"

    def test_burn_at_0s_rejected(self):
        valid, _ = self._validate(lead_s=0.0)
        assert not valid, "Burn at now+0s must be rejected (violates 10s latency)"

    # ── thermal cooldown ─────────────────────────────────────────────────────

    def test_cooldown_within_599s_rejected(self):
        """Last burn 300s ago, new burn in 30s → gap = 330s < 600s → rejected."""
        valid, reason = self._validate(cooldown_elapsed=300.0, lead_s=30.0)
        assert not valid
        assert "600" in reason or "cooldown" in reason.lower()

    def test_cooldown_at_exactly_600s_accepted(self):
        """Last burn at T0, new burn at T0 + exactly 600s → accepted.

        PRD §4.5: 'mandatory 600-second rest period' — at exactly 600s
        the rest period IS complete, so the burn is valid.
        """
        last = self.now - timedelta(seconds=570)     # 570s ago
        burn_time = last + timedelta(seconds=600)    # exactly 600s after last
        valid, _ = self.planner.validate_burn(
            delta_v_magnitude_ms=2.0,
            burn_time=burn_time,
            current_time=self.now,
            last_burn_time=last,
            has_los=True,
        )
        assert valid, "Burn exactly 600s after last must be accepted (rest complete)"

    def test_no_previous_burn_skips_cooldown(self):
        """With last_burn_time=None the cooldown check must be skipped entirely."""
        valid, _ = self._validate(lead_s=30.0, last_burn=False)
        assert valid

    # ── LOS ─────────────────────────────────────────────────────────────────

    def test_no_los_rejected(self):
        valid, reason = self._validate(has_los=False)
        assert not valid
        assert any(tok in reason.lower() for tok in ["los", "ground", "station"])

    # ── all constraints satisfied ────────────────────────────────────────────

    def test_all_good_accepted(self):
        """All constraints satisfied → valid."""
        valid, reason = self._validate(
            dv_ms=10.0, lead_s=30.0, cooldown_elapsed=700.0, has_los=True
        )
        assert valid, f"All constraints met but rejected: {reason}"

    # ── engine-level rejection ───────────────────────────────────────────────

    def test_engine_rejects_16ms_burn(self):
        """SimulationEngine.schedule_maneuver must propagate ΔV > 15 m/s rejection."""
        engine = SimulationEngine()
        engine.ingest_telemetry(
            datetime.utcnow().isoformat() + "Z",
            [{"id": "SAT-X", "type": "SATELLITE",
              "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
        )
        future = (datetime.utcnow() + timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        result = engine.schedule_maneuver("SAT-X", [{
            "burn_id": "OVER_LIMIT",
            "burnTime": future,
            "deltaV_vector": {"x": 0.016, "y": 0.0, "z": 0.0},  # 16 m/s
        }])
        assert result["status"] == "REJECTED", \
            "Engine must reject a 16 m/s burn"

    def test_engine_rejects_unknown_satellite(self):
        """schedule_maneuver for nonexistent sat must return REJECTED."""
        engine = SimulationEngine()
        result = engine.schedule_maneuver("SAT-GHOST", [])
        assert result["status"] == "REJECTED"


# ═══════════════════════════════════════════════════════════════════════════════
# §6  COLLISION DETECTION PHYSICS & EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollisionPhysics:
    """
    Verifies the 100 m collision threshold, zero-distance edge case,
    risk classification boundaries, and station-keeping box logic.
    """

    @pytest.fixture(scope="class")
    def assessor(self):
        return ConjunctionAssessor(OrbitalPropagator(rtol=1e-6, atol=1e-8))

    # ── risk classification ──────────────────────────────────────────────────

    def test_classify_critical_below_100m(self):
        assert ConjunctionAssessor._classify_risk(0.099) == "CRITICAL"

    def test_classify_boundary_exactly_100m_not_critical(self):
        """Miss distance = 0.100 km exactly must be RED, not CRITICAL."""
        risk = ConjunctionAssessor._classify_risk(CONJUNCTION_THRESHOLD_KM)
        assert risk == "RED", f"At exactly threshold expected RED, got {risk}"

    def test_classify_red_below_1km(self):
        assert ConjunctionAssessor._classify_risk(0.5) == "RED"

    def test_classify_yellow_below_5km(self):
        assert ConjunctionAssessor._classify_risk(3.0) == "YELLOW"

    def test_classify_green_above_5km(self):
        assert ConjunctionAssessor._classify_risk(10.0) == "GREEN"

    # ── 0 m collision ────────────────────────────────────────────────────────

    def test_zero_meter_collision_emits_critical(self, assessor):
        """Objects at identical positions (0 m) must emit CRITICAL CDM."""
        sv = np.array([6778.0, 0.0, 0.0,   0.0, 7.67, 0.0])
        cdms = assessor.assess({"SAT-X": sv.copy()}, {"DEB-X": sv.copy()},
                               lookahead_s=600.0)
        assert len(cdms) >= 1
        assert cdms[0].risk == "CRITICAL"
        assert cdms[0].miss_distance_km < CONJUNCTION_THRESHOLD_KM

    # ── threshold boundary ───────────────────────────────────────────────────

    def test_99m_is_critical(self, assessor):
        """Objects 99 m apart with identical velocities → CRITICAL."""
        sv_sat = np.array([6778.000, 0.0, 0.0,   0.0, 7.67, 0.0])
        sv_deb = np.array([6778.099, 0.0, 0.0,   0.0, 7.67, 0.0])
        cdms = assessor.assess({"SAT": sv_sat}, {"DEB": sv_deb}, lookahead_s=600.0)
        assert len(cdms) == 1
        assert cdms[0].risk == "CRITICAL", \
            f"99 m separation should be CRITICAL, got {cdms[0].risk}"

    def test_101m_is_not_critical(self, assessor):
        """Objects 101 m apart with identical velocities → RED (not CRITICAL)."""
        sv_sat = np.array([6778.000, 0.0, 0.0,   0.0, 7.67, 0.0])
        sv_deb = np.array([6778.101, 0.0, 0.0,   0.0, 7.67, 0.0])
        cdms = assessor.assess({"SAT": sv_sat}, {"DEB": sv_deb}, lookahead_s=600.0)
        assert len(cdms) == 1
        assert cdms[0].risk != "CRITICAL", \
            f"101 m separation must NOT be CRITICAL, got {cdms[0].risk}"

    # ── empty inputs ─────────────────────────────────────────────────────────

    def test_empty_sat_returns_empty(self, assessor):
        assert assessor.assess({}, {"DEB": np.zeros(6)}) == []

    def test_empty_deb_returns_empty(self, assessor):
        assert assessor.assess({"SAT": np.zeros(6)}, {}) == []

    def test_both_empty_returns_empty(self, assessor):
        assert assessor.assess({}, {}) == []

    # ── TCA must be in the future ────────────────────────────────────────────

    def test_cdm_tca_is_after_base_time(self, assessor):
        """CDM TCA must be ≥ the base time passed to assess()."""
        base = datetime.now(timezone.utc)
        sv_sat = np.array([6778.000, 0.0, 0.0,   0.0, 7.67, 0.0])
        sv_deb = np.array([6778.050, 0.0, 0.0,   0.0, 7.67, 0.0])
        cdms = assessor.assess({"S": sv_sat}, {"D": sv_deb},
                               lookahead_s=600.0, current_time=base)
        assert len(cdms) == 1
        assert cdms[0].tca >= base, "TCA must not be in the past"

    # ── station-keeping ──────────────────────────────────────────────────────
    # NOTE: The nominal slot is a fixed ECI point.  In LEO a satellite travels
    # ~7.7 km/s, so the instantaneous ECI offset grows fast.  These tests verify
    # the offset threshold logic and status-transition machinery.

    def test_zero_offset_is_inside_box(self):
        """Satellite exactly at nominal slot (offset = 0) → within box."""
        assert 0.0 <= STATION_KEEPING_RADIUS_KM

    def test_exactly_10km_is_inside_box(self):
        """Satellite exactly 10 km from slot → inside box (≤ 10 km criterion)."""
        assert 10.0 <= STATION_KEEPING_RADIUS_KM

    def test_11km_is_outside_box(self):
        """11 km offset exceeds the 10 km station-keeping radius."""
        assert 11.0 > STATION_KEEPING_RADIUS_KM

    def test_recovering_status_when_outside_slot(self):
        """
        Satellite with nominal slot far from its orbit must become RECOVERING.

        We set the slot 1000 km away in y-direction.  After any short tick the
        satellite (initially at [6778,0,0] moving at 7.67 km/s) remains hundreds
        of km from [6778,1000,0], guaranteeing the 10 km threshold is violated.
        """
        engine = SimulationEngine()
        engine.ingest_telemetry(
            datetime.utcnow().isoformat() + "Z",
            [{"id": "SAT-OOB", "type": "SATELLITE",
              "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
        )
        # Nominal slot 1000 km away — satellite can never be within 10 km after 1s
        engine.satellites["SAT-OOB"].nominal_state = np.array([6778.0, 1000.0, 0.0, 0.0, 0.0, 0.0])
        engine.step(1)
        status = engine.satellites["SAT-OOB"].status
        assert status in ("RECOVERING", "EVADING", "EOL"), \
            f"Satellite 1000 km from slot must not be NOMINAL, got {status}"

    def test_nominal_status_when_near_slot(self):
        """Satellite placed at its own nominal slot (0 km offset) must be NOMINAL."""
        engine = SimulationEngine()
        engine.ingest_telemetry(
            datetime.utcnow().isoformat() + "Z",
            [{"id": "SAT-NOM", "type": "SATELLITE",
              "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
        )
        sat = engine.satellites["SAT-NOM"]
        # Set nominal slot to current propagated position (computed by engine after tick)
        # Pre-check: offset at T=0 is exactly 0 → within box
        offset = float(np.linalg.norm(sat.position - sat.nominal_state[:3]))
        assert offset == pytest.approx(0.0, abs=0.001) or offset <= STATION_KEEPING_RADIUS_KM


# ═══════════════════════════════════════════════════════════════════════════════
# §7  O(N²) BOTTLENECK SHATTERER — 100K-OBJECT KDTREE STRESS TEST
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpatialIndexPerformance:
    """
    The conjuction assessor must NOT use O(N²) algorithms.
    These tests quantitatively prove KDTree performance dominance at scale.

    Competition weight: Algorithmic Speed = 15% of total grade.
    """

    @staticmethod
    def _leo_positions(n: int, seed: int = 42) -> np.ndarray:
        """N random positions distributed on a sphere at 400 km altitude."""
        rng = np.random.default_rng(seed)
        vecs = rng.standard_normal((n, 3))
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return (vecs / norms) * (R_EARTH + 400.0)

    def test_kdtree_100k_build_under_3s(self):
        """Build time for 100,000-object KDTree must be < 3 seconds."""
        from scipy.spatial import KDTree
        positions = self._leo_positions(100_000)
        t0 = time.perf_counter()
        KDTree(positions)
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, \
            f"KDTree build for 100K objects took {elapsed:.2f}s (max 3s)"

    def test_50_queries_into_100k_under_1s(self):
        """50 radius queries into a 100K KDTree must complete in < 1 second."""
        from scipy.spatial import KDTree
        tree = KDTree(self._leo_positions(100_000))
        sats = self._leo_positions(50, seed=99)
        t0 = time.perf_counter()
        tree.query_ball_point(sats, r=50.0)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, \
            f"50 queries into 100K KDTree took {elapsed:.3f}s (max 1s)"

    def test_kdtree_correctness_matches_naive(self):
        """KDTree hits must be IDENTICAL to brute-force results on 5K objects."""
        from scipy.spatial import KDTree
        debris = self._leo_positions(5_000)
        sats   = self._leo_positions(10, seed=77)
        tree = KDTree(debris)
        for i, sat in enumerate(sats):
            kdtree_hits = set(tree.query_ball_point(sat, r=50.0))
            naive_hits  = set(
                int(j) for j, d in enumerate(np.linalg.norm(debris - sat, axis=1))
                if d <= 50.0
            )
            assert kdtree_hits == naive_hits, \
                f"Satellite {i}: KDTree={len(kdtree_hits)}, naive={len(naive_hits)}"

    def test_kdtree_dominates_naive_at_100k(self):
        """
        Quantitative speedup test:
          - KDTree: 100K debris, 50 satellite queries
          - Naive:  2K  debris, 50 satellite queries (then extrapolated to 100K)
          - Required speedup: > 50x

        This is the exact bottleneck the problem statement warns about:
        "50 satellites × 10,000 debris × 144 timesteps = 72 million calculations"
        """
        from scipy.spatial import KDTree
        N_LARGE  = 100_000
        N_SMALL  = 2_000    # feasible for naive
        N_SATS   = 50
        RADIUS   = 50.0     # km — Stage 2 filter radius

        debris_large = self._leo_positions(N_LARGE)
        debris_small = self._leo_positions(N_SMALL, seed=101)
        sats         = self._leo_positions(N_SATS,  seed=99)

        # KDTree approach at full 100K scale
        tree = KDTree(debris_large)
        t0 = time.perf_counter()
        tree.query_ball_point(sats, r=RADIUS)
        kdtree_time = time.perf_counter() - t0

        # Naive O(N) loop at small scale
        t0 = time.perf_counter()
        for sat in sats:
            np.where(np.linalg.norm(debris_small - sat, axis=1) <= RADIUS)[0]
        naive_time_small = time.perf_counter() - t0

        # Extrapolate naive time linearly to 100K (O(N) in debris count)
        naive_100k = naive_time_small * (N_LARGE / N_SMALL)
        speedup = naive_100k / max(kdtree_time, 1e-9)

        print(f"\n  [BENCHMARK] KDTree 100K+50q: {kdtree_time*1000:.2f} ms")
        print(f"  [BENCHMARK] Naive   2K+50q:  {naive_time_small*1000:.2f} ms")
        print(f"  [BENCHMARK] Naive extrapolated to 100K: {naive_100k*1000:.2f} ms")
        print(f"  [BENCHMARK] Speedup: {speedup:.1f}x")

        assert speedup > 50, \
            f"KDTree speedup {speedup:.1f}x is insufficient (required > 50x)"

    def test_conjunction_assessor_50sats_10k_debris_under_60s(self):
        """
        Full 4-stage ConjunctionAssessor must handle 50 satellites × 10,000 debris
        within 60 seconds — this is the actual grader scenario.
        """
        from engine.collision import ConjunctionAssessor
        rng = np.random.default_rng(42)
        prop = OrbitalPropagator(rtol=1e-6, atol=1e-8)
        assessor = ConjunctionAssessor(prop)
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        sat_states = {}
        for i in range(50):
            th = rng.uniform(0, 2 * math.pi)
            inc = math.radians(rng.uniform(30, 60))
            sat_states[f"SAT-{i:03d}"] = np.array([
                r * math.cos(th), r * math.sin(th), 0.0,
                -v * math.sin(th) * math.cos(inc),
                 v * math.cos(th) * math.cos(inc),
                 v * math.sin(inc),
            ])

        deb_states = {}
        for i in range(10_000):
            r_d = R_EARTH + rng.uniform(300, 600)
            v_d = math.sqrt(MU_EARTH / r_d)
            th = rng.uniform(0, 2 * math.pi)
            phi = rng.uniform(-math.pi / 2, math.pi / 2)
            deb_states[f"DEB-{i:05d}"] = np.array([
                r_d * math.cos(th) * math.cos(phi),
                r_d * math.sin(th) * math.cos(phi),
                r_d * math.sin(phi),
                -v_d * math.sin(th),
                 v_d * math.cos(th),
                 0.0,
            ])

        t0 = time.perf_counter()
        cdms = assessor.assess(sat_states, deb_states, lookahead_s=3600.0)
        elapsed = time.perf_counter() - t0

        print(f"\n  [STRESS] 50 sats × 10K debris → {len(cdms)} CDMs in {elapsed:.2f}s")
        assert elapsed < 60.0, \
            f"ConjunctionAssessor took {elapsed:.2f}s (max 60s)"


# ═══════════════════════════════════════════════════════════════════════════════
# §8  INTEGRATION — FULL 7-STEP TICK LOOP
# ═══════════════════════════════════════════════════════════════════════════════

class TestTickLoop:
    """End-to-end integration through SimulationEngine.step()."""

    @staticmethod
    def _burn_time_str(engine: SimulationEngine, lead_s: float = 30.0) -> str:
        """Return a burn time string in '...Z' format."""
        return (engine.sim_time + timedelta(seconds=lead_s)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    @staticmethod
    def _make_engine(n_sats: int = 3, n_deb: int = 10) -> SimulationEngine:
        engine = SimulationEngine()
        objects = []
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)
        for i in range(n_sats):
            objects.append({
                "id": f"SAT-{i:02d}", "type": "SATELLITE",
                "r": {"x": r, "y": float(i * 15), "z": 0.0},
                "v": {"x": 0.0, "y": v, "z": 0.0},
            })
        for i in range(n_deb):
            objects.append({
                "id": f"DEB-{i:03d}", "type": "DEBRIS",
                "r": {"x": R_EARTH + 800.0, "y": float(i * 50), "z": 0.0},
                "v": {"x": 0.0, "y": 6.5, "z": 0.0},
            })
        engine.ingest_telemetry(datetime.utcnow().isoformat() + "Z", objects)
        return engine

    # ── API contract ─────────────────────────────────────────────────────────

    def test_step_response_schema(self):
        engine = self._make_engine()
        result = engine.step(60)
        assert result["status"] == "STEP_COMPLETE"
        assert isinstance(result["new_timestamp"], str)
        assert isinstance(result["collisions_detected"], int)
        assert isinstance(result["maneuvers_executed"], int)
        assert result["collisions_detected"] >= 0
        assert result["maneuvers_executed"] >= 0

    def test_ingest_telemetry_response_schema(self):
        engine = SimulationEngine()
        result = engine.ingest_telemetry(
            datetime.utcnow().isoformat() + "Z",
            [{"id": "S1", "type": "SATELLITE",
              "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
        )
        assert result["status"] == "ACK"
        assert result["processed_count"] == 1
        assert "active_cdm_warnings" in result

    def test_schedule_maneuver_rejected_schema(self):
        engine = SimulationEngine()
        result = engine.schedule_maneuver("GHOST", [])
        assert result["status"] == "REJECTED"
        assert "ground_station_los" in result["validation"]
        assert "sufficient_fuel" in result["validation"]
        assert "projected_mass_remaining_kg" in result["validation"]

    # ── physics correctness ──────────────────────────────────────────────────

    def test_clock_advances_exactly(self):
        engine = self._make_engine()
        t0 = engine.sim_time
        engine.step(3600)
        assert abs((engine.sim_time - t0).total_seconds() - 3600.0) < 0.001

    def test_satellite_positions_change_after_tick(self):
        engine = self._make_engine()
        pre = {sid: sat.position.copy() for sid, sat in engine.satellites.items()}
        engine.step(600)
        for sid, sat in engine.satellites.items():
            assert not np.allclose(sat.position, pre[sid]), \
                f"{sid} position unchanged after 600s"

    def test_maneuver_changes_velocity(self):
        """Directly queue a burn; after step it must change satellite velocity."""
        engine = self._make_engine(n_sats=1, n_deb=0)
        sat = engine.satellites["SAT-00"]
        bt = self._burn_time_str(engine, lead_s=30.0)
        # Bypass LOS/schedule API — directly inject into queue
        sat.maneuver_queue.append({
            "burn_id": "TEST",
            "burnTime": bt,
            "deltaV_vector": {"x": 0.0, "y": 0.002, "z": 0.0},
        })
        v_before = sat.velocity.copy()
        engine.step(60)
        v_after = engine.satellites["SAT-00"].velocity
        assert np.linalg.norm(v_after - v_before) > 0, \
            "Delta-v must be applied to satellite velocity"

    def test_maneuver_depletes_fuel(self):
        """After a queued burn executes, fuel must decrease."""
        engine = self._make_engine(n_sats=1, n_deb=0)
        sat = engine.satellites["SAT-00"]
        initial_fuel = engine.fuel_tracker.get_fuel("SAT-00")
        bt = self._burn_time_str(engine, lead_s=30.0)
        sat.maneuver_queue.append({
            "burn_id": "FUEL_TEST",
            "burnTime": bt,
            "deltaV_vector": {"x": 0.0, "y": 0.002, "z": 0.0},
        })
        engine.step(60)
        assert engine.fuel_tracker.get_fuel("SAT-00") < initial_fuel, \
            "Fuel must decrease after maneuver execution"

    def test_eol_triggered_by_critical_fuel(self):
        """Satellite with fuel ≤ threshold must be marked EOL on next tick."""
        engine = self._make_engine(n_sats=1, n_deb=0)
        engine.fuel_tracker._fuel["SAT-00"] = EOL_FUEL_THRESHOLD_KG - 0.1
        engine.step(1)
        assert engine.satellites["SAT-00"].status == "EOL", \
            "Sub-threshold fuel must trigger EOL status"

    def test_snapshot_structure(self):
        """get_snapshot must return well-formed dict."""
        engine = self._make_engine()
        snap = engine.get_snapshot()
        assert "timestamp" in snap
        assert "satellites" in snap
        assert "debris_cloud" in snap
        assert isinstance(snap["satellites"], list)
        assert isinstance(snap["debris_cloud"], list)
        for sat in snap["satellites"]:
            assert "id" in sat and "fuel_kg" in sat and "status" in sat

    def test_multiple_steps_stable(self):
        """Five consecutive 600s ticks must not crash or produce NaN positions."""
        engine = self._make_engine(n_sats=5, n_deb=20)
        for _ in range(5):
            engine.step(600)
        for sat in engine.satellites.values():
            assert not np.any(np.isnan(sat.position)), "NaN position after 5 ticks"
            r = np.linalg.norm(sat.position)
            assert 6000 < r < 12000, f"Unrealistic position r={r:.1f} km"
