/**
 * DeltaVChart.jsx — Delta-V Cost Analysis (Canvas)
 * Owner: Dev 3 (Frontend)
 *
 * PDF Section 6.2: "Delta-v cost analysis graph plotting
 * Fuel Consumed versus Collisions Avoided"
 *
 * X-axis: cumulative collisions avoided (maneuver count).
 * Y-axis: cumulative Delta-V consumed (m/s) = fuel cost.
 * Summary box: total Delta-V and collision count.
 * Demonstrates evasion algorithm efficiency.
 */

import React, { useRef, useEffect } from 'react';
import useStore from '../store';

export default function DeltaVChart() {
  const canvasRef = useRef(null);
  const { maneuverLog, collisionCount } = useStore();

  useEffect(() => {
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

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, w, h);

    const padL = 48;
    const padR = 10;
    const padT = 10;
    const padB = 36;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;

    if (!maneuverLog.length) {
      ctx.fillStyle = '#6b7280';
      ctx.font = '11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('\u0394V Cost Analysis \u2014 awaiting maneuver data', w / 2, h / 2);
      return;
    }

    // Compute cumulative delta-v (fuel consumed) and cumulative evasions (collisions avoided)
    const points = [];
    let totalDv = 0;
    let evasionCount = 0;
    for (const entry of maneuverLog) {
      totalDv += entry.delta_v_magnitude_ms || 0;
      evasionCount += 1; // Each maneuver = 1 collision avoided
      points.push({ dv: totalDv, evasions: evasionCount });
    }

    const maxDv = Math.max(totalDv, 1);
    const maxEvasions = Math.max(evasionCount, 1);

    // ── Y-axis: Cumulative Delta-V (fuel consumed) ──
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 0.5;
    ctx.fillStyle = '#4b5563';
    ctx.font = '8px Inter, monospace';
    ctx.textAlign = 'right';
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
      const val = (maxDv * i) / ySteps;
      const y = padT + chartH - (i / ySteps) * chartH;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.fillText(val.toFixed(1), padL - 3, y + 3);
    }

    // ── X-axis: Collisions Avoided ──
    ctx.textAlign = 'center';
    ctx.fillStyle = '#4b5563';
    const xSteps = Math.min(maxEvasions, 8);
    const xLabelStep = Math.max(1, Math.floor(maxEvasions / xSteps));
    for (let i = 0; i <= maxEvasions; i += xLabelStep) {
      const x = padL + (i / maxEvasions) * chartW;
      ctx.fillText(`${i}`, x, h - padB + 14);
      // Grid line
      if (i > 0) {
        ctx.beginPath();
        ctx.moveTo(x, padT);
        ctx.lineTo(x, padT + chartH);
        ctx.strokeStyle = '#1f2937';
        ctx.lineWidth = 0.3;
        ctx.stroke();
      }
    }

    // ── Area fill under curve ──
    ctx.beginPath();
    ctx.moveTo(padL, padT + chartH);
    for (const pt of points) {
      const x = padL + (pt.evasions / maxEvasions) * chartW;
      const y = padT + chartH - (pt.dv / maxDv) * chartH;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(padL + chartW, padT + chartH);
    ctx.closePath();

    const gradient = ctx.createLinearGradient(0, padT, 0, padT + chartH);
    gradient.addColorStop(0, '#06b6d422');
    gradient.addColorStop(1, '#06b6d404');
    ctx.fillStyle = gradient;
    ctx.fill();

    // ── Line ──
    ctx.beginPath();
    for (let i = 0; i < points.length; i++) {
      const x = padL + (points[i].evasions / maxEvasions) * chartW;
      const y = padT + chartH - (points[i].dv / maxDv) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 2;
    ctx.stroke();

    // ── Data points ──
    for (const pt of points) {
      const x = padL + (pt.evasions / maxEvasions) * chartW;
      const y = padT + chartH - (pt.dv / maxDv) * chartH;
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fillStyle = '#06b6d4';
      ctx.fill();
    }

    // ── Axis labels ──
    ctx.fillStyle = '#6b7280';
    ctx.font = '8px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Collisions Avoided', padL + chartW / 2, h - 3);

    ctx.save();
    ctx.translate(8, padT + chartH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Fuel Consumed \u0394V (m/s)', 0, 0);
    ctx.restore();

    // ── Summary box ──
    ctx.fillStyle = '#111827';
    ctx.fillRect(padL + 5, padT + 2, 145, 32);
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = 0.5;
    ctx.strokeRect(padL + 5, padT + 2, 145, 32);
    ctx.fillStyle = '#06b6d4';
    ctx.font = '9px Inter, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`Total \u0394V: ${totalDv.toFixed(2)} m/s`, padL + 10, padT + 14);
    ctx.fillStyle = collisionCount > 0 ? '#ff3355' : '#00ff88';
    ctx.fillText(
      `Collisions: ${collisionCount} | Avoided: ${evasionCount}`,
      padL + 10,
      padT + 26
    );
  }, [maneuverLog, collisionCount]);

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
        {'\u0394'}V Cost Analysis
      </h3>
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
