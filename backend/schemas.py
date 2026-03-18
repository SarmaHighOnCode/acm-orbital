"""
schemas.py — Pydantic Request/Response Models (API Contract)
════════════════════════════════════════════════════════════
FROZEN AFTER DAY 1. These models define the exact JSON contract between
the grading system and our API. They also serve as the bridge between
Dev 2 (API Layer) and Dev 1 (Physics Engine).

All field names match the problem statement PDF verbatim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Shared Primitives ────────────────────────────────────────────────────

class Vector3D(BaseModel):
    """3D vector in ECI J2000 frame."""
    x: float
    y: float
    z: float


# ── Telemetry ────────────────────────────────────────────────────────────

class TelemetryObject(BaseModel):
    """Single orbital object state vector."""
    id: str
    type: Literal["SATELLITE", "DEBRIS"]
    r: Vector3D                        # Position in km (ECI)
    v: Vector3D                        # Velocity in km/s (ECI)


class TelemetryRequest(BaseModel):
    """POST /api/telemetry — request body."""
    timestamp: datetime
    objects: list[TelemetryObject]


class TelemetryResponse(BaseModel):
    """POST /api/telemetry — response body."""
    status: Literal["ACK"] = "ACK"
    processed_count: int
    active_cdm_warnings: int


# ── Maneuver Scheduling ─────────────────────────────────────────────────

class BurnCommand(BaseModel):
    """Single burn in a maneuver sequence."""
    burn_id: str
    burnTime: datetime
    deltaV_vector: Vector3D            # Delta-V in km/s (API unit)


class ManeuverRequest(BaseModel):
    """POST /api/maneuver/schedule — request body."""
    satelliteId: str
    maneuver_sequence: list[BurnCommand]


class ManeuverValidation(BaseModel):
    """Validation result for a maneuver request."""
    ground_station_los: bool
    sufficient_fuel: bool
    projected_mass_remaining_kg: float


class ManeuverResponse(BaseModel):
    """POST /api/maneuver/schedule — response body."""
    status: Literal["SCHEDULED", "REJECTED"]
    validation: ManeuverValidation


# ── Simulation Step ──────────────────────────────────────────────────────

class SimulateStepRequest(BaseModel):
    """POST /api/simulate/step — request body."""
    step_seconds: float = Field(gt=0)


class SimulateStepResponse(BaseModel):
    """POST /api/simulate/step — response body."""
    status: Literal["STEP_COMPLETE"] = "STEP_COMPLETE"
    new_timestamp: datetime
    collisions_detected: int
    maneuvers_executed: int


# ── Visualization Snapshot ───────────────────────────────────────────────

class SatelliteSnapshot(BaseModel):
    """Single satellite in the visualization snapshot (geodetic coords)."""
    id: str
    lat: float                         # Geodetic latitude (degrees)
    lon: float                         # Geodetic longitude (degrees)
    alt_km: float                      # Altitude above WGS84 ellipsoid (km)
    fuel_kg: float
    status: Literal["NOMINAL", "EVADING", "RECOVERING", "EOL"]
    uptime_score: float = 1.0
    time_outside_box_s: float = 0.0
    queued_burns: int = 0


class CDMSnapshot(BaseModel):
    """Single CDM summary for the frontend bullseye plot."""
    satellite_id: str
    debris_id: str
    tca: str                           # ISO-8601 datetime string
    miss_distance_km: float
    risk: str
    relative_velocity_km_s: float


class SnapshotResponse(BaseModel):
    """GET /api/visualization/snapshot — response body."""
    timestamp: datetime
    satellites: list[SatelliteSnapshot]
    debris_cloud: list[list]           # Flattened tuples: [ID, lat, lon, alt]
    active_cdm_count: int
    maneuver_queue_depth: int
    cdms: list[CDMSnapshot] = []
    maneuver_log: list[dict] = []      # Last 50 maneuver execution events
    collision_count: int = 0
