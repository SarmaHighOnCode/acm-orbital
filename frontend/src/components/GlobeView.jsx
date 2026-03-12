/**
 * GlobeView.jsx — 3D Three.js Globe + Satellite & Debris Points
 * Owner: Dev 3 (Frontend)
 *
 * PERFORMANCE RULES:
 * - Debris: THREE.Points + BufferGeometry (single draw call for 10K+)
 * - Satellites: THREE.Points + BufferGeometry (single draw call for 50+)
 * - Use useRef, NEVER useState for position updates
 * - Mutate typed arrays directly in useFrame()
 */

import React, { useRef, useMemo, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import * as THREE from 'three';
import useStore from '../store';
import { SCALE_FACTOR, STATUS_COLORS } from '../utils/constants';

const DEG2RAD = Math.PI / 180;
const R_EARTH_KM = 6378.137;

/**
 * Convert lat/lon/alt to Cartesian Three.js coordinates.
 * x = right, y = up (north pole), z = towards camera
 */
function geoToCartesian(lat, lon, altKm) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const latRad = lat * DEG2RAD;
  const lonRad = lon * DEG2RAD;
  return {
    x: r * Math.cos(latRad) * Math.cos(lonRad),
    y: r * Math.sin(latRad),
    z: r * Math.cos(latRad) * Math.sin(lonRad),
  };
}

/* ── Earth Sphere ─────────────────────────────────────────── */
function Earth() {
  return (
    <mesh>
      <sphereGeometry args={[6.378, 64, 64]} />
      <meshStandardMaterial color="#1a3a5c" wireframe={false} />
    </mesh>
  );
}

/* ── Satellite Points ─────────────────────────────────────── */
function SatellitePoints() {
  const pointsRef = useRef();
  const satellites = useStore((s) => s.satellites);

  const { positions, colors } = useMemo(() => {
    const count = Math.max(satellites.length, 1);
    return {
      positions: new Float32Array(count * 3),
      colors: new Float32Array(count * 3),
    };
  }, [satellites.length]);

  useEffect(() => {
    if (!satellites.length) return;
    const statusColorMap = {
      NOMINAL:    new THREE.Color(STATUS_COLORS.NOMINAL),
      EVADING:    new THREE.Color(STATUS_COLORS.EVADING),
      RECOVERING: new THREE.Color(STATUS_COLORS.RECOVERING),
      EOL:        new THREE.Color(STATUS_COLORS.EOL),
    };
    const defaultColor = new THREE.Color(0x00ff88);

    for (let i = 0; i < satellites.length; i++) {
      const sat = satellites[i];
      const { x, y, z } = geoToCartesian(sat.lat, sat.lon, sat.alt_km);
      positions[i * 3]     = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      const c = statusColorMap[sat.status] || defaultColor;
      colors[i * 3]     = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }

    if (pointsRef.current) {
      pointsRef.current.geometry.attributes.position.needsUpdate = true;
      pointsRef.current.geometry.attributes.color.needsUpdate = true;
      pointsRef.current.geometry.setDrawRange(0, satellites.length);
    }
  }, [satellites, positions, colors]);

  if (!satellites.length) return null;

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={satellites.length}
          array={positions}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-color"
          count={satellites.length}
          array={colors}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        vertexColors
        sizeAttenuation
        transparent
        opacity={0.9}
        depthWrite={false}
      />
    </points>
  );
}

/* ── Debris Points ────────────────────────────────────────── */
function DebrisPoints() {
  const pointsRef = useRef();
  const debrisCloud = useStore((s) => s.debrisCloud);

  const positions = useMemo(() => {
    if (!debrisCloud.length) return null;
    const arr = new Float32Array(debrisCloud.length * 3);
    for (let i = 0; i < debrisCloud.length; i++) {
      const d = debrisCloud[i]; // [id, lat, lon, alt_km]
      if (!d || d.length < 4) continue;
      const { x, y, z } = geoToCartesian(d[1], d[2], d[3]);
      arr[i * 3]     = x;
      arr[i * 3 + 1] = y;
      arr[i * 3 + 2] = z;
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
        size={0.03}
        color="#4a5568"
        transparent
        opacity={0.5}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

/* ── Main GlobeView ───────────────────────────────────────── */
export default function GlobeView() {
  return (
    <Canvas
      camera={{ position: [0, 0, 20], fov: 45 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: '#0a0e1a' }}
    >
      <ambientLight intensity={0.3} />
      <directionalLight position={[10, 5, 5]} intensity={1} />
      <Stars radius={100} depth={50} count={2000} factor={4} fade speed={1} />
      <Earth />
      <SatellitePoints />
      <DebrisPoints />
      <OrbitControls enableDamping dampingFactor={0.05} />
    </Canvas>
  );
}
