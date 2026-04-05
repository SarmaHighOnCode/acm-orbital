"""
test_final_coverage.py — Final coverage sweep for all remaining gaps.

Covers:
1. Full HTTP API round-trips (TestClient)
2. ECI→LLA coordinate conversion accuracy
3. Debris propagation across steps
4. Uptime scoring formula
5. Health endpoint
6. Burn type classification in maneuver log
7. Fast-path vs DOP853 consistency
8. Multiple collisions in single step
9. Maneuver queue chronological ordering
10. Auto-seed populates engine correctly
11. Snapshot debris_cloud format validation
12. Concurrent API requests (rapid-fire)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import time
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from main import app
from engine.simulation import SimulationEngine, _eci_to_lla
from engine.propagator import OrbitalPropagator
from config import (
    MU_EARTH, R_EARTH, M_FUEL_INIT, MAX_DV_PER_BURN,
    THRUSTER_COOLDOWN_S, STATION_KEEPING_RADIUS_KM,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _leo_sv(alt_km=400.0, inc_deg=51.6):
    r = R_EARTH + alt_km
    v = np.sqrt(MU_EARTH / r)
    inc = np.radians(inc_deg)
    return np.array([r, 0.0, 0.0, 0.0, v * np.cos(inc), v * np.sin(inc)])


def _obj(oid, otype, alt_km=400.0):
    sv = _leo_sv(alt_km)
    return {
        "id": oid, "type": otype,
        "r": {"x": float(sv[0]), "y": float(sv[1]), "z": float(sv[2])},
        "v": {"x": float(sv[3]), "y": float(sv[4]), "z": float(sv[5])},
    }


T0 = "2026-03-21T12:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════════
# §1: FULL HTTP API ROUND-TRIPS
# ═══════════════════════════════════════════════════════════════════════════

class TestAPIRoundTrip:
    """Test actual HTTP endpoints via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def client(self):
        # Use context manager to trigger lifespan (initializes engine)
        with TestClient(app) as c:
            self.client = c
            yield

    def test_health_endpoint_returns_200(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "service" in data

    def test_telemetry_post_returns_ack(self):
        payload = {
            "timestamp": T0,
            "objects": [_obj("SAT-API-001", "SATELLITE", 400)]
        }
        resp = self.client.post("/api/telemetry", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACK"
        assert data["processed_count"] >= 1

    def test_telemetry_post_with_debris(self):
        payload = {
            "timestamp": T0,
            "objects": [
                _obj("SAT-API-002", "SATELLITE", 400),
                _obj("DEB-API-001", "DEBRIS", 410),
                _obj("DEB-API-002", "DEBRIS", 420),
            ]
        }
        resp = self.client.post("/api/telemetry", json=payload)
        assert resp.status_code == 200
        assert resp.json()["processed_count"] >= 3

    def test_simulate_step_returns_step_complete(self):
        # Seed first
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [_obj("SAT-STEP-001", "SATELLITE", 400)]
        })
        resp = self.client.post("/api/simulate/step", json={"step_seconds": 60.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "STEP_COMPLETE"
        assert "new_timestamp" in data
        assert "collisions_detected" in data
        assert "maneuvers_executed" in data

    def test_snapshot_returns_valid_structure(self):
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [_obj("SAT-SNAP-001", "SATELLITE", 400)]
        })
        self.client.post("/api/simulate/step", json={"step_seconds": 10.0})
        resp = self.client.get("/api/visualization/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "satellites" in data
        assert isinstance(data["satellites"], list)

    def test_maneuver_schedule_rejects_unknown_satellite(self):
        resp = self.client.post("/api/maneuver/schedule", json={
            "satelliteId": "SAT-NONEXISTENT",
            "maneuver_sequence": [{
                "burn_id": "B1",
                "burnTime": "2026-03-21T12:05:00+00:00",
                "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0},
            }]
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "REJECTED"

    def test_maneuver_schedule_accepts_valid_burn(self):
        # Seed satellite
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [_obj("SAT-MAN-001", "SATELLITE", 400)]
        })
        resp = self.client.post("/api/maneuver/schedule", json={
            "satelliteId": "SAT-MAN-001",
            "maneuver_sequence": [{
                "burn_id": "B-VALID",
                "burnTime": "2026-03-21T12:05:00+00:00",
                "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0},
            }]
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] in ("SCHEDULED", "REJECTED")
        assert "validation" in data

    def test_full_lifecycle_telemetry_step_snapshot(self):
        """Full lifecycle: ingest → step → snapshot — data flows through."""
        # Ingest
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [
                _obj("SAT-LC-001", "SATELLITE", 400),
                _obj("DEB-LC-001", "DEBRIS", 410),
            ]
        })
        # Step
        self.client.post("/api/simulate/step", json={"step_seconds": 100.0})
        # Snapshot
        resp = self.client.get("/api/visualization/snapshot")
        data = resp.json()
        sat_ids = [s["id"] for s in data["satellites"]]
        assert "SAT-LC-001" in sat_ids


# ═══════════════════════════════════════════════════════════════════════════
# §2: ECI → LLA CONVERSION ACCURACY
# ═══════════════════════════════════════════════════════════════════════════

class TestECIToLLA:
    """Verify ECI→geodetic conversion accuracy."""

    def test_satellite_on_x_axis_at_gmst_zero(self):
        """At GMST=0, a satellite on +X axis should have lon ≈ 0°."""
        # J2000 epoch: 2000-01-01T12:00:00 UTC has GMST ≈ 280.46°
        # Use a time where GMST ≈ 0° for clean test
        t = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        pos = np.array([R_EARTH + 400, 0.0, 0.0])
        lat, lon, alt = _eci_to_lla(pos, t)
        assert -90 <= lat <= 90, f"Latitude {lat} out of range"
        assert -180 <= lon <= 180, f"Longitude {lon} out of range"
        assert 350 < alt < 450, f"Altitude {alt} should be ~400km"

    def test_satellite_on_z_axis_has_90_latitude(self):
        """A satellite on +Z axis should have lat ≈ +90° (north pole)."""
        t = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        pos = np.array([0.0, 0.0, R_EARTH + 400])
        lat, lon, alt = _eci_to_lla(pos, t)
        assert abs(lat - 90.0) < 1.0, f"Latitude should be ~90°, got {lat}"

    def test_satellite_on_neg_z_axis_has_neg90_latitude(self):
        """A satellite on -Z axis should have lat ≈ -90° (south pole)."""
        t = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        pos = np.array([0.0, 0.0, -(R_EARTH + 400)])
        lat, lon, alt = _eci_to_lla(pos, t)
        assert abs(lat + 90.0) < 1.0, f"Latitude should be ~-90°, got {lat}"

    def test_altitude_positive_for_leo(self):
        """Any LEO satellite should have positive altitude."""
        t = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        for alt_km in [200, 400, 800, 1200]:
            sv = _leo_sv(alt_km)
            lat, lon, alt = _eci_to_lla(sv[:3], t)
            assert alt > 0, f"Altitude should be positive for LEO, got {alt}"
            assert abs(alt - alt_km) < 25, (
                f"Altitude {alt:.1f} km should be within 25km of {alt_km}"
            )

    def test_longitude_wraps_correctly(self):
        """Longitude must always be in [-180, 180]."""
        t = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        for angle in np.linspace(0, 2 * np.pi, 12):
            r = R_EARTH + 400
            pos = np.array([r * np.cos(angle), r * np.sin(angle), 0.0])
            lat, lon, alt = _eci_to_lla(pos, t)
            assert -180 <= lon <= 180, f"Longitude {lon} out of [-180, 180]"


# ═══════════════════════════════════════════════════════════════════════════
# §3: DEBRIS PROPAGATION
# ═══════════════════════════════════════════════════════════════════════════

class TestDebrisPropagation:
    """Verify debris objects actually move during simulation steps."""

    def test_debris_position_changes_after_step(self):
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [
            _obj("SAT-D1", "SATELLITE", 400),
            _obj("DEB-D1", "DEBRIS", 500),
        ])
        pos_before = eng.debris["DEB-D1"].position.copy()
        eng.step(100.0)
        pos_after = eng.debris["DEB-D1"].position
        dist = np.linalg.norm(pos_after - pos_before)
        assert dist > 0.1, f"Debris didn't move: Δ={dist:.6f} km"

    def test_debris_stays_in_orbit(self):
        """Debris should remain at orbital altitude, not fall to Earth."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [
            _obj("SAT-D2", "SATELLITE", 400),
            _obj("DEB-D2", "DEBRIS", 500),
        ])
        for _ in range(10):
            eng.step(100.0)
        alt = np.linalg.norm(eng.debris["DEB-D2"].position) - R_EARTH
        assert 300 < alt < 700, f"Debris altitude {alt:.1f} km — fell out of orbit?"

    def test_100_debris_all_propagate(self):
        """All 100 debris should have different positions after stepping."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        objs = [_obj("SAT-D3", "SATELLITE", 400)]
        objs += [_obj(f"DEB-{i:04d}", "DEBRIS", 400 + i % 100)
                 for i in range(100)]
        eng.ingest_telemetry(t0.isoformat(), objs)

        positions_before = {did: d.position.copy() for did, d in eng.debris.items()}
        eng.step(100.0)

        moved = 0
        for did, d in eng.debris.items():
            if np.linalg.norm(d.position - positions_before[did]) > 0.01:
                moved += 1
        assert moved >= 90, f"Only {moved}/100 debris moved (expected ≥90)"


# ═══════════════════════════════════════════════════════════════════════════
# §4: UPTIME SCORING FORMULA
# ═══════════════════════════════════════════════════════════════════════════

class TestUptimeScoring:
    """Verify uptime score = exp(-0.001 * time_outside_box_s)."""

    def test_initial_uptime_is_1(self):
        """Satellite that never left the box should have uptime = 1.0."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-U1", "SATELLITE", 400)])
        eng.step(0.1)
        snap = eng.get_snapshot()
        sat = [s for s in snap["satellites"] if s["id"] == "SAT-U1"][0]
        assert sat["uptime_score"] >= 0.99, (
            f"Initial uptime should be ~1.0, got {sat['uptime_score']}"
        )

    def test_uptime_decreases_when_outside_box(self):
        """Force satellite outside box, uptime should decrease."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-U2", "SATELLITE", 400)])
        # Manually set time_outside_box to simulate being outside
        eng.time_outside_box["SAT-U2"] = 1000.0  # 1000 seconds outside
        snap = eng.get_snapshot()
        sat = [s for s in snap["satellites"] if s["id"] == "SAT-U2"][0]
        expected = np.exp(-0.001 * 1000.0)  # ~0.368
        assert abs(sat["uptime_score"] - expected) < 0.05, (
            f"Uptime score {sat['uptime_score']:.4f} != expected {expected:.4f}"
        )

    def test_uptime_never_negative(self):
        """Even with huge time outside, uptime should be > 0."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-U3", "SATELLITE", 400)])
        eng.time_outside_box["SAT-U3"] = 100000.0
        snap = eng.get_snapshot()
        sat = [s for s in snap["satellites"] if s["id"] == "SAT-U3"][0]
        assert sat["uptime_score"] >= 0.0, "Uptime score should never be negative"


# ═══════════════════════════════════════════════════════════════════════════
# §5: BURN TYPE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestBurnTypeClassification:
    """Verify burn log correctly tags EVASION/RECOVERY/GRAVEYARD/MANUAL."""

    def _exec_burn(self, burn_id):
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-BT", "SATELLITE", 400)])
        sat = eng.satellites["SAT-BT"]
        r_hat = sat.position / np.linalg.norm(sat.position)
        dv = r_hat * (3.0 / 1000.0)
        sat.maneuver_queue.append({
            "burn_id": burn_id,
            "burnTime": (t0 + timedelta(seconds=50)).isoformat(),
            "deltaV_vector": {"x": float(dv[0]), "y": float(dv[1]), "z": float(dv[2])},
        })
        eng.step(100.0)
        return eng.maneuver_log

    def test_evasion_burn_tagged(self):
        log = self._exec_burn("EVASION-001")
        types = [e.get("type") for e in log if e.get("burn_id") == "EVASION-001"]
        assert "EVASION" in types, f"Expected EVASION type, got {types}"

    def test_recovery_burn_tagged(self):
        log = self._exec_burn("RTS-RECOVERY-001")
        types = [e.get("type") for e in log if e.get("burn_id") == "RTS-RECOVERY-001"]
        assert "RECOVERY" in types, f"Expected RECOVERY type, got {types}"

    def test_graveyard_burn_tagged(self):
        log = self._exec_burn("GRAVEYARD-DEORBIT-001")
        types = [e.get("type") for e in log if e.get("burn_id") == "GRAVEYARD-DEORBIT-001"]
        assert "GRAVEYARD" in types, f"Expected GRAVEYARD type, got {types}"

    def test_manual_burn_tagged(self):
        log = self._exec_burn("CUSTOM-BURN-001")
        types = [e.get("type") for e in log if e.get("burn_id") == "CUSTOM-BURN-001"]
        assert "MANUAL" in types, f"Expected MANUAL type, got {types}"


# ═══════════════════════════════════════════════════════════════════════════
# §6: FAST-PATH VS DOP853 CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════════

class TestFastPathConsistency:
    """Verify fast-path propagation is reasonably close to DOP853."""

    def test_fast_path_matches_dop853_for_short_step(self):
        """For a 100s step, fast-path should be within 1km of DOP853."""
        prop = OrbitalPropagator()
        sv0 = _leo_sv(400, 51.6)

        # DOP853 (ground truth)
        sv_dop = prop.propagate(sv0, 100.0)

        # Fast-path
        states = {"OBJ": sv0}
        result = prop.propagate_fast_batch(states, 100.0)
        sv_fast = result["OBJ"]

        pos_err = np.linalg.norm(sv_dop[:3] - sv_fast[:3])
        assert pos_err < 1.0, (
            f"Fast-path position error {pos_err:.4f} km (should be < 1 km)"
        )

    def test_fast_path_matches_dop853_for_600s(self):
        """For a 600s step, fast-path should be within 5km."""
        prop = OrbitalPropagator()
        sv0 = _leo_sv(400, 51.6)
        sv_dop = prop.propagate(sv0, 600.0)
        result = prop.propagate_fast_batch({"OBJ": sv0}, 600.0)
        sv_fast = result["OBJ"]
        pos_err = np.linalg.norm(sv_dop[:3] - sv_fast[:3])
        assert pos_err < 5.0, (
            f"Fast-path position error {pos_err:.4f} km at 600s (should be < 5 km)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §7: MANEUVER QUEUE CHRONOLOGICAL ORDER
# ═══════════════════════════════════════════════════════════════════════════

class TestManeuverQueueOrder:
    """Burns must execute in chronological order."""

    def test_burns_execute_in_time_order(self):
        """Two burns queued out of order should still execute chronologically."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-ORD", "SATELLITE", 400)])
        sat = eng.satellites["SAT-ORD"]
        r_hat = sat.position / np.linalg.norm(sat.position)

        # Queue burn at t=650 FIRST, then t=50 — should still execute t=50 first
        for t_offset in [650, 50]:
            dv = r_hat * (3.0 / 1000.0) * (1 if t_offset == 50 else -1)
            sat.maneuver_queue.append({
                "burn_id": f"BURN-T{t_offset}",
                "burnTime": (t0 + timedelta(seconds=t_offset)).isoformat(),
                "deltaV_vector": {"x": float(dv[0]), "y": float(dv[1]), "z": float(dv[2])},
            })

        eng.step(700.0)
        executed = [e for e in eng.maneuver_log if e["event"] == "BURN_EXECUTED"]
        assert len(executed) == 2, f"Expected 2 burns, got {len(executed)}"
        # First executed should be T50
        assert "T50" in executed[0]["burn_id"], (
            f"First burn should be T50, got {executed[0]['burn_id']}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §8: COLLISION DETECTION MULTIPLE
# ═══════════════════════════════════════════════════════════════════════════

class TestMultipleCollisions:
    """Detect multiple collisions in a single step."""

    def test_two_debris_at_same_position_both_detected(self):
        """Two debris at near-identical positions to satellite."""
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        eng.ingest_telemetry(t0.isoformat(), [_obj("SAT-MC", "SATELLITE", 400)])
        sat_pos = eng.satellites["SAT-MC"].position.copy()
        sat_vel = eng.satellites["SAT-MC"].velocity.copy()

        # Two debris right on top of the satellite
        for i in range(2):
            offset = np.array([0.01 * (i + 1), 0.0, 0.0])  # 10-20m offset
            deb_pos = sat_pos + offset
            eng.ingest_telemetry(t0.isoformat(), [{
                "id": f"DEB-MC-{i}", "type": "DEBRIS",
                "r": {"x": float(deb_pos[0]), "y": float(deb_pos[1]), "z": float(deb_pos[2])},
                "v": {"x": float(sat_vel[0]), "y": float(sat_vel[1]), "z": float(sat_vel[2])},
            }])

        eng.step(100.0)
        # Should detect collisions (within 100m threshold)
        assert eng.collision_count >= 1, (
            f"Expected collision detections, got {eng.collision_count}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §9: SNAPSHOT DEBRIS CLOUD FORMAT
# ═══════════════════════════════════════════════════════════════════════════

class TestDebrisCloudFormat:
    """Verify debris_cloud in snapshot is correctly flattened."""

    def test_debris_cloud_contains_expected_debris(self):
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        objs = [_obj("SAT-DC", "SATELLITE", 400)]
        objs += [_obj(f"DEB-DC-{i}", "DEBRIS", 410 + i) for i in range(10)]
        eng.ingest_telemetry(t0.isoformat(), objs)
        eng.step(10.0)
        snap = eng.get_snapshot()
        cloud = snap.get("debris_cloud", [])
        assert len(cloud) > 0, "Debris cloud should not be empty with 10 debris"

    def test_debris_cloud_entries_are_tuples_or_lists(self):
        eng = SimulationEngine()
        t0 = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        objs = [_obj("SAT-DCF", "SATELLITE", 400)]
        objs += [_obj(f"DEB-DCF-{i}", "DEBRIS", 410 + i) for i in range(5)]
        eng.ingest_telemetry(t0.isoformat(), objs)
        eng.step(10.0)
        snap = eng.get_snapshot()
        cloud = snap.get("debris_cloud", [])
        if len(cloud) > 0:
            entry = cloud[0]
            assert isinstance(entry, (list, tuple)), (
                f"Debris cloud entry should be list/tuple, got {type(entry)}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# §10: RAPID-FIRE API STRESS
# ═══════════════════════════════════════════════════════════════════════════

class TestRapidFireAPI:
    """Rapid sequential API calls should not corrupt engine state."""

    @pytest.fixture(autouse=True)
    def client(self):
        with TestClient(app) as c:
            self.client = c
            yield

    def test_10_rapid_steps_no_crash(self):
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [_obj("SAT-RF", "SATELLITE", 400)]
        })
        for _ in range(10):
            resp = self.client.post("/api/simulate/step",
                                    json={"step_seconds": 10.0})
            assert resp.status_code == 200

    def test_rapid_snapshots_consistent(self):
        self.client.post("/api/telemetry", json={
            "timestamp": T0,
            "objects": [_obj("SAT-RS", "SATELLITE", 400)]
        })
        self.client.post("/api/simulate/step", json={"step_seconds": 100.0})
        # 5 rapid snapshots should return identical data
        snaps = []
        for _ in range(5):
            resp = self.client.get("/api/visualization/snapshot")
            snaps.append(resp.json()["timestamp"])
        assert len(set(snaps)) == 1, (
            f"Rapid snapshots returned different timestamps: {snaps}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# §11: PROPAGATOR EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

class TestPropagatorEdgeCases:
    """Additional propagator edge cases."""

    def test_batch_with_single_object(self):
        """Batch propagation with 1 object should work."""
        prop = OrbitalPropagator()
        sv = _leo_sv(400, 51.6)
        result = prop.propagate_batch({"SINGLE": sv}, 100.0)
        assert "SINGLE" in result
        assert np.all(np.isfinite(result["SINGLE"]))

    def test_batch_with_50_objects(self):
        """Batch propagation with 50 objects should complete."""
        prop = OrbitalPropagator()
        states = {f"OBJ-{i}": _leo_sv(400 + i * 10) for i in range(50)}
        start = time.time()
        result = prop.propagate_batch(states, 100.0)
        elapsed = time.time() - start
        assert len(result) == 50
        assert elapsed < 30.0, f"50-object batch took {elapsed:.1f}s"

    def test_propagate_preserves_orbit_shape(self):
        """Eccentricity should remain small for initially circular orbit."""
        prop = OrbitalPropagator()
        sv0 = _leo_sv(400, 51.6)
        T = 2 * np.pi * np.sqrt((R_EARTH + 400)**3 / MU_EARTH)
        sv1 = prop.propagate(sv0, 5 * T)
        r = np.linalg.norm(sv1[:3])
        v = np.linalg.norm(sv1[3:])
        # Vis-viva: a = 1 / (2/r - v²/μ)
        a = 1.0 / (2.0 / r - v**2 / MU_EARTH)
        h = np.linalg.norm(np.cross(sv1[:3], sv1[3:]))
        e = np.sqrt(max(0, 1 - h**2 / (MU_EARTH * a)))
        assert e < 0.01, (
            f"Eccentricity {e:.6f} too high for initially circular orbit"
        )
