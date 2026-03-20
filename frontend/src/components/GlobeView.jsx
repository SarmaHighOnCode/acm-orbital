/**
 * GlobeView.jsx — 3D Three.js/WebGL Globe with Full Orbital Visualization
 */

import React, { useRef, useMemo, useEffect, useCallback } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Stars, Html } from '@react-three/drei';
import * as THREE from 'three';
import useStore from '../store';
import { SCALE_FACTOR, STATUS_COLORS } from '../utils/constants';

const DEG2RAD = Math.PI / 180;
const R_EARTH = 6.378;
const R_EARTH_KM = 6378.137;

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

/* ── Earth with bright visible texture ─────────────────── */
function Earth() {
  const meshRef = useRef();

  const texture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 2048;
    canvas.height = 1024;
    const ctx = canvas.getContext('2d');

    // Ocean — clearly visible deep blue
    const grad = ctx.createLinearGradient(0, 0, 0, 1024);
    grad.addColorStop(0,   '#061830');
    grad.addColorStop(0.2, '#0b2d55');
    grad.addColorStop(0.5, '#0d3468');
    grad.addColorStop(0.8, '#0b2d55');
    grad.addColorStop(1,   '#061830');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 2048, 1024);

    // Lat/lon grid
    ctx.strokeStyle = 'rgba(30, 90, 160, 0.25)';
    ctx.lineWidth = 0.8;
    for (let lo = 0; lo <= 360; lo += 30) {
      const x = (lo / 360) * 2048;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 1024); ctx.stroke();
    }
    for (let la = 0; la <= 180; la += 30) {
      const y = (la / 180) * 1024;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(2048, y); ctx.stroke();
    }
    // Equator highlight
    ctx.strokeStyle = 'rgba(60, 140, 220, 0.4)';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, 512); ctx.lineTo(2048, 512); ctx.stroke();

    const toC = (lo, la) => [((lo + 180) / 360) * 2048, ((90 - la) / 180) * 1024];

    const drawLand = (coords, fill, stroke) => {
      ctx.fillStyle = fill;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      coords.forEach(([lo, la], i) => {
        const [x, y] = toC(lo, la);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    };

    const landFill   = 'rgba(22, 88, 44, 0.92)';
    const landStroke = 'rgba(48, 180, 90, 0.75)';

    // North America
    drawLand([[-168,71],[-140,70],[-100,74],[-82,70],[-65,47],[-55,47],[-60,44],[-75,44],[-80,25],[-85,30],[-90,28],[-105,20],[-118,32],[-122,37],[-124,49],[-130,55],[-140,60],[-150,62],[-165,65],[-168,71]], landFill, landStroke);
    // Greenland
    drawLand([[-70,76],[-35,83],[-20,83],[-18,75],[-25,68],[-45,60],[-60,63],[-70,76]], landFill, landStroke);
    // South America
    drawLand([[-80,12],[-65,12],[-50,2],[-35,-5],[-36,-13],[-40,-22],[-44,-23],[-48,-27],[-52,-33],[-60,-38],[-65,-44],[-68,-55],[-72,-50],[-70,-40],[-72,-30],[-72,-18],[-78,-2],[-80,0],[-80,12]], landFill, landStroke);
    // Europe
    drawLand([[-10,36],[0,38],[10,43],[20,46],[30,60],[28,70],[15,70],[5,62],[-5,48],[-10,44],[-10,36]], landFill, landStroke);
    // Scandinavia
    drawLand([[5,57],[10,62],[15,70],[28,71],[30,65],[25,58],[5,57]], landFill, landStroke);
    // Africa
    drawLand([[-18,15],[0,15],[10,37],[22,37],[38,12],[42,12],[50,12],[50,2],[40,-10],[35,-20],[25,-35],[18,-35],[12,-25],[8,-5],[0,5],[-18,15]], landFill, landStroke);
    // Asia (west)
    drawLand([[28,42],[40,42],[45,38],[55,22],[68,24],[75,18],[80,28],[85,28],[92,28],[100,18],[105,10],[110,0],[115,5],[120,25],[125,35],[130,40],[138,36],[140,42],[135,48],[130,48],[120,50],[110,54],[100,60],[90,72],[75,72],[60,70],[40,68],[28,62],[28,42]], landFill, landStroke);
    // Australia
    drawLand([[114,-22],[122,-18],[135,-12],[138,-12],[142,-10],[148,-18],[153,-27],[152,-38],[140,-38],[130,-33],[118,-28],[114,-26],[114,-22]], landFill, landStroke);
    // Japan
    drawLand([[130,31],[132,34],[134,35],[136,35],[138,38],[141,41],[145,44],[143,44],[140,40],[138,36],[133,33],[130,31]], landFill, landStroke);

    // Ice caps
    const iceFill = 'rgba(200,220,240,0.5)';
    const iceStroke = 'rgba(180,210,235,0.6)';
    drawLand([[0,75],[60,78],[120,76],[180,74],[240,76],[300,78],[360,75]], iceFill, iceStroke);
    drawLand([[0,-70],[60,-72],[120,-74],[180,-76],[240,-74],[300,-72],[360,-70]], iceFill, iceStroke);

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }, []);

  // Slow self-rotation
  useFrame((_, delta) => {
    if (meshRef.current) meshRef.current.rotation.y += delta * 0.01;
  });

  return (
    <mesh ref={meshRef} rotation={[0, -Math.PI / 2, 0]}>
      <sphereGeometry args={[R_EARTH, 96, 64]} />
      <meshStandardMaterial
        map={texture}
        roughness={0.85}
        metalness={0.05}
        emissive="#061428"
        emissiveIntensity={0.15}
      />
    </mesh>
  );
}

/* ── Atmosphere layers ─────────────────────────────────── */
function Atmosphere() {
  return (
    <>
      {/* Inner haze */}
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.012, 64, 64]} />
        <meshBasicMaterial color="#2255cc" transparent opacity={0.10} side={THREE.BackSide} depthWrite={false} />
      </mesh>
      {/* Outer glow */}
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.04, 64, 64]} />
        <meshBasicMaterial color="#0033aa" transparent opacity={0.05} side={THREE.BackSide} depthWrite={false} />
      </mesh>
    </>
  );
}

/* ── Terminator (day/night) ──────────────────────────── */
function TerminatorOverlay({ timestamp }) {
  const meshRef = useRef();
  useFrame(() => {
    if (!meshRef.current || !timestamp) return;
    const d = new Date(timestamp);
    const dayOfYear = Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86400000);
    const hourAngle = ((d.getUTCHours() + d.getUTCMinutes() / 60) / 24) * Math.PI * 2;
    const decl = -23.44 * Math.cos((360 / 365) * (dayOfYear + 10) * DEG2RAD) * DEG2RAD;
    const sunDir = new THREE.Vector3(
      Math.cos(decl) * Math.cos(hourAngle),
      Math.sin(decl),
      Math.cos(decl) * Math.sin(hourAngle)
    ).normalize();
    meshRef.current.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), sunDir.clone().negate());
  });
  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[R_EARTH * 1.003, 64, 64, 0, Math.PI]} />
      <meshBasicMaterial color="#000820" transparent opacity={0.55} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}

/* ── LEO altitude reference ring ────────────────────── */
function OrbitRing({ altKm = 400, color = '#1a4060', opacity = 0.3 }) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const pts = useMemo(() => {
    const arr = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      arr.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
    }
    return arr;
  }, [r]);
  return (
    <line>
      <bufferGeometry setFromPoints={pts} />
      <lineBasicMaterial color={color} transparent opacity={opacity} />
    </line>
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
    for (let i = 0; i < Math.min(satellites.length, maxCount); i++) {
      const sat = satellites[i];
      const pos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      positions[i * 3] = pos.x; positions[i * 3 + 1] = pos.y; positions[i * 3 + 2] = pos.z;
      const c = statusColorMap[sat.status] || defaultColor;
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
      sizes[i] = sat.id === selectedSatellite ? 0.22 : 0.12;
    }
    if (pointsRef.current) {
      pointsRef.current.geometry.attributes.position.needsUpdate = true;
      pointsRef.current.geometry.attributes.color.needsUpdate = true;
      pointsRef.current.geometry.attributes.size.needsUpdate = true;
      pointsRef.current.geometry.setDrawRange(0, Math.min(satellites.length, maxCount));
    }
  }, [satellites, selectedSatellite, positions, colors, sizes]);

  if (!satellites.length) return null;
  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={maxCount} array={positions} itemSize={3} />
        <bufferAttribute attach="attributes-color"    count={maxCount} array={colors}    itemSize={3} />
        <bufferAttribute attach="attributes-size"     count={maxCount} array={sizes}     itemSize={1} />
      </bufferGeometry>
      <pointsMaterial size={0.12} vertexColors sizeAttenuation transparent opacity={1.0} depthWrite={false} />
    </points>
  );
}

/* ── Selected satellite ring ─────────────────────────── */
function SelectionRing() {
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const ringRef = useRef();

  const selected = satellites.find((s) => s.id === selectedSatellite);

  useFrame(() => {
    if (!ringRef.current) return;
    ringRef.current.rotation.y += 0.02;
  });

  if (!selected) return null;
  const pos = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  const color = STATUS_HEX[selected.status] || '#00ff88';

  return (
    <mesh ref={ringRef} position={[pos.x, pos.y, pos.z]}>
      <torusGeometry args={[0.18, 0.015, 8, 32]} />
      <meshBasicMaterial color={color} transparent opacity={0.8} />
    </mesh>
  );
}

/* ── Satellite Label ─────────────────────────────────── */
function SatelliteLabels() {
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const selected = satellites.find((s) => s.id === selectedSatellite);
  if (!selected) return null;
  const pos = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  return (
    <Html position={[pos.x, pos.y + 0.28, pos.z]} center style={{ pointerEvents: 'none' }}>
      <div style={{
        color: STATUS_HEX[selected.status] || '#00ff88',
        fontSize: '11px',
        fontFamily: 'JetBrains Mono, monospace',
        background: 'rgba(6,10,20,0.9)',
        padding: '3px 8px',
        borderRadius: '4px',
        border: `1px solid ${STATUS_HEX[selected.status] || '#00ff88'}66`,
        whiteSpace: 'nowrap',
        boxShadow: `0 0 8px ${STATUS_HEX[selected.status] || '#00ff88'}44`,
      }}>
        ▶ {selected.id} · {selected.fuel_kg?.toFixed(1)}kg · {selected.status}
      </div>
    </Html>
  );
}

/* ── Satellite Trails ─────────────────────────────────── */
function SatelliteTrails() {
  const satHistory = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const satellites = useStore((s) => s.satellites);

  const satStatusMap = useMemo(() => {
    const m = {};
    for (const sat of satellites) m[sat.id] = sat.status;
    return m;
  }, [satellites]);

  const trails = useMemo(() => {
    const result = [];
    for (const [satId, history] of Object.entries(satHistory)) {
      if (!history || history.length < 2) continue;
      const isSelected = satId === selectedSatellite;
      const points = history.map((pt) => geoToCartesian(pt.lat, pt.lon, pt.alt || 400));
      const status = satStatusMap[satId] || 'NOMINAL';
      const color = isSelected ? (STATUS_HEX[status] || '#00ff88') : '#2a6090';
      result.push({ satId, points, isSelected, color });
    }
    return result;
  }, [satHistory, selectedSatellite, satStatusMap]);

  return (
    <group>
      {trails.map(({ satId, points, isSelected, color }) => (
        <line key={`trail-${satId}`}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={points.length}
              array={new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={isSelected ? 0.9 : 0.55} />
        </line>
      ))}
    </group>
  );
}

/* ── Predicted Trajectory ────────────────────────────── */
function PredictedTrajectory() {
  const lineRef = useRef();
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
    const pts = [];
    for (let i = 0; i <= 54; i++) {
      let lat = last.lat + dlat * i;
      let lon = last.lon + dlon * i;
      if (lat > 90) lat = 180 - lat;
      if (lat < -90) lat = -180 - lat;
      if (lon > 180) lon -= 360;
      if (lon < -180) lon += 360;
      pts.push(geoToCartesian(lat, lon, last.alt || 400));
    }
    return pts;
  }, [satHistory, selectedSatellite]);

  useEffect(() => {
    if (lineRef.current?.geometry) lineRef.current.computeLineDistances();
  }, [prediction]);

  if (!prediction) return null;
  return (
    <line ref={lineRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={prediction.length}
          array={new Float32Array(prediction.flatMap((p) => [p.x, p.y, p.z]))}
          itemSize={3}
        />
      </bufferGeometry>
      <lineDashedMaterial color="#00ff88" transparent opacity={0.6} dashSize={0.18} gapSize={0.09} />
    </line>
  );
}

/* ── Debris Points ────────────────────────────────────── */
function DebrisPoints() {
  const debrisCloud = useStore((s) => s.debrisCloud);
  const positions = useMemo(() => {
    if (!debrisCloud.length) return null;
    const arr = new Float32Array(debrisCloud.length * 3);
    for (let i = 0; i < debrisCloud.length; i++) {
      const d = debrisCloud[i];
      if (!d || d.length < 4) continue;
      const pos = geoToCartesian(d[1], d[2], d[3]);
      arr[i * 3] = pos.x; arr[i * 3 + 1] = pos.y; arr[i * 3 + 2] = pos.z;
    }
    return arr;
  }, [debrisCloud]);
  if (!positions) return null;
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={debrisCloud.length} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.025} color="#7896b0" transparent opacity={0.45} sizeAttenuation depthWrite={false} />
    </points>
  );
}

/* ── Ground Station Markers (prominent) ─────────────── */
function GroundStationMarkers() {
  const pulsRef = useRef({});
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    Object.values(pulsRef.current).forEach((mesh, i) => {
      if (!mesh) return;
      const s = 1 + 0.3 * Math.abs(Math.sin(t * 1.5 + i));
      mesh.scale.setScalar(s);
    });
  });

  return (
    <group>
      {GROUND_STATIONS.map((gs, idx) => {
        const pos = geoToCartesian(gs.lat, gs.lon, 0);
        const surfacePos = pos.clone().normalize().multiplyScalar(R_EARTH * 1.002);
        // Outward direction from Earth centre
        const outward = surfacePos.clone().normalize();

        return (
          <group key={gs.id} position={surfacePos.toArray()}>
            {/* Base disc on surface */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <circleGeometry args={[0.06, 16]} />
              <meshBasicMaterial color="#fbbf24" transparent opacity={0.7} side={THREE.DoubleSide} />
            </mesh>
            {/* Upward spike */}
            <mesh position={[0, 0.06, 0]}>
              <coneGeometry args={[0.025, 0.12, 6]} />
              <meshBasicMaterial color="#fde68a" />
            </mesh>
            {/* Pulsing ring */}
            <mesh
              ref={(el) => { pulsRef.current[gs.id] = el; }}
              rotation={[Math.PI / 2, 0, 0]}
            >
              <ringGeometry args={[0.07, 0.10, 20]} />
              <meshBasicMaterial color="#fbbf24" transparent opacity={0.45} side={THREE.DoubleSide} />
            </mesh>
            {/* Label */}
            <Html position={[0, 0.22, 0]} center style={{ pointerEvents: 'none' }}>
              <div style={{
                color: '#fde68a',
                fontSize: '9px',
                fontFamily: 'JetBrains Mono, monospace',
                background: 'rgba(6,10,20,0.85)',
                padding: '2px 5px',
                borderRadius: '3px',
                border: '1px solid #fbbf2455',
                whiteSpace: 'nowrap',
                boxShadow: '0 0 6px #fbbf2433',
              }}>
                ◆ {gs.name}
              </div>
            </Html>
          </group>
        );
      })}
    </group>
  );
}

/* ── CDM Threat Lines ─────────────────────────────────── */
function CDMLines() {
  const cdms = useStore((s) => s.cdms);
  const satellites = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);

  const lines = useMemo(() => {
    if (!cdms.length) return [];
    const satMap = {};
    for (const sat of satellites) satMap[sat.id] = sat;
    const result = [];
    for (const cdm of cdms.slice(0, 20)) {
      const sat = satMap[cdm.satellite_id];
      if (!sat) continue;
      const satPos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      const deb = debrisCloud.find((d) => d[0] === cdm.debris_id);
      if (!deb) continue;
      const debPos = geoToCartesian(deb[1], deb[2], deb[3]);
      const color = cdm.risk === 'CRITICAL' ? '#ff0000'
        : cdm.risk === 'RED'      ? '#ff3355'
        : cdm.risk === 'YELLOW'   ? '#ffaa00'
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
          <lineBasicMaterial color={color} transparent opacity={0.7} />
        </line>
      ))}
    </group>
  );
}

/* ── Click to select satellite ────────────────────────── */
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
    let closest = null, closestDist = 0.3;
    for (const sat of satellites) {
      const pos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      const dist = raycaster.ray.distanceToPoint(pos);
      if (dist < closestDist) { closestDist = dist; closest = sat.id; }
    }
    if (closest) setSelectedSatellite(closest);
  }, [camera, raycaster, gl, satellites, setSelectedSatellite]);

  useEffect(() => {
    gl.domElement.addEventListener('click', handleClick);
    return () => gl.domElement.removeEventListener('click', handleClick);
  }, [gl, handleClick]);
  return null;
}

/* ── HUD Overlay ──────────────────────────────────────── */
function HUDOverlay() {
  const satellites = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);
  const cdms = useStore((s) => s.cdms);
  return (
    <Html position={[-R_EARTH * 2.6, R_EARTH * 2.1, 0]} style={{ pointerEvents: 'none' }}>
      <div style={{
        color: '#9ca3af',
        fontSize: '10px',
        fontFamily: 'JetBrains Mono, monospace',
        lineHeight: '1.6',
      }}>
        <div style={{ color: '#e5e7eb', fontSize: '11px', fontWeight: 600, marginBottom: 2 }}>ORBITAL VIEW</div>
        <div><span style={{ color: '#00ff88' }}>■</span> {satellites.length} satellites</div>
        <div><span style={{ color: '#7896b0' }}>■</span> {debrisCloud.length.toLocaleString()} debris</div>
        <div style={{ color: cdms.length > 0 ? '#ffaa00' : '#6b7280' }}>
          <span>⚠</span> {cdms.length} CDMs active
        </div>
      </div>
    </Html>
  );
}

/* ── Main GlobeView ───────────────────────────────────── */
export default function GlobeView() {
  const timestamp = useStore((s) => s.timestamp);

  return (
    <Canvas
      camera={{ position: [0, 4, 20], fov: 42 }}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      style={{ background: '#020810' }}
      dpr={[1, 2]}
    >
      {/* Lighting: bright enough to see the Earth texture */}
      <ambientLight intensity={0.7} />
      <directionalLight position={[15, 8, 8]} intensity={1.1} color="#ffffff" />
      <directionalLight position={[-8, -4, -8]} intensity={0.25} color="#4466bb" />
      <pointLight position={[0, 12, 0]} intensity={0.3} color="#5588ff" />

      <Stars radius={250} depth={80} count={5000} factor={4} fade speed={0.3} />

      <Earth />
      <Atmosphere />
      <TerminatorOverlay timestamp={timestamp} />

      {/* Orbit altitude reference rings */}
      <OrbitRing altKm={400}  color="#1a5070" opacity={0.35} />
      <OrbitRing altKm={800}  color="#1a4060" opacity={0.20} />

      <SatellitePoints />
      <SelectionRing />
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
        minDistance={9}
        maxDistance={45}
        enablePan={false}
      />
    </Canvas>
  );
}
