/**
 * GroundTrack.jsx — 2D Canvas Equirectangular Ground Track Map
 * Owner: Dev 3 (Frontend)
 *
 * CENTERPIECE MODULE — highest visual impact.
 * PDF Section 6.2 Requirements:
 *   1. Real-time satellite location markers               [x]
 *   2. 90-min historical trailing path (fading polyline)  [x]
 *   3. 90-min predicted dashed trajectory                 [x]
 *   4. Dynamic Terminator Line shadow overlay             [x]
 *   5. Debris cloud rendered via Canvas (NOT DOM)         [x]
 * Extra:
 *   - Continental outlines (simplified coastline vertices)
 *   - Ground station markers (6 triangles from PRD §4.6)
 *   - Click-to-select satellite
 */

import React, { useRef, useEffect, useCallback } from 'react';
import useStore from '../store';
import { geoToMercator } from '../utils/coordinates';

const STATUS_COLORS = {
  NOMINAL: '#00ff88',
  EVADING: '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL: '#ff3355',
};

// PRD §4.6 Ground Station locations
const GROUND_STATIONS = [
  { id: 'GS-001', name: 'Bengaluru', lat: 13.0333, lon: 77.5167 },
  { id: 'GS-002', name: 'Svalbard', lat: 78.2297, lon: 15.4077 },
  { id: 'GS-003', name: 'Goldstone', lat: 35.4266, lon: -116.89 },
  { id: 'GS-004', name: 'P. Arenas', lat: -53.15, lon: -70.9167 },
  { id: 'GS-005', name: 'IIT Delhi', lat: 28.545, lon: 77.1926 },
  { id: 'GS-006', name: 'McMurdo', lat: -77.8463, lon: 166.6682 },
];

// Simplified continental outlines (major coastline vertices, lat/lon)
const CONTINENTS = [
  // North America
  [
    [49,-125],[60,-140],[70,-160],[72,-155],[71,-135],[60,-110],
    [49,-95],[45,-82],[30,-82],[25,-80],[30,-85],[29,-90],
    [26,-97],[32,-117],[37,-122],[48,-124],[49,-125],
  ],
  // South America
  [
    [12,-72],[7,-77],[-5,-81],[-15,-75],[-23,-70],[-40,-65],
    [-55,-68],[-56,-70],[-52,-75],[-45,-65],[-35,-57],[-23,-43],
    [-7,-35],[5,-52],[10,-62],[12,-72],
  ],
  // Europe
  [
    [36,-10],[43,-9],[48,-5],[51,2],[54,8],[57,10],[60,5],
    [63,10],[65,14],[70,20],[70,30],[60,30],[55,22],[50,14],
    [45,12],[40,18],[37,22],[36,28],[36,-10],
  ],
  // Africa
  [
    [37,-2],[35,10],[32,33],[30,33],[12,44],[2,42],[-12,40],
    [-26,33],[-35,18],[-34,20],[-30,30],[-22,35],[-10,40],
    [5,10],[5,-5],[15,-17],[22,-17],[36,-5],[37,-2],
  ],
  // Asia
  [
    [42,27],[40,50],[42,60],[50,55],[52,60],[55,70],[50,80],
    [45,80],[35,75],[25,67],[20,73],[22,88],[22,97],[10,98],
    [1,104],[-8,115],[-8,140],[5,120],[20,110],[22,115],
    [30,122],[40,120],[45,135],[50,140],[55,135],[60,140],
    [65,170],[70,180],[75,100],[73,80],[65,60],[60,50],
    [45,42],[40,30],[42,27],
  ],
  // Australia
  [
    [-12,131],[-12,136],[-16,136],[-14,141],[-20,149],[-25,153],
    [-28,153],[-35,151],[-39,146],[-38,141],[-32,134],[-32,128],
    [-22,114],[-15,124],[-12,131],
  ],
];

function drawTerminator(ctx, w, h, timestamp) {
  if (!timestamp) return;
  const d = new Date(timestamp);
  const dayOfYear = Math.floor(
    (d - new Date(d.getUTCFullYear(), 0, 0)) / 86400000
  );
  const declination = -23.44 * Math.cos((2 * Math.PI * (dayOfYear + 10)) / 365);
  const hourAngle =
    ((d.getUTCHours() + d.getUTCMinutes() / 60) / 24) * 360 - 180;

  ctx.save();
  ctx.beginPath();

  for (let lon = -180; lon <= 180; lon += 2) {
    const lonDiff = lon - hourAngle;
    const terminatorLat =
      Math.atan(
        -Math.cos((lonDiff * Math.PI) / 180) /
          Math.tan((declination * Math.PI) / 180)
      ) *
      (180 / Math.PI);

    const { x, y } = geoToMercator(terminatorLat, lon, w, h);
    if (lon === -180) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }

  if (declination >= 0) {
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
  } else {
    ctx.lineTo(w, 0);
    ctx.lineTo(0, 0);
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.fill();
  ctx.restore();

  // Terminator line stroke
  ctx.strokeStyle = 'rgba(255, 200, 50, 0.25)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let lon = -180; lon <= 180; lon += 2) {
    const lonDiff = lon - hourAngle;
    const terminatorLat =
      Math.atan(
        -Math.cos((lonDiff * Math.PI) / 180) /
          Math.tan((declination * Math.PI) / 180)
      ) *
      (180 / Math.PI);
    const { x, y } = geoToMercator(terminatorLat, lon, w, h);
    if (lon === -180) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

/**
 * Simple linear prediction from last two history points for ~90 minutes.
 */
function predictTrack(history) {
  if (!history || history.length < 2) return [];
  const last = history[history.length - 1];
  const prev = history[history.length - 2];
  const dlat = last.lat - prev.lat;
  let dlon = last.lon - prev.lon;
  if (dlon > 180) dlon -= 360;
  if (dlon < -180) dlon += 360;

  const points = [];
  for (let i = 1; i <= 54; i++) {
    let pLon = last.lon + dlon * i;
    const pLat = Math.max(-89, Math.min(89, last.lat + dlat * i));
    pLon = ((pLon + 180) % 360 + 360) % 360 - 180;
    points.push({ lat: pLat, lon: pLon });
  }
  return points;
}

export default function GroundTrack() {
  const canvasRef = useRef(null);
  const { satellites, debrisCloud, timestamp, cdms } = useStore();
  const satHistory = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const setSelectedSatellite = useStore((s) => s.setSelectedSatellite);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;

    // ── Background ──
    ctx.fillStyle = '#070d1a';
    ctx.fillRect(0, 0, w, h);

    // ── Continental outlines ──
    ctx.strokeStyle = '#162040';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#0e1a2e';
    for (const coast of CONTINENTS) {
      ctx.beginPath();
      for (let i = 0; i < coast.length; i++) {
        const { x, y } = geoToMercator(coast[i][0], coast[i][1], w, h);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    // ── Grid lines ──
    ctx.strokeStyle = '#0f1a2b';
    ctx.lineWidth = 0.5;
    for (let lon = -180; lon <= 180; lon += 30) {
      const { x } = geoToMercator(0, lon, w, h);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const { y } = geoToMercator(lat, 0, w, h);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // ── Terminator (day/night boundary) ──
    drawTerminator(ctx, w, h, timestamp);

    // ── Grid labels ──
    ctx.fillStyle = '#2a3a52';
    ctx.font = '9px Inter, monospace';
    ctx.textAlign = 'center';
    for (let lon = -180; lon <= 180; lon += 60) {
      const { x } = geoToMercator(0, lon, w, h);
      ctx.fillText(`${lon}\u00b0`, x, h - 3);
    }
    ctx.textAlign = 'right';
    for (let lat = -60; lat <= 60; lat += 30) {
      const { y } = geoToMercator(lat, 0, w, h);
      ctx.fillText(`${lat}\u00b0`, w - 3, y + 3);
    }

    // ── Ground station coverage circles + markers ──
    for (const gs of GROUND_STATIONS) {
      const { x, y } = geoToMercator(gs.lat, gs.lon, w, h);

      // Coverage circle (~2500 km radius at LEO 400km ≈ ~22° ground arc)
      const coverageRadiusDeg = 22;
      const rx = (coverageRadiusDeg / 360) * w;
      const ry = (coverageRadiusDeg / 180) * h;
      ctx.beginPath();
      ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(74, 144, 217, 0.04)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(74, 144, 217, 0.15)';
      ctx.lineWidth = 0.5;
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Triangle marker
      const s = 5;
      ctx.beginPath();
      ctx.moveTo(x, y - s);
      ctx.lineTo(x - s, y + s);
      ctx.lineTo(x + s, y + s);
      ctx.closePath();
      ctx.fillStyle = '#4a90d9';
      ctx.fill();
      ctx.strokeStyle = '#6abaff';
      ctx.lineWidth = 0.5;
      ctx.stroke();
      ctx.fillStyle = '#6abaff';
      ctx.font = '7px Inter, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(gs.name, x, y + s + 9);
    }

    // ── DEBRIS CLOUD (batched 1px dots — handles 10K+ at 60fps) ──
    if (debrisCloud.length > 0) {
      ctx.fillStyle = 'rgba(100, 116, 139, 0.35)';
      for (let i = 0; i < debrisCloud.length; i++) {
        const d = debrisCloud[i]; // [id, lat, lon, alt]
        if (!d || d.length < 4) continue;
        const { x, y } = geoToMercator(d[1], d[2], w, h);
        ctx.fillRect(x, y, 1, 1);
      }
    }

    // ── Satellite trails (fading polylines) ──
    for (const sat of satellites) {
      const trail = satHistory[sat.id];
      if (!trail || trail.length < 2) continue;
      const color = STATUS_COLORS[sat.status] || '#00ff88';

      for (let i = 1; i < trail.length; i++) {
        const prev = geoToMercator(trail[i - 1].lat, trail[i - 1].lon, w, h);
        const curr = geoToMercator(trail[i].lat, trail[i].lon, w, h);
        if (Math.abs(curr.x - prev.x) > w * 0.5) continue;

        const alpha = (i / trail.length) * 0.5;
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(curr.x, curr.y);
        ctx.strokeStyle = color;
        ctx.globalAlpha = alpha;
        ctx.lineWidth = sat.id === selectedSatellite ? 1.5 : 1;
        ctx.stroke();
      }
      ctx.globalAlpha = 1.0;
    }

    // ── 90-min Predicted Trajectory (dashed line) ──
    for (const sat of satellites) {
      const trail = satHistory[sat.id];
      const predicted = predictTrack(trail);
      if (predicted.length === 0) continue;

      const color = STATUS_COLORS[sat.status] || '#00ff88';
      const isSelected = sat.id === selectedSatellite;
      ctx.strokeStyle = color + '44';
      ctx.lineWidth = isSelected ? 1.2 : 0.6;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      const start = geoToMercator(sat.lat, sat.lon, w, h);
      ctx.moveTo(start.x, start.y);
      for (let j = 0; j < predicted.length; j++) {
        const pt = geoToMercator(predicted[j].lat, predicted[j].lon, w, h);
        if (j > 0) {
          const prevPt = j === 1
            ? start
            : geoToMercator(predicted[j - 1].lat, predicted[j - 1].lon, w, h);
          if (Math.abs(pt.x - prevPt.x) > w * 0.5) {
            ctx.stroke();
            ctx.beginPath();
          }
        }
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // ── Satellite dots ──
    if (!satellites.length) {
      ctx.fillStyle = '#6b7280';
      ctx.font = '12px Inter, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('Ground Track \u2014 awaiting satellite data', 12, 20);
      return;
    }

    for (const sat of satellites) {
      const { x: px, y: py } = geoToMercator(sat.lat, sat.lon, w, h);
      const color = STATUS_COLORS[sat.status] || '#00ff88';
      const isSelected = sat.id === selectedSatellite;

      // Outer glow
      ctx.beginPath();
      ctx.arc(px, py, isSelected ? 10 : 7, 0, Math.PI * 2);
      ctx.fillStyle = color + '22';
      ctx.fill();

      // Main dot
      ctx.beginPath();
      ctx.arc(px, py, isSelected ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      // White ring for selected
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(px, py, 7, 0, Math.PI * 2);
        ctx.strokeStyle = '#ffffff88';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Label
      ctx.fillStyle = '#9ca3af';
      ctx.font = '8px Inter, monospace';
      ctx.textAlign = 'left';
      ctx.fillText(sat.id.replace('SAT-Alpha-', '\u03b1'), px + 6, py + 3);
    }

    // ── Header label ──
    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(
      `Ground Track \u2014 ${satellites.length} sats \u00b7 ${debrisCloud.length.toLocaleString()} debris \u00b7 ${cdms.length} CDMs`,
      12, 16
    );

    // ── Legend (bottom-left) ──
    const lx = 8;
    let ly = h - 8;
    ctx.font = '8px Inter, monospace';
    ctx.textAlign = 'left';
    const legendItems = [
      { color: '#00ff88', label: 'Nominal' },
      { color: '#ffaa00', label: 'Evading' },
      { color: '#3b82f6', label: 'Recovering' },
      { color: '#ff3355', label: 'EOL' },
      { color: 'rgba(100,116,139,0.6)', label: 'Debris' },
      { color: '#4a90d9', label: 'Ground Stn' },
    ];
    // Background box
    const legendH = legendItems.length * 11 + 6;
    ctx.fillStyle = 'rgba(10, 14, 26, 0.85)';
    ctx.fillRect(lx - 2, ly - legendH + 4, 80, legendH);
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 0.5;
    ctx.strokeRect(lx - 2, ly - legendH + 4, 80, legendH);
    ly = ly - legendH + 14;
    for (const item of legendItems) {
      ctx.fillStyle = item.color;
      ctx.fillRect(lx, ly - 4, 6, 6);
      ctx.fillStyle = '#6b7280';
      ctx.fillText(item.label, lx + 10, ly + 1);
      ly += 11;
    }

    // ── Selected Satellite Info Box (bottom-right) ──
    const selSat = satellites.find((s) => s.id === selectedSatellite);
    if (selSat) {
      const bw = 160;
      const bh = 52;
      const bx = w - bw - 6;
      const by = h - bh - 6;
      ctx.fillStyle = 'rgba(10, 14, 26, 0.9)';
      ctx.fillRect(bx, by, bw, bh);
      ctx.strokeStyle = '#00ff8833';
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, bw, bh);

      ctx.fillStyle = '#00ff88';
      ctx.font = 'bold 9px Inter, monospace';
      ctx.textAlign = 'left';
      ctx.fillText(selSat.id.replace('SAT-Alpha-', '\u03b1'), bx + 6, by + 12);
      ctx.fillStyle = STATUS_COLORS[selSat.status] || '#6b7280';
      ctx.font = '8px Inter, monospace';
      ctx.fillText(selSat.status, bx + 40, by + 12);

      ctx.fillStyle = '#9ca3af';
      ctx.font = '8px Inter, monospace';
      ctx.fillText(`LAT ${selSat.lat.toFixed(2)}\u00b0  LON ${selSat.lon.toFixed(2)}\u00b0`, bx + 6, by + 24);
      ctx.fillText(`ALT ${(selSat.alt_km || selSat.alt || 400).toFixed(0)} km`, bx + 6, by + 35);

      // Fuel mini-bar
      const fuelPct = Math.max(0, (selSat.fuel_kg / 50) * 100);
      const fuelColor = fuelPct > 70 ? '#00ff88' : fuelPct > 30 ? '#ffaa00' : '#ff3355';
      ctx.fillStyle = '#1f2937';
      ctx.fillRect(bx + 6, by + 40, bw - 50, 5);
      ctx.fillStyle = fuelColor;
      ctx.fillRect(bx + 6, by + 40, (bw - 50) * fuelPct / 100, 5);
      ctx.fillStyle = '#6b7280';
      ctx.fillText(`${selSat.fuel_kg.toFixed(1)}kg`, bx + bw - 40, by + 45);
    }
  }, [satellites, debrisCloud, timestamp, satHistory, cdms, selectedSatellite]);

  useEffect(() => {
    draw();
  }, [draw]);

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas.parentElement);
    return () => ro.disconnect();
  }, [draw]);

  // Click-to-select satellite
  const handleClick = useCallback(
    (e) => {
      const canvas = canvasRef.current;
      if (!canvas || !satellites.length) return;
      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      for (const sat of satellites) {
        const { x, y } = geoToMercator(sat.lat, sat.lon, rect.width, rect.height);
        const dx = cx - x;
        const dy = cy - y;
        if (dx * dx + dy * dy < 100) {
          setSelectedSatellite(sat.id);
          break;
        }
      }
    },
    [satellites, setSelectedSatellite]
  );

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full cursor-crosshair"
      style={{ display: 'block' }}
      onClick={handleClick}
    />
  );
}
