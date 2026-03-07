/**
 * GlobeView.jsx — 3D Three.js Globe + Debris Points
 * Owner: Dev 3 (Frontend)
 *
 * PERFORMANCE RULES:
 * - Debris: THREE.Points + BufferGeometry (single draw call for 10K+)
 * - Satellites: THREE.InstancedMesh (single draw call for 50+)
 * - Use useRef, NEVER useState for position updates
 * - Mutate typed arrays directly in useFrame()
 */

import React, { useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';

function Earth() {
  return (
    <mesh>
      <sphereGeometry args={[6.378, 64, 64]} />
      <meshStandardMaterial color="#1a3a5c" wireframe={false} />
    </mesh>
  );
}

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
      <OrbitControls enableDamping dampingFactor={0.05} />
      {/* TODO: Dev 3 — Add debris Points, satellite InstancedMesh, orbit trails */}
    </Canvas>
  );
}
