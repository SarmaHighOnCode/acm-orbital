/**
 * GroundTrack.jsx — 2D Canvas Mercator Projection
 * Owner: Dev 3 (Frontend)
 *
 * Uses Canvas 2D API (NOT SVG, NOT DOM divs) for performance.
 * Renders: satellite markers, grid overlay, status legend.
 */

import React, { useRef, useEffect } from 'react';
import useStore from '../store';
import { geoToMercator } from '../utils/coordinates';

const STATUS_COLORS_CSS = {
  NOMINAL: '#00ff88',
  EVADING: '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL: '#ff3355',
};

const trailHistory = new Map();
const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;

function getDayOfYear(d) {
  const start = new Date(d.getFullYear(), 0, 0);
  return Math.floor((d - start) / 86400000);
}

function drawTerminator(ctx, w, h, timestamp) {
  if (!timestamp) return;
  const d = new Date(timestamp);
  const hourUTC = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  const sunLonRad = -(hourUTC * 15) * DEG2RAD;
  const sunLatRad = 23.44 * DEG2RAD * Math.sin((2 * Math.PI * (getDayOfYear(d) - 81)) / 365);

  const pts = [];
  for (let px = 0; px <= w; px += 2) {
    const lonDeg = (px / w) * 360 - 180;
    const latRad = Math.atan2(-Math.cos(lonDeg * DEG2RAD - sunLonRad), Math.tan(sunLatRad));
    const { x, y } = geoToMercator(latRad * RAD2DEG, lonDeg, w, h);
    pts.push({ x, y });
  }
  ctx.beginPath();
  pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  if (sunLatRad >= 0) { ctx.lineTo(w, h); ctx.lineTo(0, h); }
  else { ctx.lineTo(w, 0); ctx.lineTo(0, 0); }
  ctx.closePath();
  ctx.fillStyle = 'rgba(0, 0, 20, 0.3)';
  ctx.fill();
  ctx.beginPath();
  pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.strokeStyle = 'rgba(255, 200, 50, 0.25)';
  ctx.lineWidth = 1;
  ctx.stroke();
}

function updateTrails(satellites) {
  const activeIds = new Set(satellites.map(s => s.id));
  for (const sat of satellites) {
    let trail = trailHistory.get(sat.id);
    if (!trail) { trail = []; trailHistory.set(sat.id, trail); }
    trail.push({ lat: sat.lat, lon: sat.lon });
    if (trail.length > 2700) trail.splice(0, trail.length - 2700);
  }
  for (const id of trailHistory.keys()) {
    if (!activeIds.has(id)) trailHistory.delete(id);
  }
}

function drawTrails(ctx, satellites, w, h) {
  ctx.lineWidth = 1;
  for (const sat of satellites) {
    const trail = trailHistory.get(sat.id);
    if (!trail || trail.length < 2) continue;
    const color = STATUS_COLORS_CSS[sat.status] || '#00ff88';
    const len = trail.length;
    for (let i = 1; i < len; i++) {
      const { x: x0, y: y0 } = geoToMercator(trail[i - 1].lat, trail[i - 1].lon, w, h);
      const { x: x1, y: y1 } = geoToMercator(trail[i].lat, trail[i].lon, w, h);
      if (Math.abs(x1 - x0) > w * 0.5) continue;
      const alpha = 0.05 + (i / (len - 1)) * 0.55;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.strokeStyle = color + Math.round(alpha * 255).toString(16).padStart(2, '0');
      ctx.stroke();
    }
  }
}

function drawPredictions(ctx, satellites, w, h) {
  const INC = 55 * DEG2RAD, PERIOD = 5400, EARTH_ROT = 0.004178, STEPS = 20;
  const DT = (90 * 60) / STEPS;
  ctx.lineWidth = 1;
  for (const sat of satellites) {
    const color = STATUS_COLORS_CSS[sat.status] || '#00ff88';
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    const sinRatio = Math.max(-1, Math.min(1, Math.sin(sat.lat * DEG2RAD) / Math.sin(INC)));
    let angle = Math.asin(sinRatio);
    let lon = sat.lon;
    const pts = [geoToMercator(sat.lat, sat.lon, w, h)];
    for (let s = 1; s <= STEPS; s++) {
      angle += (2 * Math.PI * DT) / PERIOD;
      const predLat = Math.asin(Math.sin(INC) * Math.sin(angle)) * RAD2DEG;
      lon -= EARTH_ROT * DT;
      const predLon = ((lon + 180) % 360 + 360) % 360 - 180;
      pts.push(geoToMercator(predLat, predLon, w, h));
    }
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.3)`;
    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      if (i === 0 || Math.abs(pts[i].x - pts[i - 1].x) > w * 0.5) ctx.moveTo(pts[i].x, pts[i].y);
      else ctx.lineTo(pts[i].x, pts[i].y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

export default function GroundTrack() {
  const canvasRef = useRef(null);
  const { satellites, timestamp } = useStore();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const { width, height } = canvas.getBoundingClientRect();
    canvas.width = width;
    canvas.height = height;

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, width, height);

    // Terminator (day/night boundary)
    drawTerminator(ctx, width, height, timestamp);

    // Grid lines
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 12; i++) {
      const x = (i / 12) * width;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let i = 0; i <= 6; i++) {
      const y = (i / 6) * height;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    // Axis labels
    ctx.fillStyle = '#374151';
    ctx.font = '9px Inter, monospace';
    ctx.textAlign = 'center';
    for (let lon = -180; lon <= 180; lon += 60) {
      const { x } = geoToMercator(0, lon, width, height);
      ctx.fillText(`${lon}°`, x, height - 3);
    }
    ctx.textAlign = 'right';
    for (let lat = -60; lat <= 60; lat += 30) {
      const { y } = geoToMercator(lat, 0, width, height);
      ctx.fillText(`${lat}°`, width - 3, y + 3);
    }

    if (!satellites.length) {
      ctx.fillStyle = '#6b7280';
      ctx.font = '12px Inter, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('Ground Track — awaiting satellite data', 12, 20);
      return;
    }

    updateTrails(satellites);
    drawTrails(ctx, satellites, width, height);
    drawPredictions(ctx, satellites, width, height);

    // Plot satellites using lat/lon directly from API
    for (const sat of satellites) {
      const { x: px, y: py } = geoToMercator(sat.lat, sat.lon, width, height);

      const color = STATUS_COLORS_CSS[sat.status] || '#00ff88';

      // Glow
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = color + '33';
      ctx.fill();

      // Dot
      ctx.beginPath();
      ctx.arc(px, py, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }

    // Header label
    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`Ground Track — ${satellites.length} satellites`, 12, 16);
  }, [satellites, timestamp]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ display: 'block' }}
    />
  );
}
