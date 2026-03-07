/**
 * GroundTrack.jsx — 2D Canvas Mercator Projection
 * Owner: Dev 3 (Frontend)
 *
 * Uses Canvas 2D API (NOT SVG, NOT DOM divs) for performance.
 * Renders: satellite markers, 90-min trails, day/night terminator.
 */

import React, { useRef, useEffect } from 'react';
import useStore from '../store';

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

    // Placeholder label
    ctx.fillStyle = '#6b7280';
    ctx.font = '12px Inter, sans-serif';
    ctx.fillText('Ground Track — awaiting satellite data', 12, 20);

    // TODO: Dev 3 — Plot satellite positions, trails, terminator
  }, [satellites]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ display: 'block' }}
    />
  );
}
