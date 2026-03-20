"""
simulation.py — SimulationEngine (Master Orchestrator)
══════════════════════════════════════════════════════
THE CONTRACT: This is the single entry point the API layer uses.
Dev 2 calls these methods.  Dev 1 implements them.
Neither touches the other's internals.
Owner: Dev 1 (Physics Engine)

Tick sequence (PRD §4.7):
    1. Propagate all objects (vectorised DOP853 batch — O(N) solver calls)
    2. Execute scheduled maneuvers (apply ΔV, deduct fuel, enforce 600 s cooldown)
    3. Run conjunction assessment (4-stage KDTree pipeline — O(S log D + k·F))
       + instantaneous collision scan at current positions (O(S log D) KDTree)
    4. Update station-keeping status (10 km nominal slot check)
    5. Auto-plan maneuvers (queue evasion+recovery for CRITICAL CDMs)
    6. Check EOL thresholds (fuel ≤ 2.5 kg → graveyard)
    7. Advance simulation clock
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.spatial import KDTree as _KDTree

from config import (
    CONJUNCTION_THRESHOLD_KM,
    EOL_FUEL_THRESHOLD_KG,
    STATION_KEEPING_RADIUS_KM,
    SIGNAL_LATENCY_S,
    THRUSTER_COOLDOWN_S,
    ISP,
    G0,
    M_DRY,
    MU_EARTH,
    R_EARTH,
    RTOL,
    ATOL,
)
from engine.models import Satellite, Debris, CDM
from engine.propagator import OrbitalPropagator
from engine.collision import ConjunctionAssessor
from engine.maneuver_planner import ManeuverPlanner
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork

logger = logging.getLogger("acm.engine.simulation")


_J2000_EPOCH = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_WGS84_F = 1.0 / 298.257223563   # WGS84 flattening


def _gmst_rad(sim_time: datetime) -> float:
    """Compute Greenwich Mean Sidereal Time in radians."""
    dt_seconds = (sim_time - _J2000_EPOCH).total_seconds()
    gmst_deg = 280.46061837 + 360.98564736629 * (dt_seconds / 86400.0)
    return np.radians(gmst_deg % 360.0)


def _eci_to_lla(position: np.ndarray, sim_time: datetime) -> tuple[float, float, float]:
    """Convert ECI position [x, y, z] km to (lat_deg, lon_deg, alt_km).

    Accounts for Earth rotation (GMST) to obtain geodetic longitude, and
    uses WGS84 ellipsoidal approximation for altitude.
    """
    x, y, z = position
    r = np.linalg.norm(position)
    lat_rad = np.arcsin(np.clip(z / r, -1.0, 1.0))
    lat_deg = float(np.degrees(lat_rad))

    # Longitude = Right Ascension − GMST
    ra = np.arctan2(y, x)
    lon_rad = ra - _gmst_rad(sim_time)
    lon_deg = float(np.degrees(lon_rad))
    lon_deg = ((lon_deg + 180.0) % 360.0) - 180.0

    # WGS84 ellipsoidal local Earth radius: R(lat) ≈ R_eq * (1 − f·sin²(lat))
    r_local = 6378.137 * (1.0 - _WGS84_F * np.sin(lat_rad) ** 2)
    alt_km = r - r_local

    return lat_deg, lon_deg, alt_km


def _eci_to_lla_batch(positions: np.ndarray, sim_time: datetime) -> np.ndarray:
    """Convert a batch of ECI positions [x, y, z] km to (lat, lon, alt).

    Args:
        positions: shape (N, 3) in km.
        sim_time:  Current simulation time (UTC, tz-aware).

    Returns:
        np.ndarray of shape (N, 3) where columns are (lat_deg, lon_deg, alt_km).
    """
    if positions.size == 0:
        return np.empty((0, 3))

    r = np.linalg.norm(positions, axis=1)
    r_safe = np.where(r == 0, 1.0, r)

    # Geocentric latitude
    lat_rad = np.arcsin(np.clip(positions[:, 2] / r_safe, -1.0, 1.0))
    lat_deg = np.degrees(lat_rad)

    # Geodetic longitude = Right Ascension − GMST
    ra = np.arctan2(positions[:, 1], positions[:, 0])
    gmst = _gmst_rad(sim_time)
    lon_deg = np.degrees(ra - gmst)
    lon_deg = ((lon_deg + 180.0) % 360.0) - 180.0

    # WGS84 ellipsoidal altitude
    r_local = 6378.137 * (1.0 - _WGS84_F * np.sin(lat_rad) ** 2)
    alt_km = r - r_local

    return np.column_stack([lat_deg, lon_deg, alt_km])


class SimulationEngine:
    """Master orchestrator for the ACM orbital debris collision-avoidance simulation.

    Maintains the simulation clock, all satellite and debris state, and coordinates
    the propagation, collision-detection, maneuver-planning, and fuel subsystems.

    Thread-safety note: This class is designed for single-threaded use.  The
    ConjunctionAssessor temporarily mutates propagator tolerances during debris
    propagation; concurrent step() calls would require per-thread propagator
    instances.
    """

    def __init__(self) -> None:
        # Timezone-aware UTC clock — datetime.utcnow() is deprecated in Python 3.12+
        self.sim_time: datetime = datetime.now(timezone.utc)
        self._time_set_by_telemetry: bool = False  # guards backward-time check
        self.satellites: dict[str, Satellite] = {}
        self.debris: dict[str, Debris] = {}
        self.active_cdms: list[CDM] = []
        self.collision_log: list[dict] = []
        self.maneuver_log: list[dict] = []
        self.collision_count: int = 0

        # Uptime tracking — seconds each satellite spends outside station-keeping box
        self.time_outside_box: dict[str, float] = {}

        # Subsystem components
        self.propagator    = OrbitalPropagator(rtol=RTOL, atol=ATOL)
        self.assessor      = ConjunctionAssessor(self.propagator)
        self.planner       = ManeuverPlanner(propagator=self.propagator)
        self.fuel_tracker  = FuelTracker()
        self.gs_network    = GroundStationNetwork()

        logger.info("SimulationEngine initialized at %s", self.sim_time.isoformat())

    # ── THE CONTRACT (API Layer calls these) ──────────────────────────────────

    def ingest_telemetry(self, timestamp: str, objects: list) -> dict:
        """Ingest raw telemetry and update / register orbital objects.

        Called by: POST /api/telemetry

        Args:
            timestamp: ISO-8601 epoch string (e.g. "2025-01-01T00:00:00Z").
            objects:   List of TelemetryObject Pydantic models (from API).

        Returns:
            ACK payload with processed_count and active_cdm_warnings.
        """
        new_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        # Never allow simulation clock to go backward (only after first ingest)
        if self._time_set_by_telemetry and new_time < self.sim_time:
            logger.warning(
                "TELEMETRY | Backward timestamp %s < %s — keeping current time",
                new_time.isoformat(), self.sim_time.isoformat(),
            )
        else:
            self.sim_time = new_time
            self._time_set_by_telemetry = True

        for obj in objects:
            # Handle both dict (from tests) and Pydantic models (from API)
            if hasattr(obj, "r"):
                r_obj, v_obj = obj.r, obj.v
                o_id, o_type = obj.id, obj.type
                pos = np.array([r_obj.x, r_obj.y, r_obj.z])
                vel = np.array([v_obj.x, v_obj.y, v_obj.z])
            else:
                pos = np.array([obj["r"]["x"], obj["r"]["y"], obj["r"]["z"]])
                vel = np.array([obj["v"]["x"], obj["v"]["y"], obj["v"]["z"]])
                o_id, o_type = obj["id"], obj["type"]

            # Reject unphysical objects (inside Earth or at origin)
            r_mag = np.linalg.norm(pos)
            if r_mag < R_EARTH:  # below Earth surface → decayed/unphysical
                logger.warning(
                    "TELEMETRY | Rejected %s: |r| = %.1f km (sub-surface)", o_id, r_mag
                )
                continue

            if o_type == "SATELLITE":
                if o_id not in self.satellites:
                    sat = Satellite(
                        id=o_id, position=pos, velocity=vel,
                        timestamp=self.sim_time,
                    )
                    sat.nominal_state = sat.state_vector.copy()
                    self.satellites[o_id] = sat
                    self.fuel_tracker.register_satellite(o_id)
                else:
                    self.satellites[o_id].position = pos
                    self.satellites[o_id].velocity = vel
            else:
                if o_id not in self.debris:
                    self.debris[o_id] = Debris(
                        id=o_id, position=pos, velocity=vel,
                        timestamp=self.sim_time,
                    )
                else:
                    self.debris[o_id].position = pos
                    self.debris[o_id].velocity = vel

        processed = len(objects)
        logger.info(
            "TELEMETRY | Ingested %d objects | CDMs active: %d",
            processed, len(self.active_cdms),
        )

        # ── INTER-TICK ASSESSMENT (Safety Fix) ───────────────────────────────
        # Run assessment immediately so that critical risks are detected and
        # evasive maneuvers can be scheduled BEFORE the first simulation step.
        # Adaptive lookahead: scale down for large debris clouds to maintain
        # real-time performance.  The full 24h window is restored in step().
        sat_states = {s.id: s.state_vector for s in self.satellites.values()}
        _n_deb = len(self.debris)
        _ingest_lookahead = 86400.0 if _n_deb <= 2000 else (
            7200.0 if _n_deb <= 5000 else 1800.0
        )
        self.active_cdms = self.assessor.assess(
            sat_states,
            {d.id: d.state_vector for d in self.debris.values()},
            lookahead_s=_ingest_lookahead,
            current_time=self.sim_time,
        )
        # Add Sat-vs-Sat pass
        self.active_cdms.extend(self.assessor.assess_sat_vs_sat(
            sat_states,
            lookahead_s=_ingest_lookahead,
            current_time=self.sim_time,
        ))
        self._auto_plan_maneuvers(self.sim_time)

        return {
            "status": "ACK",
            "processed_count": processed,
            "active_cdm_warnings": len(self.active_cdms),
        }

    def schedule_maneuver(self, satellite_id: str, sequence: list[dict]) -> dict:
        """Validate and queue a multi-burn maneuver sequence for a satellite.

        Called by: POST /api/maneuver/schedule

        ΔV vectors arrive from the API in km/s; converted to m/s internally for
        constraint validation (MAX_DV_PER_BURN is expressed in m/s per PRD §4.5).

        Cooldown is enforced ACROSS THE ENTIRE SEQUENCE, not just against historical
        burns — a 5-burn sequence cannot bypass the 600 s rule between its own burns.

        Args:
            satellite_id: Target satellite identifier.
            sequence:     List of burn dicts: {burnTime, deltaV_vector{x,y,z} km/s}.

        Returns:
            Scheduling response with status ("SCHEDULED" | "REJECTED") and
            validation fields.
        """
        if satellite_id not in self.satellites:
            return {
                "status": "REJECTED",
                "validation": {
                    "ground_station_los": False,
                    "sufficient_fuel": False,
                    "projected_mass_remaining_kg": 0.0,
                },
            }

        sat = self.satellites[satellite_id]
        if sat.status == "EOL" or self.fuel_tracker.is_eol(satellite_id):
            # Ensure status is synchronized if fuel is already EOL
            if sat.status != "EOL":
                sat.status = "EOL"
            
            logger.warning("MANEUVER | %s | REJECTED | Satellite is EOL", satellite_id)
            return {
                "status": "REJECTED",
                "reason": "Satellite is EOL",
                "validation": {
                    "ground_station_los": False,
                    "sufficient_fuel": False,
                    "projected_mass_remaining_kg": float(sat.wet_mass_kg),
                },
            }

        simulated_fuel = self.fuel_tracker.get_fuel(satellite_id)

        # Seed effective_last_burn from executed history AND already-queued future
        # burns so that cooldown is enforced end-to-end across submitted sequences.
        effective_last_burn: datetime | None = sat.last_burn_time
        if sat.maneuver_queue:
            last_queued_time = max(
                datetime.fromisoformat(b["burnTime"].replace("Z", "+00:00"))
                for b in sat.maneuver_queue
            )
            if effective_last_burn is None or last_queued_time > effective_last_burn:
                effective_last_burn = last_queued_time

        for burn in sequence:
            dv_kms  = burn["deltaV_vector"]
            dv_vec  = np.array([dv_kms["x"], dv_kms["y"], dv_kms["z"]])
            dv_magnitude_ms = float(np.linalg.norm(dv_vec)) * 1000.0   # km/s → m/s

            burn_time = datetime.fromisoformat(
                burn["burnTime"].replace("Z", "+00:00")
            )

            dt_to_burn = (burn_time - self.sim_time).total_seconds()
            if dt_to_burn > 0:
                burn_pos = self.propagator.propagate(sat.state_vector, dt_to_burn)[:3]
            else:
                burn_pos = sat.position

            has_los = self.gs_network.check_line_of_sight(burn_pos, burn_time)

            is_valid, reason = self.planner.validate_burn(
                delta_v_magnitude_ms=dv_magnitude_ms,
                burn_time=burn_time,
                current_time=self.sim_time,
                last_burn_time=effective_last_burn,
                has_los=has_los,
            )

            if not is_valid:
                logger.warning("MANEUVER | %s | REJECTED | %s", satellite_id, reason)
                return {
                    "status": "REJECTED",
                    "reason": reason,
                    "validation": {
                        "ground_station_los": has_los,
                        "sufficient_fuel": self.fuel_tracker.sufficient_fuel(
                            satellite_id, dv_magnitude_ms
                        ),
                        "projected_mass_remaining_kg": float(M_DRY + simulated_fuel),
                    },
                }

            fuel_needed = self.fuel_tracker.estimate_fuel_consumption(satellite_id, dv_magnitude_ms)

            if simulated_fuel < fuel_needed:
                logger.warning("MANEUVER | %s | REJECTED | Insufficient fuel", satellite_id)
                return {
                    "status": "REJECTED",
                    "reason": "Insufficient fuel",
                    "validation": {
                        "ground_station_los": has_los,
                        "sufficient_fuel": False,
                        "projected_mass_remaining_kg": float(M_DRY + simulated_fuel),
                    },
                }

            simulated_fuel -= fuel_needed

            # Advance the sequence-local last-burn pointer for the next iteration
            effective_last_burn = burn_time

        sat.maneuver_queue.extend(sequence)
        logger.info("MANEUVER | %s | Queued %d burns", satellite_id, len(sequence))

        return {
            "status": "SCHEDULED",
            "validation": {
                "ground_station_los": True,
                "sufficient_fuel": True,
                "projected_mass_remaining_kg": float(M_DRY + simulated_fuel),
            },
        }

    def step(self, step_seconds: int) -> dict:
        """Advance the simulation clock and execute the full physics tick.

        **Sub-step burn execution**: Burns are applied at their scheduled times
        DURING propagation, not after.  The step is split into segments at each
        burn boundary so that the post-burn trajectory is physically correct.

        Called by: POST /api/simulate/step

        Args:
            step_seconds: Time step duration in seconds.

        Returns:
            Tick summary: status, new_timestamp, collisions_detected,
            maneuvers_executed.
        """
        old_time    = self.sim_time
        target_time = self.sim_time + timedelta(seconds=step_seconds)
        collisions_detected = 0
        maneuvers_executed  = 0

        # ── Zero-step: no-op tick ──
        if step_seconds == 0:
            return {
                "status": "STEP_COMPLETE",
                "new_timestamp": self.sim_time.isoformat(),
                "collisions_detected": 0,
                "maneuvers_executed": 0,
            }

        # ── Sub-sampling parameters for collision scan ──
        if step_seconds <= 3600:
            _sub_interval = 300.0
        elif step_seconds <= 21600:
            _sub_interval = 600.0
        else:
            _sub_interval = 1800.0
        _n_sub = max(1, min(int(step_seconds / _sub_interval), 72))
        # Relative sample times within the step (seconds from old_time)
        _sample_times_rel = [step_seconds * float(f)
                             for f in np.linspace(0.0, 1.0, _n_sub + 1)[1:]]

        # ── Propagate nominal slots for the full step (unaffected by burns) ──
        nominal_states = {sid: sat.nominal_state for sid, sat in self.satellites.items()}
        if nominal_states:
            new_nominal = self.propagator.propagate_batch(nominal_states, step_seconds)
            for sid, sv in new_nominal.items():
                self.satellites[sid].nominal_state = sv

        # ── Collect and sort all burns in this step window ──
        all_window_burns: list[tuple[datetime, str, dict]] = []
        for sat_id, sat in self.satellites.items():
            sat.maneuver_queue.sort(key=lambda x: x["burnTime"])
            pending: list[dict] = []
            for burn in sat.maneuver_queue:
                bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                if bt <= old_time:
                    logger.warning("MANEUVER | %s | Discarding stale burn", sat_id)
                elif bt <= target_time:
                    all_window_burns.append((bt, sat_id, burn))
                else:
                    pending.append(burn)
            sat.maneuver_queue = pending
        all_window_burns.sort(key=lambda x: x[0])

        # Group burns by exact time
        burns_at: dict[float, list[tuple[str, dict]]] = {}
        for bt, sid, burn in all_window_burns:
            t_rel = (bt - old_time).total_seconds()
            burns_at.setdefault(t_rel, []).append((sid, burn))

        # Segment boundaries (relative seconds from old_time)
        seg_bounds = sorted(set(
            [0.0] + list(burns_at.keys()) + [float(step_seconds)]
        ))

        # ── Debris: single dense propagation for the full step ──
        _deb_ids: list[str] = list(self.debris.keys())
        _deb_dense_sol = None
        if _deb_ids:
            deb_states_init = {did: deb.state_vector for did, deb in self.debris.items()}
            if step_seconds <= 600 and len(_deb_ids) > 100:
                new_deb_final = OrbitalPropagator.propagate_fast_batch(
                    deb_states_init, step_seconds
                )
            else:
                _deb_dense_ids_list, _deb_dense_sol = \
                    self.propagator.propagate_dense_batch(deb_states_init, step_seconds)
                new_deb_final = dict(zip(
                    _deb_dense_ids_list, _deb_dense_sol(step_seconds)
                ))
            for did, sv in new_deb_final.items():
                self.debris[did].state_vector = sv

        # ── Satellites: segmented propagation with mid-step burns ──
        # Track satellite positions at each collision-scan sample time.
        saved_sat_pos: dict[float, dict[str, np.ndarray]] = {}

        for seg_idx in range(len(seg_bounds) - 1):
            seg_start = seg_bounds[seg_idx]
            seg_end   = seg_bounds[seg_idx + 1]
            seg_dt    = seg_end - seg_start
            if seg_dt <= 0:
                continue

            # Which collision-scan samples fall in (seg_start, seg_end]?
            seg_samples = [t for t in _sample_times_rel
                           if seg_start < t <= seg_end]

            cur_sat_states = {
                sid: sat.state_vector for sid, sat in self.satellites.items()
            }

            if seg_samples and len(cur_sat_states) > 0:
                # Dense propagation for this segment (needed for sub-sampling)
                seg_ids, seg_sol = self.propagator.propagate_dense_batch(
                    cur_sat_states, seg_dt
                )
                for t_sample in seg_samples:
                    t_in_seg = t_sample - seg_start
                    sv_at_t = seg_sol(t_in_seg)   # (S, 6)
                    saved_sat_pos[t_sample] = {
                        seg_ids[j]: sv_at_t[j, :3].copy()
                        for j in range(len(seg_ids))
                    }
                # Advance satellites to segment end
                final_seg = seg_sol(seg_dt)
                for j, sid in enumerate(seg_ids):
                    self.satellites[sid].state_vector = final_seg[j].copy()
            elif cur_sat_states:
                # No sub-samples needed — standard batch propagation
                new_sat = self.propagator.propagate_batch(cur_sat_states, seg_dt)
                for sid, sv in new_sat.items():
                    self.satellites[sid].state_vector = sv

            # ── Apply burns at this segment boundary ──
            if seg_end in burns_at:
                seg_end_dt = old_time + timedelta(seconds=seg_end)
                for sat_id, burn in burns_at[seg_end]:
                    sat = self.satellites[sat_id]
                    dv = burn["deltaV_vector"]
                    dv_vec = np.array([dv["x"], dv["y"], dv["z"]])
                    dv_mag_ms = float(np.linalg.norm(dv_vec)) * 1000.0

                    # Runtime re-validation: fuel
                    if not self.fuel_tracker.sufficient_fuel(sat_id, dv_mag_ms):
                        logger.warning(
                            "MANEUVER | %s | %s | SKIPPED — insufficient fuel",
                            sat_id, burn.get("burn_id", "BURN"))
                        continue
                    # Runtime re-validation: cooldown
                    if sat.last_burn_time is not None:
                        gap = (seg_end_dt - sat.last_burn_time).total_seconds()
                        if gap < THRUSTER_COOLDOWN_S:
                            logger.warning(
                                "MANEUVER | %s | %s | SKIPPED — cooldown (%.0fs)",
                                sat_id, burn.get("burn_id", "BURN"), gap)
                            continue

                    # Execute burn: apply ΔV at the correct epoch
                    sat.velocity += dv_vec
                    fuel_before = self.fuel_tracker.get_fuel(sat_id)
                    self.fuel_tracker.consume(sat_id, dv_mag_ms)
                    sat.fuel_kg = self.fuel_tracker.get_fuel(sat_id)
                    sat.last_burn_time = seg_end_dt
                    sat.status = "EVADING"
                    maneuvers_executed += 1

                    burn_id_str = burn.get("burn_id", "BURN")
                    if "RTS" in burn_id_str.upper() or "RECOVERY" in burn_id_str.upper():
                        burn_type = "RECOVERY"
                    elif "EVASION" in burn_id_str.upper() or "EVA" in burn_id_str.upper():
                        burn_type = "EVASION"
                    elif "GRAVEYARD" in burn_id_str.upper() or "EOL" in burn_id_str.upper():
                        burn_type = "GRAVEYARD"
                    else:
                        burn_type = "MANUAL"
                    log_entry = {
                        "event": "BURN_EXECUTED",
                        "type": burn_type,
                        "timestamp": seg_end_dt.isoformat(),
                        "satellite_id": sat_id,
                        "burn_id": burn_id_str,
                        "delta_v_magnitude_ms": round(dv_mag_ms, 4),
                        "delta_v_vector_km_s": {
                            "x": round(float(dv_vec[0]), 6),
                            "y": round(float(dv_vec[1]), 6),
                            "z": round(float(dv_vec[2]), 6),
                        },
                        "fuel_consumed_kg": round(fuel_before - sat.fuel_kg, 3),
                        "fuel_remaining_kg": round(sat.fuel_kg, 2),
                        "mass_after_kg": round(M_DRY + sat.fuel_kg, 2),
                    }
                    logger.info("MANEUVER | %s", json.dumps(log_entry))
                    self.maneuver_log.append(log_entry)

        # ── Step 3a: 24-hour CDM scan (uses final post-burn states) ──
        sat_states_snapshot = {s.id: s.state_vector for s in self.satellites.values()}
        # Adaptive lookahead: scale down for very large debris clouds
        _step_n_deb = len(self.debris)
        _step_lookahead = 86400.0 if _step_n_deb <= 2000 else (
            7200.0 if _step_n_deb <= 5000 else 1800.0
        )
        self.active_cdms = self.assessor.assess(
            sat_states_snapshot,
            {d.id: d.state_vector for d in self.debris.values()},
            lookahead_s=_step_lookahead,
            current_time=target_time,
        )
        self.active_cdms.extend(self.assessor.assess_sat_vs_sat(
            sat_states_snapshot,
            lookahead_s=_step_lookahead,
            current_time=target_time,
        ))

        # ── Step 3b: Collision scan at sub-samples (burn-aware) ──
        if self.satellites and self.debris and _deb_ids:
            _logged_pairs: set[tuple[str, str]] = set()

            for t_sample in _sample_times_rel:
                sample_time = old_time + timedelta(seconds=t_sample)

                # Satellite positions: from saved sub-sample data or final state
                if t_sample in saved_sat_pos:
                    sp = saved_sat_pos[t_sample]
                    _sat_ids_at_t = list(sp.keys())
                    _sat_pos = np.array([sp[sid] for sid in _sat_ids_at_t])
                else:
                    _sat_ids_at_t = list(self.satellites.keys())
                    _sat_pos = np.array([
                        self.satellites[sid].position for sid in _sat_ids_at_t
                    ])

                # Debris positions: from dense solution or final state
                if _deb_dense_sol is not None:
                    _all_deb = _deb_dense_sol(t_sample)
                    _deb_pos = _all_deb[:, :3]
                    _deb_ids_at_t = _deb_dense_ids_list
                else:
                    _deb_ids_at_t = _deb_ids
                    _deb_pos = np.array([
                        self.debris[did].position for did in _deb_ids_at_t
                    ])

                if len(_sat_pos) == 0 or len(_deb_pos) == 0:
                    continue

                _deb_tree = _KDTree(_deb_pos)
                hit_lists = _deb_tree.query_ball_point(
                    _sat_pos, r=CONJUNCTION_THRESHOLD_KM
                )

                for s_idx, neighbors in enumerate(hit_lists):
                    if not neighbors:
                        continue
                    s_id = _sat_ids_at_t[s_idx]
                    for deb_idx in neighbors:
                        d_id = _deb_ids_at_t[deb_idx]
                        pair = (s_id, d_id)
                        if pair in _logged_pairs:
                            continue
                        _logged_pairs.add(pair)
                        dist = float(np.linalg.norm(
                            _sat_pos[s_idx] - _deb_pos[deb_idx]
                        ))
                        collisions_detected += 1
                        self.collision_count += 1
                        entry = {
                            "event": "COLLISION",
                            "timestamp": sample_time.isoformat(),
                            "satellite_id": s_id,
                            "debris_id": d_id,
                            "distance_km": round(dist, 4),
                        }
                        logger.critical("COLLISION | %s", json.dumps(entry))
                        self.collision_log.append(entry)

        # ── Step 4: Station-keeping status + Uptime tracking ──
        for sat in self.satellites.values():
            if sat.status == "EOL":
                continue

            slot_offset = float(np.linalg.norm(
                sat.position - sat.nominal_state[:3]
            ))
            in_slot = slot_offset <= STATION_KEEPING_RADIUS_KM

            if not in_slot:
                self.time_outside_box[sat.id] = (
                    self.time_outside_box.get(sat.id, 0.0) + step_seconds
                )

            if sat.status == "EVADING" and sat.maneuver_queue:
                continue

            if in_slot:
                sat.status = "NOMINAL"
            else:
                sat.status = "RECOVERING"

            _, _, alt = _eci_to_lla(sat.position, target_time)
            if not (200.0 <= alt <= 2000.0):
                logger.warning(
                    "CONSTRAINTS | %s | Altitude %.1f km outside LEO band",
                    sat.id, alt,
                )

            if sat.status == "RECOVERING" and not sat.maneuver_queue:
                rts_burns = self.planner.plan_return_to_slot(
                    satellite=sat,
                    nominal_state=sat.nominal_state,
                    current_time=target_time,
                )
                if rts_burns:
                    sanitized = [
                        {k: v for k, v in b.items() if not k.startswith('_')}
                        for b in rts_burns
                    ]
                    sat.maneuver_queue.extend(sanitized)
                    logger.info(
                        "RTS-PLAN | %s | Queued recovery (offset=%.2f km)",
                        sat.id, slot_offset,
                    )

        # ── Step 5: Auto-plan evasion maneuvers ──
        self._auto_plan_maneuvers(target_time)

        # ── Step 6: EOL threshold check ──
        for sat_id, sat in self.satellites.items():
            if self.fuel_tracker.is_eol(sat_id) and sat.status != "EOL":
                sat.status = "EOL"
                remaining_fuel = self.fuel_tracker.get_fuel(sat_id)
                if remaining_fuel > 0.1 and not sat.maneuver_queue:
                    earliest_burn = target_time + timedelta(
                        seconds=SIGNAL_LATENCY_S + 60
                    )
                    _EOL_SEARCH_S = 6000
                    dense_eol = self.propagator.propagate_dense(
                        sat.state_vector, _EOL_SEARCH_S
                    )
                    graveyard_time: datetime | None = None
                    test_t = earliest_burn
                    while (test_t - target_time).total_seconds() <= _EOL_SEARCH_S:
                        dt_check = (test_t - target_time).total_seconds()
                        pos_check = dense_eol(dt_check)[:3]
                        if self.gs_network.check_line_of_sight(pos_check, test_t):
                            graveyard_time = test_t
                            break
                        test_t += timedelta(seconds=60)

                    if graveyard_time is not None:
                        dt_burn = (graveyard_time - target_time).total_seconds()
                        sv_at_burn = dense_eol(dt_burn)
                        # Hohmann-style de-orbit: lower perigee to ~150 km
                        # ΔV ≈ −v_circ × (1 − sqrt(r_target / r_current)) retrograde
                        r_cur = np.linalg.norm(sv_at_burn[:3])
                        v_circ = np.sqrt(MU_EARTH / r_cur)
                        r_target = 6378.137 + 150.0  # 150 km perigee
                        dv_retro_kms = v_circ * (1.0 - np.sqrt(r_target / r_cur))
                        # Cap to remaining fuel capability
                        max_dv_kms = remaining_fuel * ISP * G0 / (
                            (M_DRY + remaining_fuel) * 1000.0
                        )
                        dv_retro_kms = min(dv_retro_kms, max_dv_kms * 0.9)
                        dv_rtn = np.array([0.0, -dv_retro_kms, 0.0])
                        dv_eci = self.planner.rtn_to_eci(
                            sv_at_burn[:3], sv_at_burn[3:], dv_rtn
                        )
                        sat.maneuver_queue.append({
                            "burn_id": f"GRAVEYARD_{sat_id}",
                            "burnTime": graveyard_time.isoformat(),
                            "deltaV_vector": {
                                "x": float(dv_eci[0]),
                                "y": float(dv_eci[1]),
                                "z": float(dv_eci[2]),
                            },
                        })
                        logger.warning(
                            "EOL | %s | Graveyard burn ΔV=%.3f km/s at %s",
                            sat_id, dv_retro_kms, graveyard_time.isoformat(),
                        )
                    else:
                        logger.warning(
                            "EOL | %s | No LOS window; graveyard deferred",
                            sat_id,
                        )
                logger.warning(
                    "EOL | %s | Fuel=%.2f kg ≤ threshold (%.1f kg)",
                    sat_id, remaining_fuel, EOL_FUEL_THRESHOLD_KG,
                )

        # ── Step 7: Advance simulation clock ──
        self.sim_time = target_time
        logger.info(
            "SIMULATE | %s → %s | CDMs: %d | Collisions: %d | Maneuvers: %d",
            old_time.isoformat(), self.sim_time.isoformat(),
            len(self.active_cdms), collisions_detected, maneuvers_executed,
        )

        return {
            "status": "STEP_COMPLETE",
            "new_timestamp": self.sim_time.isoformat(),
            "collisions_detected": collisions_detected,
            "maneuvers_executed": maneuvers_executed,
        }

    def _auto_plan_maneuvers(self, current_time: datetime) -> None:
        """Scan active CDMs and queue evasion maneuvers for CRITICAL risks.
        
        Groups multiple threats per satellite to avoid redundant or conflicting
        burn sequences within the thruster cooldown window.
        """
        critical_groups: dict[str, list[CDM]] = {}
        for cdm in self.active_cdms:
            if cdm.risk in ("CRITICAL", "RED"):
                critical_groups.setdefault(cdm.satellite_id, []).append(cdm)
                # If it's a Sat-vs-Sat conjunction, the "debris" side also needs to evaluate it
                if cdm.debris_id in self.satellites:
                    critical_groups.setdefault(cdm.debris_id, []).append(cdm)

        for sat_id, group in critical_groups.items():
            sat = self.satellites.get(sat_id)
            if sat is None:
                continue
            if sat.status == "EOL":
                continue   # skip auto-planning for decommissioned satellites
            
            # If already evading with a non-empty queue, don't interrupt the sequence.
            if sat.status == "EVADING" and sat.maneuver_queue:
                continue

            # IDENTIFY THE EARLIEST THREAT (PRD §4.5)
            most_critical = min(group, key=lambda c: c.tca)
            
            # Identify the "other" object in the conjunction
            other_id = most_critical.debris_id if most_critical.satellite_id == sat_id else most_critical.satellite_id
            
            target = self.debris.get(other_id)
            if target is None:
                target = self.satellites.get(other_id)
            
            if target is None:
                continue

            # ── Health-Aware Handshake (Global Optimization) ──
            # If both are satellites, coordinate so only the healthier one burns.
            if target.obj_type == "SATELLITE":
                sat_fuel = self.fuel_tracker.get_fuel(sat_id)
                target_fuel = self.fuel_tracker.get_fuel(target.id)
                
                # If target satellite is significantly healthier (>2kg more fuel),
                # let it handle the burn instead of the current satellite.
                if target_fuel > sat_fuel + 2.0:
                    logger.info("AUTO-PLAN | %s | Yielding evasion to healthier peer %s (%.1fkg > %.1fkg)",
                                sat_id, target.id, target_fuel, sat_fuel)
                    continue 
                
                # If fuel levels are ties or current is healthier, current takes the burn.
                # If target is healthier by < 2kg, current still takes it to avoid 
                # both yielding or both burning. 
                # (The healthier one will evaluate this too and will NOT yield).

            burns = self.planner.plan_evasion(
                satellite=sat, debris=target,
                tca=most_critical.tca, miss_distance_km=most_critical.miss_distance_km,
                current_time=current_time,
            )

            # LOS blackout guard: reschedule out-of-contact burns (PRD §4.4)
            if burns:
                max_dt = 0.0
                for burn in burns:
                    bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                    dt = (bt - current_time).total_seconds()
                    if dt > max_dt: max_dt = dt
                
                if max_dt > 0:
                    dense_sol = self.propagator.propagate_dense(sat.state_vector, max_dt)
                else:
                    dense_sol = lambda t: sat.state_vector

                for burn in burns:
                    bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                    def has_los_at(t_check: datetime) -> bool:
                        dt_check = (t_check - current_time).total_seconds()
                        pos = dense_sol(dt_check)[:3] if dt_check > 0 else sat.position
                        return self.gs_network.check_line_of_sight(pos, t_check)

                    if not has_los_at(bt):
                        # 1. Try moving the burn EARLIER towards the signal latency limit
                        earliest = current_time + timedelta(seconds=SIGNAL_LATENCY_S)
                        test_bt = bt - timedelta(seconds=10)
                        found_los = False
                        while test_bt >= earliest:
                            if has_los_at(test_bt):
                                burn["burnTime"] = test_bt.isoformat()
                                bt = test_bt
                                found_los = True
                                break
                            test_bt -= timedelta(seconds=10)
                        
                        # 2. If still no LOS, try moving it LATER towards TCA
                        if not found_los:
                            # Handle both string and datetime TCA objects
                            tca_val = most_critical.tca
                            if isinstance(tca_val, str):
                                tca_dt = datetime.fromisoformat(tca_val.replace("Z", "+00:00"))
                            else:
                                tca_dt = tca_val
                            
                            latest = min(bt + timedelta(seconds=1800), tca_dt - timedelta(seconds=30))
                            test_bt = bt + timedelta(seconds=10)
                            while test_bt <= latest:
                                if has_los_at(test_bt):
                                    burn["burnTime"] = test_bt.isoformat()
                                    bt = test_bt
                                    found_los = True
                                    break
                                test_bt += timedelta(seconds=10)

                        if not found_los:
                            burn["_skip"] = True

            # Cooldown enforcement: auto-planned burns must respect the 600s rule
            effective_last_auto: datetime | None = sat.last_burn_time
            if sat.maneuver_queue:
                last_queued = max(
                    datetime.fromisoformat(b["burnTime"].replace("Z", "+00:00"))
                    for b in sat.maneuver_queue
                )
                if effective_last_auto is None or last_queued > effective_last_auto:
                    effective_last_auto = last_queued

            validated_burns: list[dict] = []
            for burn in burns:
                if burn.get("_skip"):
                    continue
                bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                if effective_last_auto is not None:
                    cooldown_gap = (bt - effective_last_auto).total_seconds()
                    if cooldown_gap < THRUSTER_COOLDOWN_S:
                        # Shift burn forward to satisfy cooldown constraint
                        bt = effective_last_auto + timedelta(seconds=THRUSTER_COOLDOWN_S + 1)
                        burn["burnTime"] = bt.isoformat()
                validated_burns.append(burn)
                effective_last_auto = bt

            if validated_burns:
                sat.maneuver_queue.extend(validated_burns)
                sat.status = "EVADING"
                logger.info(
                    "AUTO-PLAN | %s | Grouped %d threats | Planned evasion for (%s) miss=%.4f km",
                    sat_id, len(group), target.id, most_critical.miss_distance_km
                )
            elif burns:
                # Evasion was planned but all burns were skipped due to LOS blackout
                logger.critical(
                    "UNRESOLVABLE | %s | Collision with %s at %s - No LOS available for mandatory evasion",
                    sat_id, target.id, 
                    most_critical.tca.isoformat() if hasattr(most_critical.tca, 'isoformat') else most_critical.tca
                )

    def get_snapshot(self) -> dict:
        """Return the current simulation state for frontend rendering.

        Called by: GET /api/visualization/snapshot

        Satellite positions are converted to lat/lon/alt for the globe renderer.
        The debris cloud is encoded as flat [id, lat, lon, alt] tuples to
        minimise serialisation payload size for 10 000+ objects.

        Returns:
            Snapshot dict with satellites, debris_cloud, CDMs, maneuver log,
            collision count, and uptime scores.
        """
        satellites = []
        if self.satellites:
            sat_ids = list(self.satellites.keys())
            sat_positions = np.array([sat.position for sat in self.satellites.values()])
            sat_lla = _eci_to_lla_batch(sat_positions, self.sim_time)
            
            for i, sid in enumerate(sat_ids):
                sat = self.satellites[sid]
                t_out = self.time_outside_box.get(sid, 0.0)
                satellites.append({
                    "id":       sat.id,
                    "lat":      round(float(sat_lla[i, 0]), 3),
                    "lon":      round(float(sat_lla[i, 1]), 3),
                    "alt_km":   round(float(sat_lla[i, 2]), 1),
                    "fuel_kg":  max(0.0, round(self.fuel_tracker.get_fuel(sat.id), 2)),
                    "status":   sat.status,
                    "uptime_score": round(float(np.exp(-0.001 * t_out)), 4),
                    "time_outside_box_s": round(t_out, 1),
                    "queued_burns": len(sat.maneuver_queue),
                })

        debris_cloud = []
        if self.debris:
            debris_ids = list(self.debris.keys())
            debris_pos = np.array([deb.position for deb in self.debris.values()])
            debris_lla = _eci_to_lla_batch(debris_pos, self.sim_time)
            # Vectorized rounding for 10K+ debris performance
            lats = np.round(debris_lla[:, 0], 2)
            lons = np.round(debris_lla[:, 1], 2)
            alts = np.round(debris_lla[:, 2], 1)
            debris_cloud = [
                [debris_ids[i], float(lats[i]), float(lons[i]), float(alts[i])]
                for i in range(len(debris_ids))
            ]

        total_queued = sum(len(s.maneuver_queue) for s in self.satellites.values())

        # CDM summaries for frontend bullseye + timeline
        cdm_list = []
        for cdm in self.active_cdms:
            tca_iso = cdm.tca.isoformat() if hasattr(cdm.tca, 'isoformat') else str(cdm.tca)
            cdm_list.append({
                "satellite_id": cdm.satellite_id,
                "debris_id": cdm.debris_id,
                "tca": tca_iso,
                "miss_distance_km": round(cdm.miss_distance_km, 4),
                "risk": cdm.risk,
                "relative_velocity_km_s": round(cdm.relative_velocity_km_s, 3),
            })

        return {
            "timestamp":           self.sim_time.isoformat(),
            "satellites":          satellites,
            "debris_cloud":        debris_cloud,
            "active_cdm_count":    len(self.active_cdms),
            "maneuver_queue_depth": total_queued,
            "cdms":                cdm_list,
            "maneuver_log":        self.maneuver_log[-50:],  # Last 50 events
            "collision_count":     self.collision_count,
        }
