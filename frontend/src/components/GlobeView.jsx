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

/* ── Sun position from timestamp ─────────────────────────
 *  Returns a unit vector pointing toward the Sun in the
 *  same ECI-like frame the globe uses.
 *  Uses a simplified solar position model (accurate to ~1°). */
function sunDirection(timestamp) {
  const d = timestamp ? new Date(timestamp) : new Date();
  const dayOfYear = Math.floor(
    (d - new Date(d.getUTCFullYear(), 0, 0)) / 86400000
  );
  // Solar declination (angle above/below equator)
  const declRad = -23.44 * DEG2RAD * Math.cos((2 * Math.PI * (dayOfYear + 10)) / 365);
  // Hour angle: where the Sun is in longitude (0° at solar noon UTC)
  const utcHours = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  const haRad = ((utcHours / 24) * 360 - 180) * DEG2RAD;
  // Convert to cartesian (same frame as geoToCartesian with lon=0 at +X)
  return new THREE.Vector3(
    Math.cos(declRad) * Math.cos(haRad),
    Math.sin(declRad),
    Math.cos(declRad) * Math.sin(haRad)
  );
}

/* ── GMST rotation for Earth ─────────────────────────────
 *  Returns the Y-axis rotation angle so continents face the
 *  correct direction for the given timestamp. */
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
  return new THREE.Vector3(
    r * Math.cos(latRad) * Math.cos(lonRad),
    r * Math.sin(latRad),
    r * Math.cos(latRad) * Math.sin(lonRad)
  );
}

/* ── Earth ─────────────────────────────────────────────── */
function Earth() {
  const meshRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  /* Day-side texture (bright oceans + green land) */
  const dayTexture = useMemo(() => {
    const W = 2048, H = 1024;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');

    /* Ocean gradient */
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0,    '#0a2a60');
    grad.addColorStop(0.15, '#1a5090');
    grad.addColorStop(0.5,  '#2068b8');
    grad.addColorStop(0.85, '#1a5090');
    grad.addColorStop(1,    '#0a2a60');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    /* Lat/lon grid */
    ctx.strokeStyle = 'rgba(80, 150, 230, 0.18)';
    ctx.lineWidth = 0.7;
    for (let lo = 0; lo <= 360; lo += 30) {
      const x = (lo / 360) * W;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let la = 0; la <= 180; la += 30) {
      const y = (la / 180) * H;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    /* Equator */
    ctx.strokeStyle = 'rgba(100, 190, 255, 0.35)';
    ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();

    const toC = (lo, la) => [((lo + 180) / 360) * W, ((90 - la) / 180) * H];
    const drawLand = (coords, fill, stroke) => {
      ctx.fillStyle = fill; ctx.strokeStyle = stroke; ctx.lineWidth = 1.6;
      ctx.beginPath();
      coords.forEach(([lo, la], i) => {
        const [x, y] = toC(lo, la);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath(); ctx.fill(); ctx.stroke();
    };

    const F = 'rgba(45, 145, 65, 0.97)';
    const S = 'rgba(90, 210, 110, 0.85)';

    /* North America */
    drawLand([[-168,71],[-140,70],[-100,74],[-82,70],[-65,47],[-55,47],[-60,44],
              [-75,44],[-80,25],[-85,30],[-90,28],[-105,20],[-118,32],[-122,37],
              [-124,49],[-130,55],[-140,60],[-150,62],[-165,65],[-168,71]], F, S);
    /* Greenland */
    drawLand([[-70,76],[-35,83],[-20,83],[-18,75],[-25,68],[-45,60],[-60,63],[-70,76]], F, S);
    /* South America */
    drawLand([[-80,12],[-65,12],[-50,2],[-35,-5],[-36,-13],[-40,-22],[-44,-23],
              [-48,-27],[-52,-33],[-60,-38],[-65,-44],[-68,-55],[-72,-50],
              [-70,-40],[-72,-30],[-72,-18],[-78,-2],[-80,0],[-80,12]], F, S);
    /* Europe */
    drawLand([[-10,36],[0,38],[10,43],[20,46],[30,60],[28,70],[15,70],
              [5,62],[-5,48],[-10,44],[-10,36]], F, S);
    /* Scandinavia */
    drawLand([[5,57],[10,62],[15,70],[28,71],[30,65],[25,58],[5,57]], F, S);
    /* Africa */
    drawLand([[-18,15],[0,15],[10,37],[22,37],[38,12],[42,12],[50,12],[50,2],
              [40,-10],[35,-20],[25,-35],[18,-35],[12,-25],[8,-5],[0,5],[-18,15]], F, S);
    /* Asia */
    drawLand([[28,42],[40,42],[45,38],[55,22],[68,24],[75,18],[80,28],[85,28],
              [92,28],[100,18],[105,10],[110,0],[115,5],[120,25],[125,35],[130,40],
              [138,36],[140,42],[135,48],[130,48],[120,50],[110,54],[100,60],
              [90,72],[75,72],[60,70],[40,68],[28,62],[28,42]], F, S);
    /* Australia */
    drawLand([[114,-22],[122,-18],[135,-12],[138,-12],[142,-10],[148,-18],
              [153,-27],[152,-38],[140,-38],[130,-33],[118,-28],[114,-26],[114,-22]], F, S);
    /* Japan */
    drawLand([[130,31],[132,34],[134,35],[136,35],[138,38],[141,41],
              [145,44],[143,44],[140,40],[138,36],[133,33],[130,31]], F, S);
    /* New Zealand */
    drawLand([[166,-46],[168,-43],[170,-38],[172,-36],[174,-37],[172,-40],[168,-46],[166,-46]], F, S);

    /* Ice caps */
    const IF = 'rgba(210, 230, 248, 0.55)';
    const IS = 'rgba(190, 220, 245, 0.65)';
    drawLand([[0,75],[60,78],[120,76],[180,74],[240,76],[300,78],[360,75]], IF, IS);
    drawLand([[0,-70],[60,-72],[120,-74],[180,-76],[240,-74],[300,-72],[360,-70]], IF, IS);

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }, []);

  /* Night-side emissive texture (dim city lights + dark ocean) */
  const nightTexture = useMemo(() => {
    const W = 2048, H = 1024;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');

    /* Very dark base (night ocean) */
    ctx.fillStyle = '#010408';
    ctx.fillRect(0, 0, W, H);

    /* Faint grid visible at night */
    ctx.strokeStyle = 'rgba(20, 50, 90, 0.15)';
    ctx.lineWidth = 0.5;
    for (let lo = 0; lo <= 360; lo += 30) {
      const x = (lo / 360) * W;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let la = 0; la <= 180; la += 30) {
      const y = (la / 180) * H;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    /* City light clusters — bright dots in populated regions */
    const toC = (lo, la) => [((lo + 180) / 360) * W, ((90 - la) / 180) * H];
    const cities = [
      /* Major city clusters: [lon, lat, intensity, spread] */
      [-74, 40, 1.0, 12],   /* NYC */
      [-87, 41, 0.8, 10],   /* Chicago */
      [-118, 34, 0.9, 11],  /* LA */
      [-43, -22, 0.7, 10],  /* Rio */
      [-46, -23, 0.8, 10],  /* Sao Paulo */
      [-3, 51, 0.9, 12],    /* London */
      [2, 48, 0.8, 10],     /* Paris */
      [13, 52, 0.6, 8],     /* Berlin */
      [37, 55, 0.7, 9],     /* Moscow */
      [31, 30, 0.6, 8],     /* Cairo */
      [77, 28, 0.9, 13],    /* Delhi */
      [72, 19, 0.8, 10],    /* Mumbai */
      [88, 22, 0.6, 8],     /* Kolkata */
      [100, 13, 0.5, 7],    /* Bangkok */
      [121, 31, 0.9, 12],   /* Shanghai */
      [116, 39, 0.9, 12],   /* Beijing */
      [139, 35, 1.0, 13],   /* Tokyo */
      [126, 37, 0.7, 9],    /* Seoul */
      [151, -33, 0.6, 8],   /* Sydney */
      [-99, 19, 0.7, 9],    /* Mexico City */
      [55, 25, 0.5, 7],     /* Dubai */
      [106, -6, 0.6, 8],    /* Jakarta */
      [103, 1, 0.5, 7],     /* Singapore */
    ];
    for (const [lon, lat, intensity, spread] of cities) {
      const [cx, cy] = toC(lon, lat);
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, spread);
      const a = Math.round(intensity * 180);
      grad.addColorStop(0, `rgba(255, 220, 140, ${intensity * 0.9})`);
      grad.addColorStop(0.4, `rgba(255, 180, 80, ${intensity * 0.4})`);
      grad.addColorStop(1, 'rgba(255, 160, 50, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(cx - spread, cy - spread, spread * 2, spread * 2);
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }, []);

  /* Rotate Earth to match real-world orientation via GMST */
  useFrame(() => {
    if (!meshRef.current) return;
    const rot = gmstRotation(timestamp);
    meshRef.current.rotation.y = -rot - Math.PI / 2;
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[R_EARTH, 96, 64]} />
      <meshStandardMaterial
        map={dayTexture}
        emissiveMap={nightTexture}
        emissive={new THREE.Color('#ffffff')}
        emissiveIntensity={1.2}
        roughness={0.85}
        metalness={0.05}
      />
    </mesh>
  );
}

/* ── Sunlight — directional light positioned at the Sun ── */
function Sunlight() {
  const lightRef = useRef();
  const timestamp = useStore((s) => s.timestamp);

  useFrame(() => {
    if (!lightRef.current) return;
    const dir = sunDirection(timestamp);
    lightRef.current.position.set(dir.x * 50, dir.y * 50, dir.z * 50);
  });

  return (
    <directionalLight
      ref={lightRef}
      color="#fff5e6"
      intensity={2.2}
      position={[50, 0, 0]}
    />
  );
}

/* ── Atmosphere glow layers ────────────────────────────── */
function Atmosphere() {
  return (
    <>
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.013, 64, 64]} />
        <meshBasicMaterial color="#2266ee" transparent opacity={0.08} side={THREE.BackSide} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[R_EARTH * 1.04, 64, 64]} />
        <meshBasicMaterial color="#0044cc" transparent opacity={0.04} side={THREE.BackSide} depthWrite={false} />
      </mesh>
    </>
  );
}

/* ── LEO altitude reference ring ───────────────────────── */
function OrbitRing({ altKm = 400, color = '#1a4060', opacity = 0.35 }) {
  const r = (R_EARTH_KM + altKm) * SCALE_FACTOR;
  const geometry = useMemo(() => {
    const pts = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, [r]);
  return (
    <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity }))} />
  );
}

/* ── Satellite Points ──────────────────────────────────── */
function SatellitePoints() {
  const pointsRef = useRef();
  const satellites = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const maxCount = 200;
  const { positions, colors, sizes } = useMemo(() => ({
    positions: new Float32Array(maxCount * 3),
    colors:    new Float32Array(maxCount * 3),
    sizes:     new Float32Array(maxCount),
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
      sizes[i] = sat.id === selectedSatellite ? 0.22 : 0.12;
    }
    if (pointsRef.current) {
      pointsRef.current.geometry.attributes.position.needsUpdate = true;
      pointsRef.current.geometry.attributes.color.needsUpdate    = true;
      pointsRef.current.geometry.attributes.size.needsUpdate     = true;
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

/* ── Selection ring around chosen satellite ────────────── */
function SelectionRing() {
  const satellites        = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const ringRef           = useRef();

  const selected = satellites.find((s) => s.id === selectedSatellite);

  useFrame(() => {
    if (ringRef.current) ringRef.current.rotation.y += 0.025;
  });

  if (!selected) return null;
  const pos   = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  const color = STATUS_HEX[selected.status] || '#00ff88';

  return (
    <mesh ref={ringRef} position={[pos.x, pos.y, pos.z]}>
      <torusGeometry args={[0.20, 0.014, 8, 36]} />
      <meshBasicMaterial color={color} transparent opacity={0.85} />
    </mesh>
  );
}

/* ── Label for the selected satellite ─────────────────── */
function SatelliteLabels() {
  const satellites        = useStore((s) => s.satellites);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const selected          = satellites.find((s) => s.id === selectedSatellite);
  if (!selected) return null;
  const pos   = geoToCartesian(selected.lat, selected.lon, selected.alt_km || 400);
  const color = STATUS_HEX[selected.status] || '#00ff88';
  return (
    <Html position={[pos.x, pos.y + 0.30, pos.z]} center style={{ pointerEvents: 'none' }}>
      <div style={{
        color,
        fontSize: '11px',
        fontFamily: 'JetBrains Mono, monospace',
        background: 'rgba(5, 8, 18, 0.92)',
        padding: '3px 8px',
        borderRadius: '4px',
        border: `1px solid ${color}55`,
        whiteSpace: 'nowrap',
        boxShadow: `0 0 10px ${color}44`,
      }}>
        ▶ {selected.id} · {selected.fuel_kg?.toFixed(1)}kg · {selected.status}
      </div>
    </Html>
  );
}

/* ── Satellite trails ──────────────────────────────────── */
function SatelliteTrails() {
  const satHistory        = useStore((s) => s.satHistory);
  const selectedSatellite = useStore((s) => s.selectedSatellite);
  const satellites        = useStore((s) => s.satellites);

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
      const points     = history.map((pt) => geoToCartesian(pt.lat, pt.lon, pt.alt || 400));
      const status     = satStatusMap[satId] || 'NOMINAL';
      const color      = isSelected ? (STATUS_HEX[status] || '#00ff88') : '#2a6090';
      result.push({ satId, points, isSelected, color });
    }
    return result;
  }, [satHistory, selectedSatellite, satStatusMap]);

  return (
    <group>
      {trails.map(({ satId, points, isSelected, color }) => {
        const arr = new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]));
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
        return (
          <primitive
            key={`trail-${satId}`}
            object={new THREE.Line(
              geo,
              new THREE.LineBasicMaterial({ color, transparent: true, opacity: isSelected ? 0.9 : 0.6 })
            )}
          />
        );
      })}
    </group>
  );
}

/* ── Predicted trajectory (dashed) ────────────────────── */
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
    const dlon = last.lon - prev.lon;
    const pts = [];
    for (let i = 0; i <= 54; i++) {
      let lat = last.lat + dlat * i;
      let lon = last.lon + dlon * i;
      if (lat > 90)   { lat =  180 - lat; }
      if (lat < -90)  { lat = -180 - lat; }
      if (lon > 180)  lon -= 360;
      if (lon < -180) lon += 360;
      pts.push(geoToCartesian(lat, lon, last.alt || 400));
    }
    return pts;
  }, [satHistory, selectedSatellite]);

  const lineRef = useRef();
  useEffect(() => {
    if (lineRef.current?.geometry) lineRef.current.computeLineDistances();
  }, [prediction]);

  if (!prediction) return null;
  const arr = new Float32Array(prediction.flatMap((p) => [p.x, p.y, p.z]));
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  return (
    <primitive
      ref={lineRef}
      object={new THREE.Line(
        geo,
        new THREE.LineDashedMaterial({ color: '#00ff88', transparent: true, opacity: 0.6, dashSize: 0.18, gapSize: 0.09 })
      )}
    />
  );
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
      <pointsMaterial size={0.025} color="#7896b0" transparent opacity={0.45} sizeAttenuation depthWrite={false} />
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

  /* Surface position */
  const surfacePos = useMemo(() => {
    const p = geoToCartesian(gs.lat, gs.lon, 0);
    return p.clone().normalize().multiplyScalar(R_EARTH * 1.002);
  }, [gs.lat, gs.lon]);

  /* Rotate group so local +Y points radially outward */
  const quaternion = useMemo(() =>
    new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      surfacePos.clone().normalize()
    )
  , [surfacePos]);

  return (
    <group position={surfacePos.toArray()} quaternion={quaternion.toArray()}>
      {/* Flat disc on surface */}
      <mesh>
        <circleGeometry args={[0.065, 18]} />
        <meshBasicMaterial color="#fbbf24" transparent opacity={0.75} side={THREE.DoubleSide} />
      </mesh>
      {/* Vertical spike */}
      <mesh position={[0, 0.13, 0]}>
        <coneGeometry args={[0.028, 0.22, 6]} />
        <meshBasicMaterial color="#fde68a" />
      </mesh>
      {/* Pulsing ring */}
      <mesh ref={pulsRef}>
        <ringGeometry args={[0.08, 0.115, 22]} />
        <meshBasicMaterial color="#fbbf24" transparent opacity={0.50} side={THREE.DoubleSide} />
      </mesh>
      {/* Label */}
      <Html position={[0, 0.38, 0]} center style={{ pointerEvents: 'none' }}>
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
          ◆ {gs.name}
        </div>
      </Html>
    </group>
  );
}

function GroundStationMarkers() {
  return (
    <group>
      {GROUND_STATIONS.map((gs) => <GroundStationMarker key={gs.id} gs={gs} />)}
    </group>
  );
}

/* ── CDM threat lines ──────────────────────────────────── */
function CDMLines() {
  const cdms        = useStore((s) => s.cdms);
  const satellites  = useStore((s) => s.satellites);
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
      const deb    = debrisCloud.find((d) => d[0] === cdm.debris_id);
      if (!deb) continue;
      const debPos = geoToCartesian(deb[1], deb[2], deb[3]);
      const color  = cdm.risk === 'CRITICAL' ? '#ff0000'
        : cdm.risk === 'RED'    ? '#ff3355'
        : cdm.risk === 'YELLOW' ? '#ffaa00'
        : '#00ff88';
      result.push({ key: `${cdm.satellite_id}-${cdm.debris_id}-${result.length}`, satPos, debPos, color });
    }
    return result;
  }, [cdms, satellites, debrisCloud]);

  return (
    <group>
      {lines.map(({ key, satPos, debPos, color }) => {
        const arr = new Float32Array([satPos.x, satPos.y, satPos.z, debPos.x, debPos.y, debPos.z]);
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
        return (
          <primitive
            key={key}
            object={new THREE.Line(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }))}
          />
        );
      })}
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

/* ── Main GlobeView ────────────────────────────────────── */
export default function GlobeView() {
  return (
    <Canvas
      camera={{ position: [0, 4, 20], fov: 42 }}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      style={{ background: '#020810' }}
      dpr={[1, 2]}
    >
      {/* Lighting: dim ambient so night side is dark + sun directional */}
      <ambientLight intensity={0.08} color="#1a2a4a" />
      <Sunlight />

      {/* Stars */}
      <Stars radius={250} depth={80} count={5000} factor={4} fade speed={0.3} />

      <Earth />
      <Atmosphere />

      {/* Orbit altitude reference rings */}
      <OrbitRing altKm={400} color="#1a6070" opacity={0.40} />
      <OrbitRing altKm={800} color="#1a4060" opacity={0.25} />

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
