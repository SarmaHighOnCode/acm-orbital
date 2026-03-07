/**
 * constants.js — Shared Rendering Constants
 * Owner: Dev 3 (Frontend)
 */

// Earth
export const R_EARTH_KM = 6378.137;
export const SCALE_FACTOR = 1 / 1000; // km to Three.js units

// Satellite status colors (hex)
export const STATUS_COLORS = {
  NOMINAL: 0x00ff88,
  EVADING: 0xffaa00,
  RECOVERING: 0x3b82f6,
  EOL: 0xff3355,
};

// Conjunction risk colors
export const RISK_COLORS = {
  GREEN: '#00ff88',
  YELLOW: '#ffaa00',
  RED: '#ff3355',
  CRITICAL: '#ff0000',
};

// Polling
export const SNAPSHOT_POLL_MS = 2000;

// Rendering
export const MAX_DEBRIS_POINTS = 15000;
export const MAX_SATELLITES = 100;
