import { Canvas } from "@react-three/fiber";
import { Physics } from "@react-three/cannon";
import { OrbitControls, Environment } from "@react-three/drei";
import { Scene } from "./Scene";

export default function App() {
  return (
    <div style={{ width: "100vw", height: "100vh", background: "#0a0a0f" }}>
      <Canvas camera={{ position: [0, 8, 14], fov: 50 }} shadows>
        <ambientLight intensity={0.3} />
        <directionalLight position={[5, 10, 5]} intensity={1} castShadow />
        <Physics gravity={[0, -9.81, 0]}>
          <Scene />
        </Physics>
        <OrbitControls />
        <Environment preset="night" />
      </Canvas>
    </div>
  );
}
