/**
 * Dashboard.jsx — Layout Orchestrator (CSS Grid)
 * Owner: Dev 3 (Frontend)
 *
 * 4-panel dashboard grid with header status bar.
 */

import React from 'react';
import GlobeView from './GlobeView';
import GroundTrack from './GroundTrack';
import BullseyePlot from './BullseyePlot';
import FuelHeatmap from './FuelHeatmap';
import ManeuverTimeline from './ManeuverTimeline';
import useStore from '../store';

export default function Dashboard() {
  const { timestamp, activeCdmCount, satellites } = useStore();

  return (
    <div className="w-full h-full flex flex-col bg-space-900">
      {/* Header */}
      <header className="h-12 flex items-center justify-between px-6 border-b border-space-700 bg-space-800/80 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold tracking-tight">🛰️ ACM-Orbital</span>
          <span className="text-xs text-gray-500 font-mono">Orbital Insight Visualizer</span>
        </div>
        <div className="flex items-center gap-6 text-xs font-mono text-gray-400">
          <span>SIM: {timestamp || '—'}</span>
          <span>SATS: {satellites.length}</span>
          <span className={activeCdmCount > 0 ? 'text-eol' : 'text-nominal'}>
            CDMs: {activeCdmCount}
          </span>
        </div>
      </header>

      {/* Main Grid */}
      <main className="flex-1 grid grid-cols-3 grid-rows-2 gap-1 p-1 min-h-0">
        {/* 3D Globe — large panel */}
        <div className="col-span-2 row-span-1 rounded-lg overflow-hidden border border-space-700 bg-space-800">
          <GlobeView />
        </div>

        {/* Fuel Heatmap */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800 p-3">
          <FuelHeatmap />
        </div>

        {/* Ground Track */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800">
          <GroundTrack />
        </div>

        {/* Bullseye Plot */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800 p-3">
          <BullseyePlot />
        </div>

        {/* Maneuver Timeline */}
        <div className="rounded-lg overflow-hidden border border-space-700 bg-space-800 p-3">
          <ManeuverTimeline />
        </div>
      </main>
    </div>
  );
}
