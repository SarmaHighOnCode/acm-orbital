/**
 * FuelHeatmap.jsx — Fleet Fuel Gauges & Δv Analysis
 * Owner: Dev 3 (Frontend)
 *
 * - Fuel gauge bar per satellite (green→yellow→red gradient)
 * - Fleet status counters (NOMINAL / EVADING / RECOVERING / EOL)
 * - Delta-v cost vs collisions avoided (Recharts)
 */

import React, { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
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

const STATUS_COLORS = {
  NOMINAL: '#00ff88',
  EVADING: '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL: '#ff3355',
};

const MAX_FUEL = 50;

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

export default function FuelHeatmap() {
  const { satellites, selectedSatellite, setSelectedSatellite } = useStore();

  const chartData = useMemo(
    () =>
      satellites.map((sat) => ({
        shortId: sat.id.slice(-4),
        fullId: sat.id,
        consumed: MAX_FUEL - sat.fuel_kg,
        status: sat.status,
      })),
    [satellites]
  );

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
      <div className="flex-1 overflow-y-auto space-y-1 min-h-0">
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

      {/* Δv Cost Analysis chart */}
      {satellites.length > 0 && (
        <div className="mt-3 shrink-0">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
            Δv Cost Analysis
          </h3>
          <div style={{ width: '100%', height: 140 }}>
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
