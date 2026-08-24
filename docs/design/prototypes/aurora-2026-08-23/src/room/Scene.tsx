/* The room and the object.
 *
 * Four bodies of nodes hanging in a lit room, each turning very slowly about
 * its own tilted axis — code largest and nearest, knowledge smallest and
 * furthest. A relation inside a plane is a chord through its body; a relation
 * across planes is an arc that leaves one body and lands on another. At rest
 * only the spine is drawn, as fine threads, plus the live attempt's path with
 * one light travelling it. That light is the room's heartbeat and the only
 * motion loud enough to notice.
 *
 * Everything that gives the forms weight is baked rather than post-processed:
 * a painted contact shadow under every node, a painted shadow under every
 * body, a lit back wall carrying its own falloff. An ambient-occlusion pass is
 * exactly the kind of thing that quietly does not run under software GL, and a
 * contact shadow missing from the picture is the difference between a placed
 * object and a grey turnaround render. */

import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import {
  allEdges, backbone, LIVE_PATH, measuredCost, neighbourhood,
  type Fixture, type GNode, type Lens, type ViewMode,
} from '../data';
import { BODIES, buildLayouts, hitRadius, ORDERED_SCALE, PLANE_ORDER } from './layout';
import { ACCENT, ACCENT_DIM, discTexture, ellipseTexture, FLOOR, SELECT, TINT, wallTexture } from './materials';
import { bus, touch } from './bus';

export type CamView = 'room' | 'along' | 'flat';

const VIEWS: Record<CamView, { az: number; el: number; dist: number }> = {
  room: { az: 0.135, el: 0.055, dist: 16.4 },
  along: { az: 0.62, el: 0.115, dist: 15.8 },
  flat: { az: 0.0, el: 0.0, dist: 15.2 },
};

/** the object stands in the corridor the glass panels leave open */
const GROUP = new THREE.Vector3(1.46, -0.16, 0);
const FLOOR_Y = -2.62;
const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

export interface SceneProps {
  fx: Fixture;
  view: ViewMode;
  camView: CamView;
  resetReq: number;
  selected: string | null;
  hovered: string | null;
  lit: string[];
  depth: 1 | 2 | 0;
  lens: Lens;
  motion: boolean;
  /** the inspector column takes width; the object steps back rather than hide */
  shift: number;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}

/* ------------------------------------------------------------------- form */

function form(kind: string): 'bead' | 'slab' | 'facet' | 'plate' {
  if (kind === 'method' || kind === 'function') return 'bead';
  if (kind === 'schema' || kind === 'enum') return 'facet';
  if (kind === 'doc' || kind === 'adr' || kind === 'concept' || kind === 'claim' || kind === 'issue') return 'plate';
  return 'slab';
}

function NodeMesh({ f, r, color, emissive, ei, hollow }:
  { f: string; r: number; color: string; emissive: string; ei: number; hollow: boolean }) {
  const mat = (
    <meshStandardMaterial
      color={color} roughness={hollow ? 0.85 : 0.34} metalness={hollow ? 0.02 : 0.22}
      emissive={emissive} emissiveIntensity={ei}
      transparent={hollow} opacity={hollow ? 0.30 : 1}
    />
  );
  if (f === 'bead') return <mesh castShadow><sphereGeometry args={[r, 22, 16]} />{mat}</mesh>;
  if (f === 'facet') return <mesh castShadow rotation={[0.30, 0.62, 0.42]}><octahedronGeometry args={[r * 1.46, 0]} />{mat}</mesh>;
  if (f === 'plate') return <mesh castShadow rotation={[Math.PI / 2 - 0.26, 0, 0.18]}><cylinderGeometry args={[r * 1.30, r * 1.30, r * 0.62, 24]} />{mat}</mesh>;
  return <mesh castShadow rotation={[-0.16, 0.20, 0]}><boxGeometry args={[r * 2.6, r * 1.62, r * 0.94]} />{mat}</mesh>;
}

/* ------------------------------------------------------------------ rooms */

function Shell({ shadows }: { shadows: React.RefObject<THREE.Group> }) {
  const wall = useMemo(wallTexture, []);
  const ell = useMemo(ellipseTexture, []);
  return (
    <group>
      {/* the lit back wall, painted and exempt from the fog, so the falloff it
          carries is the falloff you see — under software GL as well */}
      <mesh position={[GROUP.x - 0.5, 0.6, -9.4]}>
        <planeGeometry args={[44, 28]} />
        <meshBasicMaterial map={wall} fog={false} toneMapped={false} depthWrite={false} />
      </mesh>
      <mesh position={[GROUP.x, FLOOR_Y, -1.4]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[46, 30]} />
        <meshStandardMaterial color={FLOOR} roughness={0.96} metalness={0.02} />
      </mesh>
      {/* one painted shadow per body, so each of the four owns the ground */}
      <group ref={shadows}>
        {PLANE_ORDER.map((p, i) => {
          const b = BODIES[p];
          return (
            <sprite key={p} position={[GROUP.x + b.c.x, FLOOR_Y + 0.014, b.c.z + 0.4]}
              scale={[b.R * 4.6, b.R * 1.5, 1]}>
              <spriteMaterial map={ell} color="#000000" transparent opacity={0.66 - i * 0.11} depthWrite={false} />
            </sprite>
          );
        })}
      </group>
    </group>
  );
}

function Lights() {
  return (
    <>
      {/* soft omnidirectional base, split in temperature: cool sky, warm ground */}
      <hemisphereLight color="#8FA6C8" groundColor="#3A2E22" intensity={0.66} />
      <ambientLight intensity={0.15} color="#7C8BA6" />
      {/* key: warm, upper left front. It is the only light that casts. */}
      <directionalLight
        castShadow
        position={[GROUP.x - 6.0, 7.4, 8.0]}
        intensity={2.85}
        color="#FFE7C6"
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-9} shadow-camera-right={9}
        shadow-camera-top={8} shadow-camera-bottom={-8}
        shadow-camera-near={1} shadow-camera-far={32}
        shadow-bias={-0.0014} shadow-normalBias={0.024}
      />
      {/* fill: cool, low right — separates the far side of every form */}
      <directionalLight position={[GROUP.x + 7.5, -3.0, 4.5]} intensity={0.95} color="#7FA2D6" />
      {/* rim: cool, from behind — the silhouette light */}
      <directionalLight position={[GROUP.x + 1.0, 2.4, -9]} intensity={1.35} color="#BFD4F2" />
    </>
  );
}

/* ------------------------------------------------------------------ scene */

export default function Scene(props: SceneProps) {
  const { fx, view, camView, resetReq, selected, hovered, lit, depth, lens, motion, shift, onHover, onSelect } = props;
  const edges = useMemo(() => allEdges(fx), [fx]);
  const L = useMemo(() => buildLayouts(fx, edges), [fx, edges]);
  const spine = useMemo(() => new Set(backbone(edges)), [edges]);
  const cost = useMemo(() => measuredCost(fx), [fx]);
  const disc = useMemo(discTexture, []);
  const { camera, gl, size } = useThree();

  const morph = useRef(view === 'ordered' ? 1 : 0);
  const target = view === 'ordered' ? 1 : 0;
  const shiftRef = useRef(shift);

  /* Each body's turn, as a quaternion. Held in a ref and read by everything
     that needs a world position, so nodes, chords, arcs and the projected
     labels all agree on where a node is inside a single frame. */
  const spinAngle = useRef<Record<string, number>>({ code: 0, type: 0, data: 0, knowledge: 0 });
  const quats = useMemo(() => {
    const q: Record<string, THREE.Quaternion> = {};
    for (const p of PLANE_ORDER) q[p] = new THREE.Quaternion();
    return q;
  }, []);

  const pos = useMemo(() => new Map<string, THREE.Vector3>(), []);
  const tmp = useMemo(() => new THREE.Vector3(), []);
  const readPos = (id: string) => {
    const p = L.plane[id];
    const b = BODIES[p];
    tmp.copy(L.local[id]).applyQuaternion(quats[p]).add(b.c);
    const o = L.ordered[id];
    const t = easeInOut(morph.current);
    const v = pos.get(id) ?? new THREE.Vector3();
    v.set(tmp.x + (o.x - tmp.x) * t, tmp.y + (o.y - tmp.y) * t, tmp.z + (o.z - tmp.z) * t);
    pos.set(id, v);
    return v;
  };
  fx.graph.nodes.forEach(n => readPos(n.id));

  const focus = hovered ?? selected;
  const near = useMemo(
    () => (focus ? neighbourhood(edges, focus, depth) : null),
    [edges, focus, depth]
  );
  const livePairs = useMemo(() => {
    const s = new Set<string>();
    for (let i = 0; i < LIVE_PATH.length - 1; i++) s.add(LIVE_PATH[i] + '>' + LIVE_PATH[i + 1]);
    return s;
  }, []);

  /* ---------------------------------------------------------------- camera */
  const cam = useRef({ az: VIEWS[camView].az, el: VIEWS[camView].el, dist: VIEWS[camView].dist, gx: GROUP.x });
  const drag = useRef({ az: 0, el: 0, zoom: 0 });
  const lastReset = useRef(resetReq);

  useEffect(() => {
    if (resetReq !== lastReset.current) {
      lastReset.current = resetReq;
      drag.current = { az: 0, el: 0, zoom: 0 };
    }
  }, [resetReq]);

  useEffect(() => {
    const el = gl.domElement;
    let down = false, px = 0, py = 0;
    const onDown = (e: PointerEvent) => { down = true; px = e.clientX; py = e.clientY; touch(); };
    const onUp = () => { down = false; };
    const onMove = (e: PointerEvent) => {
      if (!down) return;
      drag.current.az = THREE.MathUtils.clamp(drag.current.az + (e.clientX - px) * 0.0042, -0.9, 0.9);
      drag.current.el = THREE.MathUtils.clamp(drag.current.el - (e.clientY - py) * 0.0032, -0.35, 0.45);
      px = e.clientX; py = e.clientY; touch();
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      drag.current.zoom = THREE.MathUtils.clamp(drag.current.zoom + e.deltaY * 0.004, -4.5, 6);
      touch();
    };
    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointermove', onMove);
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointermove', onMove);
      el.removeEventListener('wheel', onWheel);
    };
  }, [gl]);

  const place = (az: number, el: number, dist: number) => {
    camera.position.set(
      Math.sin(az) * Math.cos(el) * dist,
      Math.sin(el) * dist + 0.30,
      Math.cos(az) * Math.cos(el) * dist
    );
    camera.lookAt(0, 0.05, 0);
  };
  useEffect(() => {
    const v = VIEWS[camView];
    place(v.az, v.el, v.dist);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ------------------------------------------------------------- per frame */
  const groupRef = useRef<THREE.Group>(null!);
  const shadowsRef = useRef<THREE.Group>(null);
  const travelRef = useRef<THREE.Group>(null!);
  const tRef = useRef(0);
  const v3 = useMemo(() => new THREE.Vector3(), []);
  const shellRefs = useRef<Record<string, THREE.Mesh | null>>({});

  useFrame((_, dt) => {
    const d = Math.min(dt, 0.05);
    tRef.current += motion ? d : 0;

    if (morph.current !== target) {
      const k2 = 1 - Math.pow(0.0006, d);
      morph.current += (target - morph.current) * (d === 0 ? 1 : k2);
      if (Math.abs(target - morph.current) < 0.002) morph.current = target;
    }
    shiftRef.current += (shift - shiftRef.current) * (d === 0 ? 1 : 1 - Math.pow(0.0012, d));

    // each body turns about its own axis, slowly, and never all at one rate
    const spatial = 1 - easeInOut(morph.current);
    for (const p of PLANE_ORDER) {
      if (motion) spinAngle.current[p] += BODIES[p].spin * d * spatial;
      quats[p].setFromAxisAngle(BODIES[p].axis, spinAngle.current[p]);
      const m = shellRefs.current[p];
      if (m) {
        m.visible = spatial > 0.04;
        (m.material as THREE.Material & { opacity: number }).opacity = 0.055 * spatial;
      }
    }
    if (shadowsRef.current) {
      shadowsRef.current.visible = spatial > 0.02;
      shadowsRef.current.traverse(o => {
        const mm = (o as THREE.Sprite).material as (THREE.Material & { opacity: number; userData: { base?: number } }) | undefined;
        if (!mm || !('opacity' in mm)) return;
        if (mm.userData.base === undefined) mm.userData.base = mm.opacity;
        mm.opacity = mm.userData.base * spatial;
      });
    }

    // camera: a named position, the reader's drag, and a drift that waits for
    // stillness. The inspector column pushes the object back rather than over.
    const v = VIEWS[camView];
    const still = Date.now() - bus.touched > 2600;
    const t = tRef.current;
    const driftA = motion && still ? Math.sin(t / 21) * 0.018 : 0;
    const driftE = motion && still ? Math.sin(t / 29) * 0.008 : 0;
    const want = {
      az: v.az + drag.current.az + driftA,
      el: v.el + drag.current.el + driftE,
      dist: (v.dist + drag.current.zoom) * (1 + 0.58 * shiftRef.current),
      gx: GROUP.x * (1 + 0.58 * shiftRef.current) + 0.36 * shiftRef.current,
    };
    const k = d === 0 ? 1 : 1 - Math.pow(0.0009, d);
    cam.current.az += (want.az - cam.current.az) * k;
    cam.current.el += (want.el - cam.current.el) * k;
    cam.current.dist += (want.dist - cam.current.dist) * k;
    cam.current.gx += (want.gx - cam.current.gx) * k;
    place(cam.current.az, cam.current.el, cam.current.dist);
    if (groupRef.current) groupRef.current.position.x = cam.current.gx;

    // project every node, and every body's silhouette, into CSS pixels
    const hw = size.width / 2, hh = size.height / 2;
    const gx = cam.current.gx;
    for (const n of fx.graph.nodes) {
      const p = readPos(n.id);
      v3.set(p.x + gx, p.y + GROUP.y, p.z).project(camera);
      const zdepth = v3.z;
      const x = (v3.x + 1) * hw, y = (1 - v3.y) * hh;
      const rw = L.radius[n.id] * (view === 'ordered' ? ORDERED_SCALE : 1);
      v3.set(p.x + gx, p.y + GROUP.y + rw, p.z).project(camera);
      const ry = Math.abs((1 - v3.y) * hh - y);
      v3.set(p.x + gx, p.y + GROUP.y + hitRadius(rw), p.z).project(camera);
      const hy = Math.abs((1 - v3.y) * hh - y);
      bus.pts.set(n.id, { id: n.id, x, y, r: ry, z: zdepth, hit: hy * 2 });
    }
    bus.spheres.clear();
    if (spatial > 0.5) {
      for (const p of PLANE_ORDER) {
        const b = BODIES[p];
        v3.set(b.c.x + gx, b.c.y + GROUP.y, b.c.z).project(camera);
        const x = (v3.x + 1) * hw, y = (1 - v3.y) * hh;
        v3.set(b.c.x + gx, b.c.y + GROUP.y + b.R * 1.18, b.c.z).project(camera);
        const r = Math.abs((1 - v3.y) * hh - y);
        bus.spheres.set(p, { x, y, r });
      }
    }
    bus.frame++;

    // the light travelling the live attempt's path
    if (travelRef.current) {
      const period = 9.0;
      const u = motion ? (t % period) / period : 0.06;
      const eased = u < 0.84 ? easeInOut(u / 0.84) : 1;
      const segs = LIVE_PATH.length - 1;
      const f = Math.min(0.9999, eased) * segs;
      const i = Math.floor(f), fr = f - i;
      const a = readPos(LIVE_PATH[i]), b2 = readPos(LIVE_PATH[Math.min(segs, i + 1)]);
      const cross = L.plane[LIVE_PATH[i]] !== L.plane[LIVE_PATH[Math.min(segs, i + 1)]];
      const lift = cross && spatial > 0.5 ? Math.sin(fr * Math.PI) * a.distanceTo(b2) * 0.22 : 0;
      travelRef.current.position.set(
        a.x + (b2.x - a.x) * fr,
        a.y + (b2.y - a.y) * fr + lift,
        a.z + (b2.z - a.z) * fr + lift * 0.4
      );
      const fade = u > 0.84 ? Math.max(0, 1 - (u - 0.84) / 0.16) : Math.min(1, u / 0.04);
      travelRef.current.scale.setScalar(0.55 + 0.45 * fade);
      travelRef.current.visible = motion ? fade > 0.02 : true;
    }
  });

  /* ------------------------------------------------------------------ draw */
  const litSet = useMemo(() => new Set(lit), [lit]);

  /** a relation across bodies leaves one and lands on the other: an arc */
  const arcPoints = (a: THREE.Vector3, b2: THREE.Vector3, cross: boolean): [number, number, number][] => {
    if (!cross) return [[a.x, a.y, a.z], [b2.x, b2.y, b2.z]];
    const out: [number, number, number][] = [];
    const lift = a.distanceTo(b2) * 0.22;
    for (let i = 0; i <= 18; i++) {
      const t = i / 18, s = Math.sin(t * Math.PI);
      out.push([
        a.x + (b2.x - a.x) * t,
        a.y + (b2.y - a.y) * t + s * lift,
        a.z + (b2.z - a.z) * t + s * lift * 0.4,
      ]);
    }
    return out;
  };

  return (
    <>
      <color attach="background" args={['#0A0908']} />
      {/* aerial perspective: the far body loses contrast with distance. It is
          the depth cue a depth-of-field pass would have given, and it renders
          everywhere — including under software GL. */}
      <fog attach="fog" args={['#141109', 18.5, 38]} />
      <Lights />
      <Shell shadows={shadowsRef} />

      <group ref={groupRef} position={[GROUP.x, GROUP.y, 0]}>
        {/* the shell each body of nodes sits on: barely there, but it is what
            makes four clusters read as four bodies with volume */}
        {PLANE_ORDER.map(p => {
          const b = BODIES[p];
          return (
            <mesh key={p} ref={el => (shellRefs.current[p] = el)} position={[b.c.x, b.c.y, b.c.z]}>
              <sphereGeometry args={[b.R * 1.03, 32, 24]} />
              <meshBasicMaterial color={TINT[p]} transparent opacity={0.055}
                depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.BackSide} />
            </mesh>
          );
        })}

        {/* relations */}
        {edges.map((e, i) => {
          const inSpine = spine.has(i);
          const isLive = livePairs.has(e.s + '>' + e.t);
          const touching = near ? (near.has(e.s) && near.has(e.t)) : false;
          const proposed = lens === 'evidence' && !e.verified;
          if (!inSpine && !isLive && !touching && !proposed) return null;
          const a = readPos(e.s), b2 = readPos(e.t);
          const col = proposed && !touching ? ACCENT : isLive ? ACCENT_DIM : touching ? (e.verified ? '#D6CBB8' : ACCENT) : '#8A8073';
          const op = proposed && !touching ? 0.48 : isLive ? 0.62 : touching ? (e.verified ? 0.82 : 0.66) : 0.46;
          return (
            <Line
              key={e.s + '>' + e.t + i}
              points={arcPoints(a, b2, e.cross && morph.current < 0.5)}
              color={col} transparent opacity={op}
              lineWidth={touching || isLive ? 1.4 : 1}
              dashed={!e.verified} dashSize={0.10} gapSize={0.08}
              depthWrite={false}
            />
          );
        })}

        {/* nodes */}
        {fx.graph.nodes.map((n: GNode) => {
          const p = readPos(n.id);
          const r = L.radius[n.id] * (view === 'ordered' ? ORDERED_SCALE : 1);
          const isLit = litSet.has(n.id);
          const isSel = selected === n.id;
          const isHov = hovered === n.id;
          const dim = near ? !near.has(n.id) : false;
          const hollow = lens === 'cost' && !cost[n.id];
          const base = TINT[n.plane];
          const color = isSel ? SELECT : base;
          const emissive = isSel ? SELECT : isLit ? ACCENT : base;
          const ei = isSel ? 0.48 : isLit ? 0.95 : isHov ? 0.24 : 0.0;
          return (
            <group key={n.id} position={[p.x, p.y, p.z]}>
              <sprite position={[r * 0.75, -r * 0.72, -r * 1.15]} scale={[r * 4.4, r * 4.4, 1]}>
                <spriteMaterial map={disc} color="#050403" transparent opacity={0.68} depthWrite={false} />
              </sprite>
              <group scale={dim ? 0.9 : 1}>
                <NodeMesh f={form(n.kind)} r={r} color={color} emissive={emissive} ei={ei} hollow={hollow} />
              </group>
              {(isLit || isSel) && (
                <sprite scale={[r * 12, r * 12, 1]}>
                  <spriteMaterial map={disc} color={isSel ? SELECT : ACCENT} transparent
                    opacity={isSel ? 0.32 : 0.44} depthWrite={false} blending={THREE.AdditiveBlending} />
                </sprite>
              )}
              <mesh
                visible={false}
                onPointerOver={(e) => { e.stopPropagation(); touch(); onHover(n.id); }}
                onPointerOut={() => onHover(null)}
                onClick={(e) => { e.stopPropagation(); touch(); onSelect(n.id); }}
              >
                <sphereGeometry args={[hitRadius(r), 8, 6]} />
              </mesh>
            </group>
          );
        })}

        {/* the light travelling the live attempt's path */}
        <group ref={travelRef}>
          <mesh>
            <sphereGeometry args={[0.042, 14, 10]} />
            <meshStandardMaterial color={ACCENT} emissive={ACCENT} emissiveIntensity={2.6} toneMapped={false} />
          </mesh>
          <sprite scale={[0.62, 0.62, 1]}>
            <spriteMaterial map={disc} color={ACCENT} transparent opacity={0.58} depthWrite={false} blending={THREE.AdditiveBlending} />
          </sprite>
        </group>
      </group>
    </>
  );
}

export { GROUP };
