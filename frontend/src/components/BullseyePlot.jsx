/**
 * BullseyePlot.jsx — Polar Conjunction Proximity Chart (SVG)
 * Owner: Dev 3 (Frontend)
 *
 * Center = selected satellite. Concentric rings = distance thresholds.
 * Color: Green >5km, Yellow <5km, Red <1km.
 */

import React from 'react';
import useStore from '../store';

const RING_RADII = [
  { r: 80, label: '1 km', color: '#ff335555' },
  { r: 55, label: '5 km', color: '#ffaa0033' },
  { r: 30, label: '10 km', color: '#00ff8822' },
];

export default function BullseyePlot() {
  const { selectedSatellite, activeCdmCount, satellites } = useStore();

  const selectedData = selectedSatellite
    ? satellites.find((s) => s.id === selectedSatellite)
    : null;

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Conjunction Bullseye
      </h3>
      <div className="flex-1 flex items-center justify-center">
        {selectedSatellite ? (
          <div className="flex flex-col items-center gap-2">
            <svg viewBox="0 0 200 200" width="160" height="160">
              {/* Concentric risk rings */}
              {RING_RADII.map(({ r, label, color }, i) => (
                <g key={i}>
                  <circle
                    cx="100"
                    cy="100"
                    r={r}
                    fill={color}
                    stroke="#374151"
                    strokeWidth="0.5"
                  />
                  <text
                    x="100"
                    y={100 - r + 12}
                    textAnchor="middle"
                    fill="#6b7280"
                    fontSize="8"
                    fontFamily="Inter, monospace"
                  >
                    {label}
                  </text>
                </g>
              ))}
              {/* Center dot — selected satellite */}
              <circle cx="100" cy="100" r="3" fill="#00ff88" />
              {/* Crosshairs */}
              <line x1="100" y1="10" x2="100" y2="190" stroke="#1f2937" strokeWidth="0.5" />
              <line x1="10" y1="100" x2="190" y2="100" stroke="#1f2937" strokeWidth="0.5" />
            </svg>
            <div className="text-center">
              <p className="text-xs font-mono text-gray-300">{selectedSatellite}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {selectedData ? selectedData.status : '—'} · {activeCdmCount} CDMs
              </p>
              <p className="text-xs text-gray-600 mt-0.5">
                Fuel: {selectedData ? selectedData.fuel_kg.toFixed(1) : '—'} kg
              </p>
            </div>
          </div>
        ) : (
          <p className="text-gray-600 text-sm">Select a satellite to view conjunctions</p>
        )}
      </div>
    </div>
  );
}
