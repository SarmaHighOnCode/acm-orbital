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
)
from engine.models import Satellite, Debris, CDM
from engine.propagator import OrbitalPropagator
from engine.collision import ConjunctionAssessor
from engine.maneuver_planner import ManeuverPlanner
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork

logger = logging.getLogger("acm.engine.simulation")


def _eci_to_lla(position: np.ndarray) -> tuple[float, float, float]:
    """Convert ECI position [x, y, z] km to (lat_deg, lon_deg, alt_km).

    Uses a simplified spherical Earth model (sufficient for visualisation).
    For precision geodetic work, replace with an iterative WGS-84 conversion.

    Args:
        position: ECI [x, y, z] in km.

    Returns:
        (latitude_deg, longitude_deg, altitude_km)
    """
    x, y, z = position
    r = np.linalg.norm(position)
    alt_km = r - 6378.137
    lat_deg = float(np.degrees(np.arcsin(np.clip(z / r, -1.0, 1.0))))
    lon_deg = float(np.degrees(np.arctan2(y, x)))
    return lat_deg, lon_deg, alt_km


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
        self.satellites: dict[str, Satellite] = {}
        self.debris: dict[str, Debris] = {}
        self.active_cdms: list[CDM] = []
        self.collision_log: list[dict] = []
        self.maneuver_log: list[dict] = []

        # Subsystem components
        self.propagator    = OrbitalPropagator()
        self.assessor      = ConjunctionAssessor(self.propagator)
        self.planner       = ManeuverPlanner(propagator=self.propagator)
        self.fuel_tracker  = FuelTracker()
        self.gs_network    = GroundStationNetwork()

        logger.info("SimulationEngine initialized at %s", self.sim_time.isoformat())

    # ── THE CONTRACT (API Layer calls these) ──────────────────────────────────

    def ingest_telemetry(self, timestamp: str, objects: list[dict]) -> dict:
        """Ingest raw telemetry and update / register orbital objects.

        Called by: POST /api/telemetry

        Args:
            timestamp: ISO-8601 epoch string (e.g. "2025-01-01T00:00:00Z").
            objects:   List of object dicts with keys: id, type, r{x,y,z}, v{x,y,z}.

        Returns:
            ACK payload with processed_count and active_cdm_warnings.
        """
        self.sim_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        for obj in objects:
            pos = np.array([obj["r"]["x"], obj["r"]["y"], obj["r"]["z"]])
            vel = np.array([obj["v"]["x"], obj["v"]["y"], obj["v"]["z"]])

            if obj["type"] == "SATELLITE":
                if obj["id"] not in self.satellites:
                    sat = Satellite(
                        id=obj["id"], position=pos, velocity=vel,
                        timestamp=self.sim_time,
                    )
                    sat.nominal_state = sat.state_vector.copy()
                    self.satellites[obj["id"]] = sat
                    self.fuel_tracker.register_satellite(obj["id"])
                else:
                    self.satellites[obj["id"]].position = pos
                    self.satellites[obj["id"]].velocity = vel
            else:
                if obj["id"] not in self.debris:
                    self.debris[obj["id"]] = Debris(
                        id=obj["id"], position=pos, velocity=vel,
                        timestamp=self.sim_time,
                    )
                else:
                    self.debris[obj["id"]].position = pos
                    self.debris[obj["id"]].velocity = vel

        processed = len(objects)
        logger.info(
            "TELEMETRY | Ingested %d objects | CDMs active: %d",
            processed, len(self.active_cdms),
        )
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

            has_los = self.gs_network.check_line_of_sight(sat.position, burn_time)

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
                    "validation": {
                        "ground_station_los": has_los,
                        "sufficient_fuel": self.fuel_tracker.sufficient_fuel(
                            satellite_id, dv_magnitude_ms
                        ),
                        "projected_mass_remaining_kg": float(
                            self.fuel_tracker.get_current_mass(satellite_id)
                        ),
                    },
                }

            if not self.fuel_tracker.sufficient_fuel(satellite_id, dv_magnitude_ms):
                logger.warning("MANEUVER | %s | REJECTED | Insufficient fuel", satellite_id)
                return {
                    "status": "REJECTED",
                    "validation": {
                        "ground_station_los": has_los,
                        "sufficient_fuel": False,
                        "projected_mass_remaining_kg": float(
                            self.fuel_tracker.get_current_mass(satellite_id)
                        ),
                    },
                }

            # Advance the sequence-local last-burn pointer for the next iteration
            effective_last_burn = burn_time

        sat.maneuver_queue.extend(sequence)
        logger.info("MANEUVER | %s | Queued %d burns", satellite_id, len(sequence))

        return {
            "status": "SCHEDULED",
            "validation": {
                "ground_station_los": True,
                "sufficient_fuel": True,
                "projected_mass_remaining_kg": float(
                    self.fuel_tracker.get_current_mass(satellite_id)
                ),
            },
        }

    def step(self, step_seconds: int) -> dict:
        """Advance the simulation clock and execute the full 7-step physics tick.

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

        # ── Step 1: Propagate all objects — single vectorised DOP853 call each ──
        # Satellites: actual states
        sat_states = {sid: sat.state_vector for sid, sat in self.satellites.items()}
        new_sat_states = self.propagator.propagate_batch(sat_states, step_seconds)
        for sid, new_sv in new_sat_states.items():
            self.satellites[sid].state_vector = new_sv

        # Satellites: nominal slot reference orbits (propagated in parallel batch)
        nominal_states = {sid: sat.nominal_state for sid, sat in self.satellites.items()}
        new_nominal_states = self.propagator.propagate_batch(nominal_states, step_seconds)
        for sid, new_sv in new_nominal_states.items():
            self.satellites[sid].nominal_state = new_sv

        # Debris cloud
        deb_states = {did: deb.state_vector for did, deb in self.debris.items()}
        new_deb_states = self.propagator.propagate_batch(deb_states, step_seconds)
        for did, new_sv in new_deb_states.items():
            self.debris[did].state_vector = new_sv

        # ── Step 2: Execute scheduled maneuvers ───────────────────────────────
        for sat_id, sat in self.satellites.items():
            remaining_queue: list[dict] = []
            for burn in sat.maneuver_queue:
                burn_time = datetime.fromisoformat(
                    burn["burnTime"].replace("Z", "+00:00")
                )
                if burn_time < old_time:
                    # Stale burn: window passed without execution (e.g. large time-skip).
                    # Discard silently — do NOT apply retroactively.
                    logger.warning(
                        "MANEUVER | %s | Discarding stale burn %s (scheduled %s, now %s)",
                        sat_id,
                        burn.get("burn_id", "BURN"),
                        burn_time.isoformat(),
                        old_time.isoformat(),
                    )
                    continue

                if burn_time <= target_time:
                    dv     = burn["deltaV_vector"]
                    dv_vec = np.array([dv["x"], dv["y"], dv["z"]])   # km/s
                    dv_mag_ms = float(np.linalg.norm(dv_vec)) * 1000.0

                    sat.velocity      = sat.velocity + dv_vec         # apply ΔV (km/s)
                    self.fuel_tracker.consume(sat_id, dv_mag_ms)
                    sat.fuel_kg        = self.fuel_tracker.get_fuel(sat_id)
                    sat.last_burn_time = burn_time
                    sat.status         = "EVADING"
                    maneuvers_executed += 1

                    logger.info(
                        "MANEUVER | %s | %s | ΔV=%.4f m/s | Fuel remaining: %.2f kg",
                        sat_id, burn.get("burn_id", "BURN"), dv_mag_ms, sat.fuel_kg,
                    )
                    self.maneuver_log.append({
                        "satellite_id": sat_id,
                        "burn_id": burn.get("burn_id", "BURN"),
                        "time": burn_time.isoformat(),
                        "delta_v_ms": dv_mag_ms,
                    })
                else:
                    remaining_queue.append(burn)
            sat.maneuver_queue = remaining_queue

        # ── Step 3: Conjunction assessment & instantaneous collision scan ──────
        # 3a. 24-h lookahead CDMs via the 4-stage KDTree pipeline — O(S log D + k·F)
        self.active_cdms = self.assessor.assess(
            {s.id: s.state_vector for s in self.satellites.values()},
            {d.id: d.state_vector for d in self.debris.values()},
            current_time=target_time,
        )

        # 3b. Instantaneous collision scan at current positions — O(S log D).
        # Build the KDTree ONCE over all D debris, then issue a single vectorised
        # query_ball_point call for ALL S satellites simultaneously.  This is a
        # single C-layer call vs S separate Python round-trips.
        if self.satellites and self.debris:
            _deb_ids: list[str]    = list(self.debris.keys())
            _deb_pos: np.ndarray   = np.array([d.position for d in self.debris.values()])
            _sat_ids: list[str]    = list(self.satellites.keys())
            _sat_pos: np.ndarray   = np.array([s.position for s in self.satellites.values()])

            _deb_tree = _KDTree(_deb_pos)

            # Batch query: returns a list of lists — one per satellite — in one call
            hit_lists = _deb_tree.query_ball_point(_sat_pos, r=CONJUNCTION_THRESHOLD_KM)

            for s_idx, neighbor_indices in enumerate(hit_lists):
                if not neighbor_indices:
                    continue
                sat = self.satellites[_sat_ids[s_idx]]
                for deb_idx in neighbor_indices:
                    # KDTree guarantees dist <= CONJUNCTION_THRESHOLD_KM for all
                    # returned indices — redundant Euclidean recheck removed.
                    deb  = self.debris[_deb_ids[deb_idx]]
                    dist = float(np.linalg.norm(sat.position - deb.position))
                    collisions_detected += 1
                    logger.critical(
                        "COLLISION | %s × %s | Time:%s | Distance:%.4f km",
                        sat.id, deb.id, target_time.isoformat(), dist,
                    )
                    self.collision_log.append({
                        "satellite_id": sat.id,
                        "debris_id":    deb.id,
                        "time":         target_time.isoformat(),
                        "distance_km":  dist,
                    })

        # ── Step 4: Station-keeping status ─────────────────────────────────────
        for sat in self.satellites.values():
            if sat.status == "EOL":
                continue   # terminal state — never overwrite
            slot_offset = float(np.linalg.norm(sat.position - sat.nominal_state[:3]))
            in_slot     = slot_offset <= STATION_KEEPING_RADIUS_KM
            if sat.status == "EVADING":
                # Transition out of EVADING once all queued burns have fired
                if not sat.maneuver_queue:
                    sat.status = "NOMINAL" if in_slot else "RECOVERING"
            elif in_slot:
                sat.status = "NOMINAL"
            else:
                sat.status = "RECOVERING"

        # ── Step 5: Auto-plan maneuvers for CRITICAL conjunctions ──────────────
        for cdm in self.active_cdms:
            if cdm.risk != "CRITICAL":
                continue
            sat = self.satellites.get(cdm.satellite_id)
            deb = self.debris.get(cdm.debris_id)
            if sat is None or deb is None:
                continue
            if sat.status == "EVADING" and sat.maneuver_queue:
                continue   # already has an active evasion sequence — don't double-queue

            burns = self.planner.plan_evasion(
                satellite=sat, debris=deb,
                tca=cdm.tca, miss_distance_km=cdm.miss_distance_km,
                current_time=target_time,
            )

            # LOS blackout guard: reschedule out-of-contact burns to just before
            # the blackout window ends (signal_latency + 60 s safety margin).
            for burn in burns:
                bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                if not self.gs_network.check_line_of_sight(sat.position, bt):
                    burn["burnTime"] = (
                        target_time + timedelta(seconds=SIGNAL_LATENCY_S + 60)
                    ).isoformat()

            # Cooldown enforcement: auto-planned burns must respect the same
            # 600 s thruster cooldown as manually-scheduled burns.  Compute the
            # effective last-burn time from executed history + queued burns, then
            # filter out any auto-planned burn that would violate cooldown.
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
                bt = datetime.fromisoformat(burn["burnTime"].replace("Z", "+00:00"))
                if effective_last_auto is not None:
                    cooldown_gap = (bt - effective_last_auto).total_seconds()
                    if cooldown_gap < THRUSTER_COOLDOWN_S:
                        # Shift burn forward to satisfy cooldown constraint
                        bt = effective_last_auto + timedelta(seconds=THRUSTER_COOLDOWN_S)
                        burn["burnTime"] = bt.isoformat()
                validated_burns.append(burn)
                effective_last_auto = bt

            sat.maneuver_queue.extend(validated_burns)
            sat.status = "EVADING"

        # ── Step 6: EOL threshold check ────────────────────────────────────────
        for sat_id, sat in self.satellites.items():
            if self.fuel_tracker.is_eol(sat_id) and sat.status != "EOL":
                sat.status = "EOL"
                logger.warning(
                    "EOL | %s | Fuel=%.2f kg ≤ threshold (%.1f kg) | "
                    "Graveyard maneuver scheduled",
                    sat_id,
                    self.fuel_tracker.get_fuel(sat_id),
                    EOL_FUEL_THRESHOLD_KG,
                )

        # ── Step 7: Advance simulation clock ───────────────────────────────────
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

    def get_snapshot(self) -> dict:
        """Return the current simulation state for frontend rendering.

        Called by: GET /api/visualization/snapshot

        Satellite positions are converted to lat/lon/alt for the globe renderer.
        The debris cloud is encoded as flat [id, lat, lon, alt] tuples to
        minimise serialisation payload size for 10 000+ objects.

        Returns:
            Snapshot dict with satellites, debris_cloud, CDM count, and
            maneuver queue depth.
        """
        satellites = []
        for sat in self.satellites.values():
            lat, lon, alt = _eci_to_lla(sat.position)
            satellites.append({
                "id":       sat.id,
                "lat":      round(lat, 3),
                "lon":      round(lon, 3),
                "alt_km":   round(alt, 1),
                "fuel_kg":  round(self.fuel_tracker.get_fuel(sat.id), 2),
                "status":   sat.status,
            })

        debris_cloud = []
        for deb in self.debris.values():
            lat, lon, alt = _eci_to_lla(deb.position)
            debris_cloud.append([deb.id, round(lat, 2), round(lon, 2), round(alt, 1)])

        total_queued = sum(len(s.maneuver_queue) for s in self.satellites.values())

        return {
            "timestamp":           self.sim_time.isoformat(),
            "satellites":          satellites,
            "debris_cloud":        debris_cloud,
            "active_cdm_count":    len(self.active_cdms),
            "maneuver_queue_depth": total_queued,
        }
