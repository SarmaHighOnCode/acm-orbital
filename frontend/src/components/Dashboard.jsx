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

import React, { useState, useCallback, Suspense } from 'react';
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

/* ── Physics Proof Modal ─────────────────────────────────────────────── */
function PhysicsProofModal({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  React.useEffect(() => {
    let cancelled = false;
    fetch('/api/physics-proof')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const statusColor = (s) => s === 'PASS' ? '#00ff88' : '#ff3355';

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 560, maxHeight: '80vh', overflowY: 'auto',
          background: '#111827', border: '1px solid #374151',
          borderRadius: 12, padding: 24,
          fontFamily: 'JetBrains Mono, monospace', color: '#e5e7eb',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: '#00ff88', margin: 0 }}>
            Physics Engine Proof
          </h2>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#6b7280',
            fontSize: 18, cursor: 'pointer', padding: '2px 6px',
          }}>✕</button>
        </div>

        {loading && (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280', fontSize: 12 }}>
            Running live benchmarks...
          </div>
        )}

        {error && (
          <div style={{ color: '#ff3355', fontSize: 12, padding: 20, textAlign: 'center' }}>
            Error: {error}
          </div>
        )}

        {data && (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16,
              padding: '8px 12px', borderRadius: 8,
              background: data.overall === 'ALL PASS' ? 'rgba(0,255,136,0.08)' : 'rgba(255,51,85,0.08)',
              border: `1px solid ${data.overall === 'ALL PASS' ? '#00ff8833' : '#ff335533'}`,
            }}>
              <span style={{ fontSize: 20 }}>{data.overall === 'ALL PASS' ? '✓' : '✗'}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: data.overall === 'ALL PASS' ? '#00ff88' : '#ff3355' }}>
                {data.overall}
              </span>
              <span style={{ fontSize: 11, color: '#6b7280', marginLeft: 'auto' }}>
                {data.test_count} tests verified
              </span>
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #374151', color: '#6b7280' }}>
                  <th style={{ textAlign: 'left', padding: '6px 4px' }}>Benchmark</th>
                  <th style={{ textAlign: 'right', padding: '6px 4px' }}>Result</th>
                  <th style={{ textAlign: 'right', padding: '6px 4px' }}>Threshold</th>
                  <th style={{ textAlign: 'center', padding: '6px 4px' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.benchmarks.map((b, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #1f2937' }}>
                    <td style={{ padding: '6px 4px', color: '#d1d5db' }}>{b.test}</td>
                    <td style={{ textAlign: 'right', padding: '6px 4px', color: '#9ca3af' }}>{b.result}</td>
                    <td style={{ textAlign: 'right', padding: '6px 4px', color: '#6b7280' }}>{b.threshold}</td>
                    <td style={{ textAlign: 'center', padding: '6px 4px', fontWeight: 700, color: statusColor(b.status) }}>
                      {b.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {data.engine_state && (
              <div style={{ marginTop: 16, padding: '8px 12px', background: '#0a0e1a', borderRadius: 8, fontSize: 11 }}>
                <div style={{ color: '#6b7280', marginBottom: 6, fontWeight: 600 }}>Engine State</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px', color: '#9ca3af' }}>
                  <span>Satellites: {data.engine_state.satellites}</span>
                  <span>Debris: {data.engine_state.debris}</span>
                  <span>Sim Time: {data.engine_state.sim_time}</span>
                  <span>Uptime: {data.engine_state.uptime_score}</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { timestamp, activeCdmCount, satellites, collisionCount, maneuverQueueDepth, maneuverLog, cdms, error, connected } =
    useStore();
  const [view, setView] = useState('2d');
  const [showPhysicsProof, setShowPhysicsProof] = useState(false);

  // Compute rubric-aligned metrics
  const totalFuel = satellites.reduce((s, sat) => s + (sat.fuel_kg || 0), 0);
  const maxFuel = satellites.length * 50;
  const fleetFuelPct = maxFuel > 0 ? ((totalFuel / maxFuel) * 100).toFixed(1) : '—';
  const nominalCount = satellites.filter((s) => s.status === 'NOMINAL').length;
  const uptimePct = satellites.length > 0 ? ((nominalCount / satellites.length) * 100).toFixed(0) : '—';
  const totalDv = maneuverLog.reduce((s, m) => s + (m.delta_v_magnitude_ms || 0), 0);
  const evasions = maneuverLog.length;
  const safetyScore = evasions + collisionCount > 0
    ? ((evasions / (evasions + collisionCount)) * 100).toFixed(0)
    : '100';

  // CDM risk breakdown
  const riskCounts = cdms.reduce((acc, c) => { acc[c.risk] = (acc[c.risk] || 0) + 1; return acc; }, {});

  return (
    <div className="w-full h-full flex flex-col bg-space-900">
      {/* Header — Mission Control Status Bar */}
      <header className="shrink-0 border-b border-space-700 bg-space-800/80 backdrop-blur-sm">
        {/* Top row: title + key metrics */}
        <div className="h-10 flex items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-nominal animate-pulse" />
            <span className="text-base font-semibold tracking-tight">ACM-Orbital</span>
            <span className="text-[10px] text-gray-500 font-mono hidden lg:inline">Autonomous Constellation Manager</span>
          </div>
          <div className="flex items-center gap-4 text-[10px] font-mono">
            {/* Safety Score */}
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded" style={{
              background: collisionCount > 0 ? 'rgba(255,51,85,0.1)' : 'rgba(0,255,136,0.08)',
              border: `1px solid ${collisionCount > 0 ? '#ff335533' : '#00ff8825'}`,
            }}>
              <span className="text-gray-500">SAFETY</span>
              <span className={collisionCount > 0 ? 'text-eol font-bold' : 'text-nominal font-bold'}>
                {safetyScore}%
              </span>
            </div>
            {/* Fleet Fuel */}
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded" style={{
              background: 'rgba(6,182,212,0.08)',
              border: '1px solid rgba(6,182,212,0.2)',
            }}>
              <span className="text-gray-500">FUEL</span>
              <span className="text-cyan-400 font-bold">{fleetFuelPct}%</span>
              <span className="text-gray-600">{totalDv.toFixed(1)}m/s used</span>
            </div>
            {/* Uptime */}
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded" style={{
              background: 'rgba(0,255,136,0.06)',
              border: '1px solid rgba(0,255,136,0.15)',
            }}>
              <span className="text-gray-500">UPTIME</span>
              <span className="text-nominal font-bold">{uptimePct}%</span>
              <span className="text-gray-600">{nominalCount}/{satellites.length}</span>
            </div>

            {!connected && (
              <span className="text-evading animate-pulse">RECONNECTING...</span>
            )}
            {error && connected && (
              <span className="text-eol">API ERR</span>
            )}
            <button
              onClick={() => setShowPhysicsProof(true)}
              style={{
                padding: '3px 10px',
                fontSize: 10,
                fontFamily: 'JetBrains Mono, monospace',
                fontWeight: 600,
                color: '#00ff88',
                background: 'rgba(0, 255, 136, 0.08)',
                border: '1px solid rgba(0, 255, 136, 0.25)',
                borderRadius: 5,
                cursor: 'pointer',
                letterSpacing: '0.5px',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => { e.target.style.background = 'rgba(0, 255, 136, 0.18)'; }}
              onMouseLeave={(e) => { e.target.style.background = 'rgba(0, 255, 136, 0.08)'; }}
            >
              Physics Proof
            </button>
          </div>
        </div>
        {/* Bottom row: telemetry ticker */}
        <div className="h-6 flex items-center px-4 gap-5 text-[10px] font-mono text-gray-500 border-t border-space-700/50 bg-space-900/40">
          <span className="text-gray-600">SIM {timestamp ? new Date(timestamp).toISOString().slice(0, 19) + 'Z' : '\u2014'}</span>
          <span>SATS <span className="text-gray-300">{satellites.length}</span></span>
          <span>CDMs <span className={activeCdmCount > 0 ? 'text-evading font-semibold' : 'text-gray-300'}>{activeCdmCount}</span>
            {riskCounts.CRITICAL > 0 && <span className="text-eol ml-1">{riskCounts.CRITICAL} CRIT</span>}
            {riskCounts.RED > 0 && <span className="text-red-400 ml-1">{riskCounts.RED} RED</span>}
            {riskCounts.YELLOW > 0 && <span className="text-evading ml-1">{riskCounts.YELLOW} YLW</span>}
          </span>
          <span>QUEUE <span className="text-gray-300">{maneuverQueueDepth}</span></span>
          <span>EVASIONS <span className="text-cyan-400">{evasions}</span></span>
          <span className={collisionCount > 0 ? 'text-eol font-bold' : ''}>
            COL <span className={collisionCount > 0 ? 'text-eol' : 'text-nominal'}>{collisionCount}</span>
          </span>
          <span className="ml-auto text-gray-600">
            {satellites.filter(s => s.status === 'EVADING').length > 0 &&
              <span className="text-evading mr-3">{satellites.filter(s => s.status === 'EVADING').length} EVADING</span>
            }
            {satellites.filter(s => s.status === 'EOL').length > 0 &&
              <span className="text-eol">{satellites.filter(s => s.status === 'EOL').length} EOL</span>
            }
          </span>
        </div>
      </header>

      {/* Main Grid — 3 cols x 2 rows */}
      <main className="flex-1 grid grid-cols-3 grid-rows-2 gap-1 p-1 min-h-0"
            style={{ position: 'relative', zIndex: showPhysicsProof ? -1 : 'auto' }}>
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

      {/* Physics Proof Modal */}
      {showPhysicsProof && (
        <PhysicsProofModal onClose={() => setShowPhysicsProof(false)} />
      )}
    </div>
  );
}
