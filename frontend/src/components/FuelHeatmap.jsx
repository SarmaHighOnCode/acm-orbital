/**
 * FuelHeatmap.jsx — Fleet Fuel Gauges (Sorted + Enhanced)
 * Owner: Dev 3 (Frontend)
 *
 * PDF Section 6.2: "Visual fuel gauge representing mfuel for every satellite"
 *
 * - Sorted by fuel remaining (lowest first — critical at top)
 * - Gradient colors: green > yellow > red > black (EOL)
 * - Percentage text overlay
 * - Fleet status counters with total fuel
 */

import React, { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import useStore from '../store';

const STATUS_COLORS = {
  NOMINAL: '#00ff88',
  EVADING: '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL: '#ff3355',
};

function CostTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-space-800 border border-space-600 rounded px-2 py-1 text-xs">
      <p className="text-gray-300 font-mono">{d.fullId}</p>
      <p className="text-gray-400">Consumed: {d.consumed.toFixed(2)} kg</p>
      <p style={{ color: STATUS_COLORS[d.status] }}>{d.status}</p>
    </div>
  );
}

function FuelBar({ id, fuelKg, status, maxFuel = 50, onClick, isSelected }) {
  const pct = Math.max(0, (fuelKg / maxFuel) * 100);
  const isEOL = status === 'EOL';
  const color = isEOL
    ? '#1a1a2e'
    : pct > 70
    ? '#00ff88'
    : pct > 30
    ? '#ffaa00'
    : '#ff3355';

  return (
    <div
      className={`flex items-center gap-2 text-xs cursor-pointer rounded px-1 py-0.5 transition-colors ${
        isSelected ? 'bg-space-600 ring-1 ring-nominal/30' : 'hover:bg-space-700/50'
      }`}
      onClick={() => onClick(id)}
    >
      <span className="w-16 truncate font-mono text-gray-400 text-[10px]">
        {id.replace('SAT-Alpha-', '\u03b1')}
      </span>
      <div className="flex-1 h-3 bg-space-700 rounded-full overflow-hidden relative">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${pct}%`,
            backgroundColor: color,
            boxShadow: isEOL ? 'none' : `0 0 6px ${color}44`,
          }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-[8px] font-mono text-white/70">
          {pct.toFixed(0)}%
        </span>
      </div>
      <span className="w-14 text-right font-mono text-gray-500 text-[10px]">
        {fuelKg.toFixed(1)} kg
      </span>
    </div>
  );
}

export default function FuelHeatmap() {
  const { satellites, selectedSatellite, setSelectedSatellite } = useStore();

  // Sort: lowest fuel first (most critical at top)
  const sorted = useMemo(
    () => [...satellites].sort((a, b) => a.fuel_kg - b.fuel_kg),
    [satellites]
  );

  const statusCounts = satellites.reduce(
    (acc, sat) => {
      acc[sat.status] = (acc[sat.status] || 0) + 1;
      return acc;
    },
    { NOMINAL: 0, EVADING: 0, RECOVERING: 0, EOL: 0 }
  );

  const totalFuel = satellites.reduce((s, sat) => s + sat.fuel_kg, 0);

  const chartData = useMemo(
    () =>
      satellites.map((sat) => ({
        shortId: sat.id.slice(-4),
        fullId: sat.id,
        consumed: 50 - sat.fuel_kg,
        status: sat.status,
      })),
    [satellites]
  );

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
        Fleet Fuel Status
      </h3>

      {/* Status counters */}
      <div className="flex gap-3 mb-1 text-[10px] font-mono">
        <span className="text-nominal">NOM: {statusCounts.NOMINAL}</span>
        <span className="text-evading">EVD: {statusCounts.EVADING}</span>
        <span className="text-gray-400">REC: {statusCounts.RECOVERING}</span>
        <span className="text-eol">EOL: {statusCounts.EOL}</span>
      </div>

      {/* Fleet fuel summary with progress bar */}
      <div className="mb-2">
        <div className="flex justify-between text-[9px] font-mono text-gray-500 mb-0.5">
          <span>Fleet: {totalFuel.toFixed(1)} / {satellites.length * 50} kg</span>
          <span>{satellites.length > 0 ? ((totalFuel / (satellites.length * 50)) * 100).toFixed(1) : 0}%</span>
        </div>
        <div className="h-1.5 bg-space-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${satellites.length > 0 ? (totalFuel / (satellites.length * 50)) * 100 : 0}%`,
              background: `linear-gradient(90deg, #ff3355, #ffaa00 40%, #00ff88 80%)`,
            }}
          />
        </div>
      </div>

      {/* Fuel bars */}
      <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
        {sorted.length > 0 ? (
          sorted.map((sat) => (
            <FuelBar
              key={sat.id}
              id={sat.id}
              fuelKg={sat.fuel_kg}
              status={sat.status}
              onClick={setSelectedSatellite}
              isSelected={selectedSatellite === sat.id}
            />
          ))
        ) : (
          <p className="text-gray-600 text-sm">Awaiting telemetry data...</p>
        )}
      </div>

      {/* Δv Cost Analysis chart (from abc branch) */}
      {satellites.length > 0 && (
        <div className="mt-2 shrink-0">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
            Δv Cost Analysis
          </h3>
          <div style={{ width: '100%', height: 120 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                <XAxis
                  dataKey="shortId"
                  tick={{ fill: '#9ca3af', fontSize: 9 }}
                  axisLine={{ stroke: '#4b5563' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#9ca3af', fontSize: 9 }}
                  axisLine={{ stroke: '#4b5563' }}
                  tickLine={false}
                  label={{
                    value: 'kg',
                    position: 'insideTopLeft',
                    offset: 10,
                    style: { fill: '#6b7280', fontSize: 9 },
                  }}
                />
                <Tooltip content={<CostTooltip />} cursor={false} />
                <Bar dataKey="consumed" radius={[2, 2, 0, 0]}>
                  {chartData.map((entry, idx) => (
                    <Cell key={idx} fill={STATUS_COLORS[entry.status] || '#6b7280'} fillOpacity={0.85} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
