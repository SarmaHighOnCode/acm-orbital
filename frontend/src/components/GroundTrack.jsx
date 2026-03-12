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

export default function GroundTrack() {
  const canvasRef = useRef(null);
  const { satellites } = useStore();

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
  }, [satellites]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ display: 'block' }}
    />
  );
}
