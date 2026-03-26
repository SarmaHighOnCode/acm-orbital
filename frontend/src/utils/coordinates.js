/**
 * coordinates.js — Geographic Coordinate Conversion
 * Owner: Dev 3 (Frontend)
 */

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
