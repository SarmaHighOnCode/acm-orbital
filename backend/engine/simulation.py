"""
simulation.py — SimulationEngine (Master Orchestrator)
══════════════════════════════════════════════════════
THE CONTRACT: This is the single entry point the API layer uses.
Dev 2 calls these methods. Dev 1 implements them.
Neither touches the other's internals.

Owner: Dev 1 (Physics Engine)

Tick sequence (PRD §4.7):
  1. Propagate all objects
  2. Execute scheduled maneuvers (apply ΔV, deduct fuel, enforce cooldown)
  3. Run conjunction assessment (detect collisions at miss < 0.1 km)
  4. Update station-keeping status (10 km nominal slot check)
  5. Auto-plan maneuvers (queue evasion+recovery for CRITICAL CDMs)
  6. Check EOL thresholds (fuel ≤ 2.5 kg → graveyard)
  7. Generate snapshot
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np

from config import (
    CONJUNCTION_THRESHOLD_KM,
    EOL_FUEL_THRESHOLD_KG,
    STATION_KEEPING_RADIUS_KM,
    SIGNAL_LATENCY_S,
)
from engine.models import Satellite, Debris, CDM
from engine.propagator import OrbitalPropagator
from engine.collision import ConjunctionAssessor
from engine.maneuver_planner import ManeuverPlanner
from engine.fuel_tracker import FuelTracker
from engine.ground_stations import GroundStationNetwork

logger = logging.getLogger("acm.engine.simulation")


def _eci_to_lla(position: np.ndarray) -> tuple[float, float, float]:
    """Convert ECI position [x,y,z] km to (lat_deg, lon_deg, alt_km).

    Simplified spherical Earth model (sufficient for visualization).
    """
    x, y, z = position
    r = np.linalg.norm(position)
    alt_km = r - 6378.137
    lat_deg = float(np.degrees(np.arcsin(np.clip(z / r, -1.0, 1.0))))
    lon_deg = float(np.degrees(np.arctan2(y, x)))
    return lat_deg, lon_deg, alt_km


class SimulationEngine:
    """Master orchestrator for the ACM simulation.

    Maintains simulation clock, satellite/debris state, and coordinates
    all physics subsystems (propagation, collision, maneuver, fuel).
    """

    def __init__(self):
        self.sim_time: datetime = datetime.utcnow()
        self.satellites: dict[str, Satellite] = {}
        self.debris: dict[str, Debris] = {}
        self.active_cdms: list[CDM] = []
        self.collision_log: list[dict] = []
        self.maneuver_log: list[dict] = []

        # Subsystem components
        self.propagator = OrbitalPropagator()
        self.assessor = ConjunctionAssessor(self.propagator)
        self.planner = ManeuverPlanner(propagator=self.propagator)
        self.fuel_tracker = FuelTracker()
        self.gs_network = GroundStationNetwork()

        logger.info("SimulationEngine initialized at %s", self.sim_time.isoformat())

    # ── THE CONTRACT (API Layer calls these) ─────────────────────────────

    def ingest_telemetry(self, timestamp: str, objects: list[dict]) -> dict:
        """Called by POST /api/telemetry."""
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
                    sat.nominal_slot = pos.copy()
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
        """Called by POST /api/maneuver/schedule.

        Validates each burn against operational constraints before scheduling.
        ΔV arrives from API in km/s — converted to m/s for engine validation.
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

        # Seed effective_last_burn_time from executed history AND queued future burns.
        # This prevents a multi-burn sequence from violating the 600 s cooldown among
        # its own burns (e.g. B1 at T+700 s and B2 at T+1200 s are only 500 s apart).
        effective_last_burn = sat.last_burn_time
        if sat.maneuver_queue:
            last_queued_time = max(
                datetime.fromisoformat(b["burnTime"].replace("Z", "+00:00"))
                for b in sat.maneuver_queue
            )
            if effective_last_burn is None or last_queued_time > effective_last_burn:
                effective_last_burn = last_queued_time

        for burn in sequence:
            dv_kms = burn["deltaV_vector"]
            dv_vec = np.array([dv_kms["x"], dv_kms["y"], dv_kms["z"]])
            dv_magnitude_ms = float(np.linalg.norm(dv_vec)) * 1000.0  # km/s → m/s

            burn_time = datetime.fromisoformat(
                burn["burnTime"].replace("Z", "+00:00")
            )

            # Ground station LOS check
            has_los = self.gs_network.check_line_of_sight(
                sat.position, burn_time
            )

            # Constraint validation — use sequence-aware last burn time so cooldown
            # is enforced both against executed history and earlier burns in this batch.
            is_valid, reason = self.planner.validate_burn(
                delta_v_magnitude_ms=dv_magnitude_ms,
                burn_time=burn_time,
                current_time=self.sim_time,
                last_burn_time=effective_last_burn,
                has_los=has_los,
                fuel_kg=self.fuel_tracker.get_fuel(satellite_id),
            )

            if not is_valid:
                logger.warning(
                    "MANEUVER | %s | REJECTED | %s", satellite_id, reason
                )
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

            # Fuel sufficiency check
            if not self.fuel_tracker.sufficient_fuel(satellite_id, dv_magnitude_ms):
                logger.warning(
                    "MANEUVER | %s | REJECTED | Insufficient fuel", satellite_id
                )
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

            # Advance effective last burn so the next burn in this sequence
            # is validated against cooldown from THIS burn, not an older one.
            effective_last_burn = burn_time

        # All burns validated — queue them
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
        """Advance simulation clock and execute the full 7-step tick."""
        old_time = self.sim_time
        target_time = self.sim_time + timedelta(seconds=step_seconds)
        collisions_detected = 0
        maneuvers_executed = 0

        # ── Step 1: Propagate all objects ────────────────────────────────
        for sat in self.satellites.values():
            sat.state_vector = self.propagator.propagate(
                sat.state_vector, step_seconds
            )

        for deb in self.debris.values():
            deb.state_vector = self.propagator.propagate(
                deb.state_vector, step_seconds
            )

        # ── Step 2: Execute scheduled maneuvers ─────────────────────────
        for sat_id, sat in self.satellites.items():
            remaining_queue = []
            for burn in sat.maneuver_queue:
                burn_time = datetime.fromisoformat(
                    burn["burnTime"].replace("Z", "+00:00")
                )
                if burn_time < old_time:
                    # Stale burn: window already passed without execution (e.g. after
                    # a large time skip). Silently discard — do not execute retroactively.
                    logger.warning(
                        "MANEUVER | %s | Discarding stale burn %s (scheduled %s, now %s)",
                        sat_id, burn.get("burn_id", "BURN"),
                        burn_time.isoformat(), old_time.isoformat(),
                    )
                    continue
                if burn_time <= target_time:
                    dv = burn["deltaV_vector"]
                    dv_vec = np.array([dv["x"], dv["y"], dv["z"]])  # km/s
                    dv_mag_ms = float(np.linalg.norm(dv_vec)) * 1000.0

                    # Apply ΔV to satellite velocity (km/s)
                    sat.velocity = sat.velocity + dv_vec

                    # Deduct fuel
                    self.fuel_tracker.consume(sat_id, dv_mag_ms)
                    sat.fuel_kg = self.fuel_tracker.get_fuel(sat_id)
                    sat.last_burn_time = burn_time
                    sat.status = "EVADING"
                    maneuvers_executed += 1

                    logger.info(
                        "MANEUVER | %s | %s | ΔV=%.4f m/s | Fuel remaining: %.2f kg",
                        sat_id, burn.get("burn_id", "BURN"),
                        dv_mag_ms, sat.fuel_kg,
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

        # ── Step 3: Conjunction assessment & collision detection ─────────
        self.active_cdms = self.assessor.assess(
            {s.id: s.state_vector for s in self.satellites.values()},
            {d.id: d.state_vector for d in self.debris.values()},
            current_time=target_time,
        )

        # Check for actual collisions at current positions
        for sat in self.satellites.values():
            for deb in self.debris.values():
                dist = float(np.linalg.norm(sat.position - deb.position))
                if dist < CONJUNCTION_THRESHOLD_KM:
                    collisions_detected += 1
                    logger.critical(
                        "COLLISION | %s × %s | Time:%s | Distance:%.4f km",
                        sat.id, deb.id, target_time.isoformat(), dist,
                    )
                    self.collision_log.append({
                        "satellite_id": sat.id,
                        "debris_id": deb.id,
                        "time": target_time.isoformat(),
                        "distance_km": dist,
                    })

        # ── Step 4: Station-keeping status ───────────────────────────────
        for sat in self.satellites.values():
            if sat.status == "EOL":
                continue  # terminal — never overwrite
            slot_offset = float(np.linalg.norm(sat.position - sat.nominal_slot))
            in_slot = slot_offset <= STATION_KEEPING_RADIUS_KM
            if sat.status == "EVADING":
                # Transition out of EVADING once all queued burns have fired.
                # Without this the satellite would be EVADING forever after any maneuver.
                if not sat.maneuver_queue:
                    sat.status = "NOMINAL" if in_slot else "RECOVERING"
            elif in_slot:
                sat.status = "NOMINAL"
            else:
                sat.status = "RECOVERING"

        # ── Step 5: Auto-plan maneuvers for CRITICAL conjunctions ────────
        for cdm in self.active_cdms:
            if cdm.risk != "CRITICAL":
                continue
            sat = self.satellites.get(cdm.satellite_id)
            deb = self.debris.get(cdm.debris_id)
            if sat is None or deb is None:
                continue
            # Don't double-queue if already evading
            if sat.status == "EVADING" and sat.maneuver_queue:
                continue

            burns = self.planner.plan_evasion(
                satellite=sat, debris=deb,
                tca=cdm.tca, miss_distance_km=cdm.miss_distance_km,
                current_time=target_time,
            )

            # Check LOS for scheduled burns, defer if in blackout
            for burn in burns:
                bt = datetime.fromisoformat(
                    burn["burnTime"].replace("Z", "+00:00")
                )
                if not self.gs_network.check_line_of_sight(sat.position, bt):
                    # Pre-schedule before blackout — move burn earlier
                    burn["burnTime"] = (
                        target_time + timedelta(seconds=SIGNAL_LATENCY_S + 60)
                    ).isoformat()

            sat.maneuver_queue.extend(burns)
            sat.status = "EVADING"

        # ── Step 6: EOL threshold check ──────────────────────────────────
        for sat_id, sat in self.satellites.items():
            if self.fuel_tracker.is_eol(sat_id) and sat.status != "EOL":
                sat.status = "EOL"
                logger.warning(
                    "EOL | %s | Fuel=%.2f kg ≤ threshold (%.1f kg) | "
                    "Graveyard maneuver scheduled",
                    sat_id, self.fuel_tracker.get_fuel(sat_id),
                    EOL_FUEL_THRESHOLD_KG,
                )

        # ── Step 7: Advance clock ────────────────────────────────────────
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
        """Called by GET /api/visualization/snapshot.

        Returns current state for frontend rendering.
        Satellite positions converted to lat/lon.
        Debris cloud uses flattened [id, lat, lon, alt] tuples.
        """
        satellites = []
        for sat in self.satellites.values():
            lat, lon, alt = _eci_to_lla(sat.position)
            satellites.append({
                "id": sat.id,
                "lat": round(lat, 3),
                "lon": round(lon, 3),
                "alt_km": round(alt, 1),
                "fuel_kg": round(self.fuel_tracker.get_fuel(sat.id), 2),
                "status": sat.status,
            })

        debris_cloud = []
        for deb in self.debris.values():
            lat, lon, alt = _eci_to_lla(deb.position)
            debris_cloud.append([deb.id, round(lat, 2), round(lon, 2), round(alt, 1)])

        total_queued = sum(len(s.maneuver_queue) for s in self.satellites.values())

        return {
            "timestamp": self.sim_time.isoformat(),
            "satellites": satellites,
            "debris_cloud": debris_cloud,
            "active_cdm_count": len(self.active_cdms),
            "maneuver_queue_depth": total_queued,
        }
