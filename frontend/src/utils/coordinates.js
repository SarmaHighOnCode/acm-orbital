/**
 * coordinates.js — ECI to Geographic Coordinate Conversion
 * Owner: Dev 3 (Frontend)
 */

const R_EARTH = 6378.137; // km

/**
 * Convert ECI [x, y, z] position to geodetic [lat, lon, alt].
 * Simplified — does not account for Earth rotation (GMST).
 * TODO: Dev 3 — Add GMST correction for accurate lon.
 *
 * @param {number} x - ECI x in km
 * @param {number} y - ECI y in km
 * @param {number} z - ECI z in km
 * @returns {{ lat: number, lon: number, alt: number }}
 */
export function eciToGeodetic(x, y, z) {
  const r = Math.sqrt(x * x + y * y + z * z);
  const lat = Math.asin(z / r) * (180 / Math.PI);
  const lon = Math.atan2(y, x) * (180 / Math.PI);
  const alt = r - R_EARTH;
  return { lat, lon, alt };
}

/**
 * Convert geodetic [lat, lon] to Mercator pixel coordinates.
 *
 * @param {number} lat - Latitude in degrees
 * @param {number} lon - Longitude in degrees
 * @param {number} width - Canvas width
 * @param {number} height - Canvas height
 * @returns {{ x: number, y: number }}
 */
export function geoToMercator(lat, lon, width, height) {
  const x = ((lon + 180) / 360) * width;
  const y = ((90 - lat) / 180) * height;
  return { x, y };
}
