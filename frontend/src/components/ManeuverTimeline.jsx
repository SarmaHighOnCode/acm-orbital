/**
 * ManeuverTimeline.jsx — Horizontal Timeline with Sim Clock
 * Owner: Dev 3 (Frontend)
 *
 * Horizontal scrollable timeline showing:
 * - Current simulation time marker
 * - Burn blocks (cyan) when maneuvers are queued
 * - 600s cooldown periods (gray)
 * - Fleet status summary when idle
 */

import React from 'react';
import useStore from '../store';

export default function ManeuverTimeline() {
  const { maneuverQueueDepth, timestamp, satellites } = useStore();

  const simDate = timestamp ? new Date(timestamp) : null;
  const hourFraction = simDate
    ? (simDate.getUTCHours() * 3600 + simDate.getUTCMinutes() * 60 + simDate.getUTCSeconds()) / 86400
    : 0;

  // Count statuses for fleet summary
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
        Maneuver Timeline
      </h3>
      <div className="flex-1 flex flex-col gap-2">
        {/* Status bar */}
        <div className="flex items-center gap-3 text-xs font-mono text-gray-400">
          {maneuverQueueDepth > 0 ? (
            <span className="text-nominal">● {maneuverQueueDepth} burn(s) queued</span>
          ) : (
            <span className="text-gray-500">● Fleet idle — no evasion burns pending</span>
          )}
        </div>

        {/* 24h Timeline bar — always visible */}
        <div className="relative flex-1 bg-space-700 rounded overflow-hidden min-h-[32px]">
          {/* Hour markers */}
          {Array.from({ length: 24 }, (_, i) => (
            <div
              key={i}
              className="absolute top-0 bottom-0 border-l border-space-600"
              style={{ left: `${(i / 24) * 100}%` }}
            >
              <span className="text-[7px] text-gray-600 ml-1 font-mono">
                {String(i).padStart(2, '0')}h
              </span>
            </div>
          ))}
          {/* Current time marker */}
          {simDate && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-nominal z-10"
              style={{ left: `${hourFraction * 100}%` }}
            >
              <div className="absolute -top-1 -left-1 w-2 h-2 rounded-full bg-nominal" />
              <div className="absolute bottom-1 -left-6 text-[8px] text-nominal font-mono whitespace-nowrap">
                {simDate.toISOString().slice(11, 19)}Z
              </div>
            </div>
          )}
        </div>

        {/* Legend + fleet summary */}
        <div className="flex justify-between items-center">
          <div className="flex gap-4 text-[10px] text-gray-500">
            <span><span className="inline-block w-2 h-2 bg-cyan-400 rounded-sm mr-1" />Burn</span>
            <span><span className="inline-block w-2 h-2 bg-gray-600 rounded-sm mr-1" />Cooldown</span>
            <span><span className="inline-block w-2 h-2 bg-orange-500 rounded-sm mr-1" />Blackout</span>
          </div>
          <div className="text-[10px] font-mono text-gray-600">
            {statusCounts.NOMINAL} NOM · {statusCounts.EVADING} EVD · {statusCounts.EOL} EOL
          </div>
        </div>
      </div>
    </div>
  );
}
