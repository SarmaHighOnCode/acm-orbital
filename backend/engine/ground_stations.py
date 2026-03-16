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
from datetime import datetime, timezone
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
        """Check if satellite is visible from ANY ground station."""
        for gs in self.stations:
            if self.compute_elevation(sat_eci_position, gs, timestamp) >= gs["min_elev_deg"]:
                return True
        return False

    @staticmethod
    def compute_elevation(
        sat_eci: np.ndarray, station: dict, timestamp: datetime
    ) -> float:
        """Compute elevation angle of satellite as seen from ground station."""
        # 1. Convert Geodetic (lat, lon, alt) to ECEF
        lat = np.radians(station["lat"])
        lon = np.radians(station["lon"])
        alt = station["elev_m"] / 1000.0  # km
        
        cos_lat = np.cos(lat)
        r_gs = (R_EARTH + alt)
        gs_ecef = r_gs * np.array([
            cos_lat * np.cos(lon),
            cos_lat * np.sin(lon),
            np.sin(lat)
        ])

        # 2. Rotate GS ECEF to ECI using Greenwich Mean Sidereal Time (GMST)
        # J2000.0 Epoch: 2000-01-01 12:00:00 UTC (JD 2451545.0)
        j2000_epoch = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        dt_seconds = (timestamp - j2000_epoch).total_seconds()
        
        # Standard GMST formula: GMST_0 + rate * dt
        # GMST at J2000 noon is approx 18.697 hours = 280.46 degrees
        # Earth rotation rate is approx 360.985 degrees per day
        gmst_deg = 280.46061837 + 360.98564736629 * (dt_seconds / 86400.0)
        rotation_angle = np.radians(gmst_deg % 360.0)
        
        c, s = np.cos(rotation_angle), np.sin(rotation_angle)
        rot_matrix = np.array([
            [c, -s, 0],
            [s,  c, 0],
            [0,  0, 1]
        ])
        gs_eci = rot_matrix @ gs_ecef

        # 3. Compute range vector and its elevation
        range_vector = sat_eci - gs_eci
        range_norm = np.linalg.norm(range_vector)
        
        # Local vertical is approximately the unit vector of gs_eci
        local_vertical = gs_eci / np.linalg.norm(gs_eci)
        
        # sin(el) = (range . vertical) / |range|
        sin_el = np.dot(range_vector, local_vertical) / range_norm
        elevation_deg = np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))
        
        return float(elevation_deg)
