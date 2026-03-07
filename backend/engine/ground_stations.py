"""
ground_stations.py — Line-of-Sight Visibility Calculation
═════════════════════════════════════════════════════════
Determines if a satellite is visible from any ground station
based on elevation angle above the local horizon.
Owner: Dev 1 (Physics Engine)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from config import R_EARTH

logger = logging.getLogger("acm.engine.ground_stations")

# ── Ground Station Data ──────────────────────────────────────────────────
# Loaded from CSV or hardcoded fallback per PRD Section 4.6

GROUND_STATIONS = [
    {"id": "GS-001", "name": "ISTRAC_Bengaluru",
     "lat": 13.0333, "lon": 77.5167, "elev_m": 820, "min_elev_deg": 5.0},
    {"id": "GS-002", "name": "Svalbard_Sat_Station",
     "lat": 78.2297, "lon": 15.4077, "elev_m": 400, "min_elev_deg": 5.0},
    {"id": "GS-003", "name": "Goldstone_Tracking",
     "lat": 35.4266, "lon": -116.89, "elev_m": 1000, "min_elev_deg": 10.0},
    {"id": "GS-004", "name": "Punta_Arenas",
     "lat": -53.15, "lon": -70.9167, "elev_m": 30, "min_elev_deg": 5.0},
    {"id": "GS-005", "name": "IIT_Delhi_Ground_Node",
     "lat": 28.545, "lon": 77.1926, "elev_m": 225, "min_elev_deg": 15.0},
    {"id": "GS-006", "name": "McMurdo_Station",
     "lat": -77.8463, "lon": 166.6682, "elev_m": 10, "min_elev_deg": 5.0},
]


class GroundStationNetwork:
    """Manages ground station LOS calculations."""

    def __init__(self, stations: list[dict] | None = None):
        self.stations = stations or GROUND_STATIONS

    def check_line_of_sight(
        self, sat_eci_position: np.ndarray, timestamp: datetime
    ) -> bool:
        """Check if satellite is visible from ANY ground station.

        Args:
            sat_eci_position: [x, y, z] in km (ECI J2000)
            timestamp: Current simulation time (for Earth rotation)

        Returns:
            True if at least one ground station has LOS
        """
        # TODO: Dev 1 — implement elevation angle calculation:
        #   1. Convert ground station geodetic (lat, lon, alt) to ECEF
        #   2. Rotate to ECI using GMST at timestamp
        #   3. Compute elevation angle from station to satellite
        #   4. Compare against station's min_elev_deg
        return True  # Stub: assume LOS always available

    @staticmethod
    def compute_elevation(
        sat_eci: np.ndarray, station: dict, timestamp: datetime
    ) -> float:
        """Compute elevation angle of satellite as seen from ground station.

        Args:
            sat_eci: Satellite ECI position [x,y,z] in km
            station: Ground station dict with lat, lon, elev_m, min_elev_deg
            timestamp: For Earth rotation (GMST calculation)

        Returns:
            Elevation angle in degrees above local horizon

        TODO: Dev 1 — implement ECEF→ECI rotation and elevation formula.
        """
        return 90.0  # Stub
