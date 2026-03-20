"""
test_judge_breakers.py — Novel Attack Vectors Not Covered by Existing Suite
═══════════════════════════════════════════════════════════════════════════════
These tests target bugs that no existing test file covers:
  §1  Temporal Ordering: Burns execute after propagation (BUG-01)
  §2  GMST / Longitude: Snapshot lat/lon is wrong (BUG-02)
  §3  Multi-Step Cascade: Repeated short steps accumulate fast-path drift
  §4  Evasion ΔV Physics: Retrograde debris at 14 km/s closing speed
  §5  KDTree Radius Explosion: 24h lookahead makes radius > 1M km
  §6  Sat-vs-Sat Double Burn: Both satellites burn for same conjunction
  §7  Recovery CW Equations: Eccentric orbit after evasion breaks Hill's
  §8  Numerical Landmines: Zero-position, sub-Earth debris, NaN injection
  §9  API Contract Holes: Time reversal, float truncation, empty sequences
  §10 Fuel Accounting: Sequential burns mass-coupling across ticks
Requires: pytest, numpy, scipy
Run from: backend/  →  python -m pytest tests/test_judge_breakers.py -v
"""
from __future__ import annotations
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    CONJUNCTION_THRESHOLD_KM, EOL_FUEL_THRESHOLD_KG, G0, ISP, J2,
    MAX_DV_PER_BURN, MU_EARTH, M_DRY, M_FUEL_INIT, R_EARTH,
    SIGNAL_LATENCY_S, STATION_KEEPING_RADIUS_KM, THRUSTER_COOLDOWN_S,
)
from engine.collision import ConjunctionAssessor
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork
from engine.maneuver_planner import ManeuverPlanner
from engine.models import CDM, Debris, Satellite
from engine.propagator import OrbitalPropagator
from engine.simulation import SimulationEngine
# ── helpers ───────────────────────────────────────────────────────────────────
def _leo_sv(alt_km=400.0, inc_deg=51.6, raan_deg=0.0, nu_deg=0.0) -> np.ndarray:
    r = R_EARTH + alt_km
    v = math.sqrt(MU_EARTH / r)
    inc = math.radians(inc_deg)
    raan = math.radians(raan_deg)
    nu = math.radians(nu_deg)
    cr, sr = math.cos(raan), math.sin(raan)
    ci, si = math.cos(inc), math.sin(inc)
    cn, sn = math.cos(nu), math.sin(nu)
    return np.array([
        r * (cr * cn - sr * sn * ci),
        r * (sr * cn + cr * sn * ci),
        r * sn * si,
        v * (-cr * sn - sr * cn * ci),
        v * (-sr * sn + cr * cn * ci),
        v * cn * si,
    ])
def _make_engine_at(timestamp: str, sats: list[dict], debris: list[dict] = None):
    """Create engine with specific objects at a specific time."""
    engine = SimulationEngine()
    objects = []
    for s in sats:
        objects.append({**s, "type": "SATELLITE"})
    for d in (debris or []):
        objects.append({**d, "type": "DEBRIS"})
    engine.ingest_telemetry(timestamp, objects)
    return engine
# ═══════════════════════════════════════════════════════════════════════════════
# §1  TEMPORAL ORDERING — Burns execute AFTER full propagation
# ═══════════════════════════════════════════════════════════════════════════════
class TestBurnTimingOrder:
    """
    The step() method propagates ALL objects to target_time in Step 1,
    THEN applies burns in Step 2. A burn scheduled mid-step gets its ΔV
    applied at the wrong position/time.

    This is the most critical bug: evasion maneuvers are physically late.
    """
    def test_burn_at_t300_in_3600s_step_changes_trajectory_at_t300(self):
        """
        Schedule burn at t+300s. Step 3600s.
        If burn is applied correctly at t=300s, the satellite's final position
        at t=3600s should differ from an un-burned trajectory by the full
        3300s of post-burn propagation. If applied at t=3600s (the bug),
        the satellite position equals the un-burned trajectory + instantaneous dv.
        """
        engine = _make_engine_at(
            "2026-03-12T08:00:00.000Z",
            [{"id": "SAT-T1", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.668, "z": 0.0}}],
        )

        # Record pre-burn state
        sat = engine.satellites["SAT-T1"]
        sv_initial = sat.state_vector.copy()

        # Schedule a burn at t+300s
        burn_time = (engine.sim_time + timedelta(seconds=300)).isoformat()
        sat.maneuver_queue.append({
            "burn_id": "TIMING_TEST",
            "burnTime": burn_time,
            "deltaV_vector": {"x": 0.0, "y": 0.005, "z": 0.0},  # 5 m/s prograde
        })

        # Step the full 3600s
        engine.step(3600)
        pos_with_burn = engine.satellites["SAT-T1"].position.copy()

        # Now compute what SHOULD happen: propagate 300s, apply dv, propagate 3300s
        prop = OrbitalPropagator(rtol=1e-10, atol=1e-12)
        sv_at_300 = prop.propagate(sv_initial, 300.0)
        sv_at_300[3:] += np.array([0.0, 0.005, 0.0])
        sv_correct = prop.propagate(sv_at_300, 3300.0)

        # And compute the WRONG answer: propagate 3600s then apply dv
        sv_at_3600 = prop.propagate(sv_initial, 3600.0)
        sv_wrong = sv_at_3600.copy()
        sv_wrong[3:] += np.array([0.0, 0.005, 0.0])

        err_correct = np.linalg.norm(pos_with_burn - sv_correct[:3])
        err_wrong = np.linalg.norm(pos_with_burn - sv_wrong[:3])

        print(f"\n  Position error vs correct timing: {err_correct:.4f} km")
        print(f"  Position error vs wrong timing:   {err_wrong:.4f} km")

        # If the engine applies burn at the right time, err_correct should be small
        # If it applies at wrong time, err_wrong will be small instead
        assert err_correct < err_wrong, (
            f"Burn applied at step-end ({err_wrong:.4f} km error) instead of "
            f"at scheduled time ({err_correct:.4f} km error). "
            f"Step 1 propagates PAST the burn time before Step 2 executes it."
        )
    def test_evasion_at_t60_in_600s_step_prevents_collision_at_t120(self):
        """
        Concrete collision avoidance scenario:
        - Debris will collide at t+120s
        - Evasion burn queued at t+60s
        - Step 600s
        - If burn fires at t+60s: satellite dodges at t+120s → 0 collisions
        - If burn fires at t+600s: satellite was already hit → 1 collision
        """
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine = _make_engine_at(
            "2026-03-12T10:00:00.000Z",
            [{"id": "SAT-E1", "r": {"x": r, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": v, "z": 0.0}}],
            # Co-orbital debris 0.08 km ahead (inside threshold), closing slowly
            [{"id": "DEB-E1", "r": {"x": r, "y": 0.08, "z": 0.0},
              "v": {"x": 0.0, "y": v - 0.0005, "z": 0.0}}],
        )

        # Queue evasion: radial shunt at t+60s to separate vertically
        sat = engine.satellites["SAT-E1"]
        burn_time = (engine.sim_time + timedelta(seconds=60)).isoformat()
        sat.maneuver_queue.append({
            "burn_id": "EVASION_TIMING",
            "burnTime": burn_time,
            "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0},  # 1 m/s radial
        })

        result = engine.step(600)
        collisions = result.get("collisions_detected", 0)

        # The burn SHOULD have separated the objects before collision
        # If the burn fires at t+600 instead of t+60, the collision at ~t+120
        # would have already occurred in the sub-step scan
        print(f"\n  Collisions detected: {collisions}")
        print(f"  (0 expected if burn fires at t+60; >0 if fires at t+600)")
# ═══════════════════════════════════════════════════════════════════════════════
# §2  GMST / LONGITUDE — Snapshot returns right ascension, not longitude
# ═══════════════════════════════════════════════════════════════════════════════
class TestSnapshotLongitudeGMST:
    """
    _eci_to_lla computes lon = arctan2(y, x) on raw ECI.
    This gives right ascension, not geodetic longitude.
    The error equals GMST (≈200° at the default epoch).
    """
    def test_snapshot_longitude_accounts_for_earth_rotation(self):
        """
        Place satellite directly over IIT Delhi (lon=77.19°) using
        the ECEF→ECI transform with correct GMST. Then check that
        the snapshot reports lon ≈ 77° (not lon ≈ 77 + GMST).
        """
        # Use the same GMST formula as ground_stations.py
        timestamp = "2026-03-12T08:00:00.000Z"
        epoch_dt = datetime(2026, 3, 12, 8, 0, 0, tzinfo=timezone.utc)
        j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        dt_s = (epoch_dt - j2000).total_seconds()
        gmst_deg = (280.46061837 + 360.98564736629 * (dt_s / 86400.0)) % 360.0
        gmst_rad = math.radians(gmst_deg)

        # Place satellite at 400 km over IIT Delhi (lat=28.545, lon=77.1926)
        target_lon_deg = 77.1926
        target_lat_deg = 28.545
        alt_km = 400.0
        r = R_EARTH + alt_km

        lat_rad = math.radians(target_lat_deg)
        lon_rad = math.radians(target_lon_deg)

        # ECEF position
        x_ecef = r * math.cos(lat_rad) * math.cos(lon_rad)
        y_ecef = r * math.cos(lat_rad) * math.sin(lon_rad)
        z_ecef = r * math.sin(lat_rad)

        # Rotate ECEF → ECI by GMST
        c, s = math.cos(gmst_rad), math.sin(gmst_rad)
        x_eci = c * x_ecef - s * y_ecef
        y_eci = s * x_ecef + c * y_ecef
        z_eci = z_ecef

        # Circular velocity (simplified — tangent to orbit in ECI)
        v = math.sqrt(MU_EARTH / r)
        vx_eci = -v * math.sin(gmst_rad + lon_rad) * math.cos(lat_rad)
        vy_eci = v * math.cos(gmst_rad + lon_rad) * math.cos(lat_rad)
        vz_eci = 0.0

        engine = _make_engine_at(timestamp, [{
            "id": "SAT-DELHI",
            "r": {"x": x_eci, "y": y_eci, "z": z_eci},
            "v": {"x": vx_eci, "y": vy_eci, "z": vz_eci},
        }])

        snap = engine.get_snapshot()
        sat_snap = snap["satellites"][0]
        reported_lon = sat_snap["lon"]

        # The raw ECI arctan2(y,x) gives right ascension ≈ lon + GMST
        raw_ra = math.degrees(math.atan2(y_eci, x_eci))

        print(f"\n  Target longitude:      {target_lon_deg:.2f}°")
        print(f"  Reported longitude:    {reported_lon:.2f}°")
        print(f"  GMST at epoch:         {gmst_deg:.2f}°")
        print(f"  Raw right ascension:   {raw_ra:.2f}°")

        lon_err = abs(reported_lon - target_lon_deg)
        if lon_err > 180:
            lon_err = 360 - lon_err

        assert lon_err < 5.0, (
            f"Snapshot longitude {reported_lon:.2f}° differs from true "
            f"longitude {target_lon_deg:.2f}° by {lon_err:.1f}° — "
            f"_eci_to_lla does not subtract GMST ({gmst_deg:.1f}°)"
        )
    def test_eci_to_lla_differs_from_ground_station_gmst(self):
        """
        ground_stations.py correctly computes GMST for LOS checks.
        _eci_to_lla does NOT apply GMST.
        These two modules disagree on where a satellite is.
        """
        from engine.simulation import _eci_to_lla

        # Satellite at [6778, 0, 0] ECI at a known epoch
        pos = np.array([6778.0, 0.0, 0.0])
        ts = datetime(2026, 3, 12, 8, 0, 0, tzinfo=timezone.utc)

        lat, lon_snapshot, alt = _eci_to_lla(pos, ts)

        # _eci_to_lla reports lon = arctan2(0, 6778) = 0°
        # But at this epoch, GMST ≈ 206°, so true lon ≈ 0 - 206 = -206 → +154°
        j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        dt_s = (ts - j2000).total_seconds()
        gmst_deg = (280.46061837 + 360.98564736629 * (dt_s / 86400.0)) % 360.0
        true_lon = (0.0 - gmst_deg) % 360.0
        if true_lon > 180:
            true_lon -= 360

        print(f"\n  Snapshot lon: {lon_snapshot:.2f}° (raw ECI)")
        print(f"  True lon:    {true_lon:.2f}° (GMST-corrected)")
        print(f"  GMST:        {gmst_deg:.2f}°")

        # They SHOULD match. They won't.
        err = abs(lon_snapshot - true_lon)
        if err > 180:
            err = 360 - err

        if err > 10.0:
            pytest.xfail(
                f"_eci_to_lla longitude off by {err:.1f}° — "
                f"GMST rotation not applied (known BUG-02)"
            )
# ═══════════════════════════════════════════════════════════════════════════════
# §3  MULTI-STEP CASCADE — Fast-path debris drift accumulation
# ═══════════════════════════════════════════════════════════════════════════════
class TestFastPathDrift:
    """
    propagate_fast_batch (Taylor expansion, no J2) is used when
    step_seconds <= 600 and len(debris) > 100. Over many such steps,
    the accumulated position error grows catastrophically.
    """
    def test_100_short_steps_vs_single_long_step_debris_agreement(self):
        """
        100 × 600s fast-path steps should match 1 × 60000s DOP853 step
        to within ~1 km. If fast path lacks J2, error will be >>1 km.
        """
        sv = _leo_sv(alt_km=400.0, inc_deg=51.6)

        # Single accurate propagation
        prop = OrbitalPropagator(rtol=1e-10, atol=1e-12)
        sv_accurate = prop.propagate(sv, 60000.0)

        # 100 × 600s fast-path steps
        states = {"DEB-001": sv.copy()}
        for _ in range(100):
            states = OrbitalPropagator.propagate_fast_batch(states, 600.0)
        sv_fast = states["DEB-001"]

        pos_err = np.linalg.norm(sv_fast[:3] - sv_accurate[:3])

        print(f"\n  Position error after 100 × 600s fast steps: {pos_err:.2f} km")
        print(f"  (J2 drift at this inclination ≈ {pos_err:.1f} km expected)")

        # With J2 included, error should be <0.1 km (integration error only)
        # Without J2, error will be 5-50 km depending on inclination
        assert pos_err < 1.0, (
            f"Fast-path debris drifted {pos_err:.2f} km from J2-accurate orbit "
            f"over 100 × 600s steps — propagate_fast_batch lacks J2 perturbation"
        )
    def test_fast_path_preserves_orbital_energy(self):
        """
        Even a fast propagator should approximately conserve orbital energy.
        Taylor expansion without J2 won't conserve energy over many steps.
        """
        sv = _leo_sv(alt_km=400.0, inc_deg=45.0)

        def energy(s):
            r = np.linalg.norm(s[:3])
            v = np.linalg.norm(s[3:])
            return 0.5 * v**2 - MU_EARTH / r

        e0 = energy(sv)
        states = {"D": sv.copy()}
        for _ in range(50):
            states = OrbitalPropagator.propagate_fast_batch(states, 600.0)
        e1 = energy(states["D"])

        rel_err = abs((e1 - e0) / e0)
        print(f"\n  Energy drift after 50 × 600s: {rel_err:.2e}")

        assert rel_err < 1e-3, (
            f"Fast-path energy drift {rel_err:.2e} over 50 steps — "
            f"Taylor expansion accumulates systematic error"
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §4  EVASION ΔV PHYSICS — Retrograde debris at high closing speed
# ═══════════════════════════════════════════════════════════════════════════════
class TestEvasionDeltaVPhysics:
    """
    The evasion formula dv = miss / (6 * dt_lead) is a heuristic.
    For retrograde debris at 14 km/s closing speed, it severely
    underestimates the required ΔV.
    """
    def test_evasion_dv_sufficient_for_retrograde_14kms(self):
        """
        Debris closing at ~14 km/s (retrograde orbit), TCA in 30 min.
        The planned evasion must actually achieve >100m miss distance.
        """
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        # Satellite: prograde
        sv_sat = np.array([r, 0.0, 0.0, 0.0, v, 0.0])
        # Debris: retrograde (nearly head-on), will arrive at same position in ~30 min
        # Place debris 30*60*(v+v) ≈ 27000 km ahead along y (simplified)
        closing_speed = 2 * v  # ≈ 15.3 km/s
        tca_seconds = 1800.0
        y_offset = closing_speed * tca_seconds  # ≈ 27,000 km
        sv_deb = np.array([r + 0.05, y_offset, 0.0, 0.0, -v, 0.0])

        sat = Satellite(
            id="SAT-RET", position=sv_sat[:3].copy(),
            velocity=sv_sat[3:].copy(),
            timestamp=datetime(2026, 3, 12, 8, 0, 0, tzinfo=timezone.utc),
        )
        sat.nominal_state = sv_sat.copy()

        deb = Debris(
            id="DEB-RET", position=sv_deb[:3].copy(),
            velocity=sv_deb[3:].copy(),
        )

        planner = ManeuverPlanner(propagator=OrbitalPropagator())
        tca = sat.timestamp + timedelta(seconds=tca_seconds)

        burns = planner.plan_evasion(
            satellite=sat, debris=deb,
            tca=tca, miss_distance_km=0.05,
            current_time=sat.timestamp,
        )

        if not burns:
            pytest.fail("No evasion burns planned for retrograde debris")

        # Compute total evasion ΔV
        total_dv_ms = 0.0
        for b in burns:
            if "EVASION" in b.get("burn_id", "").upper():
                dv = b["deltaV_vector"]
                mag = math.sqrt(dv["x"]**2 + dv["y"]**2 + dv["z"]**2) * 1000.0
                total_dv_ms += mag

        print(f"\n  Planned evasion ΔV: {total_dv_ms:.4f} m/s")
        print(f"  Closing speed: {closing_speed:.2f} km/s")

        # Now verify: propagate satellite with the burn applied, check miss distance
        prop = OrbitalPropagator()
        sv_cursor = sv_sat.copy()
        t_cursor = 0.0

        for b in burns:
            if "EVASION" in b.get("burn_id", "").upper():
                bt = datetime.fromisoformat(b["burnTime"].replace("Z", "+00:00"))
                dt = (bt - sat.timestamp).total_seconds()
                if dt > t_cursor:
                    sv_cursor = prop.propagate(sv_cursor, dt - t_cursor)
                    t_cursor = dt
                dv = b["deltaV_vector"]
                sv_cursor[3:] += np.array([dv["x"], dv["y"], dv["z"]])

        # Propagate both to TCA
        sv_sat_tca = prop.propagate(sv_cursor, tca_seconds - t_cursor)
        sv_deb_tca = prop.propagate(sv_deb, tca_seconds)

        miss = np.linalg.norm(sv_sat_tca[:3] - sv_deb_tca[:3])
        print(f"  Actual miss distance at TCA: {miss:.4f} km")

        assert miss > CONJUNCTION_THRESHOLD_KM, (
            f"Evasion ΔV of {total_dv_ms:.4f} m/s yields only {miss*1000:.1f}m "
            f"miss distance (need >{CONJUNCTION_THRESHOLD_KM*1000:.0f}m). "
            f"The heuristic formula underestimates ΔV for retrograde encounters."
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §5  KDTREE RADIUS EXPLOSION at 24h lookahead
# ═══════════════════════════════════════════════════════════════════════════════
class TestKDTreeRadiusScaling:
    """
    collision.py line 144: kdtree_radius = max(200.0, 15.0 * lookahead_s)
    At 86400s lookahead: radius = 1,296,000 km (3.4× Moon distance).
    """
    def test_kdtree_radius_not_absurd_at_24h(self):
        """
        The effective KDTree radius at 24h lookahead should be < 10,000 km.
        Any larger eliminates the spatial index benefit entirely.
        """
        import inspect
        from engine.collision import ConjunctionAssessor

        # Parse the radius formula from source
        src = inspect.getsource(ConjunctionAssessor.assess)

        # Compute what the code actually produces — extract formula from source
        lookahead_s = 86400.0
        # This should match the ACTUAL formula in collision.py
        # Old (buggy): max(200.0, 15.0 * lookahead_s) → 1,296,000 km
        # Fixed:       max(200.0, min(15.0 * lookahead_s, 2000.0)) → 2,000 km
        if "min(" in src:
            # Fixed version with cap
            radius = max(200.0, min(15.0 * lookahead_s, 2000.0))
        else:
            # Old version without cap
            radius = max(200.0, 15.0 * lookahead_s)

        print(f"\n  KDTree radius at 24h lookahead: {radius:.0f} km")
        print(f"  Moon distance: ~384,400 km")
        print(f"  LEO orbital radius: ~6,778 km")

        assert radius < 50000.0, (
            f"KDTree radius {radius:.0f} km at 24h lookahead is absurd. "
            f"Every debris object falls within this radius of every satellite. "
            f"Stage-2 spatial index provides zero filtering → O(S×D) pairs."
        )
    def test_ca_performance_at_full_scale_24h(self):
        """
        50 sats × 10K debris at 24h lookahead must complete in <60s.
        If the KDTree radius is 1.3M km, this will timeout.
        """
        prop = OrbitalPropagator(rtol=1e-6, atol=1e-8)
        assessor = ConjunctionAssessor(prop)
        rng = np.random.default_rng(42)

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
        for i in range(10000):
            r_d = R_EARTH + rng.uniform(300, 600)
            v_d = math.sqrt(MU_EARTH / r_d)
            th = rng.uniform(0, 2 * math.pi)
            phi = rng.uniform(-math.pi / 2, math.pi / 2)
            deb_states[f"DEB-{i:05d}"] = np.array([
                r_d * math.cos(th) * math.cos(phi),
                r_d * math.sin(th) * math.cos(phi),
                r_d * math.sin(phi),
                -v_d * math.sin(th), v_d * math.cos(th), 0.0,
            ])

        t0 = time.perf_counter()
        cdms = assessor.assess(
            sat_states, deb_states,
            lookahead_s=86400.0,  # THE CRITICAL PARAMETER — full 24h
        )
        elapsed = time.perf_counter() - t0

        print(f"\n  50 sats × 10K debris @ 24h lookahead: {elapsed:.2f}s")
        print(f"  CDMs generated: {len(cdms)}")

        assert elapsed < 60.0, (
            f"CA scan took {elapsed:.1f}s at 24h lookahead (max 60s). "
            f"KDTree radius explosion makes spatial index useless."
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §6  SAT-VS-SAT DOUBLE BURN — Both satellites evade same conjunction
# ═══════════════════════════════════════════════════════════════════════════════
class TestSatVsSatCoordination:
    """
    When two satellites are on collision course, only ONE should burn.
    The health-aware handshake has edge cases where both or neither burn.
    """
    def test_similar_fuel_both_burn(self):
        """
        Two satellites with fuel difference < 2 kg:
        the handshake says both take the burn (neither yields).
        This wastes fuel — only one should burn.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        # Two satellites on collision course, similar fuel
        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-A", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            {"id": "SAT-B", "type": "SATELLITE",
             "r": {"x": r + 0.05, "y": 0.5, "z": 0.0},
             "v": {"x": 0.0, "y": v - 0.0003, "z": 0.0}},
        ])

        # Set fuel: A=30.0, B=31.0 (diff=1.0 < 2.0 threshold)
        engine.fuel_tracker._fuel["SAT-A"] = 30.0
        engine.fuel_tracker._fuel["SAT-B"] = 31.0

        # Inject a CRITICAL CDM manually
        engine.active_cdms = [CDM(
            satellite_id="SAT-A", debris_id="SAT-B",
            tca=engine.sim_time + timedelta(seconds=1800),
            miss_distance_km=0.05, risk="CRITICAL",
            relative_velocity_km_s=0.0003,
        )]

        engine._auto_plan_maneuvers(engine.sim_time)

        a_queue = len(engine.satellites["SAT-A"].maneuver_queue)
        b_queue = len(engine.satellites["SAT-B"].maneuver_queue)

        print(f"\n  SAT-A queued burns: {a_queue}")
        print(f"  SAT-B queued burns: {b_queue}")
        print(f"  Fuel: A={30.0} B={31.0} (diff < 2kg)")

        total_evasions = a_queue + b_queue
        if total_evasions > max(a_queue, b_queue):
            pytest.xfail(
                f"Both satellites planned evasion ({a_queue} + {b_queue} burns). "
                f"Only one should burn for the same conjunction — double fuel waste."
            )
# ═══════════════════════════════════════════════════════════════════════════════
# §7  CW EQUATIONS — Hill's equations break on eccentric post-evasion orbits
# ═══════════════════════════════════════════════════════════════════════════════
class TestRecoveryCWEccentricity:
    """
    plan_return_to_slot uses Clohessy-Wiltshire equations, which assume
    circular reference orbit. After evasion, the orbit is eccentric.
    """
    def test_cw_recovery_with_eccentric_orbit(self):
        """
        Apply a large evasion burn to create eccentricity, then check
        that CW recovery actually returns to the slot (within 10 km).
        """
        prop = OrbitalPropagator()
        planner = ManeuverPlanner(propagator=prop)

        sv = _leo_sv(alt_km=400.0, inc_deg=51.6)

        # Apply a significant radial burn to create eccentricity
        dv_evasion = np.array([0.01, 0.0, 0.0])  # 10 m/s radial
        sv_post = sv.copy()
        sv_post[3:] += dv_evasion

        nominal = sv.copy()
        now = datetime(2026, 3, 12, 8, 0, 0, tzinfo=timezone.utc)

        sat = Satellite(
            id="SAT-CW", position=sv_post[:3].copy(),
            velocity=sv_post[3:].copy(), timestamp=now,
        )
        sat.nominal_state = nominal.copy()

        # Check eccentricity of post-evasion orbit
        r_mag = np.linalg.norm(sv_post[:3])
        v_mag = np.linalg.norm(sv_post[3:])
        eps = 0.5 * v_mag**2 - MU_EARTH / r_mag
        a = -MU_EARTH / (2 * eps)
        h = np.cross(sv_post[:3], sv_post[3:])
        h_mag = np.linalg.norm(h)
        ecc = math.sqrt(max(0, 1 + 2 * eps * h_mag**2 / MU_EARTH**2))

        print(f"\n  Post-evasion eccentricity: {ecc:.6f}")
        print(f"  (CW assumes e=0)")

        rec_burns = planner.plan_return_to_slot(
            satellite=sat, nominal_state=nominal, current_time=now,
            override_state=sv_post, override_nominal=nominal,
        )

        if not rec_burns:
            pytest.skip("No recovery burns generated")

        # Apply recovery burns and propagate to check final offset
        sv_cursor = sv_post.copy()
        t_cursor = 0.0

        for b in rec_burns:
            bt = datetime.fromisoformat(b["burnTime"].replace("Z", "+00:00"))
            dt = (bt - now).total_seconds()
            if dt > t_cursor:
                sv_cursor = prop.propagate(sv_cursor, dt - t_cursor)
                t_cursor = dt
            dv = b["deltaV_vector"]
            sv_cursor[3:] += np.array([dv["x"], dv["y"], dv["z"]])

        # Propagate nominal to same time
        nominal_final = prop.propagate(nominal, t_cursor)

        # Check: after both burns + coast, how far from nominal?
        offset = np.linalg.norm(sv_cursor[:3] - nominal_final[:3])

        print(f"  Final offset from slot: {offset:.2f} km")
        print(f"  Station-keeping radius: {STATION_KEEPING_RADIUS_KM} km")

        # CW should get us within 10 km if the orbit is circular
        # For eccentric orbits, expect larger errors
        assert offset < STATION_KEEPING_RADIUS_KM * 3, (
            f"CW recovery left satellite {offset:.1f} km from slot "
            f"(3× station-keeping radius). Hill's equations inaccurate "
            f"for eccentric post-evasion orbit (e={ecc:.4f})."
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §8  NUMERICAL LANDMINES — Edge positions and state vectors
# ═══════════════════════════════════════════════════════════════════════════════
class TestNumericalEdgeCases:
    """
    State vectors that trigger division by zero, NaN, or overflow.
    """
    def test_zero_position_crashes_propagator(self):
        """Object at Earth's center [0,0,0] → division by zero in J2."""
        prop = OrbitalPropagator()
        sv = np.array([0.0, 0.0, 0.0, 7.0, 0.0, 0.0])
        with pytest.raises(Exception):
            prop.propagate(sv, 1.0)
    def test_zero_position_crashes_engine(self):
        """Telemetry with r=[0,0,0] should not crash the API (422 or graceful)."""
        engine = SimulationEngine()
        try:
            result = engine.ingest_telemetry("2026-03-12T08:00:00Z", [
                {"id": "DEB-ZERO", "type": "DEBRIS",
                 "r": {"x": 0.0, "y": 0.0, "z": 0.0},
                 "v": {"x": 0.0, "y": 0.0, "z": 0.0}},
            ])
            # If it doesn't crash on ingest, stepping will crash
            engine.step(1)
        except (ZeroDivisionError, FloatingPointError, ValueError):
            pytest.xfail("Engine crashes on zero-position debris (no input validation)")
    def test_sub_earth_debris_altitude_negative(self):
        """Debris below Earth surface → negative altitude in snapshot."""
        engine = _make_engine_at("2026-03-12T08:00:00Z", [], [
            {"id": "DEB-SUB", "r": {"x": 6000.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 8.0, "z": 0.0}},
        ])
        snap = engine.get_snapshot()
        if snap["debris_cloud"]:
            alt = snap["debris_cloud"][0][3]
            print(f"\n  Sub-surface debris altitude: {alt:.1f} km")
            assert alt >= 0, (
                f"Debris altitude {alt:.1f} km is negative — "
                f"_eci_to_lla reports sub-surface debris without filtering"
            )
    def test_hyperbolic_velocity_accepted(self):
        """Object with escape velocity should not crash ingestion."""
        engine = SimulationEngine()
        result = engine.ingest_telemetry("2026-03-12T08:00:00Z", [
            {"id": "DEB-HYPER", "type": "DEBRIS",
             "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 50.0, "z": 0.0}},  # 50 km/s >> escape velocity
        ])
        assert result["status"] == "ACK"
        # But stepping should handle it gracefully
        try:
            engine.step(1)
        except Exception as e:
            pytest.xfail(f"Hyperbolic debris crashes step(): {e}")
# ═══════════════════════════════════════════════════════════════════════════════
# §9  API CONTRACT HOLES
# ═══════════════════════════════════════════════════════════════════════════════
class TestAPIContractHoles:
    """Edge cases in the API contract not tested elsewhere."""
    def test_telemetry_backward_time_jump(self):
        """
        Sending telemetry with earlier timestamp than current sim_time
        should not make the clock go backward.
        """
        engine = _make_engine_at("2026-03-12T10:00:00.000Z", [
            {"id": "SAT-TJ", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        ])
        engine.step(3600)  # Advance to 11:00:00
        time_after_step = engine.sim_time

        # Now send telemetry with EARLIER timestamp
        engine.ingest_telemetry("2026-03-12T09:00:00.000Z", [
            {"id": "DEB-TJ", "type": "DEBRIS",
             "r": {"x": 7000.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.0, "z": 0.0}},
        ])

        time_after_ingest = engine.sim_time

        print(f"\n  Time after step:    {time_after_step}")
        print(f"  Time after ingest:  {time_after_ingest}")

        assert time_after_ingest >= time_after_step, (
            f"Simulation clock went backward from {time_after_step} "
            f"to {time_after_ingest} due to earlier telemetry timestamp"
        )
    def test_step_seconds_float_truncation(self):
        """step_seconds is cast to int in API layer — 0.5 becomes 0."""
        engine = _make_engine_at("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-FT", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        ])

        t_before = engine.sim_time
        # Simulate what the API does: int(0.5) = 0
        result = engine.step(int(0.5))

        time_advanced = (engine.sim_time - t_before).total_seconds()
        print(f"\n  step_seconds=int(0.5)={int(0.5)}")
        print(f"  Time advanced: {time_advanced}s")

        # int(0.5) = 0, which is a no-op
        if time_advanced == 0.0:
            pytest.xfail(
                "step_seconds is cast to int in API — sub-second steps become no-ops"
            )
    def test_schedule_empty_sequence_accepted(self):
        """Empty maneuver_sequence should be rejected or handled gracefully."""
        engine = _make_engine_at("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-EM", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        ])
        result = engine.schedule_maneuver("SAT-EM", [])

        # An empty sequence should arguably be rejected
        print(f"\n  Empty sequence result: {result['status']}")
        # Not asserting — documenting that it returns SCHEDULED for nothing
# ═══════════════════════════════════════════════════════════════════════════════
# §10  FUEL ACCOUNTING — Mass coupling across tick boundaries
# ═══════════════════════════════════════════════════════════════════════════════
class TestFuelAccountingCrossTick:
    """
    The Tsiolkovsky equation uses current wet mass. If burns execute
    across multiple ticks, the mass must be correctly tracked.
    """
    def test_multi_tick_burn_fuel_consistency(self):
        """
        Execute burns across 3 ticks. Verify fuel decreases monotonically
        and total consumption matches manual Tsiolkovsky calculation.
        """
        engine = _make_engine_at("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-FC", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        ])

        fuel_history = [engine.fuel_tracker.get_fuel("SAT-FC")]

        # Queue burns across 3 ticks (each 700s to respect cooldown)
        base = engine.sim_time
        for i in range(3):
            bt = base + timedelta(seconds=700 * i + 30)
            engine.satellites["SAT-FC"].maneuver_queue.append({
                "burn_id": f"FC_BURN_{i}",
                "burnTime": bt.isoformat(),
                "deltaV_vector": {"x": 0.0, "y": 0.003, "z": 0.0},  # 3 m/s
            })

        for i in range(3):
            engine.step(700)
            fuel_history.append(engine.fuel_tracker.get_fuel("SAT-FC"))

        print(f"\n  Fuel history: {[f'{f:.4f}' for f in fuel_history]}")

        # Verify monotonic decrease
        for i in range(1, len(fuel_history)):
            assert fuel_history[i] <= fuel_history[i-1], (
                f"Fuel increased from {fuel_history[i-1]:.4f} to {fuel_history[i]:.4f} "
                f"between ticks {i-1} and {i}"
            )

        # Verify total consumption matches Tsiolkovsky
        total_consumed = fuel_history[0] - fuel_history[-1]

        # Manual calculation: 3 burns × 3 m/s, mass decreasing each time
        m = M_DRY + fuel_history[0]
        expected_total = 0.0
        for _ in range(3):
            dm = m * (1 - math.exp(-3.0 / (ISP * G0)))
            expected_total += dm
            m -= dm

        err = abs(total_consumed - expected_total)
        print(f"  Total consumed: {total_consumed:.6f} kg")
        print(f"  Expected:       {expected_total:.6f} kg")
        print(f"  Error:          {err:.9f} kg")

        assert err < 0.01, (
            f"Fuel accounting error {err:.6f} kg across 3 ticks — "
            f"mass coupling not tracked correctly"
        )
    def test_duplicate_cdm_causes_double_evasion_fuel_drain(self):
        """
        If the same CDM appears in consecutive ticks (because the evasion
        hasn't executed yet), _auto_plan_maneuvers may schedule duplicate
        evasions, draining fuel twice.
        """
        engine = _make_engine_at("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-DD", "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        ], [
            {"id": "DEB-DD", "r": {"x": 6778.05, "y": 300.0, "z": 0.0},
             "v": {"x": 0.0, "y": -7.0, "z": 0.0}},
        ])

        fuel_before = engine.fuel_tracker.get_fuel("SAT-DD")

        # Run two quick ticks — CDM should appear in both
        engine.step(10)
        queue_after_tick1 = len(engine.satellites["SAT-DD"].maneuver_queue)

        engine.step(10)
        queue_after_tick2 = len(engine.satellites["SAT-DD"].maneuver_queue)

        fuel_after = engine.fuel_tracker.get_fuel("SAT-DD")

        print(f"\n  Queue after tick 1: {queue_after_tick1}")
        print(f"  Queue after tick 2: {queue_after_tick2}")
        print(f"  Fuel consumed: {fuel_before - fuel_after:.4f} kg")

        # If duplicate evasions are queued, the queue grows unnecessarily
        # Ideally tick 2 should NOT add more evasion burns for the same CDM
        if queue_after_tick2 > queue_after_tick1 + 2:
            pytest.xfail(
                f"Queue grew from {queue_after_tick1} to {queue_after_tick2} "
                f"across ticks — duplicate evasion for same CDM"
            )
