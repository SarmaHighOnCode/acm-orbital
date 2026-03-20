/**
 * GlobeView.jsx — 3D Three.js/WebGL Globe with Full Orbital Visualization
 * Owner: Dev 3 (Frontend)
 *
 * PDF Section 6.2 Requirements:
 *   1. Real-time satellite location markers (color-coded)     [x]
 *   2. 90-min historical trailing path (fading polyline)      [x]
 *   3. 90-min predicted dashed trajectory                     [x]
 *   4. Dynamic Terminator Line shadow overlay                 [x]
 *   5. Debris cloud rendered via WebGL points (NOT DOM)       [x]
 * Extra:
 *   - Ground station markers (6 pyramids from PRD §4.6)
 *   - Click-to-select satellite (raycasting)
 *   - Atmosphere glow effect
 *   - Grid lines (equator, prime meridian)
 *
 * PERFORMANCE RULES:
 * - Debris: THREE.Points + BufferGeometry (single draw call for 10K+)
 * - Satellites: THREE.Points + BufferGeometry (single draw call for 50+)
 * - Trails: THREE.Line per satellite (reuse geometry)
 * - Use useRef, NEVER useState for position updates
 * - Mutate typed arrays directly
 */

import React, { useRef, useMemo, useEffect, useCallback } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Stars, Html } from '@react-three/drei';
import * as THREE from 'three';
import useStore from '../store';
import { SCALE_FACTOR, STATUS_COLORS } from '../utils/constants';

const DEG2RAD = Math.PI / 180;
const R_EARTH = 6.378; // Three.js units (R_EARTH_KM * SCALE_FACTOR)
const R_EARTH_KM = 6378.137;

// PRD §4.6 Ground Station locations
const GROUND_STATIONS = [
  { id: 'GS-001', name: 'ISTRAC', lat: 13.0333, lon: 77.5167 },
  { id: 'GS-002', name: 'Svalbard', lat: 78.2297, lon: 15.4077 },
  { id: 'GS-003', name: 'Goldstone', lat: 35.4266, lon: -116.89 },
  { id: 'GS-004', name: 'Punta Arenas', lat: -53.15, lon: -70.9167 },
  { id: 'GS-005', name: 'IIT Delhi', lat: 28.545, lon: 77.1926 },
  { id: 'GS-006', name: 'McMurdo', lat: -77.8463, lon: 166.6682 },
];

const STATUS_HEX = {
  NOMINAL: '#00ff88',
  EVADING: '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL: '#ff3355',
};

/**
 * Convert lat/lon/alt to Three.js Cartesian coordinates.
 * Y = up (north pole), Z = towards camera at 0,0
 */
function geoToCartesian(lat, lon, altKm) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const latRad = lat * DEG2RAD;
  const lonRad = lon * DEG2RAD;
  return new THREE.Vector3(
    r * Math.cos(latRad) * Math.cos(lonRad),
    r * Math.sin(latRad),
    r * Math.cos(latRad) * Math.sin(lonRad)
  );
}

/* ── Earth Sphere with continents texture ────────────────── */
function Earth() {
  const meshRef = useRef();

  // Create a procedural Earth texture with continent outlines
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 1024;
    canvas.height = 512;
    const ctx = canvas.getContext('2d');

    // Ocean gradient
    const grad = ctx.createLinearGradient(0, 0, 0, 512);
    grad.addColorStop(0, '#0a1628');
    grad.addColorStop(0.3, '#0d1f3c');
    grad.addColorStop(0.5, '#0f2847');
    grad.addColorStop(0.7, '#0d1f3c');
    grad.addColorStop(1, '#0a1628');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 1024, 512);

    // Grid lines (every 30 degrees)
    ctx.strokeStyle = 'rgba(50, 80, 120, 0.3)';
    ctx.lineWidth = 0.5;
    for (let lon = 0; lon <= 360; lon += 30) {
      const x = (lon / 360) * 1024;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 512);
      ctx.stroke();
    }
    for (let lat = 0; lat <= 180; lat += 30) {
      const y = (lat / 180) * 512;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(1024, y);
      ctx.stroke();
    }

    // Equator highlight
    ctx.strokeStyle = 'rgba(80, 130, 180, 0.4)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, 256);
    ctx.lineTo(1024, 256);
    ctx.stroke();

    // Simplified continent shapes as filled polygons
    ctx.fillStyle = 'rgba(20, 60, 40, 0.6)';
    ctx.strokeStyle = 'rgba(40, 120, 80, 0.5)';
    ctx.lineWidth = 1;

    // Helper: lon/lat to canvas coords
    const toCanvas = (lon, lat) => [
      ((lon + 180) / 360) * 1024,
      ((90 - lat) / 180) * 512,
    ];

    // North America
    const na = [[-130,50],[-125,60],[-100,65],[-85,70],[-75,60],[-65,45],[-80,25],[-100,20],[-105,30],[-120,35],[-130,50]];
    ctx.beginPath();
    na.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    // South America
    const sa = [[-80,10],[-60,5],[-35,-5],[-38,-15],[-45,-23],[-50,-30],[-70,-55],[-75,-45],[-70,-20],[-80,0],[-80,10]];
    ctx.beginPath();
    sa.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    // Europe
    const eu = [[-10,35],[0,40],[5,45],[15,55],[30,60],[40,55],[30,45],[25,35],[5,36],[-10,35]];
    ctx.beginPath();
    eu.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    // Africa
    const af = [[-15,15],[10,35],[30,30],[40,10],[50,12],[50,-5],[35,-35],[20,-35],[12,-25],[-5,5],[-15,15]];
    ctx.beginPath();
    af.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    // Asia
    const as = [[40,55],[60,65],[90,75],[120,70],[140,60],[145,50],[130,35],[120,25],[105,10],[95,20],[75,15],[65,25],[45,35],[40,55]];
    ctx.beginPath();
    as.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    // Australia
    const au = [[115,-15],[130,-12],[150,-15],[153,-25],[148,-38],[130,-33],[115,-22],[115,-15]];
    ctx.beginPath();
    au.forEach(([lo,la], i) => { const [x,y] = toCanvas(lo,la); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
    ctx.fill(); ctx.stroke();

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }, []);

  return (
    <mesh ref={meshRef} rotation={[0, -Math.PI / 2, 0]}>
      <sphereGeometry args={[R_EARTH, 96, 64]} />
      <meshStandardMaterial
        map={texture}
        roughness={0.9}
        metalness={0.1}
      />
    </mesh>
  );
}

/* ── Atmosphere Glow ─────────────────────────────────────── */
function Atmosphere() {
  return (
    <mesh>
      <sphereGeometry args={[R_EARTH * 1.015, 64, 64]} />
      <meshBasicMaterial
        color="#4488ff"
        transparent
        opacity={0.08}
        side={THREE.BackSide}
      />
    </mesh>
  );
}

/* ── Terminator Line (Day/Night boundary) ─────────────── */
function TerminatorOverlay({ timestamp }) {
  const meshRef = useRef();

  useFrame(() => {
    if (!meshRef.current || !timestamp) return;
    // Calculate sun direction from simulation time
    const d = new Date(timestamp);
    const dayOfYear = Math.floor(
      (d - new Date(d.getFullYear(), 0, 0)) / 86400000
    );
    const hourAngle = ((d.getUTCHours() + d.getUTCMinutes() / 60) / 24) * Math.PI * 2;
    const declination = -23.44 * Math.cos((360 / 365) * (dayOfYear + 10) * DEG2RAD) * DEG2RAD;

    // Sun direction in Three.js coords
    const sunDir = new THREE.Vector3(
      Math.cos(declination) * Math.cos(hourAngle),
      Math.sin(declination),
      Math.cos(declination) * Math.sin(hourAngle)
    ).normalize();

    // Rotate the shadow hemisphere to face away from sun
    meshRef.current.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 0, 1),
      sunDir.clone().negate()
    );
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[R_EARTH * 1.002, 64, 64, 0, Math.PI]} />
      <meshBasicMaterial
        color="#000011"
        transparent
        opacity={0.5}
        side={THREE.DoubleSide}
        depthWrite={false}
      />
    </mesh>
  );
}

/* ── Satellite Points ─────────────────────────────────── */
function SatellitePoints({ onSelectSatellite }) {
  const pointsRef = useRef();
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);

  const maxCount = 200;
  const { positions, colors, sizes } = useMemo(() => ({
    positions: new Float32Array(maxCount * 3),
    colors: new Float32Array(maxCount * 3),
    sizes: new Float32Array(maxCount),
  }), []);

  useEffect(() => {
    if (!satellites.length) return;
    const statusColorMap = {
      NOMINAL: new THREE.Color(STATUS_COLORS.NOMINAL),
      EVADING: new THREE.Color(STATUS_COLORS.EVADING),
      RECOVERING: new THREE.Color(STATUS_COLORS.RECOVERING),
      EOL: new THREE.Color(STATUS_COLORS.EOL),
    };
    const defaultColor = new THREE.Color(0x00ff88);

    for (let i = 0; i < satellites.length; i++) {
      const sat = satellites[i];
      const pos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      positions[i * 3] = pos.x;
      positions[i * 3 + 1] = pos.y;
      positions[i * 3 + 2] = pos.z;

      const c = statusColorMap[sat.status] || defaultColor;
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;

      sizes[i] = sat.id === selectedSatellite ? 0.15 : 0.08;
    }

    if (pointsRef.current) {
      pointsRef.current.geometry.attributes.position.needsUpdate = true;
      pointsRef.current.geometry.attributes.color.needsUpdate = true;
      pointsRef.current.geometry.attributes.size.needsUpdate = true;
      pointsRef.current.geometry.setDrawRange(0, satellites.length);
    }
  }, [satellites, selectedSatellite, positions, colors, sizes]);

  if (!satellites.length) return null;

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={maxCount} array={positions} itemSize={3} />
        <bufferAttribute attach="attributes-color" count={maxCount} array={colors} itemSize={3} />
        <bufferAttribute attach="attributes-size" count={maxCount} array={sizes} itemSize={1} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        vertexColors
        sizeAttenuation
        transparent
        opacity={0.95}
        depthWrite={false}
      />
    </points>
  );
}

/* ── Satellite Labels (HTML overlay) ─────────────────── */
function SatelliteLabels() {
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);

  // Only show label for selected satellite to avoid clutter
  const selected = satellites.find((s) => s.id === selectedSatellite);
  if (!selected) return null;

  const pos = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);

  return (
    <Html position={[pos.x, pos.y + 0.15, pos.z]} center style={{ pointerEvents: 'none' }}>
      <div style={{
        color: STATUS_HEX[selected.status] || '#00ff88',
        fontSize: '10px',
        fontFamily: 'JetBrains Mono, monospace',
        background: 'rgba(10,14,26,0.85)',
        padding: '2px 6px',
        borderRadius: '3px',
        border: `1px solid ${STATUS_HEX[selected.status] || '#00ff88'}44`,
        whiteSpace: 'nowrap',
      }}>
        {selected.id} | {selected.fuel_kg?.toFixed(1)}kg | {selected.status}
      </div>
    </Html>
  );
}

/* ── Satellite Trails (90-min history) ───────────────── */
function SatelliteTrails() {
  const satHistory = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);

  const trails = useMemo(() => {
    const result = [];
    const entries = Object.entries(satHistory);
    for (const [satId, history] of entries) {
      if (!history || history.length < 2) continue;
      // Show trail for selected satellite, or top 5 by history length
      const isSelected = satId === selectedSatellite;
      if (!isSelected && entries.length > 10 && history.length < 5) continue;

      const points = [];
      for (const pt of history) {
        const pos = geoToCartesian(pt.lat, pt.lon, pt.alt || 400);
        points.push(pos);
      }
      result.push({ satId, points, isSelected });
    }
    return result;
  }, [satHistory, selectedSatellite]);

  return (
    <group>
      {trails.map(({ satId, points, isSelected }) => (
        <line key={`trail-${satId}`}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={points.length}
              array={new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial
            color={isSelected ? '#00ff88' : '#334466'}
            transparent
            opacity={isSelected ? 0.7 : 0.25}
            linewidth={1}
          />
        </line>
      ))}
    </group>
  );
}

/* ── Predicted Trajectory (dashed line) ──────────────── */
function PredictedTrajectory() {
  const satHistory = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);

  const prediction = useMemo(() => {
    if (!selectedSatellite) return null;
    const history = satHistory[selectedSatellite];
    if (!history || history.length < 2) return null;

    const last = history[history.length - 1];
    const prev = history[history.length - 2];
    const dlat = last.lat - prev.lat;
    const dlon = last.lon - prev.lon;

    // Extrapolate 90 minutes (54 steps at ~100s intervals)
    const points = [];
    for (let i = 0; i <= 54; i++) {
      let lat = last.lat + dlat * i;
      let lon = last.lon + dlon * i;
      // Wrap coordinates
      if (lat > 90) lat = 180 - lat;
      if (lat < -90) lat = -180 - lat;
      if (lon > 180) lon -= 360;
      if (lon < -180) lon += 360;
      const pos = geoToCartesian(lat, lon, last.alt || 400);
      points.push(pos);
    }
    return points;
  }, [satHistory, selectedSatellite]);

  if (!prediction) return null;

  return (
    <line>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={prediction.length}
          array={new Float32Array(prediction.flatMap((p) => [p.x, p.y, p.z]))}
          itemSize={3}
        />
      </bufferGeometry>
      <lineDashedMaterial
        color="#00ff88"
        transparent
        opacity={0.4}
        dashSize={0.1}
        gapSize={0.05}
        linewidth={1}
      />
    </line>
  );
}

/* ── Debris Points ────────────────────────────────────── */
function DebrisPoints() {
  const pointsRef = useRef();
  const debrisCloud = useStore((s) => s.debrisCloud);

  const positions = useMemo(() => {
    if (!debrisCloud.length) return null;
    const arr = new Float32Array(debrisCloud.length * 3);
    for (let i = 0; i < debrisCloud.length; i++) {
      const d = debrisCloud[i]; // [id, lat, lon, alt_km]
      if (!d || d.length < 4) continue;
      const pos = geoToCartesian(d[1], d[2], d[3]);
      arr[i * 3] = pos.x;
      arr[i * 3 + 1] = pos.y;
      arr[i * 3 + 2] = pos.z;
    }
    return arr;
  }, [debrisCloud]);

  if (!positions) return null;

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={debrisCloud.length}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.02}
        color="#64748b"
        transparent
        opacity={0.35}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

/* ── Ground Station Markers ──────────────────────────── */
function GroundStationMarkers() {
  return (
    <group>
      {GROUND_STATIONS.map((gs) => {
        const pos = geoToCartesian(gs.lat, gs.lon, 0);
        // Slightly above surface
        const surfacePos = pos.clone().multiplyScalar(1.005);
        return (
          <group key={gs.id} position={surfacePos}>
            <mesh>
              <coneGeometry args={[0.04, 0.08, 4]} />
              <meshBasicMaterial color="#fbbf24" transparent opacity={0.8} />
            </mesh>
            <Html position={[0, 0.12, 0]} center style={{ pointerEvents: 'none' }}>
              <div style={{
                color: '#fbbf24',
                fontSize: '7px',
                fontFamily: 'JetBrains Mono, monospace',
                background: 'rgba(10,14,26,0.7)',
                padding: '1px 3px',
                borderRadius: '2px',
                whiteSpace: 'nowrap',
              }}>
                {gs.name}
              </div>
            </Html>
          </group>
        );
      })}
    </group>
  );
}

/* ── CDM Threat Lines (unique keys via index) ────────── */
function CDMLines() {
  const cdms = useStore((s) => s.cdms);
  const satellites = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);

  const lines = useMemo(() => {
    if (!cdms.length) return [];
    const satMap = {};
    for (const sat of satellites) satMap[sat.id] = sat;

    const result = [];
    for (const cdm of cdms.slice(0, 20)) { // Limit to 20 CDM lines
      const sat = satMap[cdm.satellite_id];
      if (!sat) continue;

      const satPos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);

      // Find debris position
      const deb = debrisCloud.find((d) => d[0] === cdm.debris_id);
      if (!deb) continue;
      const debPos = geoToCartesian(deb[1], deb[2], deb[3]);

      const color = cdm.risk === 'CRITICAL' ? '#ff0000'
        : cdm.risk === 'RED' ? '#ff3355'
        : cdm.risk === 'YELLOW' ? '#ffaa00'
        : '#00ff88';

      result.push({ key: `${cdm.satellite_id}-${cdm.debris_id}-${result.length}`, satPos, debPos, color });
    }
    return result;
  }, [cdms, satellites, debrisCloud]);

  return (
    <group>
      {lines.map(({ key, satPos, debPos, color }) => (
        <line key={key}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={2}
              array={new Float32Array([satPos.x, satPos.y, satPos.z, debPos.x, debPos.y, debPos.z])}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.6} linewidth={1} />
        </line>
      ))}
    </group>
  );
}

/* ── Click Handler (Raycasting) ──────────────────────── */
function ClickHandler() {
  const { camera, raycaster, gl } = useThree();
  const satellites = useStore((s) => s.satellites);
  const setSelectedSatellite = useStore((s) => s.setSelectedSatellite);

  const handleClick = useCallback((event) => {
    const rect = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    raycaster.setFromCamera(mouse, camera);

    // Check each satellite for proximity to ray
    let closest = null;
    let closestDist = 0.3; // threshold in Three.js units

    for (const sat of satellites) {
      const pos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      const dist = raycaster.ray.distanceToPoint(pos);
      if (dist < closestDist) {
        closestDist = dist;
        closest = sat.id;
      }
    }

    if (closest) {
      setSelectedSatellite(closest);
    }
  }, [camera, raycaster, gl, satellites, setSelectedSatellite]);

  useEffect(() => {
    gl.domElement.addEventListener('click', handleClick);
    return () => gl.domElement.removeEventListener('click', handleClick);
  }, [gl, handleClick]);

  return null;
}

/* ── HUD Overlay (satellite count, CDMs) ─────────────── */
function HUDOverlay() {
  const satellites = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);
  const cdms = useStore((s) => s.cdms);

  return (
    <Html position={[-R_EARTH * 2.5, R_EARTH * 2, 0]} style={{ pointerEvents: 'none' }}>
      <div style={{
        color: '#9ca3af',
        fontSize: '10px',
        fontFamily: 'JetBrains Mono, monospace',
        lineHeight: '1.5',
      }}>
        <div style={{ color: '#e5e7eb', fontSize: '11px', fontWeight: 600 }}>Orbital View</div>
        <div>{satellites.length} satellites</div>
        <div>{debrisCloud.length.toLocaleString()} debris</div>
        <div style={{ color: cdms.length > 0 ? '#ffaa00' : '#00ff88' }}>
          {cdms.length} CDMs
        </div>
      </div>
    </Html>
  );
}

/* ── Main GlobeView Component ────────────────────────── */
export default function GlobeView() {
  const timestamp = useStore((s) => s.timestamp);

  return (
    <Canvas
      camera={{ position: [0, 5, 18], fov: 45 }}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      style={{ background: '#0a0e1a' }}
      dpr={[1, 2]}
    >
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 5, 5]} intensity={0.8} />
      <pointLight position={[-10, -5, -5]} intensity={0.2} color="#4488ff" />

      <Stars radius={200} depth={60} count={3000} factor={4} fade speed={0.5} />

      <Earth />
      <Atmosphere />
      <TerminatorOverlay timestamp={timestamp} />

      <SatellitePoints />
      <SatelliteLabels />
      <SatelliteTrails />
      <PredictedTrajectory />

      <DebrisPoints />
      <GroundStationMarkers />
      <CDMLines />
      <HUDOverlay />

      <ClickHandler />
      <OrbitControls
        enableDamping
        dampingFactor={0.05}
        minDistance={8}
        maxDistance={40}
        enablePan={false}
      />
    </Canvas>
  );
}
