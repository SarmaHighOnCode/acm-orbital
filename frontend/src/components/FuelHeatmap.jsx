/**
 * FuelHeatmap.jsx — Fleet Fuel Gauges & Δv Analysis
 * Owner: Dev 3 (Frontend)
 *
 * - Fuel gauge bar per satellite (green→yellow→red gradient)
 * - Fleet status counters (NOMINAL / EVADING / RECOVERING / EOL)
 * - Delta-v cost vs collisions avoided (Recharts)
 */

import React from 'react';
import useStore from '../store';

function FuelBar({ id, fuelKg, maxFuel = 50, onClick, isSelected }) {
  const pct = (fuelKg / maxFuel) * 100;
  const color = pct > 50 ? '#00ff88' : pct > 20 ? '#ffaa00' : '#ff3355';

  return (
    <div
      className={`flex items-center gap-2 text-xs cursor-pointer rounded px-1 transition-colors ${
        isSelected ? 'bg-space-600' : 'hover:bg-space-700/50'
      }`}
      onClick={() => onClick(id)}
    >
      <span className="w-20 truncate font-mono text-gray-400">{id}</span>
      <div className="flex-1 h-2 bg-space-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-12 text-right font-mono text-gray-500">{fuelKg.toFixed(1)}</span>
    </div>
  );
}

export default function FuelHeatmap() {
  const { satellites, selectedSatellite, setSelectedSatellite } = useStore();

  const statusCounts = satellites.reduce(
    (acc, sat) => {
      acc[sat.status] = (acc[sat.status] || 0) + 1;
      return acc;
    },
    { NOMINAL: 0, EVADING: 0, RECOVERING: 0, EOL: 0 }
  );

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Fleet Fuel Status
      </h3>

      {/* Status counters */}
      <div className="flex gap-3 mb-3 text-xs font-mono">
        <span className="text-nominal">NOM: {statusCounts.NOMINAL}</span>
        <span className="text-evading">EVD: {statusCounts.EVADING}</span>
        <span className="text-gray-400">REC: {statusCounts.RECOVERING}</span>
        <span className="text-eol">EOL: {statusCounts.EOL}</span>
      </div>

      {/* Fuel bars */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {satellites.length > 0 ? (
          satellites.map((sat) => (
            <FuelBar
              key={sat.id}
              id={sat.id}
              fuelKg={sat.fuel_kg}
              onClick={setSelectedSatellite}
              isSelected={selectedSatellite === sat.id}
            />
          ))
        ) : (
          <p className="text-gray-600 text-sm">Awaiting telemetry data...</p>
        )}
      </div>
    </div>
  );
}
