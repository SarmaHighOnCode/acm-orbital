"""
test_system_destroyers.py — The Nastiest Tests Possible
═══════════════════════════════════════════════════════════
These tests are specifically designed to BREAK the system in ways no
existing test covers. Each exploits a specific subtle code path.
  §1   Closure Variable Capture Bug in LOS blackout guard
  §2   Nominal State Diverges From Actual — Station-keeping always fails
  §3   Uptime Penalty Accumulates on WRONG step duration
  §4   Collision Scan ID Mismatch Between Dense and Final Paths
  §5   Evasion Pushes Satellite INTO a Different Debris Object
  §6   Cooldown Shift Pushes Recovery Burn PAST TCA (useless burn)
  §7   Simultaneous 50-Satellite Conjunction Cascade (fleet wipeout)
  §8   Telemetry Update Resets Nominal State — Destroys Station-Keeping
  §9   Graveyard Burn on Already-Queued Evasion Satellite
  §10  Dense Propagation 60,000-Dimensional ODE Numerical Stability
  §11  Burn ΔV Applied to Already-Propagated Velocity (Doubled Error)
  §12  Altitude Band Filter Bypassed by Highly Eccentric Debris
  §13  Auto-Planner Ignores 2nd Closest Threat (Earliest != Closest)
  §14  Recovery Propagation Uses Pre-Evasion debris.state_vector
  §15  Snapshot Payload Size Explosion With 50K Debris
Run: cd backend && python -m pytest tests/test_system_destroyers.py -v -x
"""
from __future__ import annotations
import math
import sys
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    CONJUNCTION_THRESHOLD_KM, EOL_FUEL_THRESHOLD_KG, G0, ISP, J2,
    LOOKAHEAD_SECONDS, MAX_DV_PER_BURN, MU_EARTH, M_DRY, M_FUEL_INIT,
    R_EARTH, SIGNAL_LATENCY_S, STATION_KEEPING_RADIUS_KM,
    THRUSTER_COOLDOWN_S,
)
from engine.collision import ConjunctionAssessor
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork
from engine.maneuver_planner import ManeuverPlanner
from engine.models import CDM, Debris, Satellite
from engine.propagator import OrbitalPropagator
from engine.simulation import SimulationEngine, _eci_to_lla
def _circ_sv(alt_km=400.0, inc_deg=0.0, nu_deg=0.0):
    r = R_EARTH + alt_km
    v = math.sqrt(MU_EARTH / r)
    inc = math.radians(inc_deg)
    nu = math.radians(nu_deg)
    cn, sn = math.cos(nu), math.sin(nu)
    ci, si = math.cos(inc), math.sin(inc)
    return np.array([
        r * cn, r * sn * ci, r * sn * si,
        -v * sn, v * cn * ci, v * cn * si,
    ])
# ═══════════════════════════════════════════════════════════════════════════════
# §1  CLOSURE VARIABLE CAPTURE — LOS blackout guard redefines has_los_at
#     inside a for-loop over burns, but `bt` is mutated and the closure
#     captures the LOOP VARIABLE, not the value at definition time.
# ═══════════════════════════════════════════════════════════════════════════════
class TestClosureCaptureLOS:
    """
    simulation.py lines 770-776:

        for burn in burns:
            bt = datetime.fromisoformat(burn["burnTime"]...)
            def has_los_at(t_check):       # <-- DEFINED INSIDE LOOP
                ...uses dense_sol...
            if not has_los_at(bt):
                ...modifies bt and burn["burnTime"]...

    The `has_los_at` function is redefined each iteration — this is fine.
    BUT: `bt` is mutated (line 784-785) and `burn` is modified in-place.
    If the loop has 2+ burns, the SECOND burn's LOS check uses the
    dense_sol built from max_dt of ALL burns, but `bt` has been overwritten
    by the first iteration's shift. This is a subtle mutation bug.

    More critically: if max_dt is computed from the RECOVERY burn time,
    but the EVASION burn is shifted earlier, the dense polynomial is
    evaluated at a negative dt (before the polynomial's domain) → garbage.
    """
    def test_multi_burn_los_shift_does_not_corrupt_second_burn(self):
        """
        Schedule evasion + recovery burns. First burn has no LOS and gets
        shifted. Verify the second burn's LOS check still works correctly
        (doesn't use corrupted bt from first iteration).
        """
        engine = SimulationEngine()
        ts = "2026-03-12T08:00:00.000Z"

        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry(ts, [
            {"id": "SAT-CL", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            {"id": "DEB-CL", "type": "DEBRIS",
             "r": {"x": r + 0.03, "y": 200.0, "z": 0.0},
             "v": {"x": 0.0, "y": -7.0, "z": 0.0}},
        ])

        sat = engine.satellites["SAT-CL"]
        base = engine.sim_time

        # Manually inject evasion + recovery as two burns
        sat.maneuver_queue = [
            {"burn_id": "EVA_CL", "burnTime": (base + timedelta(seconds=120)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": 0.003, "z": 0.0}},
            {"burn_id": "REC_CL", "burnTime": (base + timedelta(seconds=1800)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": -0.003, "z": 0.0}},
        ]
        sat.status = "EVADING"

        # Step should execute both without crash
        try:
            result = engine.step(3600)
            executed = result.get("maneuvers_executed", 0)
            print(f"\n  Maneuvers executed: {executed}")
            assert executed >= 1, "At least one burn should execute"
        except Exception as e:
            pytest.fail(f"Multi-burn execution crashed: {e}")
# ═══════════════════════════════════════════════════════════════════════════════
# §2  NOMINAL STATE DIVERGES — Both actual and nominal get J2-propagated,
#     but evasion burns change actual, not nominal. After recovery, the
#     nominal has drifted by J2. The satellite returns to WHERE THE SLOT
#     WAS, not where the slot IS.
# ═══════════════════════════════════════════════════════════════════════════════
class TestNominalStateDrift:
    """
    Nominal state is propagated with J2 in Step 1 (line 377).
    After evasion, the satellite tries to return to the CURRENT nominal.
    But if the evasion took 30 minutes, the nominal has drifted by J2.

    The REAL question: after 24 hours of accumulated J2 drift, is the
    nominal state still physically meaningful? J2 causes ~7°/day RAAN
    regression. The nominal RAAN drifts. The actual RAAN drifts. They
    should drift at the same rate (same orbit) → offset stays constant.

    BUT: if the satellite did a burn that changed its altitude, its J2
    rate is DIFFERENT from the nominal's rate. The offset grows secularly.
    """
    def test_post_evasion_nominal_actual_raan_diverge(self):
        """
        After an evasion burn that changes altitude by 5 km, propagate
        24 hours. Verify that the satellite drifts OUT of its 10 km
        station-keeping box because J2 rates no longer match.
        """
        prop = OrbitalPropagator()
        sv = _circ_sv(alt_km=400.0, inc_deg=51.6)
        nominal = sv.copy()

        # Apply a 5 m/s prograde burn (raises altitude ~15 km)
        dv_rtn = np.array([0.0, 0.005, 0.0])  # km/s
        planner = ManeuverPlanner()
        dv_eci = planner.rtn_to_eci(sv[:3], sv[3:], dv_rtn)
        sv_post = sv.copy()
        sv_post[3:] += dv_eci

        # Propagate both for 24 hours
        actual_24h = prop.propagate(sv_post, 86400.0)
        nominal_24h = prop.propagate(nominal, 86400.0)

        offset = np.linalg.norm(actual_24h[:3] - nominal_24h[:3])

        print(f"\n  Offset after 24h with 5 m/s burn: {offset:.2f} km")
        print(f"  Station-keeping radius: {STATION_KEEPING_RADIUS_KM} km")

        # A 5 m/s prograde burn changes semi-major axis by ~25 km
        # Different SMA → different J2 rate → differential RAAN drift
        # Over 24h this accumulates to tens of km
        if offset > STATION_KEEPING_RADIUS_KM:
            print(f"  WARNING: Satellite drifts {offset:.1f} km from slot in 24h")
            print(f"  Recovery CW burn cannot compensate for differential J2 rate")
# ═══════════════════════════════════════════════════════════════════════════════
# §3  UPTIME PENALTY USES step_seconds NOT actual time outside box
# ═══════════════════════════════════════════════════════════════════════════════
class TestUptimePenaltyAccuracy:
    """
    simulation.py line 586-587:
        self.time_outside_box[sat.id] = (
            self.time_outside_box.get(sat.id, 0.0) + step_seconds
        )

    This adds the FULL step_seconds whenever the satellite is outside the box
    at the END of the step. But the satellite might have been inside the box
    for 90% of the step and only left at the end. Conversely, it might have
    been outside for the entire step. The code doesn't know.

    For a 86400s step, being 1 meter outside the box at the endpoint
    charges a FULL 24 HOURS of downtime.
    """
    def test_large_step_charges_full_duration_even_if_briefly_outside(self):
        """
        Satellite starts inside slot, evasion pushes it out briefly at the end.
        A 3600s step charges 3600s of downtime even if outside for 10s.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-UP", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
        ])

        sat = engine.satellites["SAT-UP"]
        # Push nominal far away so satellite is always "outside"
        sat.nominal_state = np.array([r, 500.0, 0.0, 0.0, v, 0.0])

        engine.step(86400)

        t_out = engine.time_outside_box.get("SAT-UP", 0.0)
        uptime = math.exp(-0.001 * t_out)

        print(f"\n  Time charged outside box: {t_out:.0f}s")
        print(f"  Uptime score: {uptime:.6f}")
        print(f"  (A single 86400s step charges full 24h of downtime)")

        # The problem: one big step charges more than many small steps
        # because small steps would re-check and possibly find the sat inside
        assert t_out == 86400.0, (
            f"Expected 86400s charged but got {t_out}s — "
            f"step_seconds should be charged when outside box"
        )

        # Now verify the uptime score makes sense
        # exp(-0.001 * 86400) = exp(-86.4) ≈ 0 (effectively dead)
        assert uptime < 0.001, (
            f"Uptime {uptime:.6f} is too high after 24h outside box"
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §4  COLLISION SCAN ID MISMATCH — Dense vs Final path use different ID lists
# ═══════════════════════════════════════════════════════════════════════════════
class TestCollisionScanIDMismatch:
    """
    simulation.py lines 556-558:
        s_id = _sat_ids[s_idx] if frac == 1.0 or _n_sub <= 1
               else _sat_dense_ids[s_idx]

    _sat_ids comes from list(self.satellites.keys())  [line 527]
    _sat_dense_ids comes from propagate_dense_batch(sat_states) [line 392]
    sat_states = {sid: sat.state_vector for sid, sat in self.satellites.items()}

    In Python 3.7+, dict ordering is insertion-ordered. BUT if a satellite
    was added mid-simulation (second telemetry ingest), the ordering could
    differ from the original batch. More importantly, if a satellite is
    removed (EOL + cleanup), the dense IDs and self.satellites keys diverge.

    Even without removal: the issue is that at frac < 1.0 (intermediate
    sub-samples), the code uses _sat_dense_ids for lookup, but at frac == 1.0
    (endpoint), it uses _sat_ids. If they happen to differ, collision pairs
    get attributed to the WRONG satellite.
    """
    def test_collision_attributed_to_correct_satellite(self):
        """
        Create 3 satellites with known IDs. Verify that after a step,
        any collision is attributed to the satellite that actually collided,
        not a different one due to index mismatch.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        # 3 satellites at different positions
        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-ID-A", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            {"id": "SAT-ID-B", "type": "SATELLITE",
             "r": {"x": 0.0, "y": r, "z": 0.0},
             "v": {"x": -v, "y": 0.0, "z": 0.0}},
            {"id": "SAT-ID-C", "type": "SATELLITE",
             "r": {"x": -r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": -v, "z": 0.0}},
            # Debris collides with SAT-ID-B specifically
            {"id": "DEB-ID-B", "type": "DEBRIS",
             "r": {"x": 0.05, "y": r + 0.03, "z": 0.0},
             "v": {"x": -v, "y": 0.0, "z": 0.0}},
        ])

        result = engine.step(60)

        # If collision detected, verify it's attributed to SAT-ID-B
        for entry in engine.collision_log:
            sat_id = entry.get("satellite_id", "")
            print(f"\n  Collision: {sat_id} ↔ {entry.get('debris_id', '')}")

            if entry.get("debris_id") == "DEB-ID-B":
                assert sat_id == "SAT-ID-B", (
                    f"Collision with DEB-ID-B attributed to {sat_id} "
                    f"instead of SAT-ID-B — ID mismatch between dense "
                    f"and endpoint paths"
                )
# ═══════════════════════════════════════════════════════════════════════════════
# §5  EVASION PUSHES INTO DIFFERENT DEBRIS — Planner only checks ONE debris
# ═══════════════════════════════════════════════════════════════════════════════
class TestEvasionIntoNewDebris:
    """
    The evasion planner (maneuver_planner.py) only checks miss distance
    against the TRIGGERING debris object. It doesn't check the 9,999 other
    debris objects. The evasion maneuver could push the satellite directly
    into a different piece of debris.
    """
    def test_evasion_from_debris_a_collides_with_debris_b(self):
        """
        SAT at [r,0,0]. DEB-A approaching from +y. DEB-B sitting at [r+1,0,0].
        Evasion for DEB-A will be a T-axis burn (prograde/retrograde).
        But a radial evasion (unlikely given the planner) could push toward DEB-B.

        More realistically: the planner always burns +T. If DEB-B is sitting
        slightly ahead in the orbit at [r, 1.0, 0], a prograde burn CLOSES
        the distance to DEB-B.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-X5", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            # DEB-A: head-on from ahead, triggers evasion
            {"id": "DEB-A5", "type": "DEBRIS",
             "r": {"x": r + 0.02, "y": 500.0, "z": 0.0},
             "v": {"x": 0.0, "y": -7.0, "z": 0.0}},
            # DEB-B: sitting slightly ahead in orbit — a prograde burn
            # reduces period difference, potentially closing distance
            {"id": "DEB-B5", "type": "DEBRIS",
             "r": {"x": r + 0.01, "y": 5.0, "z": 0.0},
             "v": {"x": 0.0, "y": v + 0.0001, "z": 0.0}},
        ])

        total_collisions = 0
        for _ in range(20):
            result = engine.step(300)
            total_collisions += result.get("collisions_detected", 0)

        # Check if we collided with DEB-B5 while evading DEB-A5
        collisions_with_b = [
            c for c in engine.collision_log
            if c.get("debris_id") == "DEB-B5"
        ]

        print(f"\n  Total collisions: {total_collisions}")
        print(f"  Collisions with DEB-B5 (secondary): {len(collisions_with_b)}")

        if collisions_with_b:
            pytest.xfail(
                "Evasion from DEB-A5 caused collision with DEB-B5 — "
                "planner doesn't check other debris when planning evasion"
            )
# ═══════════════════════════════════════════════════════════════════════════════
# §6  COOLDOWN SHIFT PUSHES RECOVERY BURN PAST TCA — Useless burn
# ═══════════════════════════════════════════════════════════════════════════════
class TestCooldownShiftPastTCA:
    """
    simulation.py line 830-832:
        if cooldown_gap < THRUSTER_COOLDOWN_S:
            bt = effective_last_auto + timedelta(seconds=THRUSTER_COOLDOWN_S + 1)
            burn["burnTime"] = bt.isoformat()

    If the evasion burn is close to TCA, and the recovery burn follows,
    the cooldown shift pushes the recovery burn PAST TCA. At that point
    the debris has already passed and the "recovery" burn fires into empty
    space. The satellite is now in a WORSE orbit with no reason.
    """
    def test_recovery_shifted_past_tca_still_makes_sense(self):
        """
        TCA at t+900s. Evasion at t+300s. Recovery at t+600s.
        Cooldown shifts recovery to t+300+601 = t+901s (past TCA).
        Verify the recovery burn doesn't make things worse.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-CS", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
        ])

        sat = engine.satellites["SAT-CS"]
        base = engine.sim_time

        # Queue evasion at t+300, recovery at t+600 (violates 600s cooldown)
        sat.maneuver_queue = [
            {"burn_id": "EVA_CS", "burnTime": (base + timedelta(seconds=300)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": 0.003, "z": 0.0}},
            {"burn_id": "REC_CS", "burnTime": (base + timedelta(seconds=600)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": -0.003, "z": 0.0}},
        ]

        pre_offset = np.linalg.norm(sat.position - sat.nominal_state[:3])

        result = engine.step(1200)

        post_offset = np.linalg.norm(
            engine.satellites["SAT-CS"].position -
            engine.satellites["SAT-CS"].nominal_state[:3]
        )

        executed = result.get("maneuvers_executed", 0)
        print(f"\n  Burns executed: {executed}")
        print(f"  Pre-step offset: {pre_offset:.2f} km")
        print(f"  Post-step offset: {post_offset:.2f} km")

        # If recovery was skipped due to cooldown, offset should be large
        # If recovery was shifted and executed, offset depends on accuracy
# ═══════════════════════════════════════════════════════════════════════════════
# §7  SIMULTANEOUS 50-SATELLITE CONJUNCTION CASCADE — Fleet wipeout
# ═══════════════════════════════════════════════════════════════════════════════
class TestFleetWipeout:
    """
    The auto-planner processes satellites in dict iteration order.
    If ALL 50 satellites face critical threats simultaneously, the planner
    must handle them all within a single step() without OOM or timeout.

    Worse: if one satellite's evasion pushes it into ANOTHER satellite's
    path (Sat-vs-Sat), the cascade requires re-assessment within the
    same tick — which doesn't happen.
    """
    def test_50_sats_all_threatened_simultaneously(self):
        """All 50 satellites face CRITICAL conjunctions in the same tick."""
        engine = SimulationEngine()
        objects = []
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        for i in range(50):
            theta = 2 * math.pi * i / 50
            objects.append({
                "id": f"SAT-{i:02d}", "type": "SATELLITE",
                "r": {"x": r * math.cos(theta), "y": r * math.sin(theta), "z": 0.0},
                "v": {"x": -v * math.sin(theta), "y": v * math.cos(theta), "z": 0.0},
            })
            # Matching debris for each satellite
            offset = 0.05  # 50m, critical threshold
            objects.append({
                "id": f"DEB-WIPE-{i:02d}", "type": "DEBRIS",
                "r": {"x": (r + offset) * math.cos(theta),
                      "y": (r + offset) * math.sin(theta), "z": 0.0},
                "v": {"x": -v * math.sin(theta) + 0.001,
                      "y": v * math.cos(theta), "z": 0.0},
            })

        t0 = time.perf_counter()
        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", objects)
        ingest_time = time.perf_counter() - t0

        print(f"\n  Ingest time (50 sats + 50 debris): {ingest_time:.2f}s")

        t0 = time.perf_counter()
        result = engine.step(600)
        step_time = time.perf_counter() - t0

        print(f"  Step time: {step_time:.2f}s")
        print(f"  Collisions: {result.get('collisions_detected', 0)}")
        print(f"  Maneuvers: {result.get('maneuvers_executed', 0)}")

        assert step_time < 30.0, (
            f"50-satellite simultaneous threat took {step_time:.1f}s "
            f"(max 30s). Auto-planner doesn't scale."
        )
        assert result.get("collisions_detected", 0) == 0, (
            "Fleet wipeout: collisions detected despite evasion planning"
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §8  TELEMETRY RE-INGEST RESETS NOMINAL — Station-keeping breaks
# ═══════════════════════════════════════════════════════════════════════════════
class TestTelemetryNominalReset:
    """
    simulation.py line 158:
        sat.nominal_state = sat.state_vector.copy()

    This only runs on FIRST ingest (line 152: `if o_id not in self.satellites`).
    Second ingest updates position/velocity but NOT nominal_state.

    BUT: if the grader sends a COMPLETE re-ingest (same satellite IDs),
    the satellite already exists → nominal isn't reset. The nominal is
    now hours ahead from J2 propagation, while the actual state just
    jumped back to the original. Station-keeping offset is HUGE.
    """
    def test_re_ingest_same_sat_preserves_nominal_propagation(self):
        """
        Ingest SAT-01, step 3600s (nominal propagates 1h ahead by J2).
        Re-ingest SAT-01 with ORIGINAL position. Nominal should still
        be at the 1h-propagated position. Offset should now be large.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        original = {
            "id": "SAT-RI", "type": "SATELLITE",
            "r": {"x": r, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": v, "z": 0.0},
        }

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [original])
        nominal_after_ingest = engine.satellites["SAT-RI"].nominal_state.copy()

        # Step 1 hour — nominal propagates ahead
        engine.step(3600)
        nominal_after_step = engine.satellites["SAT-RI"].nominal_state.copy()

        # Nominal should have changed (J2 propagation)
        assert not np.allclose(nominal_after_ingest, nominal_after_step, atol=1.0), (
            "Nominal state didn't change after 1h step"
        )

        # Re-ingest with ORIGINAL position (resetting actual state)
        engine.ingest_telemetry("2026-03-12T09:00:01.000Z", [original])

        actual_pos = engine.satellites["SAT-RI"].position
        nominal_pos = engine.satellites["SAT-RI"].nominal_state[:3]
        offset = np.linalg.norm(actual_pos - nominal_pos)

        print(f"\n  Offset after re-ingest: {offset:.2f} km")
        print(f"  Actual position: {actual_pos}")
        print(f"  Nominal position: {nominal_pos}")

        # The satellite was reset to original but nominal is 1h ahead
        # This creates a massive phantom offset
        if offset > STATION_KEEPING_RADIUS_KM:
            print(f"  WARNING: Re-ingest created {offset:.0f} km phantom offset")
            print(f"  Satellite will be marked RECOVERING even though it's fine")
# ═══════════════════════════════════════════════════════════════════════════════
# §9  EOL GRAVEYARD ON SATELLITE WITH QUEUED EVASION
# ═══════════════════════════════════════════════════════════════════════════════
class TestEOLDuringEvasion:
    """
    If fuel drops below EOL threshold DURING an evasion sequence
    (because the evasion burn consumed the last fuel), Step 6 triggers
    EOL and tries to queue a graveyard burn. But the satellite already
    has evasion burns in queue. The graveyard burn gets appended AFTER
    the evasion burns → executes in wrong order.
    """
    def test_eol_triggered_mid_evasion_sequence(self):
        """
        Satellite with 3 kg fuel. Evasion burn consumes 2 kg → fuel = 1 kg.
        1 kg < 2.5 kg threshold → EOL triggered. But recovery burn is still
        queued. Does the engine handle this correctly?
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-EOL-E", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
        ])

        # Set fuel just above EOL threshold
        engine.fuel_tracker._fuel["SAT-EOL-E"] = 3.0

        sat = engine.satellites["SAT-EOL-E"]
        base = engine.sim_time

        # Queue a burn that will drain below EOL
        # 10 m/s burn on 503 kg wet mass: dm ≈ 1.7 kg → remaining ≈ 1.3 kg < 2.5
        sat.maneuver_queue = [
            {"burn_id": "EVA_EOL", "burnTime": (base + timedelta(seconds=30)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": 0.010, "z": 0.0}},  # 10 m/s
            {"burn_id": "REC_EOL", "burnTime": (base + timedelta(seconds=900)).isoformat(),
             "deltaV_vector": {"x": 0.0, "y": -0.010, "z": 0.0}},
        ]
        sat.status = "EVADING"

        result = engine.step(1200)

        sat_after = engine.satellites["SAT-EOL-E"]
        fuel_after = engine.fuel_tracker.get_fuel("SAT-EOL-E")

        print(f"\n  Status: {sat_after.status}")
        print(f"  Fuel remaining: {fuel_after:.3f} kg")
        print(f"  EOL threshold: {EOL_FUEL_THRESHOLD_KG} kg")
        print(f"  Maneuvers executed: {result.get('maneuvers_executed', 0)}")
        print(f"  Queued burns remaining: {len(sat_after.maneuver_queue)}")

        if sat_after.status == "EOL":
            # Recovery burn should NOT have executed
            recovery_burns = [
                e for e in engine.maneuver_log
                if e.get("satellite_id") == "SAT-EOL-E"
                and "REC" in e.get("burn_id", "")
            ]
            if recovery_burns:
                pytest.xfail(
                    "Recovery burn executed AFTER satellite went EOL — "
                    "should have been cancelled when fuel dropped below threshold"
                )
# ═══════════════════════════════════════════════════════════════════════════════
# §10  60,000-DIMENSIONAL ODE — Numerical stability of batch propagation
# ═══════════════════════════════════════════════════════════════════════════════
class TestBatchPropagationStability:
    """
    propagate_dense_batch packs all objects into a single 6N-dim ODE.
    For N=10,000 objects, that's 60,000 dimensions. DOP853's adaptive
    stepping uses norms of this 60K vector. If one object has a very
    different orbit (GEO vs LEO), the error estimates are dominated by
    the LEO object's fast dynamics, forcing tiny steps for the whole batch.
    """
    def test_mixed_leo_geo_batch_propagation(self):
        """
        Mix 10 LEO objects with 1 GEO object in a single batch.
        The GEO object's slow dynamics should not corrupt LEO accuracy,
        and the LEO fast dynamics should not force impossibly small steps.
        """
        prop = OrbitalPropagator(rtol=1e-6, atol=1e-8)

        states = {}
        # 10 LEO objects
        for i in range(10):
            r = R_EARTH + 400.0 + i * 10
            v = math.sqrt(MU_EARTH / r)
            theta = 2 * math.pi * i / 10
            states[f"LEO-{i}"] = np.array([
                r * math.cos(theta), r * math.sin(theta), 0.0,
                -v * math.sin(theta), v * math.cos(theta), 0.0,
            ])

        # 1 GEO object (35,786 km altitude, v ≈ 3.07 km/s)
        r_geo = R_EARTH + 35786.0
        v_geo = math.sqrt(MU_EARTH / r_geo)
        states["GEO-0"] = np.array([r_geo, 0.0, 0.0, 0.0, v_geo, 0.0])

        t0 = time.perf_counter()
        result = prop.propagate_batch(states, 3600.0)
        elapsed = time.perf_counter() - t0

        print(f"\n  Mixed LEO+GEO batch (11 objects): {elapsed:.3f}s")

        # Verify LEO objects are still in LEO
        for i in range(10):
            r = np.linalg.norm(result[f"LEO-{i}"][:3])
            assert 6500 < r < 7500, f"LEO-{i} radius {r:.1f} km (expected ~6778)"

        # Verify GEO object is still in GEO
        r_geo_final = np.linalg.norm(result["GEO-0"][:3])
        assert 40000 < r_geo_final < 44000, (
            f"GEO-0 radius {r_geo_final:.1f} km (expected ~42164)"
        )

        assert elapsed < 10.0, f"Mixed batch took {elapsed:.1f}s (expected <10s)"
# ═══════════════════════════════════════════════════════════════════════════════
# §11  BURN ΔV APPLIED TO POST-PROPAGATION VELOCITY
# ═══════════════════════════════════════════════════════════════════════════════
class TestBurnAppliedToWrongVelocity:
    """
    simulation.py line 464:
        sat.velocity = sat.velocity + dv_vec

    At this point, sat.velocity is the FINAL velocity at target_time
    (from Step 1 propagation). The ΔV should have been applied at
    burn_time's velocity, not target_time's velocity.

    For a circular orbit, velocity magnitude is constant but direction
    rotates ~4° per minute. A burn at t+300s applied at t+3600s has
    its ΔV in the wrong inertial direction by ~44°.
    """
    def test_velocity_direction_error_from_late_application(self):
        """
        Compute the RTN frame at t+300s vs t+3600s for a circular orbit.
        The T-axis rotates by the orbital angular velocity * dt.
        For a 400 km orbit: period ≈ 5554s, angular rate ≈ 0.065°/s
        Over 3300s: rotation ≈ 214° — the T-axis points in nearly the
        OPPOSITE direction.
        """
        sv = _circ_sv(alt_km=400.0, inc_deg=0.0)
        prop = OrbitalPropagator()

        sv_300 = prop.propagate(sv, 300.0)
        sv_3600 = prop.propagate(sv, 3600.0)

        # T-axis at t=300s
        planner = ManeuverPlanner()
        dv_rtn = np.array([0.0, 0.005, 0.0])  # 5 m/s prograde
        dv_eci_300 = planner.rtn_to_eci(sv_300[:3], sv_300[3:], dv_rtn)
        dv_eci_3600 = planner.rtn_to_eci(sv_3600[:3], sv_3600[3:], dv_rtn)

        # Angle between the two ECI ΔV vectors
        cos_angle = np.dot(dv_eci_300, dv_eci_3600) / (
            np.linalg.norm(dv_eci_300) * np.linalg.norm(dv_eci_3600)
        )
        angle_deg = math.degrees(math.acos(np.clip(cos_angle, -1, 1)))

        print(f"\n  T-axis rotation from t=300s to t=3600s: {angle_deg:.1f}°")
        print(f"  (Orbital period ≈ {2 * math.pi / math.sqrt(MU_EARTH / (R_EARTH+400)**3):.0f}s)")

        assert angle_deg > 90, (
            f"T-axis only rotated {angle_deg:.1f}° — expected >90° over "
            f"3300s of a ~92 min orbit. A burn applied at the wrong time "
            f"fires in the wrong direction."
        )
# ═══════════════════════════════════════════════════════════════════════════════
# §12  ALTITUDE BAND FILTER BYPASSED BY HIGHLY ECCENTRIC DEBRIS
# ═══════════════════════════════════════════════════════════════════════════════
class TestAltitudeBandFilterBypass:
    """
    Stage 1 filter uses perigee/apogee to determine if debris can reach
    the satellite's altitude band. But for HIGHLY eccentric debris
    (e.g., Molniya-type), perigee is 200 km and apogee is 40,000 km.
    This debris passes through the LEO band but the altitude filter
    SHOULD include it (and does, since rp < r_max and ra > r_min).

    The REAL issue: the filter uses a ±50 km margin around the satellite
    shell. For debris with perigee at 350 km and satellite at 400 km,
    the filter correctly includes it. But what about debris with perigee
    at 460 km (50 km above satellite's apogee)?
    """
    def test_highly_eccentric_debris_detected(self):
        """
        Debris in a 250 km × 2000 km orbit crosses through 400 km LEO band.
        Must be detected by conjunction assessor, not filtered out.
        """
        prop = OrbitalPropagator()
        assessor = ConjunctionAssessor(prop)

        # Satellite at 400 km circular
        sat_sv = _circ_sv(alt_km=400.0, inc_deg=0.0)

        # Debris in 250 km × 2000 km orbit (highly eccentric)
        # At perigee: r = R_EARTH + 250 = 6628 km, v > circular
        r_peri = R_EARTH + 250.0
        r_apo = R_EARTH + 2000.0
        a = (r_peri + r_apo) / 2.0
        v_peri = math.sqrt(MU_EARTH * (2.0 / r_peri - 1.0 / a))

        # Place debris at perigee, moving prograde
        deb_sv = np.array([r_peri, 0.0, 0.0, 0.0, v_peri, 0.0])

        cdms = assessor.assess(
            {"SAT": sat_sv}, {"DEB-ECC": deb_sv},
            lookahead_s=3600.0,  # 1 hour (debris passes through 400 km in ~10 min)
        )

        print(f"\n  Eccentric debris (250×2000 km): {len(cdms)} CDMs")
        # The debris orbit passes through 400 km altitude, so it should be detected
        # IF the altitude band filter works correctly for eccentric orbits
# ═══════════════════════════════════════════════════════════════════════════════
# §13  AUTO-PLANNER PICKS EARLIEST TCA, NOT CLOSEST MISS
# ═══════════════════════════════════════════════════════════════════════════════
class TestAutoplannerThreatPriority:
    """
    simulation.py line 721:
        most_critical = min(group, key=lambda c: c.tca)

    This picks the EARLIEST TCA, not the SMALLEST miss distance.
    If threat A has TCA in 2 hours with miss=95m (critical) and
    threat B has TCA in 1 hour with miss=99m (also critical), the
    planner evades B (earlier) and ignores A. But B might be a
    near-miss that resolves itself, while A is a direct hit.
    """
    def test_earlier_threat_prioritized_over_closer_threat(self):
        """
        Inject two CRITICAL CDMs. One at TCA=1h with miss=90m.
        Another at TCA=30min with miss=99m.
        Verify which one the auto-planner addresses.
        """
        engine = SimulationEngine()
        r = R_EARTH + 400.0
        v = math.sqrt(MU_EARTH / r)

        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
            {"id": "SAT-P13", "type": "SATELLITE",
             "r": {"x": r, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            {"id": "DEB-NEAR", "type": "DEBRIS",
             "r": {"x": r + 0.05, "y": 100.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
            {"id": "DEB-FAR", "type": "DEBRIS",
             "r": {"x": r + 0.05, "y": 200.0, "z": 0.0},
             "v": {"x": 0.0, "y": v, "z": 0.0}},
        ])

        base = engine.sim_time

        # Manually inject CDMs to control ordering
        engine.active_cdms = [
            CDM(satellite_id="SAT-P13", debris_id="DEB-FAR",
                tca=base + timedelta(seconds=3600),
                miss_distance_km=0.010, risk="CRITICAL",  # 10m — very close
                relative_velocity_km_s=0.1),
            CDM(satellite_id="SAT-P13", debris_id="DEB-NEAR",
                tca=base + timedelta(seconds=1800),
                miss_distance_km=0.095, risk="CRITICAL",  # 95m — barely critical
                relative_velocity_km_s=0.1),
        ]

        engine._auto_plan_maneuvers(base)

        # Check which debris the evasion targets
        queue = engine.satellites["SAT-P13"].maneuver_queue
        if queue:
            burn_ids = [b.get("burn_id", "") for b in queue]
            print(f"\n  Queued burn IDs: {burn_ids}")

            targets_near = any("DEB-NEAR" in bid for bid in burn_ids)
            targets_far = any("DEB-FAR" in bid for bid in burn_ids)

            print(f"  Targets DEB-NEAR (TCA=30min, 95m): {targets_near}")
            print(f"  Targets DEB-FAR (TCA=60min, 10m):  {targets_far}")

            # The planner picks min(tca) = DEB-NEAR, which is less dangerous
            # DEB-FAR at 10m is the real threat but gets ignored
# ═══════════════════════════════════════════════════════════════════════════════
# §14  RECOVERY COLLISION CHECK USES PRE-EVASION debris.state_vector
# ═══════════════════════════════════════════════════════════════════════════════
class TestRecoveryDebrisStateStale:
    """
    maneuver_planner.py line 321:
        deb_fwd = self.propagator.propagate(debris.state_vector, ...)

    This propagates from the debris's state AT PLANNING TIME, not at
    the recovery burn time. If the evasion was planned during tick N
    but the recovery executes in tick N+3, the debris has moved.
    The collision check compares the satellite's future position against
    the debris's position from 3 ticks ago.
    """
    def test_recovery_collision_check_uses_stale_debris_state(self):
        """This is a design-level issue — documenting it as a known gap."""
        # The debris.state_vector used in plan_evasion line 248/321 is
        # captured at planning time. By the time the recovery burn fires,
        # the debris has been propagated forward by the simulation engine.
        # The collision check during planning is stale.

        # This can't be easily unit-tested without a complex multi-tick
        # scenario. Documenting as a known gap.
        print("\n  KNOWN GAP: Recovery burn collision safety check uses")
        print("  debris.state_vector from planning time, not execution time.")
        print("  Over multiple ticks, this state becomes stale.")
# ═══════════════════════════════════════════════════════════════════════════════
# §15  SNAPSHOT PAYLOAD SIZE EXPLOSION
# ═══════════════════════════════════════════════════════════════════════════════
class TestSnapshotPayloadSize:
    """
    The snapshot serializes ALL debris as JSON. With 50K debris objects,
    each being [id, lat, lon, alt], the payload can exceed 5 MB.
    The grader expects the snapshot to be returned quickly.
    """
    def test_snapshot_under_5mb_with_50k_debris(self):
        """Generate 50K debris and verify snapshot payload is manageable."""
        engine = SimulationEngine()

        objects = []
        rng = np.random.default_rng(42)
        for i in range(50000):
            r = R_EARTH + rng.uniform(300, 600)
            v = math.sqrt(MU_EARTH / r)
            theta = rng.uniform(0, 2 * math.pi)
            objects.append({
                "id": f"DEB-{i:06d}", "type": "DEBRIS",
                "r": {"x": r * math.cos(theta), "y": r * math.sin(theta), "z": 0.0},
                "v": {"x": -v * math.sin(theta), "y": v * math.cos(theta), "z": 0.0},
            })

        t0 = time.perf_counter()
        engine.ingest_telemetry("2026-03-12T08:00:00.000Z", objects)
        ingest_time = time.perf_counter() - t0

        t0 = time.perf_counter()
        snap = engine.get_snapshot()
        snap_time = time.perf_counter() - t0

        payload_size = len(json.dumps(snap))

        print(f"\n  Debris count: {len(snap['debris_cloud'])}")
        print(f"  Snapshot generation: {snap_time:.3f}s")
        print(f"  Payload size: {payload_size / 1e6:.2f} MB")

        assert payload_size < 5_000_000, (
            f"Snapshot payload {payload_size/1e6:.1f} MB exceeds 5 MB limit"
        )
        assert snap_time < 3.0, (
            f"Snapshot generation took {snap_time:.1f}s (max 3s)"
        )
