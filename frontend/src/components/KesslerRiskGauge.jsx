/**
 * KesslerRiskGauge.jsx — Kessler Cascade Risk Indicator
 * Owner: Dev 3 (Frontend)
 *
 * UNIQUE DIFFERENTIATOR — No other team has this.
 * Shows real-time Kessler Syndrome cascade probability
 * computed from debris density per altitude shell using
 * NASA's spatial density collision model.
 *
 * Features:
 *   - Animated radial arc gauge (0–100% risk)
 *   - Color transitions: Green → Yellow → Orange → Red
 *   - Top altitude shells by crowding
 *   - Cascade probability display
 */

import React, { useEffect, useRef, useCallback } from 'react';
import useStore from '../store';

const RISK_COLORS = {
  LOW: '#00ff88',
  MODERATE: '#66dd66',
  ELEVATED: '#ffaa00',
  HIGH: '#ff6644',
  CRITICAL: '#ff3355',
};

export default function KesslerRiskGauge() {
  const data = useStore((s) => s.kesslerData);
  const setKesslerData = useStore((s) => s.setKesslerData);
  const canvasRef = useRef(null);
  const animRef = useRef({ targetAngle: 0, currentAngle: 0 });

  // Poll kessler-risk endpoint every 5 seconds
  useEffect(() => {
    let cancelled = false;
    const fetchData = () => {
      fetch('/api/kessler-risk')
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (!cancelled && d) setKesslerData(d); })
        .catch(() => {});
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

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

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, w, h);

    const cx = w * 0.35;
    const cy = h * 0.52;
    const radius = Math.min(w * 0.3, h * 0.38);

    if (!data) {
      ctx.fillStyle = '#6b7280';
      ctx.font = '10px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Loading cascade risk...', w / 2, h / 2);
      return;
    }

    const score = data.overall_risk_score || 0;
    const label = data.risk_label || 'LOW';
    const color = RISK_COLORS[label] || '#00ff88';

    // Smooth animation
    const targetAngle = score * Math.PI * 1.5; // 0 to 270°
    animRef.current.targetAngle = targetAngle;
    animRef.current.currentAngle += (targetAngle - animRef.current.currentAngle) * 0.08;
    const currentAngle = animRef.current.currentAngle;

    // ── Arc gauge background ──
    const startAngle = Math.PI * 0.75;
    const endAngle = Math.PI * 2.25;

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, radius, startAngle, endAngle);
    ctx.strokeStyle = '#1a2233';
    ctx.lineWidth = 8;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Gradient arc (filled portion)
    if (currentAngle > 0.01) {
      const grad = ctx.createLinearGradient(cx - radius, cy, cx + radius, cy);
      grad.addColorStop(0, '#00ff88');
      grad.addColorStop(0.4, '#ffaa00');
      grad.addColorStop(0.7, '#ff6644');
      grad.addColorStop(1, '#ff3355');

      ctx.beginPath();
      ctx.arc(cx, cy, radius, startAngle, startAngle + currentAngle);
      ctx.strokeStyle = grad;
      ctx.lineWidth = 8;
      ctx.lineCap = 'round';
      ctx.stroke();

      // Glow effect
      ctx.beginPath();
      ctx.arc(cx, cy, radius, startAngle, startAngle + currentAngle);
      ctx.strokeStyle = color + '33';
      ctx.lineWidth = 16;
      ctx.stroke();
    }

    // ── Center text ──
    ctx.fillStyle = color;
    ctx.font = `bold ${Math.max(14, radius * 0.45)}px JetBrains Mono, monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${(score * 100).toFixed(0)}%`, cx, cy - 4);

    ctx.fillStyle = '#6b7280';
    ctx.font = '8px Inter, monospace';
    ctx.fillText('CASCADE RISK', cx, cy + radius * 0.35);

    // ── Risk label ──
    ctx.fillStyle = color;
    ctx.font = 'bold 9px JetBrains Mono, monospace';
    ctx.fillText(label, cx, cy + radius * 0.55);

    // ── Title ──
    ctx.fillStyle = '#9ca3af';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('Kessler Syndrome Risk', 6, 14);

    // ── Right side: Shell data ──
    const shellX = w * 0.62;
    let shellY = 30;

    ctx.fillStyle = '#6b7280';
    ctx.font = '8px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText('TOP ALTITUDE SHELLS', shellX, shellY);
    shellY += 4;

    const shells = (data.top_shells || []).slice(0, 5);
    for (const shell of shells) {
      shellY += 14;
      const barW = w - shellX - 8;
      const maxCount = Math.max(...shells.map((s) => s.object_count), 1);
      const fillW = (shell.object_count / maxCount) * barW;

      // Bar background
      ctx.fillStyle = '#1a2233';
      ctx.fillRect(shellX, shellY - 7, barW, 11);

      // Bar fill
      ctx.fillStyle = shell.is_critical ? '#ff335544' : '#06b6d433';
      ctx.fillRect(shellX, shellY - 7, fillW, 11);

      // Border for critical
      if (shell.is_critical) {
        ctx.strokeStyle = '#ff335566';
        ctx.lineWidth = 1;
        ctx.strokeRect(shellX, shellY - 7, barW, 11);
      }

      // Label
      ctx.fillStyle = shell.is_critical ? '#ff6644' : '#9ca3af';
      ctx.font = '7px JetBrains Mono, monospace';
      ctx.textAlign = 'left';
      ctx.fillText(shell.alt_range, shellX + 2, shellY);
      ctx.textAlign = 'right';
      ctx.fillStyle = '#d1d5db';
      ctx.fillText(`${shell.object_count}`, shellX + barW - 2, shellY);
    }

    // ── Bottom stats ──
    shellY = h - 16;
    ctx.font = '8px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#4b5563';
    ctx.fillText(`Objects: ${data.total_objects || 0}`, shellX, shellY);
    ctx.fillText(`Critical Shells: ${data.critical_shells || 0}`, shellX + 80, shellY);

    ctx.fillStyle = '#4b5563';
    ctx.textAlign = 'left';
    ctx.fillText(
      `Crowded: ${data.most_crowded_alt_km || 0} km`,
      6, h - 6
    );

    // Request next frame for smooth animation
    if (Math.abs(animRef.current.currentAngle - animRef.current.targetAngle) > 0.005) {
      requestAnimationFrame(draw);
    }
  }, [data]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas.parentElement);
    return () => ro.disconnect();
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ display: 'block' }}
    />
  );
}
