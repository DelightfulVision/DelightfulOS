import { useRef, useState, useCallback } from "react";
import { useFrame } from "@react-three/fiber";
import { usePlane, useBox } from "@react-three/cannon";
import { usePiezo, PiezoState } from "./usePiezo";
import * as THREE from "three";

const COLORS = [
  "#FFD700", "#a78bfa", "#4ade80", "#f87171", "#38bdf8",
  "#fb923c", "#e879f9", "#34d399", "#f472b6", "#60a5fa",
];

interface FallingCube {
  id: number;
  position: [number, number, number];
  color: string;
  size: number;
  velocity: [number, number, number];
}

let cubeId = 0;

function Floor() {
  const [ref] = usePlane<THREE.Mesh>(() => ({
    rotation: [-Math.PI / 2, 0, 0],
    position: [0, -0.5, 0],
  }));
  return (
    <mesh ref={ref} receiveShadow>
      <planeGeometry args={[30, 30]} />
      <meshStandardMaterial color="#111118" />
    </mesh>
  );
}

function Walls() {
  const [back] = usePlane<THREE.Mesh>(() => ({ position: [0, 5, -8], rotation: [0, 0, 0] }));
  const [front] = usePlane<THREE.Mesh>(() => ({ position: [0, 5, 8], rotation: [0, Math.PI, 0] }));
  const [left] = usePlane<THREE.Mesh>(() => ({ position: [-8, 5, 0], rotation: [0, Math.PI / 2, 0] }));
  const [right] = usePlane<THREE.Mesh>(() => ({ position: [8, 5, 0], rotation: [0, -Math.PI / 2, 0] }));
  return <><mesh ref={back} visible={false} /><mesh ref={front} visible={false} /><mesh ref={left} visible={false} /><mesh ref={right} visible={false} /></>;
}

function PhysicsCube({ position, color, size, velocity }: {
  position: [number, number, number];
  color: string;
  size: number;
  velocity: [number, number, number];
}) {
  const [ref] = useBox<THREE.Mesh>(() => ({
    mass: size * 2,
    position,
    args: [size, size, size],
    velocity,
    angularVelocity: [
      (Math.random() - 0.5) * 10,
      (Math.random() - 0.5) * 10,
      (Math.random() - 0.5) * 10,
    ],
  }));

  return (
    <mesh ref={ref} castShadow>
      <boxGeometry args={[size, size, size]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.3}
        roughness={0.3}
        metalness={0.6}
      />
    </mesh>
  );
}

function PiezoOrb({ piezo }: { piezo: PiezoState }) {
  const meshRef = useRef<THREE.Mesh>(null!);
  const matRef = useRef<THREE.MeshStandardMaterial>(null!);

  useFrame(() => {
    if (!meshRef.current || !matRef.current) return;
    // Scale orb by RMS energy (amplified for visibility)
    const energy = Math.max(0, (piezo.rms - piezo.baseline) * 50);
    const scale = 0.5 + energy * 2;
    meshRef.current.scale.lerp(new THREE.Vector3(scale, scale, scale), 0.15);
    // Color shifts with ZCR
    const hue = 0.12 + piezo.zcr * 0.5;
    matRef.current.emissive.setHSL(hue, 0.8, 0.3 + energy * 0.3);
    matRef.current.color.setHSL(hue, 0.6, 0.5);
    // Gentle float
    meshRef.current.position.y = 3 + Math.sin(Date.now() * 0.001) * 0.3;
    meshRef.current.rotation.y += 0.005;
  });

  return (
    <mesh ref={meshRef} position={[0, 3, 0]}>
      <icosahedronGeometry args={[1, 3]} />
      <meshStandardMaterial
        ref={matRef}
        color="#FFD700"
        emissive="#FFD700"
        emissiveIntensity={0.4}
        roughness={0.2}
        metalness={0.8}
        wireframe
      />
    </mesh>
  );
}

export function Scene() {
  const [cubes, setCubes] = useState<FallingCube[]>([]);
  const [piezo, setPiezo] = useState<PiezoState>({ rms: 0, baseline: 0, peak: 0, zcr: 0 });
  const lastTapRef = useRef(0);

  const handleTap = useCallback((tap: { user: string; timestamp: number }) => {
    // Dedup within 500ms
    if (tap.timestamp - lastTapRef.current < 500) return;
    lastTapRef.current = tap.timestamp;

    const count = 3 + Math.floor(Math.random() * 5);
    const newCubes: FallingCube[] = [];
    for (let i = 0; i < count; i++) {
      newCubes.push({
        id: cubeId++,
        position: [
          (Math.random() - 0.5) * 6,
          8 + Math.random() * 4,
          (Math.random() - 0.5) * 6,
        ],
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
        size: 0.4 + Math.random() * 0.8,
        velocity: [
          (Math.random() - 0.5) * 4,
          -2 - Math.random() * 3,
          (Math.random() - 0.5) * 4,
        ],
      });
    }

    setCubes((prev) => {
      const next = [...prev, ...newCubes];
      // Cap at 100 cubes
      return next.length > 100 ? next.slice(next.length - 100) : next;
    });
  }, []);

  const handlePiezo = useCallback((state: PiezoState) => {
    setPiezo(state);
  }, []);

  usePiezo(handleTap, handlePiezo);

  return (
    <>
      <Floor />
      <Walls />
      <PiezoOrb piezo={piezo} />
      {cubes.map((c) => (
        <PhysicsCube
          key={c.id}
          position={c.position}
          color={c.color}
          size={c.size}
          velocity={c.velocity}
        />
      ))}
    </>
  );
}
