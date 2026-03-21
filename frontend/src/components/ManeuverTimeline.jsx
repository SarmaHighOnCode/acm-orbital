/**
 * ManeuverTimeline.jsx — Gantt-Style Maneuver Scheduler (Canvas)
 * Owner: Dev 3 (Frontend)
 *
 * PDF Section 6.2 Requirements:
 * 1. Chronological blocks for "Burn Start" / "Burn End"      [x]
 * 2. Mandatory 600-second thruster cooldown visualization    [x]
 * 3. Blackout zone overlap flagging                          [x]
 * 4. Current simulation time marker                          [x]
 * 5. CDM diamond markers per satellite row                   [x]
 *
 * Uses Canvas 2D for rendering to maintain 60fps.
 * Data comes from store.maneuverLog + store.cdms.
 */

import React, { useRef, useEffect, useCallback, useMemo } from 'react';
import useStore from '../store';

const COOLDOWN_S = 600; // 600-second mandatory thruster cooldown
const ROW_HEIGHT = 18;
const HEADER_H = 22;
const LABEL_W = 42;

// Ground stations from PRD §5.5.1 — used for blackout zone estimation
const GROUND_STATIONS = [
  { lat: 13.0333, lon: 77.5167, minElev: 5 },    // Bengaluru
  { lat: 78.2297, lon: 15.4077, minElev: 5 },    // Svalbard
  { lat: 35.4266, lon: -116.89, minElev: 10 },   // Goldstone
  { lat: -53.15, lon: -70.9167, minElev: 5 },    // Punta Arenas
  { lat: 28.545, lon: 77.1926, minElev: 15 },    // IIT Delhi
  { lat: -77.8463, lon: 166.6682, minElev: 5 },  // McMurdo
];

/**
 * Check if a satellite at (lat, lon, alt_km) has line-of-sight to any ground station.
 * Uses simplified geometric elevation angle check.
 */
function hasGroundContact(satLat, satLon, altKm) {
  const R = 6371; // Earth radius km
  for (const gs of GROUND_STATIONS) {
    // Great-circle distance
    const dLat = (satLat - gs.lat) * Math.PI / 180;
    const dLon = (satLon - gs.lon) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(gs.lat * Math.PI / 180) * Math.cos(satLat * Math.PI / 180) *
      Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    const groundDist = R * c;

    // Elevation angle from ground station to satellite
    const elevAngle = Math.atan2(altKm - 0, groundDist) * 180 / Math.PI;
    if (elevAngle >= gs.minElev) return true;
  }
  return false;
}

export default function ManeuverTimeline() {
  const canvasRef = useRef(null);
  const { maneuverLog, cdms, maneuverQueueDepth, timestamp, satellites, selectedSatellite } =
    useStore();
  const satHistory = useStore((s) => s.satHistory);

  const simDate = timestamp ? new Date(timestamp) : null;

  // Get unique satellite IDs
  const satIds = useMemo(() => {
    const ids = new Set();
    satellites.forEach((s) => ids.add(s.id));
    return Array.from(ids).sort();
  }, [satellites]);

  // Pre-compute blackout status for each satellite (current instant)
  const blackoutStatus = useMemo(() => {
    const status = {};
    for (const sat of satellites) {
      status[sat.id] = !hasGroundContact(sat.lat, sat.lon, sat.alt || sat.alt_km || 400);
    }
    return status;
  }, [satellites]);

  // Compute blackout windows per satellite from position history
  // Returns { [satId]: [{startMs, endMs}, ...] }
  const blackoutWindows = useMemo(() => {
    const windows = {};
    for (const satId of Object.keys(satHistory)) {
      const history = satHistory[satId];
      if (!history || history.length < 2) continue;
      const spans = [];
      let spanStart = null;

      for (let i = 0; i < history.length; i++) {
        const pt = history[i];
        const blacked = !hasGroundContact(pt.lat, pt.lon, pt.alt || 400);
        const ptMs = new Date(pt.t).getTime();

        if (blacked && spanStart === null) {
          spanStart = ptMs;
        } else if (!blacked && spanStart !== null) {
          spans.push({ startMs: spanStart, endMs: ptMs });
          spanStart = null;
        }
      }
      // If still in blackout at end of history, extend to current time + buffer
      if (spanStart !== null) {
        const lastMs = new Date(history[history.length - 1].t).getTime();
        // Extend blackout 200s past last known point (conservative estimate)
        spans.push({ startMs: spanStart, endMs: lastMs + 200_000 });
      }
      if (spans.length > 0) windows[satId] = spans;
    }
    return windows;
  }, [satHistory]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const W = rect.width;
    const H = rect.height;

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, W, H);

    if (!simDate || satIds.length === 0) {
      ctx.fillStyle = '#6b7280';
      ctx.font = '11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Timeline \u2014 awaiting simulation data', W / 2, H / 2);
      return;
    }

    // Time axis: 2-hour window centered on current time
    const centerMs = simDate.getTime();
    const windowMs = 2 * 3600 * 1000;
    const startMs = centerMs - windowMs / 2;
    const endMs = centerMs + windowMs / 2;

    const timeToX = (ms) => LABEL_W + ((ms - startMs) / windowMs) * (W - LABEL_W);

    // ── Time axis labels (10-min grid) ──
    ctx.font = '8px Inter, monospace';
    ctx.textAlign = 'center';
    const stepMs = 10 * 60 * 1000;
    for (let t = startMs; t <= endMs; t += stepMs) {
      const x = timeToX(t);
      if (x < LABEL_W || x > W) continue;
      ctx.fillStyle = '#1f2937';
      ctx.fillRect(x, HEADER_H, 0.5, H - HEADER_H - 16);
      ctx.fillStyle = '#4b5563';
      ctx.fillText(new Date(t).toISOString().slice(11, 16), x, HEADER_H - 4);
    }

    // ── Row backgrounds ──
    const satToRow = {};
    satIds.forEach((id, i) => (satToRow[id] = i));

    for (let i = 0; i < satIds.length; i++) {
      const y = HEADER_H + i * ROW_HEIGHT;
      if (y > H - 16) break;
      ctx.fillStyle = i % 2 === 0 ? '#0f1419' : '#111822';
      ctx.fillRect(0, y, W, ROW_HEIGHT);

      // Highlight selected satellite row
      if (satIds[i] === selectedSatellite) {
        ctx.fillStyle = '#00ff8810';
        ctx.fillRect(0, y, W, ROW_HEIGHT);
      }

      // ── Blackout zone bands (from position history) ──
      const satWindows = blackoutWindows[satIds[i]] || [];
      for (const bw of satWindows) {
        if (bw.endMs < startMs || bw.startMs > endMs) continue;
        const bx1 = Math.max(LABEL_W, timeToX(bw.startMs));
        const bx2 = Math.min(W, timeToX(bw.endMs));
        const bw2 = bx2 - bx1;
        if (bw2 <= 0) continue;

        ctx.fillStyle = 'rgba(255, 149, 0, 0.12)';
        ctx.fillRect(bx1, y, bw2, ROW_HEIGHT);

        // Diagonal hatching
        ctx.save();
        ctx.beginPath();
        ctx.rect(bx1, y, bw2, ROW_HEIGHT);
        ctx.clip();
        ctx.strokeStyle = 'rgba(255, 149, 0, 0.25)';
        ctx.lineWidth = 0.5;
        for (let hx = bx1 - ROW_HEIGHT; hx < bx1 + bw2; hx += 5) {
          ctx.beginPath();
          ctx.moveTo(hx, y + ROW_HEIGHT);
          ctx.lineTo(hx + ROW_HEIGHT, y);
          ctx.stroke();
        }
        ctx.restore();
      }
      // Fallback: if no history but currently blacked out, show narrow band at now
      if (satWindows.length === 0 && blackoutStatus[satIds[i]]) {
        const nowX = timeToX(centerMs);
        const fallbackW = Math.max(20, (180 / (windowMs / 1000)) * (W - LABEL_W));
        const fbx = nowX - fallbackW / 2;
        ctx.fillStyle = 'rgba(255, 149, 0, 0.12)';
        ctx.fillRect(Math.max(LABEL_W, fbx), y, fallbackW, ROW_HEIGHT);
        ctx.save();
        ctx.beginPath();
        ctx.rect(Math.max(LABEL_W, fbx), y, fallbackW, ROW_HEIGHT);
        ctx.clip();
        ctx.strokeStyle = 'rgba(255, 149, 0, 0.25)';
        ctx.lineWidth = 0.5;
        for (let hx = Math.max(LABEL_W, fbx) - ROW_HEIGHT; hx < fbx + fallbackW; hx += 5) {
          ctx.beginPath();
          ctx.moveTo(hx, y + ROW_HEIGHT);
          ctx.lineTo(hx + ROW_HEIGHT, y);
          ctx.stroke();
        }
        ctx.restore();
      }

      // Satellite label
      const isBlacked = blackoutStatus[satIds[i]];
      ctx.fillStyle = satIds[i] === selectedSatellite
        ? '#00ff88'
        : isBlacked
        ? '#ff9500'
        : '#6b7280';
      ctx.font = '8px Inter, monospace';
      ctx.textAlign = 'left';
      const label = satIds[i].replace('SAT-Alpha-', '\u03b1');
      ctx.fillText(isBlacked ? label + '\u00b7' : label, 2, y + 12);
    }

    // ── Burn blocks (cyan) + 600s cooldown (gray hatched) ──
    const burnsBySat = {};
    for (const entry of maneuverLog) {
      if (!entry.satellite_id) continue;
      if (!burnsBySat[entry.satellite_id]) burnsBySat[entry.satellite_id] = [];
      burnsBySat[entry.satellite_id].push(entry);
    }

    for (const satId of Object.keys(burnsBySat)) {
      const row = satToRow[satId];
      if (row === undefined) continue;
      const burns = burnsBySat[satId].sort(
        (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
      );

      for (let i = 0; i < burns.length; i++) {
        const entry = burns[i];
        const burnMs = new Date(entry.timestamp).getTime();
        const x = timeToX(burnMs);
        const y = HEADER_H + row * ROW_HEIGHT + 2;
        const burnW = Math.max(4, (300 / (windowMs / 1000)) * (W - LABEL_W));

        // Burn block
        if (x + burnW > LABEL_W && x < W) {
          ctx.fillStyle = '#06b6d488';
          ctx.fillRect(x - 1, y - 1, burnW + 2, ROW_HEIGHT - 2);
          ctx.fillStyle = '#06b6d4';
          ctx.fillRect(x, y, burnW, ROW_HEIGHT - 4);

          // Delta-v label
          if (entry.delta_v_magnitude_ms && burnW > 12) {
            ctx.fillStyle = '#0d1117';
            ctx.font = '6px Inter, monospace';
            ctx.textAlign = 'left';
            ctx.fillText(`${entry.delta_v_magnitude_ms.toFixed(1)}`, x + 1, y + 9);
          }

          // Flag if burn overlaps with any blackout window
          const burnEndMs = burnMs + 5000; // ~5s burn duration
          const burnOverlapsBlackout = (blackoutWindows[satId] || []).some(
            (bw) => burnMs < bw.endMs && burnEndMs > bw.startMs
          ) || (!(blackoutWindows[satId]?.length) && blackoutStatus[satId]);

          if (burnOverlapsBlackout) {
            // Orange border + warning triangle
            ctx.strokeStyle = '#ff9500';
            ctx.lineWidth = 1.5;
            ctx.strokeRect(x - 1, y - 1, burnW + 2, ROW_HEIGHT - 2);
            // Warning triangle ⚠
            const tx = x + burnW + 3;
            const ty = y + (ROW_HEIGHT - 4) / 2;
            ctx.fillStyle = '#ff9500';
            ctx.beginPath();
            ctx.moveTo(tx, ty - 4);
            ctx.lineTo(tx - 3, ty + 3);
            ctx.lineTo(tx + 3, ty + 3);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = '#0d1117';
            ctx.font = '5px Inter, monospace';
            ctx.textAlign = 'center';
            ctx.fillText('!', tx, ty + 2);
          }
        }

        // 600s Cooldown block
        const coolStartMs = burnMs + 5000;
        const coolEndMs = burnMs + COOLDOWN_S * 1000;
        const coolX1 = timeToX(coolStartMs);
        const coolX2 = timeToX(coolEndMs);
        const coolW = Math.max(0, coolX2 - coolX1);

        if (coolX1 < W && coolX2 > LABEL_W) {
          const clampedX1 = Math.max(LABEL_W, coolX1);
          const clampedW = Math.min(W - clampedX1, coolW);

          ctx.fillStyle = 'rgba(75, 85, 99, 0.4)';
          ctx.fillRect(clampedX1, y, clampedW, ROW_HEIGHT - 4);

          // Diagonal hatching
          ctx.save();
          ctx.beginPath();
          ctx.rect(clampedX1, y, clampedW, ROW_HEIGHT - 4);
          ctx.clip();
          ctx.strokeStyle = 'rgba(75, 85, 99, 0.6)';
          ctx.lineWidth = 0.5;
          for (let hx = clampedX1 - ROW_HEIGHT; hx < clampedX1 + clampedW; hx += 4) {
            ctx.beginPath();
            ctx.moveTo(hx, y + ROW_HEIGHT - 4);
            ctx.lineTo(hx + ROW_HEIGHT - 4, y);
            ctx.stroke();
          }
          ctx.restore();

          // Flag cooldown-blackout overlap (dashed orange border)
          const coolOverlapsBlackout = (blackoutWindows[satId] || []).some(
            (bw) => coolStartMs < bw.endMs && coolEndMs > bw.startMs
          ) || (!(blackoutWindows[satId]?.length) && blackoutStatus[satId]);

          if (coolOverlapsBlackout && coolW > 0) {
            ctx.save();
            ctx.strokeStyle = '#ff9500';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 2]);
            ctx.strokeRect(clampedX1, y, clampedW, ROW_HEIGHT - 4);
            ctx.setLineDash([]);
            ctx.restore();
          }

          // Cooldown violation detection
          if (i < burns.length - 1) {
            const nextBurnMs = new Date(burns[i + 1].timestamp).getTime();
            if (nextBurnMs < coolEndMs) {
              const vx = timeToX(nextBurnMs);
              ctx.fillStyle = '#ff3355';
              ctx.beginPath();
              ctx.arc(vx, y + (ROW_HEIGHT - 4) / 2, 3, 0, Math.PI * 2);
              ctx.fill();
              ctx.font = '7px Inter, monospace';
              ctx.textAlign = 'left';
              ctx.fillText('!', vx + 4, y + (ROW_HEIGHT - 4) / 2 + 2);
            }
          }
        }
      }
    }

    // ── CDM diamond markers ──
    for (const cdm of cdms) {
      const row = satToRow[cdm.satellite_id];
      if (row === undefined) continue;
      const tcaMs = new Date(cdm.tca).getTime();
      if (tcaMs < startMs || tcaMs > endMs) continue;
      const x = timeToX(tcaMs);
      const y = HEADER_H + row * ROW_HEIGHT + ROW_HEIGHT / 2;

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(Math.PI / 4);
      const size = cdm.risk === 'CRITICAL' ? 5 : 3;
      ctx.fillStyle =
        cdm.risk === 'CRITICAL'
          ? '#ff3355'
          : cdm.risk === 'RED'
          ? '#ff6644'
          : '#ffaa00';
      ctx.fillRect(-size / 2, -size / 2, size, size);
      ctx.restore();
    }

    // ── Current time marker (green line + arrow) ──
    const nowX = timeToX(centerMs);
    ctx.strokeStyle = '#00ff88';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(nowX, HEADER_H);
    ctx.lineTo(nowX, H - 16);
    ctx.stroke();

    ctx.fillStyle = '#00ff88';
    ctx.beginPath();
    ctx.moveTo(nowX, HEADER_H);
    ctx.lineTo(nowX - 4, HEADER_H - 5);
    ctx.lineTo(nowX + 4, HEADER_H - 5);
    ctx.closePath();
    ctx.fill();

    // ── Legend ──
    const legendY = H - 6;
    ctx.font = '8px Inter, sans-serif';
    ctx.textAlign = 'left';
    const items = [
      { color: '#06b6d4', label: 'Burn' },
      { color: 'rgba(75, 85, 99, 0.7)', label: 'Cooldown' },
      { color: '#ff3355', label: 'CDM' },
      { color: '#ff9500', label: 'Blackout' },
      { color: '#ff9500', label: '\u26a0 Overlap', border: true },
    ];
    let lx = 4;
    for (const item of items) {
      if (item.border) {
        // Draw bordered swatch for "overlap" legend
        ctx.fillStyle = '#06b6d4';
        ctx.fillRect(lx, legendY - 5, 8, 6);
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(lx, legendY - 5, 8, 6);
      } else {
        ctx.fillStyle = item.color;
        ctx.fillRect(lx, legendY - 5, 8, 6);
      }
      ctx.fillStyle = '#6b7280';
      ctx.fillText(item.label, lx + 10, legendY);
      lx += ctx.measureText(item.label).width + 20;
    }

    if (maneuverQueueDepth > 0) {
      ctx.fillStyle = '#00ff88';
      ctx.font = '8px Inter, monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`${maneuverQueueDepth} burn(s) queued`, W - 4, legendY);
    }
  }, [maneuverLog, cdms, maneuverQueueDepth, simDate, satIds, selectedSatellite, blackoutStatus, blackoutWindows]);

  useEffect(() => { draw(); }, [draw]);

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas.parentElement);
    return () => ro.disconnect();
  }, [draw]);

  // Count blackout satellites
  const blackedCount = Object.values(blackoutStatus).filter(Boolean).length;

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Maneuver Timeline
        </h3>
        <div className="flex items-center gap-2 text-[9px] font-mono">
          {blackedCount > 0 && (
            <span className="text-orange-400">{blackedCount} in blackout</span>
          )}
          <span className="text-gray-500">{maneuverLog.length} burns</span>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <canvas
          ref={canvasRef}
          className="w-full h-full"
          style={{ display: 'block' }}
        />
      </div>
    </div>
  );
}
