/**
 * GlobeView.jsx — 3D Three.js/WebGL Globe with Full Orbital Visualization
 * Enhanced: higher-res globe, cloud layer, orbital rings, gradient trails
 */

import React, { useRef, useMemo, useEffect, useCallback } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Stars, Html, useTexture } from '@react-three/drei';
import * as THREE from 'three';
import useStore from '../store';
import { SCALE_FACTOR, STATUS_COLORS } from '../utils/constants';

const DEG2RAD = Math.PI / 180;
const R_EARTH = 6.378;
const R_EARTH_KM = 6378.137;

/* ── Sun position from timestamp ───────────────────────── */
function sunDirection(timestamp) {
  const d = timestamp ? new Date(timestamp) : new Date();
  const dayOfYear = Math.floor(
    (d - new Date(d.getUTCFullYear(), 0, 0)) / 86400000
  );
  const declRad = -23.44 * DEG2RAD * Math.cos((2 * Math.PI * (dayOfYear + 10)) / 365);
  const utcHours = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  const haRad = ((utcHours / 24) * 360 - 180) * DEG2RAD;
  return new THREE.Vector3(
    Math.cos(declRad) * Math.cos(haRad),
    Math.sin(declRad),
    Math.cos(declRad) * Math.sin(haRad)
  );
}

/* ── GMST rotation for Earth ───────────────────────────── */
function gmstRotation(timestamp) {
  const d = timestamp ? new Date(timestamp) : new Date();
  const j2000 = new Date('2000-01-01T12:00:00Z');
  const dtDays = (d - j2000) / 86400000;
  const gmstDeg = (280.46061837 + 360.98564736629 * dtDays) % 360;
  return gmstDeg * DEG2RAD;
}

const GROUND_STATIONS = [
  { id: 'GS-001', name: 'ISTRAC',       lat: 13.0333,  lon:  77.5167 },
  { id: 'GS-002', name: 'Svalbard',     lat: 78.2297,  lon:  15.4077 },
  { id: 'GS-003', name: 'Goldstone',    lat: 35.4266,  lon: -116.89  },
  { id: 'GS-004', name: 'Punta Arenas', lat: -53.15,   lon: -70.9167 },
  { id: 'GS-005', name: 'IIT Delhi',    lat: 28.545,   lon:  77.1926 },
  { id: 'GS-006', name: 'McMurdo',      lat: -77.8463, lon: 166.6682 },
];

const STATUS_HEX = {
  NOMINAL:    '#00ff88',
  EVADING:    '#ffaa00',
  RECOVERING: '#3b82f6',
  EOL:        '#ff3355',
};

function geoToCartesian(lat, lon, altKm) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const latRad = lat * DEG2RAD;
  const lonRad = lon * DEG2RAD;
  // Three.js SphereGeometry maps lon=90°E to -Z (z = R*sin(phi) where phi=(lon+180°)),
  // so geographic z must be negated to match sphere UV orientation.
  return new THREE.Vector3(
    r * Math.cos(latRad) * Math.cos(lonRad),
    r * Math.sin(latRad),
    -r * Math.cos(latRad) * Math.sin(lonRad)
  );
}

/* ── Earth ─────────────────────────────────────────────── */
function Earth() {
  const meshRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  /* Load NASA Blue Marble textures from public/ */
  const [dayMap, nightMap] = useTexture([
    '/earth_day.jpg',
    '/earth_night.jpg',
  ]);

  /* Configure texture wrapping */
  useMemo(() => {
    [dayMap, nightMap].forEach((tex) => {
      tex.wrapS = THREE.RepeatWrapping;
      tex.colorSpace = THREE.SRGBColorSpace;
    });
  }, [dayMap, nightMap]);

  useFrame(() => {
    if (!meshRef.current) return;
    const rot = gmstRotation(timestamp);
    meshRef.current.rotation.y = -rot - Math.PI / 2;
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[R_EARTH, 128, 80]} />
      <meshStandardMaterial
        map={dayMap}
        emissiveMap={nightMap}
        emissive={new THREE.Color(1, 1, 1)}
        emissiveIntensity={0.8}
        roughness={0.9}
        metalness={0.05}
      />
    </mesh>
  );
}

/* ── Cloud Layer ───────────────────────────────────────── */
function CloudLayer() {
  const meshRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  const cloudTexture = useMemo(() => {
    const W = 1024, H = 512;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);

    // Procedural cloud bands (wispy patterns)
    const rng = { s: 42, next() { this.s = (this.s * 16807 + 0) % 2147483647; return this.s / 2147483647; } };
    for (let i = 0; i < 300; i++) {
      const cx = rng.next() * W;
      const cy = rng.next() * H;
      const rx = 20 + rng.next() * 80;
      const ry = 5 + rng.next() * 20;
      const alpha = 0.04 + rng.next() * 0.12;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, rx);
      grad.addColorStop(0, `rgba(255, 255, 255, ${alpha})`);
      grad.addColorStop(0.6, `rgba(255, 255, 255, ${alpha * 0.3})`);
      grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = grad;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(1, ry / rx);
      ctx.translate(-cx, -cy);
      ctx.fillRect(cx - rx, cy - rx, rx * 2, rx * 2);
      ctx.restore();
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }, []);

  useFrame(() => {
    if (!meshRef.current) return;
    const rot = gmstRotation(timestamp);
    // Clouds rotate slightly slower than Earth (wind drift effect)
    meshRef.current.rotation.y = -rot - Math.PI / 2 + 0.02;
  });

  return (
    <mesh ref={meshRef} raycast={() => null}>
      <sphereGeometry args={[R_EARTH * 1.005, 96, 64]} />
      <meshStandardMaterial
        map={cloudTexture}
        transparent
        opacity={0.6}
        depthWrite={false}
        side={THREE.FrontSide}
      />
    </mesh>
  );
}

/* ── Sunlight ──────────────────────────────────────────── */
function Sunlight() {
  const lightRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  useFrame(() => {
    if (!lightRef.current) return;
    const dir = sunDirection(timestamp);
    lightRef.current.position.set(dir.x * 50, dir.y * 50, dir.z * 50);
  });

  return (
    <directionalLight ref={lightRef} color="#fff5e6" intensity={2.2} position={[50, 0, 0]} />
  );
}

/* ── Atmosphere glow layers (enhanced 3-layer) ─────────── */
function Atmosphere() {
  return (
    <>
      <mesh raycast={() => null}>
        <sphereGeometry args={[R_EARTH * 1.008, 80, 64]} />
        <meshBasicMaterial color="#4488ff" transparent opacity={0.06} side={THREE.BackSide} depthWrite={false} />
      </mesh>
      <mesh raycast={() => null}>
        <sphereGeometry args={[R_EARTH * 1.025, 80, 64]} />
        <meshBasicMaterial color="#2266ee" transparent opacity={0.05} side={THREE.BackSide} depthWrite={false} />
      </mesh>
      <mesh raycast={() => null}>
        <sphereGeometry args={[R_EARTH * 1.06, 64, 64]} />
        <meshBasicMaterial color="#0044cc" transparent opacity={0.03} side={THREE.BackSide} depthWrite={false} />
      </mesh>
    </>
  );
}

/* ── LEO altitude reference ring ───────────────────────── */
function OrbitRing({ altKm = 400, color = '#1a4060', opacity = 0.35 }) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const lineObj = useMemo(() => {
    const pts = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
    }
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    return new THREE.Line(geo, mat);
  }, [r, color, opacity]);

  useEffect(() => {
    return () => { lineObj.geometry.dispose(); lineObj.material.dispose(); };
  }, [lineObj]);

  return <primitive object={lineObj} />;
}

/* ── Full Orbital Path Ring for selected satellite ─────── */
function OrbitalPathRing() {
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const satHistory = useStore((s) => s.satHistory);

  const orbitPath = useMemo(() => {
    if (!selectedSatellite) return null;
    const sat = satellites.find((s) => s.id === selectedSatellite);
    if (!sat) return null;

    const history = satHistory[selectedSatellite];
    if (!history || history.length < 3) return null;

    // Use the history + prediction to compute a full orbit ring
    // Calculate orbital velocity from last two points to extrapolate the full orbit
    const last = history[history.length - 1];
    const prev = history[history.length - 2];
    const dlat = last.lat - prev.lat;
    let dlon = last.lon - prev.lon;
    if (dlon > 180) dlon -= 360;
    if (dlon < -180) dlon += 360;

    const alt = last.alt || sat.alt_km || 400;
    const pts = [];

    // Generate 360 points for a full orbit (~90 min)
    // Orbital period at this altitude
    const nPoints = 360;
    for (let i = 0; i < nPoints; i++) {
      const frac = i / nPoints * 270; // ~270 steps to cover a full orbit
      let lat = last.lat + dlat * frac;
      let lon = last.lon + dlon * frac;

      // Wrap lat/lon properly for sinusoidal ground track
      if (lat > 90)   { lat = 180 - lat; lon += 180; }
      if (lat < -90)  { lat = -180 - lat; lon += 180; }
      lon = ((lon + 180) % 360 + 360) % 360 - 180;

      pts.push(geoToCartesian(lat, lon, alt));
    }
    // Close the loop
    pts.push(pts[0].clone());

    return pts;
  }, [satellites, selectedSatellite, satHistory]);

  const lineObj = useMemo(() => {
    if (!orbitPath) return null;
    const arr = new Float32Array(orbitPath.flatMap((p) => [p.x, p.y, p.z]));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    const mat = new THREE.LineBasicMaterial({ color: '#00ff88', transparent: true, opacity: 0.15 });
    return new THREE.Line(geo, mat);
  }, [orbitPath]);

  useEffect(() => {
    return () => {
      if (lineObj) { lineObj.geometry.dispose(); lineObj.material.dispose(); }
    };
  }, [lineObj]);

  if (!lineObj) return null;
  return <primitive object={lineObj} />;
}

/* ── Satellite Points (enhanced — larger with glow) ────── */
function SatellitePoints() {
  const pointsRef = useRef();
  const glowRef = useRef();
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const maxCount = 200;
  const { positions, colors, sizes, glowSizes } = useMemo(() => ({
    positions: new Float32Array(maxCount * 3),
    colors:    new Float32Array(maxCount * 3),
    sizes:     new Float32Array(maxCount),
    glowSizes: new Float32Array(maxCount),
  }), []);

  useEffect(() => {
    if (!satellites.length) return;
    const statusColorMap = {
      NOMINAL:    new THREE.Color(STATUS_COLORS.NOMINAL),
      EVADING:    new THREE.Color(STATUS_COLORS.EVADING),
      RECOVERING: new THREE.Color(STATUS_COLORS.RECOVERING),
      EOL:        new THREE.Color(STATUS_COLORS.EOL),
    };
    const defaultColor = new THREE.Color(0x00ff88);
    for (let i = 0; i < Math.min(satellites.length, maxCount); i++) {
      const sat = satellites[i];
      const pos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      positions[i * 3]     = pos.x;
      positions[i * 3 + 1] = pos.y;
      positions[i * 3 + 2] = pos.z;
      const c = statusColorMap[sat.status] || defaultColor;
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
      sizes[i] = sat.id === selectedSatellite ? 0.25 : 0.14;
      glowSizes[i] = sat.id === selectedSatellite ? 0.50 : 0.30;
    }
    const count = Math.min(satellites.length, maxCount);
    if (pointsRef.current) {
      pointsRef.current.geometry.attributes.position.needsUpdate = true;
      pointsRef.current.geometry.attributes.color.needsUpdate    = true;
      pointsRef.current.geometry.attributes.size.needsUpdate     = true;
      pointsRef.current.geometry.setDrawRange(0, count);
    }
    if (glowRef.current) {
      glowRef.current.geometry.attributes.position.needsUpdate = true;
      glowRef.current.geometry.attributes.color.needsUpdate    = true;
      glowRef.current.geometry.attributes.size.needsUpdate     = true;
      glowRef.current.geometry.setDrawRange(0, count);
    }
  }, [satellites, selectedSatellite, positions, colors, sizes, glowSizes]);

  if (!satellites.length) return null;
  return (
    <>
      {/* Glow layer (behind) */}
      <points ref={glowRef}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" count={maxCount} array={positions} itemSize={3} />
          <bufferAttribute attach="attributes-color"    count={maxCount} array={colors}    itemSize={3} />
          <bufferAttribute attach="attributes-size"     count={maxCount} array={glowSizes} itemSize={1} />
        </bufferGeometry>
        <pointsMaterial size={0.30} vertexColors sizeAttenuation transparent opacity={0.25} depthWrite={false} />
      </points>
      {/* Core dots */}
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" count={maxCount} array={positions} itemSize={3} />
          <bufferAttribute attach="attributes-color"    count={maxCount} array={colors}    itemSize={3} />
          <bufferAttribute attach="attributes-size"     count={maxCount} array={sizes}     itemSize={1} />
        </bufferGeometry>
        <pointsMaterial size={0.14} vertexColors sizeAttenuation transparent opacity={1.0} depthWrite={false} />
      </points>
    </>
  );
}

/* ── Selection ring around chosen satellite ────────────── */
function SelectionRing() {
  const satellites        = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const ringRef           = useRef();
  const outerRef          = useRef();

  const selected = satellites.find((s) => s.id === selectedSatellite);

  useFrame(() => {
    if (ringRef.current) ringRef.current.rotation.y += 0.025;
    if (outerRef.current) outerRef.current.rotation.y -= 0.015;
  });

  if (!selected) return null;
  const pos   = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  const color = STATUS_HEX[selected.status] || '#00ff88';

  return (
    <group position={[pos.x, pos.y, pos.z]}>
      <mesh ref={ringRef}>
        <torusGeometry args={[0.22, 0.016, 8, 36]} />
        <meshBasicMaterial color={color} transparent opacity={0.85} />
      </mesh>
      {/* Outer counter-rotating ring */}
      <mesh ref={outerRef}>
        <torusGeometry args={[0.32, 0.008, 6, 36]} />
        <meshBasicMaterial color={color} transparent opacity={0.3} />
      </mesh>
    </group>
  );
}

/* ── Label for the selected satellite ─────────────────── */
function SatelliteLabels() {
  const satellites        = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const cdms              = useStore((s) => s.cdms);
  const selected          = satellites.find((s) => s.id === selectedSatellite);
  if (!selected) return null;
  const pos   = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  const color = STATUS_HEX[selected.status] || '#00ff88';
  const satCdms = cdms.filter((c) => c.satellite_id === selected.id);

  return (
      <Html occlude="blending" position={[pos.x, pos.y + 0.35, pos.z]} center style={{ pointerEvents: 'none' }}>
      <div style={{
        color,
        fontSize: '10px',
        fontFamily: 'JetBrains Mono, monospace',
        background: 'rgba(5, 8, 18, 0.92)',
        padding: '4px 10px',
        borderRadius: '5px',
        border: `1px solid ${color}55`,
        whiteSpace: 'nowrap',
        boxShadow: `0 0 12px ${color}44`,
        lineHeight: '1.5',
      }}>
        <div style={{ fontWeight: 700 }}>{selected.id}</div>
        <div style={{ fontSize: '8px', color: '#9ca3af' }}>
          {selected.fuel_kg?.toFixed(1)}kg &middot; {selected.status}
          {satCdms.length > 0 && <span style={{ color: '#ffaa00' }}> &middot; {satCdms.length} CDMs</span>}
        </div>
        <div style={{ fontSize: '8px', color: '#6b7280' }}>
          ALT {(selected.alt_km || 400).toFixed(0)}km &middot; {selected.lat.toFixed(1)}&deg;, {selected.lon.toFixed(1)}&deg;
        </div>
      </div>
    </Html>
  );
}

/* ── Satellite trails (gradient-faded) ─────────────────── */
function SatelliteTrails() {
  const satHistory        = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const satellites        = useStore((s) => s.satellites);

  const satStatusMap = useMemo(() => {
    const m = {};
    for (const sat of satellites) m[sat.id] = sat.status;
    return m;
  }, [satellites]);

  const trailObjects = useMemo(() => {
    const result = [];
    for (const [satId, history] of Object.entries(satHistory)) {
      if (!history || history.length < 2) continue;
      const isSelected = satId === selectedSatellite;
      const status     = satStatusMap[satId] || 'NOMINAL';
      const points = history.map((pt) => geoToCartesian(pt.lat, pt.lon, pt.alt || 400));

      if (isSelected) {
        const color = STATUS_HEX[status] || '#00ff88';
        for (let i = 1; i < points.length; i++) {
          const opacity = (i / points.length) * 0.95;
          const arr = new Float32Array([points[i-1].x, points[i-1].y, points[i-1].z, points[i].x, points[i].y, points[i].z]);
          const geo = new THREE.BufferGeometry();
          geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
          const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity, linewidth: 2 });
          result.push(new THREE.Line(geo, mat));
        }
      } else {
        const arr = new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]));
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
        const mat = new THREE.LineBasicMaterial({ color: '#1a4a70', transparent: true, opacity: 0.4 });
        result.push(new THREE.Line(geo, mat));
      }
    }
    return result;
  }, [satHistory, selectedSatellite, satStatusMap]);

  useEffect(() => {
    return () => {
      for (const obj of trailObjects) {
        obj.geometry.dispose();
        obj.material.dispose();
      }
    };
  }, [trailObjects]);

  return (
    <group>
      {trailObjects.map((obj, i) => (
        <primitive key={i} object={obj} />
      ))}
    </group>
  );
}

/* ── Predicted trajectory (curved orbital arc) ─────────── */
function PredictedTrajectory() {
  const satHistory        = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);

  const prediction = useMemo(() => {
    if (!selectedSatellite) return null;
    const history = satHistory[selectedSatellite];
    if (!history || history.length < 2) return null;
    const last = history[history.length - 1];
    const prev = history[history.length - 2];
    const dlat = last.lat - prev.lat;
    let dlon = last.lon - prev.lon;
    if (dlon > 180) dlon -= 360;
    if (dlon < -180) dlon += 360;

    const pts = [];
    for (let i = 0; i <= 54; i++) {
      let lat = last.lat + dlat * i;
      let lon = last.lon + dlon * i;
      if (lat > 90)   { lat = 180 - lat; lon += 180; }
      if (lat < -90)  { lat = -180 - lat; lon += 180; }
      lon = ((lon + 180) % 360 + 360) % 360 - 180;
      pts.push(geoToCartesian(lat, lon, last.alt || 400));
    }
    return pts;
  }, [satHistory, selectedSatellite]);

  const lineObj = useMemo(() => {
    if (!prediction) return null;
    const arr = new Float32Array(prediction.flatMap((p) => [p.x, p.y, p.z]));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    const mat = new THREE.LineDashedMaterial({ color: '#00ff88', transparent: true, opacity: 0.45, dashSize: 0.15, gapSize: 0.08 });
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    return line;
  }, [prediction]);

  useEffect(() => {
    return () => {
      if (lineObj) { lineObj.geometry.dispose(); lineObj.material.dispose(); }
    };
  }, [lineObj]);

  if (!lineObj) return null;
  return <primitive object={lineObj} />;
}

/* ── Debris cloud ──────────────────────────────────────── */
function DebrisPoints() {
  const debrisCloud = useStore((s) => s.debrisCloud);
  const positions   = useMemo(() => {
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
      <pointsMaterial size={0.03} color="#7896b0" transparent opacity={0.35} sizeAttenuation depthWrite={false} />
    </points>
  );
}

/* ── Ground station 3D markers ─────────────────────────── */
function GroundStationMarker({ gs }) {
  const pulsRef = useRef();

  useFrame(({ clock }) => {
    if (!pulsRef.current) return;
    const s = 1 + 0.35 * Math.abs(Math.sin(clock.getElapsedTime() * 1.4));
    pulsRef.current.scale.setScalar(s);
  });

  const surfacePos = useMemo(() => {
    const p = geoToCartesian(gs.lat, gs.lon, 0);
    return p.clone().normalize().multiplyScalar(R_EARTH * 1.012);
  }, [gs.lat, gs.lon]);

  const quaternion = useMemo(() =>
    new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      surfacePos.clone().normalize()
    )
  , [surfacePos]);

  return (
    <group position={surfacePos.toArray()} quaternion={quaternion.toArray()}>
      <mesh>
        <circleGeometry args={[0.065, 18]} />
        <meshBasicMaterial color="#fbbf24" transparent opacity={0.75} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.13, 0]}>
        <coneGeometry args={[0.028, 0.22, 6]} />
        <meshBasicMaterial color="#fde68a" depthWrite={false} />
      </mesh>
      <mesh ref={pulsRef}>
        <ringGeometry args={[0.08, 0.115, 22]} />
        <meshBasicMaterial color="#fbbf24" transparent opacity={0.50} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
        <Html occlude="blending" position={[0, 0.38, 0]} center style={{ pointerEvents: 'none' }}>
        <div style={{
          color: '#fde68a',
          fontSize: '9px',
          fontFamily: 'JetBrains Mono, monospace',
          background: 'rgba(5, 8, 18, 0.88)',
          padding: '2px 6px',
          borderRadius: '3px',
          border: '1px solid #fbbf2450',
          whiteSpace: 'nowrap',
          boxShadow: '0 0 7px #fbbf2440',
        }}>
          {gs.name}
        </div>
      </Html>
    </group>
  );
}

function GroundStationMarkers() {
  const groupRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  // Rotate ground stations with the Earth (same GMST rotation as Earth mesh)
  useFrame(() => {
    if (!groupRef.current) return;
    const rot = gmstRotation(timestamp);
    groupRef.current.rotation.y = -rot - Math.PI / 2;
  });

  return (
    <group ref={groupRef}>
      {GROUND_STATIONS.map((gs) => <GroundStationMarker key={gs.id} gs={gs} />)}
    </group>
  );
}

/* ── CDM threat lines (pulsing for CRITICAL) ───────────── */
function CDMLines() {
  const cdms        = useStore((s) => s.cdms);
  const satellites  = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);
  const groupRef    = useRef();

  const lineObjects = useMemo(() => {
    if (!cdms.length) return [];
    const satMap = {};
    for (const sat of satellites) satMap[sat.id] = sat;
    const result = [];
    for (const cdm of cdms.slice(0, 30)) {
      const sat = satMap[cdm.satellite_id];
      if (!sat) continue;
      const satPos = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
      const deb    = debrisCloud.find((d) => d[0] === cdm.debris_id);
      if (!deb) continue;
      const debPos = geoToCartesian(deb[1], deb[2], deb[3]);
      const color  = cdm.risk === 'CRITICAL' ? '#ff0000'
        : cdm.risk === 'RED'    ? '#ff3355'
        : cdm.risk === 'YELLOW' ? '#ffaa00'
        : '#00ff88';
      const opacity = cdm.risk === 'CRITICAL' ? 0.9 : cdm.risk === 'RED' ? 0.7 : 0.5;
      const arr = new Float32Array([satPos.x, satPos.y, satPos.z, debPos.x, debPos.y, debPos.z]);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
      const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
      result.push(new THREE.Line(geo, mat));
    }
    return result;
  }, [cdms, satellites, debrisCloud]);

  // Dispose old GPU resources when lineObjects change
  useEffect(() => {
    return () => {
      for (const line of lineObjects) {
        line.geometry.dispose();
        line.material.dispose();
      }
    };
  }, [lineObjects]);

  return (
    <group ref={groupRef}>
      {lineObjects.map((obj, i) => (
        <primitive key={i} object={obj} />
      ))}
    </group>
  );
}

/* ── Click-to-select satellite ─────────────────────────── */
function ClickHandler() {
  const { camera, raycaster, gl } = useThree();
  const satellites           = useStore((s) => s.satellites);
  const setSelectedSatellite = useStore((s) => s.setSelectedSatellite);

  const handleClick = useCallback((event) => {
    const rect  = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width)  *  2 - 1,
      -((event.clientY - rect.top)  / rect.height) *  2 + 1
    );
    raycaster.setFromCamera(mouse, camera);
    let closest = null, closestDist = 0.3;
    for (const sat of satellites) {
      const pos  = geoToCartesian(sat.lat, sat.lon, sat.alt_km || 400);
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

/* ── HUD overlay ───────────────────────────────────────── */
function HUDOverlay() {
  const satellites  = useStore((s) => s.satellites);
  const debrisCloud = useStore((s) => s.debrisCloud);
  const cdms        = useStore((s) => s.cdms);
  const riskCounts  = cdms.reduce((acc, c) => { acc[c.risk] = (acc[c.risk] || 0) + 1; return acc; }, {});

  return (
    <Html position={[-R_EARTH * 2.6, R_EARTH * 2.1, 0]} style={{ pointerEvents: 'none' }}>
      <div style={{
        color: '#9ca3af',
        fontSize: '10px',
        fontFamily: 'JetBrains Mono, monospace',
        lineHeight: '1.6',
        background: 'rgba(5, 8, 18, 0.75)',
        padding: '6px 10px',
        borderRadius: '5px',
        border: '1px solid #1f293766',
      }}>
        <div style={{ color: '#e5e7eb', fontSize: '11px', fontWeight: 600, marginBottom: 2 }}>ORBITAL VIEW</div>
        <div><span style={{ color: '#00ff88' }}>&#9632;</span> {satellites.length} satellites</div>
        <div><span style={{ color: '#7896b0' }}>&#9632;</span> {debrisCloud.length.toLocaleString()} debris</div>
        {cdms.length > 0 && (
          <div style={{ color: '#ffaa00', marginTop: 2 }}>
            {cdms.length} CDMs
            {riskCounts.CRITICAL > 0 && <span style={{ color: '#ff3355' }}> ({riskCounts.CRITICAL} CRIT)</span>}
          </div>
        )}
      </div>
    </Html>
  );
}

/* ── Main GlobeView ────────────────────────────────────── */
export default function GlobeView() {
  return (
    <Canvas
      camera={{ position: [0, 4, 18], fov: 42 }}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      style={{ background: '#020810' }}
      dpr={[1, 2]}
    >
      {/* Ambient only — no directional sun, uniform look */}
      <ambientLight intensity={0.6} color="#334466" />

      {/* Stars — denser for depth */}
      <Stars radius={250} depth={80} count={7000} factor={4} fade speed={0.3} />

      <Earth />
      <CloudLayer />
      <Atmosphere />

      {/* Orbit altitude reference rings */}
      <OrbitRing altKm={400} color="#1a6070" opacity={0.40} />
      <OrbitRing altKm={800} color="#1a4060" opacity={0.20} />
      <OrbitRing altKm={1200} color="#152a45" opacity={0.12} />

      {/* Full orbital path of selected satellite */}
      <OrbitalPathRing />

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
