/**
 * Dashboard.jsx — Layout Orchestrator (CSS Grid)
 * Owner: Dev 3 (Frontend)
 *
 * 6-panel dashboard grid with header status bar.
 * Layout: 3 columns x 2 rows
 *   Row 1: [Ground Track (2 cols)]  [Fuel Heatmap]
 *   Row 2: [Maneuver Timeline]      [Bullseye]      [Delta-V Chart]
 */

import React from 'react';
import GroundTrack from './GroundTrack';
import BullseyePlot from './BullseyePlot';
import FuelHeatmap from './FuelHeatmap';
import ManeuverTimeline from './ManeuverTimeline';
import DeltaVChart from './DeltaVChart';
import useStore from '../store';

export default function Dashboard() {
  const { timestamp, activeCdmCount, satellites, collisionCount, maneuverQueueDepth, error } =
    useStore();

  return (
    <div className="w-full h-full flex flex-col bg-space-900">
      {/* Header */}
      <header className="h-12 flex items-center justify-between px-6 border-b border-space-700 bg-space-800/80 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold tracking-tight">ACM-Orbital</span>
          <span className="text-xs text-gray-500 font-mono">Autonomous Constellation Manager</span>
        </div>
        <div className="flex items-center gap-6 text-xs font-mono text-gray-400">
          <span>SIM: {timestamp ? new Date(timestamp).toISOString().slice(0, 19) + 'Z' : '\u2014'}</span>
          <span>SATS: {satellites.length}</span>
          <span className={activeCdmCount > 0 ? 'text-evading' : 'text-nominal'}>
            CDMs: {activeCdmCount}
          </span>
          <span>QUEUE: {maneuverQueueDepth}</span>
          <span className={collisionCount > 0 ? 'text-eol font-bold' : 'text-nominal'}>
            COL: {collisionCount}
          </span>
          {error && (
            <span className="text-eol">API ERR</span>
          )}
        </div>
      </header>

      {/* Main Grid — 3 cols x 2 rows */}
      <main className="flex-1 grid grid-cols-3 grid-rows-2 gap-1 p-1 min-h-0">
        {/* Ground Track Map — large panel (span 2 cols) */}
        <div className="col-span-2 row-span-1 rounded-lg overflow-hidden border border-space-700 bg-space-800">
          <GroundTrack />
        </div>

        {/* Fuel Heatmap */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800 p-3">
          <FuelHeatmap />
        </div>

        {/* Maneuver Timeline */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800 p-2">
          <ManeuverTimeline />
        </div>

        {/* Bullseye Plot */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800">
          <BullseyePlot />
        </div>

        {/* Delta-V Cost Analysis Chart */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800">
          <DeltaVChart />
        </div>
      </main>
    </div>
  );
}
