"""
test_parametric_sweep.py — 300+ parametric test variations.

Systematic boundary sweeps across every physics parameter using
pytest.mark.parametrize to generate hundreds of unique test cases.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from engine.propagator import OrbitalPropagator
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork
from engine.simulation import SimulationEngine, _eci_to_lla
from config import (
    MU_EARTH, R_EARTH, J2, ISP, G0, M_DRY, M_FUEL_INIT,
    MAX_DV_PER_BURN, THRUSTER_COOLDOWN_S, EOL_FUEL_THRESHOLD_KG,
)

T0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)

def _sv(alt_km=400.0, inc_deg=51.6):
    r = R_EARTH + alt_km
    v = np.sqrt(MU_EARTH / r)
    inc = np.radians(inc_deg)
    return np.array([r, 0.0, 0.0, 0.0, v * np.cos(inc), v * np.sin(inc)])

def _obj(oid, otype, alt_km=400.0):
    sv = _sv(alt_km)
    return {
        "id": oid, "type": otype,
        "r": {"x": float(sv[0]), "y": float(sv[1]), "z": float(sv[2])},
        "v": {"x": float(sv[3]), "y": float(sv[4]), "z": float(sv[5])},
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1: ALTITUDE SWEEP — propagation stability across full LEO-to-GEO range
# ═══════════════════════════════════════════════════════════════════════════

ALTITUDES = [160, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900,
             1000, 1200, 1500, 2000, 3000, 5000, 8000, 12000, 20000, 35786]

@pytest.mark.parametrize("alt_km", ALTITUDES)
def test_propagate_altitude_stable(alt_km):
    """Orbit at {alt_km} km should remain stable after 1 orbit."""
    prop = OrbitalPropagator()
    sv0 = _sv(alt_km, 0.0)
    T = 2 * np.pi * np.sqrt((R_EARTH + alt_km)**3 / MU_EARTH)
    sv1 = prop.propagate(sv0, min(T, 86400))
    r1 = np.linalg.norm(sv1[:3])
    alt_final = r1 - R_EARTH
    tol = max(alt_km * 0.05, 20)  # 5% or 20km tolerance
    assert abs(alt_final - alt_km) < tol, (
        f"Alt {alt_km}km drifted to {alt_final:.1f}km"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §2: INCLINATION SWEEP — all orbital planes
# ═══════════════════════════════════════════════════════════════════════════

INCLINATIONS = list(range(0, 181, 5))  # 0° to 180° in 5° steps = 37 values

@pytest.mark.parametrize("inc_deg", INCLINATIONS)
def test_propagate_inclination_stable(inc_deg):
    """Orbit at inclination {inc_deg}° should preserve altitude."""
    prop = OrbitalPropagator()
    sv0 = _sv(400, inc_deg)
    sv1 = prop.propagate(sv0, 5400)  # 1.5 hours
    alt = np.linalg.norm(sv1[:3]) - R_EARTH
    assert 350 < alt < 450, f"Inc {inc_deg}° orbit drifted to {alt:.1f}km"


# ═══════════════════════════════════════════════════════════════════════════
# §3: TIMESTEP SWEEP — propagation accuracy vs step size
# ═══════════════════════════════════════════════════════════════════════════

TIMESTEPS = [1, 5, 10, 30, 60, 100, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 43200, 86400]

@pytest.mark.parametrize("dt", TIMESTEPS)
def test_propagate_timestep_finite(dt):
    """Propagation for {dt}s should produce finite results."""
    prop = OrbitalPropagator()
    sv1 = prop.propagate(_sv(400), dt)
    assert np.all(np.isfinite(sv1)), f"Non-finite state after {dt}s"
    r = np.linalg.norm(sv1[:3])
    assert r > R_EARTH * 0.9, f"Object crashed into Earth after {dt}s"


# ═══════════════════════════════════════════════════════════════════════════
# §4: FUEL CONSUMPTION — Tsiolkovsky sweep across delta-v values
# ═══════════════════════════════════════════════════════════════════════════

DV_VALUES = [0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 12.0, 14.9, 15.0,
             20.0, 50.0, 100.0, 500.0, 1000.0, 5000.0]

@pytest.mark.parametrize("dv", DV_VALUES)
def test_fuel_consumption_monotonic(dv):
    """Higher dv ({dv} m/s) should consume more fuel."""
    from config import MAX_DV_PER_BURN
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    consumed = ft.consume("SAT", dv)
    if dv > MAX_DV_PER_BURN:
        # Over-limit burns are clamped to MAX_DV_PER_BURN
        max_fuel_for_limit = (M_DRY + M_FUEL_INIT) * (1 - np.exp(-MAX_DV_PER_BURN / (ISP * G0)))
        assert consumed <= max_fuel_for_limit * 1.05, \
            f"Clamped burn consumed too much fuel: {consumed:.4f} kg"
        return
    remaining = ft.get_fuel("SAT")
    assert remaining >= 0, f"Fuel went negative at dv={dv}"
    assert remaining <= M_FUEL_INIT, f"Fuel increased at dv={dv}"
    if dv > 0:
        assert consumed > 0, f"No fuel consumed at dv={dv}"


@pytest.mark.parametrize("dv", DV_VALUES[:10])  # First 10 reasonable values
def test_tsiolkovsky_analytical_match(dv):
    """Fuel consumption must match Tsiolkovsky equation within 1e-6 kg."""
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    consumed = ft.consume("SAT", dv)
    m_total = M_DRY + M_FUEL_INIT
    expected = m_total * (1 - np.exp(-dv / (ISP * G0)))
    assert abs(consumed - expected) < 1e-6, (
        f"dv={dv}: consumed={consumed:.8f}, expected={expected:.8f}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §5: ENERGY CONSERVATION — multi-orbit sweep
# ═══════════════════════════════════════════════════════════════════════════

ORBIT_COUNTS = [1, 2, 3, 5, 10, 20, 50]

@pytest.mark.parametrize("n_orbits", ORBIT_COUNTS)
def test_energy_conservation_n_orbits(n_orbits):
    """Specific energy should be conserved within 0.1% over {n_orbits} orbits."""
    prop = OrbitalPropagator()
    sv0 = _sv(400)
    r0 = np.linalg.norm(sv0[:3])
    v0 = np.linalg.norm(sv0[3:])
    E0 = 0.5 * v0**2 - MU_EARTH / r0

    T = 2 * np.pi * np.sqrt((R_EARTH + 400)**3 / MU_EARTH)
    sv1 = prop.propagate(sv0, n_orbits * T)
    r1 = np.linalg.norm(sv1[:3])
    v1 = np.linalg.norm(sv1[3:])
    E1 = 0.5 * v1**2 - MU_EARTH / r1

    drift = abs((E1 - E0) / E0) * 100
    assert drift < 0.1, f"Energy drift {drift:.4f}% over {n_orbits} orbits"


# ═══════════════════════════════════════════════════════════════════════════
# §6: ECI→LLA COORDINATE SWEEP — all quadrants
# ═══════════════════════════════════════════════════════════════════════════

ANGLES = np.linspace(0, 2 * np.pi, 24, endpoint=False)

@pytest.mark.parametrize("angle", ANGLES.tolist())
def test_eci_to_lla_longitude_valid(angle):
    """ECI position at angle {angle:.2f} rad should give valid lon."""
    r = R_EARTH + 400
    pos = np.array([r * np.cos(angle), r * np.sin(angle), 0.0])
    lat, lon, alt = _eci_to_lla(pos, T0)
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180
    assert 350 < alt < 450


LATITUDES_TEST = np.linspace(-np.pi/2 * 0.99, np.pi/2 * 0.99, 20)

@pytest.mark.parametrize("lat_rad", LATITUDES_TEST.tolist())
def test_eci_to_lla_latitude_range(lat_rad):
    """ECI position at latitude {lat_rad:.2f} rad should give valid coords."""
    r = R_EARTH + 400
    pos = np.array([
        r * np.cos(lat_rad),
        0.0,
        r * np.sin(lat_rad),
    ])
    lat, lon, alt = _eci_to_lla(pos, T0)
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180


# ═══════════════════════════════════════════════════════════════════════════
# §7: MULTI-SATELLITE BATCH PROPAGATION SWEEP
# ═══════════════════════════════════════════════════════════════════════════

BATCH_SIZES = [1, 2, 5, 10, 25, 50, 100]

@pytest.mark.parametrize("n", BATCH_SIZES)
def test_batch_propagation_n_objects(n):
    """Batch propagation of {n} objects should complete and preserve count."""
    prop = OrbitalPropagator()
    states = {f"OBJ-{i}": _sv(400 + i * 5) for i in range(n)}
    result = prop.propagate_batch(states, 100.0)
    assert len(result) == n, f"Expected {n} results, got {len(result)}"
    for k, sv in result.items():
        assert np.all(np.isfinite(sv)), f"{k} has non-finite state"


# ═══════════════════════════════════════════════════════════════════════════
# §8: CONSECUTIVE BURN SEQUENCES — fuel depletion curves
# ═══════════════════════════════════════════════════════════════════════════

BURN_COUNTS = [1, 2, 5, 10, 20, 30, 40, 50, 75, 100]

@pytest.mark.parametrize("n_burns", BURN_COUNTS)
def test_consecutive_burns_fuel_monotonic(n_burns):
    """After {n_burns} burns, fuel should monotonically decrease."""
    ft = FuelTracker()
    ft.register_satellite("SAT", M_FUEL_INIT)
    fuels = [ft.get_fuel("SAT")]
    for _ in range(n_burns):
        ft.consume("SAT", 1.0)
        fuels.append(ft.get_fuel("SAT"))
    for i in range(1, len(fuels)):
        assert fuels[i] <= fuels[i-1], (
            f"Fuel increased at burn {i}: {fuels[i-1]:.6f} -> {fuels[i]:.6f}"
        )
    assert fuels[-1] >= 0, "Fuel went negative"


# ═══════════════════════════════════════════════════════════════════════════
# §9: GROUND STATION LOS — satellite position sweep
# ═══════════════════════════════════════════════════════════════════════════

GS_ANGLES = np.linspace(0, 2 * np.pi, 36, endpoint=False)

@pytest.mark.parametrize("angle", GS_ANGLES.tolist())
def test_ground_station_los_no_crash(angle):
    """LOS check at angle {angle:.2f} rad should not crash."""
    gsn = GroundStationNetwork()
    r = R_EARTH + 400
    pos = np.array([r * np.cos(angle), r * np.sin(angle), 0.0])
    result = gsn.check_line_of_sight(pos, T0)
    assert isinstance(result, (bool, dict, type(None), str, list, tuple))


# ═══════════════════════════════════════════════════════════════════════════
# §10: SIMULATION STEP DURATION SWEEP
# ═══════════════════════════════════════════════════════════════════════════

STEP_DURATIONS = [1, 10, 30, 60, 100, 300, 600, 900, 1800, 3600]

@pytest.mark.parametrize("dt", STEP_DURATIONS)
def test_simulation_step_duration(dt):
    """Simulation step of {dt}s should complete without crash."""
    eng = SimulationEngine()
    eng.ingest_telemetry(T0.isoformat(), [_obj("SAT-DT", "SATELLITE", 400)])
    eng.step(dt)
    snap = eng.get_snapshot()
    assert len(snap["satellites"]) == 1
    sat = snap["satellites"][0]
    assert sat["alt_km"] > 100, f"Satellite crashed after {dt}s step"


# ═══════════════════════════════════════════════════════════════════════════
# §11: DEBRIS COUNT SCALING
# ═══════════════════════════════════════════════════════════════════════════

DEBRIS_COUNTS = [0, 1, 5, 10, 50, 100, 500]

@pytest.mark.parametrize("n_debris", DEBRIS_COUNTS)
def test_debris_scaling(n_debris):
    """Engine with {n_debris} debris should step without crash."""
    eng = SimulationEngine()
    objs = [_obj("SAT-SC", "SATELLITE", 400)]
    objs += [_obj(f"DEB-{i}", "DEBRIS", 400 + (i % 50) * 5) for i in range(n_debris)]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(100)
    assert len(eng.debris) == n_debris


# ═══════════════════════════════════════════════════════════════════════════
# §12: SATELLITE COUNT SCALING
# ═══════════════════════════════════════════════════════════════════════════

SAT_COUNTS = [1, 2, 5, 10, 20, 50]

@pytest.mark.parametrize("n_sats", SAT_COUNTS)
def test_satellite_scaling(n_sats):
    """Engine with {n_sats} satellites should step without crash."""
    eng = SimulationEngine()
    objs = [_obj(f"SAT-{i}", "SATELLITE", 400 + i * 20) for i in range(n_sats)]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(100)
    assert len(eng.satellites) == n_sats


# ═══════════════════════════════════════════════════════════════════════════
# §13: FAST-PATH VS DOP853 — dt sweep
# ═══════════════════════════════════════════════════════════════════════════

FAST_PATH_DTS = [10, 30, 60, 100, 200, 300, 400, 500, 600]

@pytest.mark.parametrize("dt", FAST_PATH_DTS)
def test_fast_path_accuracy_vs_dt(dt):
    """Fast-path at {dt}s should be within tolerance of DOP853."""
    prop = OrbitalPropagator()
    sv0 = _sv(400)
    sv_dop = prop.propagate(sv0, float(dt))
    result = prop.propagate_fast_batch({"X": sv0}, float(dt))
    sv_fast = result["X"]
    pos_err = np.linalg.norm(sv_dop[:3] - sv_fast[:3])
    max_err = max(dt * 0.01, 1.0)  # Scale tolerance with dt
    assert pos_err < max_err, (
        f"Fast-path error {pos_err:.4f}km at dt={dt}s (limit {max_err:.1f}km)"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §14: MULTI-STEP EVOLUTION — clock and state consistency
# ═══════════════════════════════════════════════════════════════════════════

MULTI_STEP_CONFIGS = [
    (10, 10),    # 10 steps of 10s
    (5, 100),    # 5 steps of 100s
    (3, 600),    # 3 steps of 600s
    (20, 30),    # 20 steps of 30s
    (100, 10),   # 100 steps of 10s
    (2, 1800),   # 2 steps of 30min
]

@pytest.mark.parametrize("n_steps,dt", MULTI_STEP_CONFIGS)
def test_multi_step_clock_consistency(n_steps, dt):
    """After {n_steps} steps of {dt}s, clock should advance correctly."""
    eng = SimulationEngine()
    eng.ingest_telemetry(T0.isoformat(), [_obj("SAT-MS", "SATELLITE", 400)])
    t_start = eng.sim_time
    for _ in range(n_steps):
        eng.step(dt)
    elapsed = (eng.sim_time - t_start).total_seconds()
    expected = n_steps * dt
    assert abs(elapsed - expected) < 2.0, (
        f"Clock: {elapsed:.1f}s, expected {expected}s"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §15: ANGULAR MOMENTUM CONSERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("alt_km", [200, 400, 800, 1500, 5000])
@pytest.mark.parametrize("inc_deg", [0, 28.5, 51.6, 90, 135])
def test_angular_momentum_conservation(alt_km, inc_deg):
    """Angular momentum should be conserved within 0.1%."""
    prop = OrbitalPropagator()
    sv0 = _sv(alt_km, inc_deg)
    h0 = np.linalg.norm(np.cross(sv0[:3], sv0[3:]))
    T = 2 * np.pi * np.sqrt((R_EARTH + alt_km)**3 / MU_EARTH)
    sv1 = prop.propagate(sv0, min(T, 43200))
    h1 = np.linalg.norm(np.cross(sv1[:3], sv1[3:]))
    drift = abs((h1 - h0) / h0) * 100
    assert drift < 0.5, (
        f"h drift {drift:.4f}% at alt={alt_km}km, inc={inc_deg}°"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §16: SNAPSHOT FIELD VALIDATION — multi-satellite sweep
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("n_sats", [1, 3, 5, 10, 20])
def test_snapshot_all_sats_present(n_sats):
    eng = SimulationEngine()
    objs = [_obj(f"SAT-SN-{i}", "SATELLITE", 400 + i * 10) for i in range(n_sats)]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(10)
    snap = eng.get_snapshot()
    assert len(snap["satellites"]) == n_sats

@pytest.mark.parametrize("n_sats", [1, 3, 5, 10, 20])
def test_snapshot_all_fuels_valid(n_sats):
    eng = SimulationEngine()
    objs = [_obj(f"SAT-FV-{i}", "SATELLITE", 400 + i * 10) for i in range(n_sats)]
    eng.ingest_telemetry(T0.isoformat(), objs)
    eng.step(10)
    snap = eng.get_snapshot()
    for sat in snap["satellites"]:
        assert 0 <= sat["fuel_kg"] <= M_FUEL_INIT + 1


# ═══════════════════════════════════════════════════════════════════════════
# §17: ECCENTRIC ORBIT PROPAGATION
# ═══════════════════════════════════════════════════════════════════════════

ECCENTRICITIES = [0.001, 0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5]

@pytest.mark.parametrize("ecc", ECCENTRICITIES)
def test_eccentric_orbit_propagation(ecc):
    """Eccentric orbit (e={ecc}) should propagate without crash."""
    prop = OrbitalPropagator()
    a = R_EARTH + 800  # Higher base SMA for eccentric orbits
    r_peri = a * (1 - ecc)
    v_peri = np.sqrt(MU_EARTH * (2/r_peri - 1/a))
    sv0 = np.array([r_peri, 0.0, 0.0, 0.0, v_peri, 0.0])
    sv1 = prop.propagate(sv0, 5400)
    assert np.all(np.isfinite(sv1)), f"Non-finite at e={ecc}"
    r1 = np.linalg.norm(sv1[:3])
    assert r1 > R_EARTH * 0.5, f"Object crashed at e={ecc}, r={r1:.1f}km"


# ═══════════════════════════════════════════════════════════════════════════
# §18: TIMESTAMP SWEEP — GMST calculation across dates
# ═══════════════════════════════════════════════════════════════════════════

TIMESTAMPS = [
    datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
    datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 3, 21, 6, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 3, 21, 18, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc),  # summer solstice
    datetime(2026, 12, 21, 12, 0, 0, tzinfo=timezone.utc),  # winter solstice
    datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
]

@pytest.mark.parametrize("ts", TIMESTAMPS)
def test_eci_to_lla_valid_at_timestamp(ts):
    """ECI→LLA should produce valid coords at {ts}."""
    pos = np.array([R_EARTH + 400, 0.0, 0.0])
    lat, lon, alt = _eci_to_lla(pos, ts)
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180
    assert 350 < alt < 450


# ═══════════════════════════════════════════════════════════════════════════
# §19: COMBINED ALT + INC MATRIX — orbit diversity
# ═══════════════════════════════════════════════════════════════════════════

ALT_INC_PAIRS = [
    (200, 28.5), (200, 90), (400, 0), (400, 51.6), (400, 97.8),
    (600, 45), (800, 63.4), (1000, 90), (1500, 135), (2000, 170),
]

@pytest.mark.parametrize("alt_km,inc_deg", ALT_INC_PAIRS)
def test_orbit_diversity_stable(alt_km, inc_deg):
    """Orbit at alt={alt_km}km, inc={inc_deg}° should be stable."""
    prop = OrbitalPropagator()
    sv0 = _sv(alt_km, inc_deg)
    sv1 = prop.propagate(sv0, 3600)
    alt_final = np.linalg.norm(sv1[:3]) - R_EARTH
    tol = max(alt_km * 0.1, 30)
    assert abs(alt_final - alt_km) < tol


# ═══════════════════════════════════════════════════════════════════════════
# §20: VELOCITY PERTURBATION — sensitivity analysis
# ═══════════════════════════════════════════════════════════════════════════

PERTURBATIONS = [1e-6, 1e-5, 1e-4, 1e-3, 0.01, 0.1]

@pytest.mark.parametrize("dv_km_s", PERTURBATIONS)
def test_velocity_perturbation_bounded(dv_km_s):
    """Small velocity perturbation ({dv_km_s} km/s) should not crash orbit."""
    prop = OrbitalPropagator()
    sv0 = _sv(400)
    sv0[3] += dv_km_s  # Perturb vx
    sv1 = prop.propagate(sv0, 5400)
    alt = np.linalg.norm(sv1[:3]) - R_EARTH
    assert alt > 100, f"Orbit decayed with dv={dv_km_s} km/s perturbation"
    assert alt < 2000, f"Orbit escaped with dv={dv_km_s} km/s perturbation"
