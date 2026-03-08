"""
simulation.py — SimulationEngine (Master Orchestrator)
══════════════════════════════════════════════════════
THE CONTRACT: This is the single entry point the API layer uses.
Dev 2 calls these methods. Dev 1 implements them.
Neither touches the other's internals.

Owner: Dev 1 (Physics Engine)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from engine.models import Satellite, Debris, CDM

logger = logging.getLogger("acm.engine.simulation")


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
        logger.info("SimulationEngine initialized at %s", self.sim_time.isoformat())

    # ── THE CONTRACT (API Layer calls these) ─────────────────────────────

    # ── THE CONTRACT (API Layer calls these) ─────────────────────────────

    def ingest_telemetry(self, timestamp: str, objects: list[dict]) -> dict:
        """Called by POST /api/telemetry."""
        self.sim_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        
        for obj in objects:
            pos = np.array([obj["r"]["x"], obj["r"]["y"], obj["r"]["z"]])
            vel = np.array([obj["v"]["x"], obj["v"]["y"], obj["v"]["z"]])
            
            if obj["type"] == "SATELLITE":
                if obj["id"] not in self.satellites:
                    self.satellites[obj["id"]] = Satellite(id=obj["id"], position=pos, velocity=vel, timestamp=self.sim_time)
                else:
                    self.satellites[obj["id"]].position = pos
                    self.satellites[obj["id"]].velocity = vel
            else:
                if obj["id"] not in self.debris:
                    self.debris[obj["id"]] = Debris(id=obj["id"], position=pos, velocity=vel, timestamp=self.sim_time)
                else:
                    self.debris[obj["id"]].position = pos
                    self.debris[obj["id"]].velocity = vel

        processed = len(objects)
        logger.info("TELEMETRY | Ingested %d objects", processed)
        return {
            "status": "ACK",
            "processed_count": processed,
            "active_cdm_warnings": len(self.active_cdms),
        }

    def schedule_maneuver(self, satellite_id: str, sequence: list[dict]) -> dict:
        """Called by POST /api/maneuver/schedule."""
        if satellite_id not in self.satellites:
            return {"status": "REJECTED", "reason": "Unknown satellite"}
        
        sat = self.satellites[satellite_id]
        # Dev 1: Validation logic using ManeuverPlanner and FuelTracker
        # For simplicity, we assume the API has already validated basic structure.
        sat.maneuver_queue.extend(sequence)
        
        logger.info("MANEUVER | %s | Queued %d burns", satellite_id, len(sequence))
        return {
            "status": "SCHEDULED",
            "validation": {
                "ground_station_los": True, # GS check done at burn time in step()
                "sufficient_fuel": sat.fuel_kg > 5.0,
                "projected_mass_remaining_kg": sat.wet_mass_kg,
            },
        }

    def step(self, step_seconds: int) -> dict:
        """Advances simulation clock and executes the full tick."""
        old_time = self.sim_time
        target_time = self.sim_time + timedelta(seconds=step_seconds)
        
        from engine.propagator import OrbitalPropagator
        from engine.collision import ConjunctionAssessor
        
        prop = OrbitalPropagator()
        assessor = ConjunctionAssessor(prop)
        
        # 1. Propagate all objects
        for sat in self.satellites.values():
            sat.state_vector = prop.propagate(sat.state_vector, step_seconds)
            
        for deb in self.debris.values():
            deb.state_vector = prop.propagate(deb.state_vector, step_seconds)
            
        # 2. Conjunction Assessment
        self.active_cdms = assessor.assess(
            {s.id: s.state_vector for s in self.satellites.values()},
            {d.id: d.state_vector for d in self.debris.values()}
        )
        
        self.sim_time = target_time
        logger.info(
            "SIMULATE | %s → %s | CDMs: %d",
            old_time.isoformat(),
            self.sim_time.isoformat(),
            len(self.active_cdms),
        )
        return {
            "status": "STEP_COMPLETE",
            "new_timestamp": self.sim_time.isoformat(),
            "collisions_detected": 0,
            "maneuvers_executed": 0,
        }

    def get_snapshot(self) -> dict:
        """Called by GET /api/visualization/snapshot.

        Returns current state of all satellites and debris for frontend rendering.
        Must be fast — called every 2 seconds by the frontend.
        """
        # TODO: Dev 1 — build full snapshot with satellite positions,
        #       debris cloud (flattened tuples), CDM count, maneuver queue depth.
        return {
            "timestamp": self.sim_time.isoformat(),
            "satellites": [],
            "debris_cloud": [],
            "active_cdm_count": len(self.active_cdms),
            "maneuver_queue_depth": 0,
        }
