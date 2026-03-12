"""
test_live_flood.py — 3-Pillar Live Stress & Accuracy Test Suite
════════════════════════════════════════════════════════════════
Principal QA Engineer · Lead Data Scientist · Chief Astrodynamics Tester

Designed to mirror exactly what the hackathon judges will execute:
  • A live telemetry flood through POST /api/telemetry
  • Cross-referenced ground-station LOS with the CSV dataset
  • Hard physics math verified to numerical precision

Pillars
───────
  §1  LIVE DATA TELEMETRY FLOOD
      1.1  100K-object ingest throughput < 5 s
      1.2  Streaming 10 × 10K batch mode (grader simulation)
      1.3  State vector fidelity after bulk ingest
      1.4  KDTree build time < 3 s on 100K positions
      1.5  50 radius queries into 100K tree < 1 s
      1.6  Proof of sub-O(N²) scaling (ratio test)
      1.7  10× mandate: 50 sats × 100K debris assessment < 120 s

  §2  DATASET & LINE-OF-SIGHT
      2.1  CSV contains exactly 6 stations with correct coordinates
      2.2  CSV values match hard-coded GroundStationNetwork config
      2.3  GroundStationNetwork loads from CSV without error
      2.4  Elevation ≈ 90° for satellite directly overhead
      2.5  Negative elevation for antipodal satellite
      2.6  Minimum elevation angle enforced per station
      2.7  All 6 stations grant LOS to overhead satellites
      2.8  Burn < 10 s rejected (signal latency)
      2.9  Burn at exactly 10 s accepted
      2.10 Engine rejects maneuver when satellite is out of LOS
      2.11 CSV-loaded network produces identical LOS decisions

  §3  STRICT PHYSICS BENCHMARKS
      3.1  Tsiolkovsky single-burn precision (< 1e-6 kg error)
      3.2  Fuel never goes negative
      3.3  Mass decreases monotonically with burns
      3.4  ISP=300 s, G₀=9.80665 m/s² constant verification
      3.5  Max-ΔV (15 m/s) depletion matches formula
      3.6  EOL at exactly ≤ 2.5 kg
      3.7  Sequential burn mass coupling (second lighter)
      3.8  50 burns without fuel going negative
      3.9  J2 acceleration formula at reference point
      3.10 J2 z-coefficient is (5z²/r² − 3), not (5z²/r² − 1)
      3.11 RAAN drift matches analytical J2 rate (± 0.05°/orbit)
      3.12 Energy conserved < 1 J/kg over one LEO orbit
      3.13 No NaN/Inf after 24 h propagation
      3.14 Batch propagation = N × single (within tolerance)
      3.15 15K-object vectorised propagation < 30 s
      3.16 J2 produces measurable RAAN shift vs two-body
      3.17 Hard constants (100 m, 600 s, 15 m/s, 10 s, 2.5 kg) exact
      3.18 Cooldown boundary: 600 s rejected, 601 s accepted

All constants are sourced from config.py — never hardcoded inline.
"""

from __future__ import annotations

import csv
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

# ── import path ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    EOL_FUEL_THRESHOLD_KG,
    G0,
    ISP,
    J2,
    CONJUNCTION_THRESHOLD_KM,
    MAX_DV_PER_BURN,
    M_DRY,
    M_FUEL_INIT,
    MU_EARTH,
    R_EARTH,
    SIGNAL_LATENCY_S,
    THRUSTER_COOLDOWN_S,
)
from engine.collision import ConjunctionAssessor
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork, GROUND_STATIONS
from engine.maneuver_planner import ManeuverPlanner
from engine.models import Satellite
from engine.propagator import OrbitalPropagator
from engine.simulation import SimulationEngine

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
GS_CSV   = DATA_DIR / "ground_stations.csv"


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _leo_sv(
    alt_km: float = 400.0,
    inc_deg: float = 51.6,
    raan_deg: float = 0.0,
    nu_deg: float = 0.0,
) -> np.ndarray:
    """Return a circular LEO ECI state vector [x,y,z,vx,vy,vz] in km/km·s⁻¹."""
    r    = R_EARTH + alt_km
    v    = math.sqrt(MU_EARTH / r)
    inc  = math.radians(inc_deg)
    raan = math.radians(raan_deg)
    nu   = math.radians(nu_deg)
    cos_raan, sin_raan = math.cos(raan), math.sin(raan)
    cos_inc,  sin_inc  = math.cos(inc),  math.sin(inc)
    cos_nu,   sin_nu   = math.cos(nu),   math.sin(nu)
    x  = r * (cos_raan * cos_nu - sin_raan * sin_nu * cos_inc)
    y  = r * (sin_raan * cos_nu + cos_raan * sin_nu * cos_inc)
    z  = r * sin_nu * sin_inc
    vx = v * (-cos_raan * sin_nu - sin_raan * cos_nu * cos_inc)
    vy = v * (-sin_raan * sin_nu + cos_raan * cos_nu * cos_inc)
    vz = v * cos_nu * sin_inc
    return np.array([x, y, z, vx, vy, vz])


def _random_leo_states(n: int, seed: int = 42) -> dict[str, np.ndarray]:
    """Generate N random-but-physically-valid LEO state vectors."""
    rng    = np.random.default_rng(seed)
    states = {}
    for i in range(n):
        alt = rng.uniform(300.0, 600.0)
        r   = R_EARTH + alt
        v   = math.sqrt(MU_EARTH / r)
        phi = rng.uniform(-math.pi / 2, math.pi / 2)
        th  = rng.uniform(0, 2 * math.pi)
        pos = r * np.array([math.cos(th) * math.cos(phi),
                             math.sin(th) * math.cos(phi),
                             math.sin(phi)])
        vel = np.array([-v * math.sin(th), v * math.cos(th), 0.0])
        states[f"DEB-{i:07d}"] = np.concatenate([pos, vel])
    return states


def _telemetry_objects_from_states(
    states: dict[str, np.ndarray],
    obj_type: str = "DEBRIS",
) -> list[dict]:
    """Convert a state-vector dict into the ingest_telemetry object format."""
    objs = []
    for oid, sv in states.items():
        objs.append({
            "id":   oid,
            "type": obj_type,
            "r":    {"x": float(sv[0]), "y": float(sv[1]), "z": float(sv[2])},
            "v":    {"x": float(sv[3]), "y": float(sv[4]), "z": float(sv[5])},
        })
    return objs


# ═══════════════════════════════════════════════════════════════════════════════
# §1  LIVE DATA TELEMETRY FLOOD
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetryFlood:
    """
    Mirrors the live grader's 100K+ object telemetry burst.

    The grader will POST state vectors in rapid-fire batches.  Every test in
    this class ensures the engine absorbs the flood without O(N²) bottlenecks.
    """

    # ── 1.1  100K bulk ingest throughput ──────────────────────────────────────

    def test_100k_bulk_ingest_under_5s(self):
        """
        Engine must ingest 100,000 debris objects in < 5 seconds.
        Failure here means the index build or dict insertion is the bottleneck.
        """
        engine = SimulationEngine()
        ts     = datetime.now(timezone.utc).isoformat()
        states = _random_leo_states(100_000, seed=42)
        objs   = _telemetry_objects_from_states(states)

        t0      = time.perf_counter()
        result  = engine.ingest_telemetry(ts, objs)
        elapsed = time.perf_counter() - t0

        print(f"\n  [1.1] Bulk 100K ingest: {elapsed:.3f} s  "
              f"({100_000 / elapsed:,.0f} obj/s)")

        assert result["status"] == "ACK"
        assert result["processed_count"] == 100_000
        assert len(engine.debris) == 100_000
        assert elapsed < 5.0, f"Ingest {elapsed:.2f}s exceeds 5s limit"

    # ── 1.2  Streaming 10 × 10K (grader simulation) ───────────────────────────

    def test_streaming_10_batches_of_10k_under_5s(self):
        """
        Simulates grader's live feed: 10 API calls × 10K objects = 100K total.
        Each call must not re-allocate the entire index from scratch.
        """
        BATCH  = 10_000
        N_CALL = 10
        engine = SimulationEngine()
        ts     = datetime.now(timezone.utc).isoformat()
        states = _random_leo_states(BATCH * N_CALL, seed=77)
        all_objs = _telemetry_objects_from_states(states)

        t0 = time.perf_counter()
        for k in range(N_CALL):
            engine.ingest_telemetry(ts, all_objs[k * BATCH:(k + 1) * BATCH])
        elapsed = time.perf_counter() - t0

        print(f"\n  [1.2] Streaming {N_CALL}×{BATCH:,}: {elapsed:.3f} s  "
              f"({N_CALL * BATCH / elapsed:,.0f} obj/s)")

        assert len(engine.debris) == N_CALL * BATCH
        assert elapsed < 5.0, f"Streaming ingest {elapsed:.2f}s > 5s limit"

    # ── 1.3  State vector fidelity after ingest ───────────────────────────────

    def test_ingest_fidelity_1k_objects(self):
        """Every ingested position and velocity must be stored bit-for-bit exact."""
        engine = SimulationEngine()
        ts     = datetime.now(timezone.utc).isoformat()
        rng    = np.random.default_rng(5)
        n      = 1_000
        raw    = {}
        objs   = []

        for i in range(n):
            pos = rng.uniform(6500.0, 7500.0, 3)
            vel = rng.uniform(6.0, 8.0, 3)
            oid = f"VERIFY-{i:04d}"
            raw[oid] = (pos.tolist(), vel.tolist())
            objs.append({
                "id": oid, "type": "DEBRIS",
                "r": {"x": pos[0], "y": pos[1], "z": pos[2]},
                "v": {"x": vel[0], "y": vel[1], "z": vel[2]},
            })

        engine.ingest_telemetry(ts, objs)

        for oid, (pos, vel) in raw.items():
            deb = engine.debris[oid]
            np.testing.assert_allclose(deb.position, pos, atol=1e-12,
                                       err_msg=f"{oid} position mismatch")
            np.testing.assert_allclose(deb.velocity, vel, atol=1e-12,
                                       err_msg=f"{oid} velocity mismatch")

    # ── 1.4  KDTree build time ────────────────────────────────────────────────

    def test_kdtree_100k_build_under_3s(self):
        """KDTree construction over 100K LEO positions must complete in < 3 s."""
        from scipy.spatial import KDTree
        rng   = np.random.default_rng(42)
        r     = R_EARTH + 400.0
        th    = rng.uniform(0, 2 * math.pi, 100_000)
        phi   = rng.uniform(-math.pi / 2, math.pi / 2, 100_000)
        pos   = r * np.column_stack([
            np.cos(th) * np.cos(phi),
            np.sin(th) * np.cos(phi),
            np.sin(phi),
        ])

        t0      = time.perf_counter()
        KDTree(pos)
        elapsed = time.perf_counter() - t0

        print(f"\n  [1.4] KDTree 100K build: {elapsed * 1000:.1f} ms")
        assert elapsed < 3.0, f"KDTree build {elapsed:.2f}s > 3s limit"

    # ── 1.5  50 radius queries into 100K tree ─────────────────────────────────

    def test_kdtree_50_queries_100k_under_1s(self):
        """50 query_ball_point calls (r=50 km) into a 100K tree: < 1 s."""
        from scipy.spatial import KDTree
        rng   = np.random.default_rng(42)
        r     = R_EARTH + 400.0
        th_d  = rng.uniform(0, 2 * math.pi, 100_000)
        phi_d = rng.uniform(-math.pi / 2, math.pi / 2, 100_000)
        deb_pos = r * np.column_stack([
            np.cos(th_d) * np.cos(phi_d),
            np.sin(th_d) * np.cos(phi_d),
            np.sin(phi_d),
        ])
        tree = KDTree(deb_pos)

        sat_pos = r * np.column_stack([
            np.cos(rng.uniform(0, 2 * math.pi, 50)),
            np.sin(rng.uniform(0, 2 * math.pi, 50)),
            np.zeros(50),
        ])

        t0      = time.perf_counter()
        tree.query_ball_point(sat_pos, r=50.0)
        elapsed = time.perf_counter() - t0

        print(f"\n  [1.5] 50 queries into 100K tree: {elapsed * 1000:.2f} ms")
        assert elapsed < 1.0, f"50 queries took {elapsed:.3f}s > 1s limit"

    # ── 1.6  Sub-O(N²) scaling proof ─────────────────────────────────────────

    def test_sub_quadratic_scaling(self):
        """
        Prove KDTree does NOT scale quadratically.

        Method: build + query at N=1K and N=10K.  O(N²) → ratio ≈ 100.
        O(N log N) → ratio ≈ 14.  We require ratio < 30 (strict).
        """
        from scipy.spatial import KDTree
        rng = np.random.default_rng(1)

        def _timed(n_deb: int) -> float:
            r   = R_EARTH + 400.0
            th  = rng.uniform(0, 2 * math.pi, n_deb)
            phi = rng.uniform(-math.pi / 2, math.pi / 2, n_deb)
            pos = r * np.column_stack([
                np.cos(th) * np.cos(phi),
                np.sin(th) * np.cos(phi),
                np.sin(phi),
            ])
            sat = r * np.column_stack([
                np.cos(rng.uniform(0, 2 * math.pi, 50)),
                np.sin(rng.uniform(0, 2 * math.pi, 50)),
                np.zeros(50),
            ])
            t0 = time.perf_counter()
            KDTree(pos).query_ball_point(sat, r=50.0)
            return time.perf_counter() - t0

        t1k  = _timed(1_000)
        t10k = _timed(10_000)
        ratio = t10k / max(t1k, 1e-9)

        print(f"\n  [1.6] 1K: {t1k*1000:.2f} ms | 10K: {t10k*1000:.2f} ms "
              f"| ratio: {ratio:.1f}x (O(N²) would be ~100x)")
        assert ratio < 30, \
            f"Scaling ratio {ratio:.1f}x > 30 — possible O(N²) regression"

    # ── 1.7  10× mandate: 50 sats × 100K debris ──────────────────────────────

    @pytest.mark.slow
    def test_10x_mandate_100k_debris_assessment_under_120s(self):
        """
        Full ConjunctionAssessor with 50 sats × 100K debris must complete < 120 s.
        The Stage 1 altitude filter eliminates ~85 % of debris before KDTree build,
        so scaling from 10K → 100K is NOT 10× slower — it's closer to 2-3×.
        """
        prop     = OrbitalPropagator(rtol=1e-4, atol=1e-6)
        assessor = ConjunctionAssessor(prop)
        rng      = np.random.default_rng(42)
        r        = R_EARTH + 400.0
        v        = math.sqrt(MU_EARTH / r)

        sat_states: dict[str, np.ndarray] = {}
        for i in range(50):
            th  = rng.uniform(0, 2 * math.pi)
            inc = math.radians(rng.uniform(30.0, 60.0))
            sat_states[f"SAT-{i:03d}"] = np.array([
                r * math.cos(th), r * math.sin(th), 0.0,
                -v * math.sin(th) * math.cos(inc),
                 v * math.cos(th) * math.cos(inc),
                 v * math.sin(inc),
            ])

        # Wide altitude spread deliberately stresses the altitude band filter
        deb_states = _random_leo_states(100_000, seed=99)

        t0      = time.perf_counter()
        cdms    = assessor.assess(sat_states, deb_states, lookahead_s=3600.0)
        elapsed = time.perf_counter() - t0

        print(f"\n  [1.7] 50 sats x 100K debris -> {len(cdms)} CDMs "
              f"in {elapsed:.2f}s")
        assert elapsed < 120.0, \
            f"100K debris assessment took {elapsed:.2f}s > 120s limit"


# ═══════════════════════════════════════════════════════════════════════════════
# §2  DATASET & LINE-OF-SIGHT
# ═══════════════════════════════════════════════════════════════════════════════

class TestGroundStationLOS:
    """
    Cross-references the ground_stations.csv with the engine's LOS logic.
    Validates the 10-second signal latency constraint end-to-end.
    """

    # ── 2.1  CSV integrity ────────────────────────────────────────────────────

    def test_csv_contains_six_stations(self):
        """ground_stations.csv must exist and contain exactly 6 station rows."""
        assert GS_CSV.exists(), f"CSV not found at {GS_CSV}"
        with GS_CSV.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 6, f"Expected 6 stations, got {len(rows)}"

    def test_csv_has_correct_station_ids(self):
        """CSV must contain all 6 canonical station IDs."""
        assert GS_CSV.exists()
        with GS_CSV.open() as f:
            ids = {r["id"] for r in csv.DictReader(f)}
        expected = {"GS-001", "GS-002", "GS-003", "GS-004", "GS-005", "GS-006"}
        assert ids == expected, f"CSV IDs {ids} != expected {expected}"

    # ── 2.2  CSV vs hard-coded config ────────────────────────────────────────

    def test_csv_lat_lon_matches_config(self):
        """Every CSV station lat/lon must match the hard-coded config to ≤ 0.001°."""
        assert GS_CSV.exists()
        with GS_CSV.open() as f:
            csv_map = {r["id"]: r for r in csv.DictReader(f)}
        for gs in GROUND_STATIONS:
            gid = gs["id"]
            assert gid in csv_map, f"{gid} missing from CSV"
            assert abs(float(csv_map[gid]["lat"]) - gs["lat"]) < 0.001, \
                f"{gid} lat mismatch"
            assert abs(float(csv_map[gid]["lon"]) - gs["lon"]) < 0.001, \
                f"{gid} lon mismatch"

    def test_csv_min_elevation_angles_correct(self):
        """CSV min_elev_deg must match the config for each station."""
        assert GS_CSV.exists()
        with GS_CSV.open() as f:
            csv_map = {r["id"]: r for r in csv.DictReader(f)}
        for gs in GROUND_STATIONS:
            csv_el = float(csv_map[gs["id"]]["min_elev_deg"])
            assert abs(csv_el - gs["min_elev_deg"]) < 0.001, \
                f"{gs['id']} min_elev_deg: CSV={csv_el}, config={gs['min_elev_deg']}"

    # ── 2.3  CSV loading into network ─────────────────────────────────────────

    def test_csv_stations_load_into_network(self):
        """GroundStationNetwork must accept CSV-parsed station list without error."""
        assert GS_CSV.exists()
        with GS_CSV.open() as f:
            csv_stations = [
                {
                    "id":           r["id"],
                    "name":         r["name"],
                    "lat":          float(r["lat"]),
                    "lon":          float(r["lon"]),
                    "elev_m":       float(r["elev_m"]),
                    "min_elev_deg": float(r["min_elev_deg"]),
                }
                for r in csv.DictReader(f)
            ]
        network = GroundStationNetwork(stations=csv_stations)
        assert len(network.stations) == 6

    # ── 2.4  Overhead satellite → ~90° elevation ─────────────────────────────

    def test_overhead_satellite_elevation_near_90_deg(self):
        """Satellite directly above ISTRAC Bengaluru must compute elevation > 70°."""
        gs  = GROUND_STATIONS[0]   # ISTRAC Bengaluru (lat=13.03°, lon=77.52°)
        lat = math.radians(gs["lat"])
        lon = math.radians(gs["lon"])
        alt_km = gs["elev_m"] / 1000.0

        # At Unix epoch (t=0) the GMST rotation angle ≈ 0 → ECEF ≈ ECI
        ts = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Place satellite 400 km directly above the ground station in ECI
        r_sat = R_EARTH + alt_km + 400.0
        sat_eci = r_sat * np.array([
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        ])

        network = GroundStationNetwork()
        el = network.compute_elevation(sat_eci, gs, ts)

        print(f"\n  [2.4] Overhead elevation at {gs['name']}: {el:.2f}°")
        assert el > 70.0, f"Expected ~90°, got {el:.2f}°"

    # ── 2.5  Antipodal satellite → negative elevation ─────────────────────────

    def test_antipodal_satellite_has_negative_elevation(self):
        """Satellite on the opposite side of Earth must show negative elevation."""
        gs  = GROUND_STATIONS[0]
        lat = math.radians(-gs["lat"])         # flip latitude
        lon = math.radians(gs["lon"] + 180.0)  # flip longitude
        r   = R_EARTH + 400.0
        sat_eci = r * np.array([
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        ])
        ts = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        el = GroundStationNetwork().compute_elevation(sat_eci, gs, ts)

        print(f"\n  [2.5] Antipodal elevation: {el:.2f}°")
        assert el < 0.0, f"Antipodal satellite must be below horizon, got {el:.2f}°"

    # ── 2.6  Minimum elevation angle enforced ─────────────────────────────────

    def test_below_minimum_elevation_denied(self):
        """
        A satellite below the station's min_elev_deg must NOT receive LOS.

        Construction: GS-005 (IIT Delhi) has min_elev_deg=15.0°.
        We synthesise a satellite at ~5° elevation and verify denial.
        """
        gs = next(s for s in GROUND_STATIONS if s["id"] == "GS-005")
        assert gs["min_elev_deg"] == 15.0

        # Build a position 85° from GS zenith so elevation ≈ 5°
        lat = math.radians(gs["lat"])
        lon = math.radians(gs["lon"])
        r   = R_EARTH + 500.0
        ts  = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Zenith direction: unit vector pointing from Earth centre to GS
        z_hat = np.array([
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        ])
        # Perpendicular direction (in equatorial plane)
        perp = np.array([-math.sin(lon), math.cos(lon), 0.0])

        # Satellite at 5° elevation: 85° from zenith
        angle_from_zenith = math.radians(85.0)
        sat_dir = (math.cos(angle_from_zenith) * z_hat
                   + math.sin(angle_from_zenith) * perp)
        sat_eci = r * sat_dir / np.linalg.norm(sat_dir)

        network = GroundStationNetwork()
        el      = network.compute_elevation(sat_eci, gs, ts)
        has_los = network.check_line_of_sight(sat_eci, ts)

        print(f"\n  [2.6] Computed elevation: {el:.2f}° | min: {gs['min_elev_deg']}° "
              f"| LOS: {has_los}")
        assert el < gs["min_elev_deg"], \
            f"Expected el < {gs['min_elev_deg']}°, got {el:.2f}°"
        assert not has_los, "LOS must be denied below min_elev_deg"

    # ── 2.7  All 6 stations grant LOS overhead ────────────────────────────────

    def test_all_six_stations_grant_los_overhead(self):
        """Every station must grant LOS when satellite is directly overhead."""
        network = GroundStationNetwork()
        ts      = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        for gs in GROUND_STATIONS:
            lat = math.radians(gs["lat"])
            lon = math.radians(gs["lon"])
            r   = R_EARTH + 500.0
            sat_eci = r * np.array([
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            ])
            assert network.check_line_of_sight(sat_eci, ts), \
                f"Station {gs['id']} must grant LOS overhead"

    # ── 2.8  Signal latency: burns < 10 s rejected ────────────────────────────

    @pytest.mark.parametrize("lead_s", [0.0, 1.0, 5.0, 9.0, 9.9])
    def test_burn_under_10s_lead_rejected(self, lead_s: float):
        """Burn with lead time < 10 s must always be rejected."""
        planner = ManeuverPlanner()
        now     = datetime.now(timezone.utc)
        valid, reason = planner.validate_burn(
            delta_v_magnitude_ms=2.0,
            burn_time=now + timedelta(seconds=lead_s),
            current_time=now,
            last_burn_time=None,
            has_los=True,
        )
        assert not valid, f"lead={lead_s}s: expected rejection"
        assert any(tok in reason.lower() for tok in ["latency", "signal", "10"]), \
            f"Rejection message doesn't mention signal latency: '{reason}'"

    # ── 2.9  Burn at exactly 10 s accepted ────────────────────────────────────

    def test_burn_at_exactly_10s_accepted(self):
        """Burn scheduled at now + SIGNAL_LATENCY_S must be accepted."""
        planner = ManeuverPlanner()
        now     = datetime.now(timezone.utc)
        valid, reason = planner.validate_burn(
            delta_v_magnitude_ms=2.0,
            burn_time=now + timedelta(seconds=SIGNAL_LATENCY_S),
            current_time=now,
            last_burn_time=None,
            has_los=True,
        )
        assert valid, f"Burn at +{SIGNAL_LATENCY_S}s must pass, got: '{reason}'"

    # ── 2.10  Engine rejects no-LOS maneuver ──────────────────────────────────

    def test_engine_rejects_maneuver_without_los(self):
        """
        Engine.schedule_maneuver must reject a burn when the satellite's
        propagated position at burn time has no ground station LOS.

        We register a satellite, deliberately position it on the opposite side
        of Earth from all stations, and verify REJECTED with los=False.
        """
        engine = SimulationEngine()
        # Freeze time to Unix epoch so Earth rotation is deterministic
        engine.sim_time = datetime(1970, 1, 1, tzinfo=timezone.utc)

        # Station with minimum lat/lon coverage is near equator/Asia.
        # Antipodal position: lat=-13°, lon=-102° (equatorial Pacific)
        lat = math.radians(-13.0)
        lon = math.radians(-102.0)
        r   = R_EARTH + 400.0
        pos = r * np.array([math.cos(lat) * math.cos(lon),
                             math.cos(lat) * math.sin(lon),
                             math.sin(lat)])
        v_circ = math.sqrt(MU_EARTH / r)
        vel = np.array([-v_circ * math.sin(lon), v_circ * math.cos(lon), 0.0])

        engine.satellites["SAT-DARK"] = Satellite(
            id="SAT-DARK", position=pos.copy(), velocity=vel.copy(),
            timestamp=engine.sim_time,
        )
        engine.satellites["SAT-DARK"].nominal_state = np.concatenate([pos, vel])
        engine.fuel_tracker.register_satellite("SAT-DARK")

        # Check whether this position actually lacks LOS
        network = GroundStationNetwork()
        has_los = network.check_line_of_sight(pos, engine.sim_time)

        if not has_los:
            burn_time = (engine.sim_time + timedelta(seconds=30)).isoformat()
            result = engine.schedule_maneuver("SAT-DARK", [{
                "burnTime": burn_time,
                "deltaV_vector": {"x": 0.002, "y": 0.0, "z": 0.0},
            }])
            assert result["status"] == "REJECTED", \
                "Engine must REJECT maneuver with no LOS"
            assert result["validation"]["ground_station_los"] is False
        else:
            pytest.skip("Selected position happens to have LOS — geometry test skipped")

    # ── 2.11  CSV network matches hard-coded network ───────────────────────────

    def test_csv_network_matches_hardcoded_network(self):
        """
        For 20 random satellite positions and timestamps, LOS from the CSV-loaded
        GroundStationNetwork must agree 100 % with the default hard-coded network.
        """
        assert GS_CSV.exists()
        with GS_CSV.open() as f:
            csv_stations = [
                {k: (float(v) if k in ("lat", "lon", "elev_m", "min_elev_deg") else v)
                 for k, v in row.items()}
                for row in csv.DictReader(f)
            ]

        default_net = GroundStationNetwork()
        csv_net     = GroundStationNetwork(stations=csv_stations)

        rng = np.random.default_rng(55)
        ts  = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        for i in range(20):
            r = R_EARTH + rng.uniform(300, 700)
            d = rng.uniform(-1.0, 1.0, 3)
            sat_eci = r * d / np.linalg.norm(d)
            assert default_net.check_line_of_sight(sat_eci, ts) \
                == csv_net.check_line_of_sight(sat_eci, ts), \
                f"LOS disagreement for satellite {i}"


# ═══════════════════════════════════════════════════════════════════════════════
# §3  STRICT PHYSICS BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTsiolkovskyPrecision:
    """
    Tsiolkovsky mass depletion verified to full numerical precision.

        Δm = m_current × (1 − e^(−|Δv| / (Isp × g₀)))

        Dry mass : 500 kg     Isp    : 300 s
        Fuel init:  50 kg     g₀     : 9.80665 m/s²
        Max ΔV   :  15 m/s    EOL    : 2.5 kg (5 % of 50 kg)
    """

    @staticmethod
    def _tsiolkovsky(m_kg: float, dv_ms: float) -> float:
        """Reference implementation of the Tsiolkovsky depletion equation."""
        return m_kg * (1.0 - math.exp(-abs(dv_ms) / (ISP * G0)))

    # ── 3.1  Single-burn precision ────────────────────────────────────────────

    def test_single_burn_precision(self):
        """Single 5 m/s burn must deplete exactly Δm = m × (1 - e^(-dv/Isp·g0))."""
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=M_FUEL_INIT)
        dv_ms     = 5.0
        m_init    = M_DRY + M_FUEL_INIT       # 550 kg
        expected  = self._tsiolkovsky(m_init, dv_ms)
        actual    = ft.consume("T", dv_ms)
        assert abs(actual - expected) < 1e-6, \
            f"ΔV={dv_ms}m/s: Δm expected={expected:.8f}, got={actual:.8f} (err={abs(actual-expected):.2e})"

    # ── 3.2  Fuel never negative ──────────────────────────────────────────────

    def test_fuel_never_negative_on_empty_tank(self):
        """Burning from a near-empty tank must clamp to 0, never go negative."""
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=0.001)
        ft.consume("T", 15.0)
        assert ft.get_fuel("T") >= 0.0, "Fuel went negative"

    # ── 3.3  Monotonic mass decrease ─────────────────────────────────────────

    def test_mass_decreases_monotonically(self):
        """Each burn must strictly decrease the total wet mass."""
        ft   = FuelTracker()
        ft.register_satellite("T", fuel_kg=M_FUEL_INIT)
        prev = M_DRY + M_FUEL_INIT
        for _ in range(10):
            ft.consume("T", 2.0)
            curr = ft.get_current_mass("T")
            assert curr < prev, "Mass must strictly decrease after each burn"
            prev = curr

    # ── 3.4  Physical constant verification ──────────────────────────────────

    def test_isp_and_g0_constants_exact(self):
        """ISP must be exactly 300 s and G0 must be exactly 9.80665 m/s²."""
        assert abs(ISP - 300.0) < 1e-10,     f"ISP={ISP} ≠ 300.0 s"
        assert abs(G0 - 9.80665) < 1e-8,     f"G0={G0} ≠ 9.80665 m/s²"

    # ── 3.5  Max-ΔV burn depletion ────────────────────────────────────────────

    def test_max_dv_burn_depletion(self):
        """15 m/s burn on 550 kg wet mass: Δm ≈ 2.80 kg (formula must match)."""
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=M_FUEL_INIT)
        expected = self._tsiolkovsky(M_DRY + M_FUEL_INIT, MAX_DV_PER_BURN)
        actual   = ft.consume("T", MAX_DV_PER_BURN)
        assert abs(actual - expected) < 1e-6, \
            f"15 m/s burn: expected Δm={expected:.6f} kg, got {actual:.6f} kg"
        # Sanity bound: should be 2–4 kg for a 550 kg satellite
        assert 1.5 < actual < 5.0, f"Δm={actual:.3f} kg outside sanity range [1.5, 5.0]"

    # ── 3.6  EOL at 2.5 kg ────────────────────────────────────────────────────

    def test_eol_threshold_at_exactly_2_5_kg(self):
        """EOL must trigger at ≤ 2.5 kg and NOT trigger above it."""
        ft = FuelTracker()
        ft.register_satellite("A", fuel_kg=EOL_FUEL_THRESHOLD_KG + 1e-6)
        assert not ft.is_eol("A"), "Fuel above threshold must NOT be EOL"
        ft.register_satellite("B", fuel_kg=EOL_FUEL_THRESHOLD_KG)
        assert ft.is_eol("B"),     "Fuel at exactly threshold must be EOL"
        ft.register_satellite("C", fuel_kg=EOL_FUEL_THRESHOLD_KG - 1e-6)
        assert ft.is_eol("C"),     "Fuel below threshold must be EOL"

    # ── 3.7  Sequential burn mass coupling ───────────────────────────────────

    def test_sequential_burn_coupling(self):
        """
        Second identical burn must consume LESS fuel than the first, because
        the wet mass at burn-2 start is lower than at burn-1 start.
        """
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=M_FUEL_INIT)
        dv_ms = 5.0
        dm1   = ft.consume("T", dv_ms)
        m2    = ft.get_current_mass("T")
        dm2   = ft.consume("T", dv_ms)

        assert dm2 < dm1, \
            f"Burn 2 ({dm2:.6f} kg) must be lighter than burn 1 ({dm1:.6f} kg)"

        # Verify coupling: dm2 = m2 × (1 - exp(-dv/(Isp·g0)))
        expected_dm2 = self._tsiolkovsky(m2, dv_ms)
        assert abs(dm2 - expected_dm2) < 1e-6, \
            f"Burn-2 coupling error: {abs(dm2 - expected_dm2):.2e} kg"

    # ── 3.8  50 burns, fuel ≥ 0 throughout ───────────────────────────────────

    def test_50_burns_fuel_stays_non_negative(self):
        """50 successive 0.5 m/s burns must never produce negative fuel."""
        ft = FuelTracker()
        ft.register_satellite("T", fuel_kg=M_FUEL_INIT)
        for i in range(50):
            ft.consume("T", 0.5)
            assert ft.get_fuel("T") >= 0.0, \
                f"Fuel went negative after burn {i + 1}"


class TestJ2AndRKPropagation:
    """
    Verifies the J2-perturbed DOP853 orbital propagator against closed-form
    analytical results and known conservation laws.
    """

    @pytest.fixture(scope="class")
    def prop(self) -> OrbitalPropagator:
        return OrbitalPropagator(rtol=1e-9, atol=1e-11)

    # ── 3.9  J2 formula at reference point ───────────────────────────────────

    def test_j2_acceleration_at_equatorial_point(self):
        """J2 total acceleration must match the reference formula at [6778, 0, 0]."""
        pos = np.array([6778.0, 0.0, 0.0])   # equatorial, on x-axis
        x, y, z = pos
        r = np.linalg.norm(pos)

        a_grav = -MU_EARTH * pos / r**3
        factor = 1.5 * J2 * MU_EARTH * R_EARTH**2 / r**5
        z2_r2  = (z / r)**2
        a_j2   = factor * np.array([
            x * (5.0 * z2_r2 - 1.0),
            y * (5.0 * z2_r2 - 1.0),
            z * (5.0 * z2_r2 - 3.0),
        ])
        a_ref = a_grav + a_j2

        a_engine = OrbitalPropagator._compute_acceleration(pos)
        np.testing.assert_allclose(a_engine, a_ref, rtol=1e-12,
                                   err_msg="J2 formula mismatch at equatorial point")

    # ── 3.10  J2 z-coefficient is (5z²/r² − 3) ──────────────────────────────

    def test_j2_z_coefficient_is_minus_three(self):
        """
        The z-component of J2 acceleration uses (5z²/r² − 3).
        Using (5z²/r² − 1) [same as x/y] would be wrong.
        """
        pos = np.array([5000.0, 2000.0, 4000.0])   # nonzero z
        r   = np.linalg.norm(pos)
        z   = pos[2]
        z2r2   = (z / r)**2
        factor = 1.5 * J2 * MU_EARTH * R_EARTH**2 / r**5

        ref_az_j2  = factor * z * (5.0 * z2r2 - 3.0)   # CORRECT coefficient
        wrong_az_j2= factor * z * (5.0 * z2r2 - 1.0)   # WRONG — same as x/y

        a_engine   = OrbitalPropagator._compute_acceleration(pos)
        a_grav_z   = -MU_EARTH * z / r**3
        az_j2_eng  = a_engine[2] - a_grav_z

        assert abs(az_j2_eng - ref_az_j2) < 1e-15, \
            f"J2 z-coeff error: engine={az_j2_eng:.6e}, ref={ref_az_j2:.6e}"
        assert abs(az_j2_eng - wrong_az_j2) > 1e-15, \
            "Engine is using (5z²/r²-1) instead of (5z²/r²-3) — WRONG formula"

    # ── 3.11  RAAN drift matches analytical J2 rate ───────────────────────────

    def test_raan_drift_matches_analytical_rate(self, prop):
        """
        Propagate one full orbit and verify RAAN drifts at the J2-predicted rate:
            dΩ/dt = -(3/2) · n · J₂ · (R_E/a)² · cos(i)

        Tolerance: ±0.05° per orbit (limited by single-orbit accumulation).
        """
        r   = R_EARTH + 400.0
        v   = math.sqrt(MU_EARTH / r)
        inc = math.radians(51.6)
        T   = 2 * math.pi * math.sqrt(r**3 / MU_EARTH)

        # Start at RAAN=0: position on x-axis, velocity in y-z plane
        sv = np.array([r, 0.0, 0.0, 0.0, v * math.cos(inc), v * math.sin(inc)])

        # Analytical RAAN drift over one period
        n_mm      = 2 * math.pi / T
        draan_dt  = -1.5 * n_mm * J2 * (R_EARTH / r)**2 * math.cos(inc)
        expected  = math.degrees(draan_dt * T)   # deg/orbit

        # Propagate
        sv_final = prop.propagate(sv, T)

        # Recover RAAN from the angular momentum vector's orientation
        h_vec = np.cross(sv_final[:3], sv_final[3:])
        h_hat = h_vec / np.linalg.norm(h_vec)
        z_hat = np.array([0.0, 0.0, 1.0])
        N     = np.cross(z_hat, h_hat)
        n_mag = np.linalg.norm(N)
        raan_final = math.degrees(math.atan2(N[1], N[0])) if n_mag > 1e-10 else 0.0

        err_deg = abs(raan_final - expected)
        print(f"\n  [3.11] RAAN drift — expected: {expected:.4f}°  "
              f"actual: {raan_final:.4f}°  err: {err_deg:.4f}°")
        assert err_deg < 0.05, \
            (f"RAAN drift {raan_final:.4f}° deviates from analytical "
             f"{expected:.4f}° by {err_deg:.4f}° (limit 0.05°)")

    # ── 3.12  Energy conservation < 1 J/kg over one orbit ────────────────────

    def test_energy_conservation_one_leo_orbit(self, prop):
        """Specific mechanical energy must be conserved to < 1 J/kg over one orbit."""
        r  = R_EARTH + 400.0
        v  = math.sqrt(MU_EARTH / r)
        sv = np.array([r, 0.0, 0.0, 0.0, v, 0.0])
        T  = 2 * math.pi * math.sqrt(r**3 / MU_EARTH)

        def sme(s: np.ndarray) -> float:
            """Specific mechanical energy in km²/s²."""
            return 0.5 * np.dot(s[3:], s[3:]) - MU_EARTH / np.linalg.norm(s[:3])

        E0 = sme(sv)
        E1 = sme(prop.propagate(sv, T))
        dE = abs(E1 - E0) * 1e6   # km²/s² → J/kg

        print(f"\n  [3.12] Energy error: {dE:.6f} J/kg over one LEO orbit")
        assert dE < 1.0, f"Energy drift {dE:.4f} J/kg > 1 J/kg limit"

    # ── 3.13  No NaN/Inf after 24 h ──────────────────────────────────────────

    def test_no_nan_after_24h(self, prop):
        """State vector must be finite and in LEO range after 86400 s."""
        sv    = _leo_sv(alt_km=400.0, inc_deg=51.6)
        final = prop.propagate(sv, 86400.0)

        assert not np.any(np.isnan(final)), "NaN in 24h propagation result"
        assert not np.any(np.isinf(final)), "Inf in 24h propagation result"
        r = np.linalg.norm(final[:3])
        assert 6000 < r < 7500, f"Position r={r:.1f} km outside LEO range after 24h"

    # ── 3.14  Batch = N × single within tolerance ─────────────────────────────

    def test_batch_equals_single_propagation(self, prop):
        """
        Batch propagation of 20 objects must agree with 20 independent single
        propagations to rtol=1e-6, atol=1e-9.
        """
        rng    = np.random.default_rng(42)
        n, dt  = 20, 3600.0
        states = _random_leo_states(n, seed=42)

        single = {oid: prop.propagate(sv, dt) for oid, sv in states.items()}
        batch  = prop.propagate_batch(states, dt)

        for oid in states:
            np.testing.assert_allclose(
                batch[oid], single[oid],
                rtol=1e-6, atol=1e-9,
                err_msg=f"Batch vs single mismatch for {oid}",
            )

    # ── 3.15  15K-object batch propagation < 30 s ────────────────────────────

    def test_15k_object_batch_propagation_under_30s(self):
        """
        15,000 objects (50 % beyond the 10K baseline) must propagate in a
        single vectorised DOP853 call within 30 seconds.
        """
        prop   = OrbitalPropagator(rtol=1e-6, atol=1e-8)
        states = _random_leo_states(15_000, seed=11)

        t0      = time.perf_counter()
        result  = prop.propagate_batch(states, dt_seconds=60.0)
        elapsed = time.perf_counter() - t0

        print(f"\n  [3.15] 15K batch propagation: {elapsed:.2f}s")
        assert len(result) == 15_000, "Wrong number of results"
        assert elapsed < 30.0, f"15K propagation took {elapsed:.2f}s > 30s"

        # Spot-check 100 random results for NaN
        for sv in list(result.values())[:100]:
            assert not np.any(np.isnan(sv)), "NaN in propagation output"

    # ── 3.16  J2 produces measurable RAAN vs two-body ────────────────────────

    def test_j2_causes_measurable_raan_shift_vs_two_body(self, prop):
        """
        J2-perturbed propagation must diverge from two-body propagation after
        one LEO orbit.  Divergence < 0.1 km would indicate J2 is not active.
        """
        r   = R_EARTH + 400.0
        v   = math.sqrt(MU_EARTH / r)
        inc = math.radians(51.6)
        sv  = np.array([r, 0.0, 0.0, 0.0, v * math.cos(inc), v * math.sin(inc)])
        T   = 2 * math.pi * math.sqrt(r**3 / MU_EARTH)

        sv_j2 = prop.propagate(sv, T)

        # Two-body reference (gravity only, no J2)
        def two_body(t, s):
            p, vv = s[:3], s[3:]
            a     = -MU_EARTH * p / np.linalg.norm(p)**3
            return np.concatenate([vv, a])

        sol = solve_ivp(two_body, [0, T], sv,
                        method="DOP853", rtol=1e-9, atol=1e-11)
        sv_2b = sol.y[:, -1]

        pos_diff = np.linalg.norm(sv_j2[:3] - sv_2b[:3])
        print(f"\n  [3.16] J2 vs two-body position difference: {pos_diff:.3f} km")
        assert pos_diff > 0.1, \
            f"J2 effect {pos_diff:.4f} km < 0.1 km — J2 may not be active"


class TestHardConstraints:
    """
    Exact numerical verification of every hard constraint from the problem
    statement.  These must NEVER be relaxed for performance reasons.
    """

    # ── 3.17  Hard constant values ────────────────────────────────────────────

    def test_conjunction_threshold_is_0_100_km(self):
        assert abs(CONJUNCTION_THRESHOLD_KM - 0.100) < 1e-10, \
            f"Threshold must be 0.100 km, got {CONJUNCTION_THRESHOLD_KM}"

    def test_cooldown_is_600s(self):
        assert abs(THRUSTER_COOLDOWN_S - 600.0) < 1e-10, \
            f"Cooldown must be 600.0 s, got {THRUSTER_COOLDOWN_S}"

    def test_max_dv_is_15ms(self):
        assert abs(MAX_DV_PER_BURN - 15.0) < 1e-10, \
            f"Max ΔV must be 15.0 m/s, got {MAX_DV_PER_BURN}"

    def test_signal_latency_is_10s(self):
        assert abs(SIGNAL_LATENCY_S - 10.0) < 1e-10, \
            f"Signal latency must be 10.0 s, got {SIGNAL_LATENCY_S}"

    def test_eol_threshold_is_5pct_of_50kg(self):
        expected = 0.05 * M_FUEL_INIT
        assert abs(EOL_FUEL_THRESHOLD_KG - expected) < 1e-10, \
            f"EOL threshold must be {expected} kg, got {EOL_FUEL_THRESHOLD_KG}"

    def test_dry_mass_is_500kg(self):
        assert abs(M_DRY - 500.0) < 1e-10, \
            f"Dry mass must be 500.0 kg, got {M_DRY}"

    def test_initial_fuel_is_50kg(self):
        assert abs(M_FUEL_INIT - 50.0) < 1e-10, \
            f"Initial fuel must be 50.0 kg, got {M_FUEL_INIT}"

    # ── 3.18  Cooldown boundary: 600 s rejected, 601 s accepted ──────────────

    def test_cooldown_exactly_600s_rejected(self):
        """Burn exactly 600 s after last burn must be REJECTED (exclusive boundary)."""
        planner = ManeuverPlanner()
        now  = datetime.now(timezone.utc)
        last = now - timedelta(seconds=570)          # last burn 570 s ago
        burn = last + timedelta(seconds=600)         # exactly 600 s later

        valid, _ = planner.validate_burn(
            delta_v_magnitude_ms=2.0,
            burn_time=burn,
            current_time=now,
            last_burn_time=last,
            has_los=True,
        )
        assert not valid, "Cooldown boundary: exactly 600 s must be REJECTED"

    def test_cooldown_601s_accepted(self):
        """Burn 601 s after last burn must be ACCEPTED."""
        planner = ManeuverPlanner()
        now  = datetime.now(timezone.utc)
        last = now - timedelta(seconds=570)
        burn = last + timedelta(seconds=601)

        valid, reason = planner.validate_burn(
            delta_v_magnitude_ms=2.0,
            burn_time=burn,
            current_time=now,
            last_burn_time=last,
            has_los=True,
        )
        assert valid, f"601 s after last burn must be ACCEPTED, got: '{reason}'"

    def test_risk_classification_exact_boundaries(self):
        """Risk levels must flip at exactly 0.100 km, 1.0 km, and 5.0 km."""
        cls = ConjunctionAssessor._classify_risk

        # Below 0.100 km → CRITICAL
        assert cls(0.0999) == "CRITICAL"
        assert cls(0.000)  == "CRITICAL"

        # At exactly 0.100 km → RED (not CRITICAL — exclusive boundary)
        assert cls(0.100) == "RED"

        # Between 0.100 and 1.0 km → RED
        assert cls(0.500) == "RED"

        # At exactly 1.0 km → YELLOW
        assert cls(1.000) == "YELLOW"

        # Between 1.0 and 5.0 km → YELLOW
        assert cls(3.000) == "YELLOW"

        # At exactly 5.0 km → GREEN
        assert cls(5.000) == "GREEN"
        assert cls(10.00) == "GREEN"

    def test_engine_rejects_16ms_dv(self):
        """Engine.schedule_maneuver must reject a 16 m/s delta-v vector."""
        engine = SimulationEngine()
        engine.ingest_telemetry(
            datetime.now(timezone.utc).isoformat(),
            [{"id": "SAT-A", "type": "SATELLITE",
              "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
              "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
        )
        future = (engine.sim_time + timedelta(seconds=120)).isoformat()
        result = engine.schedule_maneuver("SAT-A", [{
            "burnTime": future,
            "deltaV_vector": {"x": 0.016, "y": 0.0, "z": 0.0},  # 16 m/s
        }])
        assert result["status"] == "REJECTED", \
            "16 m/s ΔV must be REJECTED by engine"
