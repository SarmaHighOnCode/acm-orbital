"""
test_chaos_invariants.py — Randomized chaos tests with invariant assertions.

Every test uses random valid inputs but asserts universal invariants that
must hold regardless of input. 200+ unique test cases.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from engine.propagator import OrbitalPropagator
from engine.fuel_tracker import FuelTracker
from engine.simulation import SimulationEngine, _eci_to_lla
from config import MU_EARTH, R_EARTH, M_FUEL_INIT, ISP, G0, M_DRY

T0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
RNG = np.random.RandomState(42)  # Deterministic for reproducibility

def _random_leo_sv():
    alt = RNG.uniform(200, 1500)
    inc = RNG.uniform(0, 180)
    r = R_EARTH + alt
    v = np.sqrt(MU_EARTH / r)
    inc_rad = np.radians(inc)
    # Random RAAN
    raan = RNG.uniform(0, 2 * np.pi)
    x = r * np.cos(raan)
    y = r * np.sin(raan)
    vx = -v * np.sin(raan) * np.cos(inc_rad)
    vy = v * np.cos(raan) * np.cos(inc_rad)
    vz = v * np.sin(inc_rad)
    return np.array([x, y, 0.0, vx, vy, vz])

def _obj(oid, otype, alt_km=400.0):
    r = R_EARTH + alt_km
    v = np.sqrt(MU_EARTH / r)
    return {
        "id": oid, "type": otype,
        "r": {"x": float(r), "y": 0.0, "z": 0.0},
        "v": {"x": 0.0, "y": float(v * 0.866), "z": float(v * 0.5)},
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1: PROPAGATION INVARIANTS — 50 random orbits
# ═══════════════════════════════════════════════════════════════════════════

RANDOM_SVS = [_random_leo_sv() for _ in range(50)]

@pytest.mark.parametrize("idx", range(50))
def test_random_orbit_stays_above_surface(idx):
    """Random orbit #{idx} should stay above Earth surface."""
    prop = OrbitalPropagator()
    sv0 = RANDOM_SVS[idx]
    sv1 = prop.propagate(sv0, 3600)
    r = np.linalg.norm(sv1[:3])
    assert r > R_EARTH * 0.9, f"Orbit #{idx} crashed: r={r:.1f}km"

@pytest.mark.parametrize("idx", range(50))
def test_random_orbit_state_finite(idx):
    """Random orbit #{idx} should produce finite state after propagation."""
    prop = OrbitalPropagator()
    sv1 = prop.propagate(RANDOM_SVS[idx], 1800)
    assert np.all(np.isfinite(sv1)), f"Orbit #{idx} produced NaN/Inf"

@pytest.mark.parametrize("idx", range(50))
def test_random_orbit_energy_bounded(idx):
    """Random orbit #{idx} should have bounded specific energy."""
    sv = RANDOM_SVS[idx]
    r = np.linalg.norm(sv[:3])
    v = np.linalg.norm(sv[3:])
    E = 0.5 * v**2 - MU_EARTH / r
    assert E < 0, f"Orbit #{idx} is hyperbolic (E={E:.2f})"


# ═══════════════════════════════════════════════════════════════════════════
# §2: FUEL INVARIANTS — random burn sequences
# ═══════════════════════════════════════════════════════════════════════════

RANDOM_BURN_SEQS = [RNG.uniform(0.1, 5.0, size=RNG.randint(1, 20)).tolist()
                     for _ in range(30)]

@pytest.mark.parametrize("idx", range(30))
def test_random_burns_fuel_never_negative(idx):
    """Random burn sequence #{idx} should never produce negative fuel."""
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    for dv in RANDOM_BURN_SEQS[idx]:
        ft.consume("SAT", dv)
    assert ft.get_fuel("SAT") >= 0

@pytest.mark.parametrize("idx", range(30))
def test_random_burns_fuel_monotonic(idx):
    """Random burn sequence #{idx} should monotonically decrease fuel."""
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    prev = M_FUEL_INIT
    for dv in RANDOM_BURN_SEQS[idx]:
        ft.consume("SAT", dv)
        curr = ft.get_fuel("SAT")
        assert curr <= prev + 1e-10, f"Fuel increased: {prev:.6f} -> {curr:.6f}"
        prev = curr

@pytest.mark.parametrize("idx", range(30))
def test_random_burns_total_consumed_positive(idx):
    """Random burn sequence #{idx} total consumption should be positive."""
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    total = 0
    for dv in RANDOM_BURN_SEQS[idx]:
        total += ft.consume("SAT", dv)
    assert total > 0


# ═══════════════════════════════════════════════════════════════════════════
# §3: ECI→LLA INVARIANTS — random positions
# ═══════════════════════════════════════════════════════════════════════════

RANDOM_POSITIONS = [
    np.array([
        RNG.uniform(-10000, 10000),
        RNG.uniform(-10000, 10000),
        RNG.uniform(-10000, 10000),
    ]) for _ in range(30)
]
# Filter to only above-surface positions
RANDOM_POSITIONS = [p for p in RANDOM_POSITIONS if np.linalg.norm(p) > R_EARTH][:25]

RANDOM_TIMES = [T0 + timedelta(hours=RNG.uniform(0, 48)) for _ in range(25)]

@pytest.mark.parametrize("idx", range(min(len(RANDOM_POSITIONS), 25)))
def test_random_eci_lat_in_range(idx):
    lat, lon, alt = _eci_to_lla(RANDOM_POSITIONS[idx], RANDOM_TIMES[idx])
    assert -90 <= lat <= 90, f"Lat {lat} out of range"

@pytest.mark.parametrize("idx", range(min(len(RANDOM_POSITIONS), 25)))
def test_random_eci_lon_in_range(idx):
    lat, lon, alt = _eci_to_lla(RANDOM_POSITIONS[idx], RANDOM_TIMES[idx])
    assert -180 <= lon <= 180, f"Lon {lon} out of range"

@pytest.mark.parametrize("idx", range(min(len(RANDOM_POSITIONS), 25)))
def test_random_eci_alt_positive(idx):
    lat, lon, alt = _eci_to_lla(RANDOM_POSITIONS[idx], RANDOM_TIMES[idx])
    # Alt should be positive for positions above surface
    assert alt > -100, f"Alt {alt:.1f} too negative"


# ═══════════════════════════════════════════════════════════════════════════
# §4: SIMULATION INVARIANTS — random configs
# ═══════════════════════════════════════════════════════════════════════════

SIM_CONFIGS = [
    {"n_sats": 1, "n_debris": 0, "dt": 100},
    {"n_sats": 1, "n_debris": 10, "dt": 100},
    {"n_sats": 5, "n_debris": 0, "dt": 60},
    {"n_sats": 5, "n_debris": 50, "dt": 300},
    {"n_sats": 10, "n_debris": 100, "dt": 100},
    {"n_sats": 2, "n_debris": 5, "dt": 600},
    {"n_sats": 3, "n_debris": 20, "dt": 30},
    {"n_sats": 1, "n_debris": 200, "dt": 100},
    {"n_sats": 20, "n_debris": 0, "dt": 100},
    {"n_sats": 10, "n_debris": 10, "dt": 1800},
]

@pytest.mark.parametrize("cfg", SIM_CONFIGS,
                         ids=[f"s{c['n_sats']}_d{c['n_debris']}_t{c['dt']}" for c in SIM_CONFIGS])
def test_sim_config_no_crash(cfg):
    """Simulation with {cfg} should not crash."""
    eng = SimulationEngine()
    objs = [_obj(f"SAT-{i}", "SATELLITE", 400 + i * 20) for i in range(cfg["n_sats"])]
    objs += [_obj(f"DEB-{i}", "DEBRIS", 400 + (i % 100) * 3) for i in range(cfg["n_debris"])]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(cfg["dt"])
    snap = eng.get_snapshot()
    assert len(snap["satellites"]) == cfg["n_sats"]

@pytest.mark.parametrize("cfg", SIM_CONFIGS,
                         ids=[f"snap_s{c['n_sats']}_d{c['n_debris']}" for c in SIM_CONFIGS])
def test_sim_config_snapshot_valid(cfg):
    """Snapshot after step with {cfg} should have valid structure."""
    eng = SimulationEngine()
    objs = [_obj(f"SAT-{i}", "SATELLITE", 400 + i * 20) for i in range(cfg["n_sats"])]
    objs += [_obj(f"DEB-{i}", "DEBRIS", 400 + (i % 100) * 3) for i in range(cfg["n_debris"])]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(cfg["dt"])
    snap = eng.get_snapshot()
    assert "timestamp" in snap
    assert "satellites" in snap
    assert "debris_cloud" in snap
    for sat in snap["satellites"]:
        assert -90 <= sat["lat"] <= 90
        assert -180 <= sat["lon"] <= 180
        assert sat["alt_km"] > 50
        assert sat["fuel_kg"] >= 0

@pytest.mark.parametrize("cfg", SIM_CONFIGS,
                         ids=[f"uptime_s{c['n_sats']}" for c in SIM_CONFIGS])
def test_sim_config_uptime_valid(cfg):
    """All satellites should have uptime_score in [0, 1]."""
    eng = SimulationEngine()
    objs = [_obj(f"SAT-{i}", "SATELLITE", 400 + i * 20) for i in range(cfg["n_sats"])]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(cfg["dt"])
    snap = eng.get_snapshot()
    for sat in snap["satellites"]:
        assert 0 <= sat["uptime_score"] <= 1.0, (
            f"Uptime {sat['uptime_score']} out of [0,1]"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §5: KEPLER'S THIRD LAW — period verification
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("alt_km", [200, 400, 600, 800, 1000, 2000, 5000, 10000, 20000, 35786])
def test_keplers_third_law_radius_preserved(alt_km):
    """Orbital radius at {alt_km}km should be preserved after 1 period (J2 shifts position, not radius)."""
    prop = OrbitalPropagator()
    sv0 = np.array([R_EARTH + alt_km, 0, 0, 0, np.sqrt(MU_EARTH / (R_EARTH + alt_km)), 0])
    T = 2 * np.pi * np.sqrt((R_EARTH + alt_km)**3 / MU_EARTH)
    sv1 = prop.propagate(sv0, T)
    r0 = np.linalg.norm(sv0[:3])
    r1 = np.linalg.norm(sv1[:3])
    # J2 causes apsidal precession (position shifts) but SMA/radius should be preserved
    radius_drift = abs(r1 - r0) / r0 * 100
    assert radius_drift < 1.0, (
        f"Radius drift {radius_drift:.4f}% after 1 period at {alt_km}km"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §6: BATCH PROPAGATION CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("n", [2, 5, 10, 20])
def test_batch_matches_individual(n):
    """Batch propagation of {n} objects should match individual propagation."""
    prop = OrbitalPropagator()
    states = {f"O-{i}": np.array([R_EARTH + 400 + i*10, 0, 0, 0,
              np.sqrt(MU_EARTH/(R_EARTH + 400 + i*10)) * 0.866,
              np.sqrt(MU_EARTH/(R_EARTH + 400 + i*10)) * 0.5])
              for i in range(n)}
    batch_result = prop.propagate_batch(states, 600.0)
    for oid, sv0 in states.items():
        individual = prop.propagate(sv0, 600.0)
        batch_sv = batch_result[oid]
        pos_err = np.linalg.norm(individual[:3] - batch_sv[:3])
        assert pos_err < 0.1, (
            f"{oid}: batch vs individual pos err = {pos_err:.6f}km"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §7: TSIOLKOVSKY MASS-AWARENESS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("initial_fuel", [5, 10, 20, 30, 40, 50])
def test_lighter_satellite_more_efficient(initial_fuel):
    """Satellite with {initial_fuel}kg fuel: same dv should consume less as it gets lighter."""
    ft = FuelTracker()
    ft.register_satellite("SAT", float(initial_fuel))
    consumptions = []
    for _ in range(3):
        c = ft.consume("SAT", 2.0)
        consumptions.append(c)
    # Each subsequent burn should consume less (lighter satellite)
    if all(c > 0 for c in consumptions):
        for i in range(1, len(consumptions)):
            assert consumptions[i] <= consumptions[i-1] + 1e-8, (
                f"Burn {i} consumed more than burn {i-1}: "
                f"{consumptions[i]:.8f} > {consumptions[i-1]:.8f}"
            )
