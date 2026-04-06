/**
 * BullseyePlot.jsx — Polar Conjunction Proximity Chart (Canvas)
 * Owner: Dev 3 (Frontend)
 *
 * PDF Section 6.2 Requirements:
 * 1. Center point = selected satellite at origin             [x]
 * 2. Radial distance = Time to Closest Approach (TCA)       [x]
 * 3. Angle = relative approach vector                        [x]
 * 4. Color coding: Green(>5km) / Yellow(<5km) / Red(<1km)    [x]
 * 5. Pulsing animation for CRITICAL CDMs                     [x]
 */

import React, { useRef, useEffect, useCallback, useMemo } from 'react';
import useStore from '../store';

const RISK_COLORS = {
  CRITICAL: '#ff3355',
  RED: '#ff6644',
  YELLOW: '#ffaa00',
  GREEN: '#00ff88',
};

// Max TCA window (seconds) for the plot — CDMs beyond this are at edge
const MAX_TCA_S = 21600; // 6 hours — crossing-orbit debris have TCAs of 2-14h

/**
 * Derive a deterministic approach-vector angle from CDM properties.
 * Now dynamically mapped from backend true velocity vector data if available.
 */
function approachAngle(cdm) {
  if (cdm.rel_rtn_n !== undefined && cdm.rel_rtn_t !== undefined) {
      return Math.atan2(cdm.rel_rtn_n, cdm.rel_rtn_t);
  }
  if (cdm.approach_angle_rad !== undefined && cdm.approach_angle_rad !== null) {
      return cdm.approach_angle_rad;
  }
  // Simple hash: sum char codes of debris_id, multiply by relative velocity
  let hash = 0;
  const id = cdm.debris_id || '';
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0;
  }
  // Add relative velocity contribution for more spread
  hash += Math.floor((cdm.relative_velocity_km_s || 0) * 1000);
  // Map to [0, 2*PI)
  return ((hash % 360 + 360) % 360) * (Math.PI / 180);
}

export default function BullseyePlot() {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const { selectedSatellite, cdms, satellites, timestamp } = useStore();

  // Pick the best satellite to display: prefer selected if it has CDMs,
  // otherwise auto-pick the satellite with the most active CDMs
  const { focusSatId, focusSatData, relevantCdms } = useMemo(() => {
    const selectedCdms = cdms.filter(
      (c) => c.satellite_id === selectedSatellite || c.debris_id === selectedSatellite
    );
    if (selectedCdms.length > 0 || cdms.length === 0) {
      return {
        focusSatId: selectedSatellite,
        focusSatData: satellites.find((s) => s.id === selectedSatellite) || null,
        relevantCdms: selectedCdms,
      };
    }
    // Selected sat has no CDMs — find the satellite with the most CDMs
    const counts = {};
    for (const c of cdms) {
      counts[c.satellite_id] = (counts[c.satellite_id] || 0) + 1;
    }
    const bestId = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
    return {
      focusSatId: bestId || selectedSatellite,
      focusSatData: satellites.find((s) => s.id === (bestId || selectedSatellite)) || null,
      relevantCdms: bestId ? cdms.filter((c) => c.satellite_id === bestId) : [],
    };
  }, [cdms, selectedSatellite, satellites]);

  const draw = useCallback(
    (time) => {
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
      const cx = w / 2;
      const cy = h / 2;
      const maxR = Math.min(w, h) / 2 - 20;
      if (maxR <= 0) return; // canvas not yet laid out — ctx.arc() throws on negative radius

      // Background
      ctx.fillStyle = '#0d1117';
      ctx.fillRect(0, 0, w, h);

      if (!focusSatId) {
        ctx.fillStyle = '#6b7280';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Select a satellite to view conjunctions', cx, cy);
        return;
      }

      const nowMs = timestamp ? new Date(timestamp).getTime() : Date.now();

      // ── Concentric TCA rings (radial = time to closest approach) ──
      const rings = [
        { s: 1800, label: '30 min', color: '#ff335522' },
        { s: 3600, label: '1 hr', color: '#ff664418' },
        { s: 10800, label: '3 hr', color: '#ffaa0010' },
        { s: 21600, label: '6 hr', color: '#00ff8808' },
      ];

      for (const ring of rings) {
        const radius = (ring.s / MAX_TCA_S) * maxR;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fillStyle = ring.color;
        ctx.fill();
        ctx.strokeStyle = '#374151';
        ctx.lineWidth = 0.5;
        ctx.stroke();
        ctx.fillStyle = '#4b5563';
        ctx.font = '8px Inter, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(ring.label, cx, cy - radius + 10);
      }

      // Outer boundary
      ctx.beginPath();
      ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
      ctx.strokeStyle = '#1f2937';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Crosshairs
      ctx.strokeStyle = '#1a2333';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy - maxR);
      ctx.lineTo(cx, cy + maxR);
      ctx.moveTo(cx - maxR, cy);
      ctx.lineTo(cx + maxR, cy);
      ctx.stroke();

      // RTN compass labels
      ctx.fillStyle = '#374151';
      ctx.font = '8px Inter, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('R', cx, cy - maxR - 4);
      ctx.fillText('T', cx + maxR + 8, cy + 3);
      ctx.fillText('N', cx, cy + maxR + 12);

      // ── "No active threats" message when satellite selected but no CDMs ──
      if (relevantCdms.length === 0) {
        ctx.fillStyle = '#374151';
        ctx.font = '11px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No active threats', cx, cy + maxR * 0.45);
        ctx.fillStyle = '#2d3748';
        ctx.font = '9px Inter, sans-serif';
        ctx.fillText('Monitoring for conjunctions...', cx, cy + maxR * 0.45 + 16);
      }

      // ── CDM debris dots ──
      for (let i = 0; i < relevantCdms.length; i++) {
        const cdm = relevantCdms[i];

        // Radial = TCA (time to closest approach from current sim time)
        const tcaMs = new Date(cdm.tca).getTime();
        const tcaSeconds = Math.max(0, (tcaMs - nowMs) / 1000);
        const r = Math.min((tcaSeconds / MAX_TCA_S) * maxR, maxR);

        // Angle = approach vector (deterministic from CDM properties)
        const angle = approachAngle(cdm);
        const dx = r * Math.cos(angle);
        const dy = r * Math.sin(angle);

        // Color based on miss distance (risk level)
        const color = RISK_COLORS[cdm.risk] || '#ffaa00';
        const isCritical = cdm.risk === 'CRITICAL';

        // Pulsing animation for CRITICAL
        if (isCritical) {
          const pulse = 1 + 0.3 * Math.sin((time || 0) * 0.005);
          const pulseR = 6 * pulse;
          ctx.beginPath();
          ctx.arc(cx + dx, cy + dy, pulseR, 0, Math.PI * 2);
          ctx.fillStyle = color + '44';
          ctx.fill();
        }

        // Dot
        ctx.beginPath();
        ctx.arc(cx + dx, cy + dy, isCritical ? 4 : 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        // Label: miss distance + TCA
        ctx.fillStyle = '#9ca3af';
        ctx.font = '7px Inter, monospace';
        ctx.textAlign = 'left';
        const tcaLabel = tcaSeconds < 60
          ? `${tcaSeconds.toFixed(0)}s`
          : `${(tcaSeconds / 60).toFixed(0)}m`;
        ctx.fillText(
          `${(cdm.miss_distance_km * 1000).toFixed(0)}m T-${tcaLabel}`,
          cx + dx + 6,
          cy + dy + 3
        );
      }

      // ── Center dot (selected satellite) ──
      ctx.beginPath();
      ctx.arc(cx, cy, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#00ff88';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(cx, cy, 6, 0, Math.PI * 2);
      ctx.strokeStyle = '#00ff8844';
      ctx.lineWidth = 1;
      ctx.stroke();

      // ── Info text ──
      ctx.fillStyle = '#9ca3af';
      ctx.font = '9px Inter, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(
        focusSatId.replace('SAT-Alpha-', '\u03b1'),
        cx,
        cy + maxR + 22
      );
      if (focusSatData) {
        ctx.fillStyle = '#6b7280';
        ctx.font = '8px Inter, monospace';
        ctx.fillText(
          `${focusSatData.status} \u00b7 ${(focusSatData.fuel_kg ?? 0).toFixed(1)} kg \u00b7 ${relevantCdms.length} CDMs`,
          cx,
          cy + maxR + 32
        );
      }

      // ── Risk Distribution Bar (top-right) ──
      if (relevantCdms.length > 0) {
        const rc = { CRITICAL: 0, RED: 0, YELLOW: 0, GREEN: 0 };
        for (const c of relevantCdms) rc[c.risk] = (rc[c.risk] || 0) + 1;
        const total = relevantCdms.length;
        const barW = 80;
        const barH = 6;
        const barX = w - barW - 8;
        const barY = 8;

        // Background label
        ctx.fillStyle = 'rgba(10,14,26,0.85)';
        ctx.fillRect(barX - 4, barY - 2, barW + 8, barH + 16);
        ctx.font = '7px Inter, monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#6b7280';
        ctx.fillText(`${total} threats`, barX, barY + barH + 11);

        let offset = 0;
        for (const [risk, color] of [['CRITICAL', '#ff3355'], ['RED', '#ff6644'], ['YELLOW', '#ffaa00'], ['GREEN', '#00ff88']]) {
          if (!rc[risk]) continue;
          const segW = (rc[risk] / total) * barW;
          ctx.fillStyle = color;
          ctx.fillRect(barX + offset, barY, segW, barH);
          offset += segW;
        }
        // Border
        ctx.strokeStyle = '#37415166';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(barX, barY, barW, barH);
      }

      // Continue animation if critical CDMs
      if (relevantCdms.some((c) => c.risk === 'CRITICAL')) {
        animRef.current = requestAnimationFrame(draw);
      }
    },
    [focusSatId, relevantCdms, focusSatData, timestamp]
  );

  useEffect(() => {
    draw(performance.now());
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [draw]);

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw(performance.now()));
    ro.observe(canvas.parentElement);
    return () => ro.disconnect();
  }, [draw]);

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Conjunction Bullseye
        </h3>
        {relevantCdms.length > 0 && (
          <span className="text-[9px] font-mono text-gray-500">
            {relevantCdms.length} active CDMs
          </span>
        )}
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
