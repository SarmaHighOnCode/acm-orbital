/**
 * Dashboard.jsx — Layout Orchestrator (CSS Grid)
 * Owner: Dev 3 (Frontend)
 *
 * 6-panel dashboard grid with header status bar.
 * Layout: 3 columns x 2 rows
 *   Row 1: [Orbital View (2 cols)]  [Fuel Heatmap]
 *   Row 2: [Maneuver Timeline]      [Bullseye]      [Delta-V Chart]
 *
 * Toggle button switches between 3D Globe (Three.js) and 2D Ground Track (Canvas).
 */

import React, { useState, Suspense } from 'react';
import GlobeView from './GlobeView';
import GroundTrack from './GroundTrack';
import BullseyePlot from './BullseyePlot';
import FuelHeatmap from './FuelHeatmap';
import ManeuverTimeline from './ManeuverTimeline';
import DeltaVChart from './DeltaVChart';
import useStore from '../store';

function ViewToggle({ view, setView }) {
  return (
    <div style={{
      position: 'absolute',
      top: 8,
      right: 8,
      zIndex: 20,
      display: 'flex',
      gap: 0,
      borderRadius: 6,
      overflow: 'hidden',
      border: '1px solid rgba(100, 140, 180, 0.3)',
      background: 'rgba(5, 10, 20, 0.85)',
      backdropFilter: 'blur(6px)',
    }}>
      {[
        { key: '3d', label: '3D Globe' },
        { key: '2d', label: '2D Track' },
      ].map(({ key, label }) => (
        <button
          key={key}
          onClick={() => setView(key)}
          style={{
            padding: '4px 12px',
            fontSize: 10,
            fontFamily: 'JetBrains Mono, monospace',
            fontWeight: view === key ? 600 : 400,
            color: view === key ? '#00ff88' : '#6b7280',
            background: view === key ? 'rgba(0, 255, 136, 0.08)' : 'transparent',
            border: 'none',
            cursor: 'pointer',
            letterSpacing: '0.5px',
            transition: 'all 0.15s ease',
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function GlobeFallback() {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#020810',
      color: '#4a5568',
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 12,
    }}>
      Loading 3D Globe...
    </div>
  );
}

export default function Dashboard() {
  const { timestamp, activeCdmCount, satellites, collisionCount, maneuverQueueDepth, error, connected } =
    useStore();
  const [view, setView] = useState('3d');

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
          {!connected && (
            <span className="text-evading animate-pulse">RECONNECTING...</span>
          )}
          {error && connected && (
            <span className="text-eol">API ERR</span>
          )}
        </div>
      </header>

      {/* Main Grid — 3 cols x 2 rows */}
      <main className="flex-1 grid grid-cols-3 grid-rows-2 gap-1 p-1 min-h-0">
        {/* Orbital View — large panel (span 2 cols) with 3D/2D toggle */}
        <div className="col-span-2 row-span-1 rounded-lg overflow-hidden border border-space-700 bg-space-800"
             style={{ position: 'relative' }}>
          <ViewToggle view={view} setView={setView} />
          {view === '3d' ? (
            <Suspense fallback={<GlobeFallback />}>
              <GlobeView />
            </Suspense>
          ) : (
            <GroundTrack />
          )}
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
