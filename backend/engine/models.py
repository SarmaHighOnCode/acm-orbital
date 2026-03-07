"""
models.py — Data Classes for Orbital Objects
═════════════════════════════════════════════
Core data structures used throughout the physics engine.
Owner: Dev 1 (Physics Engine)

All positions in km (ECI J2000). All velocities in km/s.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class OrbitalObject:
    """Base class for any tracked orbital object."""
    id: str
    obj_type: str                          # "SATELLITE" or "DEBRIS"
    position: np.ndarray                   # [x, y, z] km, ECI
    velocity: np.ndarray                   # [vx, vy, vz] km/s, ECI
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def state_vector(self) -> np.ndarray:
        """Combined [x, y, z, vx, vy, vz] state vector."""
        return np.concatenate([self.position, self.velocity])

    @state_vector.setter
    def state_vector(self, sv: np.ndarray):
        self.position = sv[:3].copy()
        self.velocity = sv[3:].copy()


@dataclass
class Satellite(OrbitalObject):
    """A satellite in the constellation."""
    obj_type: str = "SATELLITE"
    fuel_kg: float = 50.0                  # Current propellant mass
    dry_mass_kg: float = 500.0             # Empty satellite mass
    nominal_slot: np.ndarray = field(default_factory=lambda: np.zeros(3))
    status: str = "NOMINAL"                # NOMINAL | EVADING | RECOVERING | EOL
    last_burn_time: datetime | None = None # For 600s cooldown enforcement
    maneuver_queue: list = field(default_factory=list)

    @property
    def wet_mass_kg(self) -> float:
        """Current total mass (dry + remaining fuel)."""
        return self.dry_mass_kg + self.fuel_kg


@dataclass
class Debris(OrbitalObject):
    """A tracked debris object."""
    obj_type: str = "DEBRIS"


@dataclass
class CDM:
    """Conjunction Data Message — a collision warning."""
    satellite_id: str
    debris_id: str
    tca: datetime                          # Time of Closest Approach
    miss_distance_km: float                # Minimum distance at TCA
    risk: str                              # "GREEN" | "YELLOW" | "RED" | "CRITICAL"
    relative_velocity_km_s: float = 0.0
