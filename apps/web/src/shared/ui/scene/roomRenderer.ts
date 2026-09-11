import {
  AgXToneMapping, Color, DataTexture, DirectionalLight, EquirectangularReflectionMapping,
  FogExp2, HemisphereLight, LinearFilter, LinearSRGBColorSpace, Material,
  Mesh, MeshStandardMaterial, Object3D, OrthographicCamera, PCFShadowMap, PerspectiveCamera,
  PMREMGenerator, Quaternion, RectAreaLight, Scene, Texture, Vector3, WebGLRenderer
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { RectAreaLightUniformsLib } from 'three/examples/jsm/lights/RectAreaLightUniformsLib.js';
import { isSceneEnvironmentId } from './environments';
import type { SceneEnvironmentId } from '../theme/types';

type Triple = [number, number, number];
interface RoomAsset {
  camera: { position: Triple; quaternion: [number, number, number, number]; target: Triple;
    type: string; near: number; far: number; fovDegrees?: number; aspect: number; orthoScale?: number };
  environment: { color: Triple; strength: number; gradient?: Array<{ position: number; color: Triple }> };
  fog: { color: Triple; density: number } | null;
  lights: Array<{ type: string; color: Triple; power: number; position: Triple;
    target: Triple; quaternion: [number, number, number, number]; width?: number; height?: number }>;
}
export interface RoomControls { speed: number; exposure: number; reduced: boolean }
export interface RoomRenderer { update: (controls: RoomControls) => void; dispose: () => void }

/** The Blender world ramp is indexed by altitude, not by viewport position. */
function skyTexture(environment: RoomAsset['environment']): DataTexture | undefined {
  const stops = environment.gradient?.filter((stop) =>
    Number.isFinite(stop.position) && stop.color.length === 3 && stop.color.every(Number.isFinite)
  ).sort((a, b) => a.position - b.position);
  if (!stops || stops.length < 2) return;
  const width = 512, height = 256;
  const pixels = new Uint8Array(width * height * 4);
  for (let row = 0; row < height; row++) {
    // DataTexture has flipY=false. Equirectangular v=0 is the south pole and
    // v=1 the north pole; below the horizon the authored ramp keeps its first stop.
    const altitude = Math.max(0, Math.sin(((row + .5) / height - .5) * Math.PI));
    let upper = stops.findIndex((stop) => stop.position >= altitude);
    if (upper < 0) upper = stops.length - 1;
    const low = stops[Math.max(0, upper - 1)], high = stops[upper];
    const span = high.position - low.position;
    const t = span > 0 ? Math.max(0, Math.min(1, (altitude - low.position) / span)) : 0;
    const channels = low.color.map((value, i) =>
      Math.round(Math.max(0, Math.min(1, value + (high.color[i] - value) * t)) * 255)
    );
    for (let column = 0; column < width; column++) {
      const offset = (row * width + column) * 4;
      pixels[offset] = channels[0]; pixels[offset + 1] = channels[1];
      pixels[offset + 2] = channels[2]; pixels[offset + 3] = 255;
    }
  }
  const texture = new DataTexture(pixels, width, height);
  texture.name = 'Local Blender sky gradient';
  texture.mapping = EquirectangularReflectionMapping;
  texture.colorSpace = LinearSRGBColorSpace;
  texture.minFilter = texture.magFilter = LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function disposeTree(root: Object3D) {
  const materials = new Set<Material>(), textures = new Set<Texture>();
  root.traverse((object) => {
    if (object instanceof DirectionalLight) object.shadow.dispose();
    if (!(object instanceof Mesh)) return;
    object.geometry.dispose();
    for (const mat of Array.isArray(object.material) ? object.material : [object.material]) materials.add(mat);
  });
  for (const mat of materials) {
    for (const value of Object.values(mat)) if (value instanceof Texture) textures.add(value);
    mat.dispose();
  }
  for (const texture of textures) texture.dispose();
}

/** Local GLB geometry in the existing room layer; no project or runtime state. */
export function createRoomRenderer(
  canvas: HTMLCanvasElement, id: SceneEnvironmentId, initial: RoomControls,
  onState: (state: 'webgl' | 'fallback') => void
): RoomRenderer {
  let renderer: WebGLRenderer | undefined;
  let scene: Scene | undefined;
  let camera: PerspectiveCamera | OrthographicCamera | undefined;
  let environment: ReturnType<PMREMGenerator['fromScene']> | undefined;
  let sky: DataTexture | undefined;
  let controls = initial, disposed = false, failed = false, ready = false;
  let frame = 0, drawn = 0, lastFrame = 0, visible = true;
  let currentX = 0, currentY = 0, targetX = 0, targetY = 0;
  const position = new Vector3(), target = new Vector3(), right = new Vector3(), up = new Vector3(0, 1, 0);
  const abort = new AbortController();
  const timeout = window.setTimeout(() => { abort.abort(); fail(); }, 20_000);
  const observer = new ResizeObserver(() => resize());
  const intersection = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible) request(); else stop();
  });

  function stop() { cancelAnimationFrame(frame); frame = 0; }
  function fail() {
    if (disposed || failed) return;
    failed = true; stop(); clearTimeout(timeout); abort.abort();
    onState('fallback');
    release();
  }
  function request() {
    if (disposed || failed || !ready || !visible || document.hidden || frame) return;
    frame = requestAnimationFrame(paint);
  }
  function paint(now: number) {
    frame = 0;
    if (!renderer || !scene || !camera || disposed || failed || document.hidden || !visible) return;
    // At most 30fps while responding to input. No continuous idle animation.
    if (now - lastFrame < 32) { frame = requestAnimationFrame(paint); return; }
    lastFrame = now;
    const wantedX = controls.reduced ? 0 : targetX * controls.speed;
    const wantedY = controls.reduced ? 0 : targetY * controls.speed;
    currentX += (wantedX - currentX) * .22;
    currentY += (wantedY - currentY) * .22;
    if (controls.reduced) currentX = currentY = 0;
    const distance = position.distanceTo(target);
    camera.position.copy(position).addScaledVector(right, currentX * distance * .025)
      .addScaledVector(up, currentY * distance * .015);
    camera.lookAt(target);
    renderer.toneMappingExposure = controls.exposure;
    try { renderer.render(scene, camera); }
    catch { fail(); return; }
    canvas.dataset.frames = String(++drawn);
    if (drawn === 1) { clearTimeout(timeout); onState('webgl'); }
    if (!controls.reduced && (Math.abs(wantedX - currentX) > .001 || Math.abs(wantedY - currentY) > .001)) request();
  }
  function resize() {
    if (!renderer || !camera) return;
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    const scale = Math.min(window.devicePixelRatio || 1, 1.25, Math.sqrt(1_100_000 / (width * height)));
    renderer.setSize(Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale)), false);
    const aspect = width / height;
    if (camera instanceof PerspectiveCamera) camera.aspect = aspect;
    else { const half = (camera.top - camera.bottom) / 2; camera.left = -half * aspect; camera.right = half * aspect; }
    camera.updateProjectionMatrix(); request();
  }
  function move(event: PointerEvent) {
    if (controls.reduced || controls.speed === 0) return;
    targetX = (event.clientX / innerWidth - .5) * 2;
    targetY = (.5 - event.clientY / innerHeight) * 2;
    request();
  }
  function visibility() { if (document.hidden) stop(); else request(); }
  function lost(event: Event) { event.preventDefault(); fail(); }
  function release() {
    observer.disconnect(); intersection.disconnect();
    window.removeEventListener('pointermove', move);
    document.removeEventListener('visibilitychange', visibility);
    canvas.removeEventListener('webglcontextlost', lost);
    if (scene) { disposeTree(scene); scene = undefined; }
    sky?.dispose(); sky = undefined;
    environment?.dispose(); environment = undefined;
    if (renderer) { renderer.dispose(); renderer.forceContextLoss(); renderer = undefined; }
  }

  async function load() {
    if (!isSceneEnvironmentId(id)) { fail(); return; }
    try {
      const base = new URL(`${import.meta.env.BASE_URL || '/'}scenes/`, location.origin);
      const responses = await Promise.all([
        fetch(new URL('manifest.json', base), { signal: abort.signal }),
        fetch(new URL(`${id}.glb`, base), { signal: abort.signal })
      ]);
      if (responses.some((r) => !r.ok)) throw new Error('Missing local room');
      const manifest = await responses[0].json() as { version: number; scenes: Record<string, RoomAsset> };
      const data = manifest.scenes[id];
      if (manifest.version !== 1 || !data || !data.camera.position.every(Number.isFinite)) throw new Error('Invalid room manifest');
      const buffer = await responses[1].arrayBuffer();
      if (disposed || abort.signal.aborted) return;
      const loader = new GLTFLoader();
      // Exported assets are self-contained. Refuse an unexpected external URI.
      loader.manager.setURLModifier((url) => {
        if (url.startsWith('data:') || url.startsWith('blob:')) return url;
        const resolved = new URL(url, base);
        if (resolved.origin !== base.origin || !resolved.pathname.startsWith(base.pathname)) throw new Error('External room resource refused');
        return resolved.href;
      });
      const gltf = await loader.parseAsync(buffer, base.href);
      if (disposed || abort.signal.aborted) { disposeTree(gltf.scene); return; }
      scene = new Scene();
      scene.add(gltf.scene);
      // Light rigs are recreated from the same export manifest (AREA isn't glTF punctual lighting).
      const importedLights: Object3D[] = [];
      gltf.scene.traverse((o) => { if ('isLight' in o && o.isLight) importedLights.push(o); });
      importedLights.forEach((o) => o.removeFromParent());
      renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'low-power' });
      renderer.setPixelRatio(1); renderer.toneMapping = AgXToneMapping;
      renderer.transmissionResolutionScale = .5;
      const forest = id === 'techno-forest';
      renderer.shadowMap.enabled = forest;
      renderer.shadowMap.type = PCFShadowMap;
      // Forest geometry and its key are static: camera parallax reuses one map.
      renderer.shadowMap.autoUpdate = false;
      renderer.shadowMap.needsUpdate = forest;
      sky = skyTexture(data.environment);
      const roomColor = forest ? new Color(.014, .043, .052) : new Color().fromArray(data.environment.color);
      scene.background = sky ?? roomColor;
      if (data.fog) scene.fog = new FogExp2(
        forest ? new Color(.018, .054, .065) : new Color().fromArray(data.fog.color),
        forest ? .026 : Math.max(.001, Math.min(.06, data.fog.density))
      );
      const studio = new RoomEnvironment();
      const pmrem = new PMREMGenerator(renderer);
      environment = pmrem.fromScene(studio, .04);
      scene.environment = environment.texture;
      scene.environmentIntensity = id === 'porcelain' ? .9 : id === 'graphite' ? .45 : forest ? .08 : .22;
      studio.dispose(); pmrem.dispose();
      scene.add(new HemisphereLight(roomColor, forest ? new Color(.007, .016, .015) : new Color(.08, .09, .1), forest ? .24 : .55));
      RectAreaLightUniformsLib.init();
      for (const rig of data.lights) {
        if (rig.type !== 'sun' && rig.type !== 'area') continue;
        const light = rig.type === 'sun'
          ? new DirectionalLight(new Color().fromArray(rig.color), rig.power)
          : new RectAreaLight(new Color().fromArray(rig.color), rig.power * (forest ? .32 : 1) / Math.max(1, (rig.width || 5) * (rig.height || rig.width || 5)) / Math.PI,
            rig.width || 5, rig.height || rig.width || 5);
        light.position.fromArray(rig.position);
        if (light instanceof DirectionalLight) { light.target.position.fromArray(rig.target); scene.add(light.target); }
        else light.quaternion.fromArray(rig.quaternion);
        scene.add(light);
      }
      if (forest) {
        const key = new DirectionalLight(new Color(.48, .78, .84), 2.3);
        key.name = 'Forest / cached moon shadow';
        key.position.set(-7, 17, 4);
        key.target.position.set(0, 0, -13);
        key.castShadow = true;
        key.shadow.mapSize.set(1024, 1024);
        key.shadow.camera.left = key.shadow.camera.bottom = -18;
        key.shadow.camera.right = key.shadow.camera.top = 18;
        key.shadow.camera.near = 1;
        key.shadow.camera.far = 65;
        key.shadow.bias = -.00025;
        key.shadow.normalBias = .035;
        scene.add(key, key.target);
      }
      scene.traverse((object) => {
        if (!(object instanceof Mesh)) return;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        const glass = materials.some((mat) => 'transmission' in mat && Number(mat.transmission) > 0);
        object.castShadow = object.receiveShadow = forest && !glass;
        for (const mat of materials) {
          if (mat instanceof MeshStandardMaterial) mat.envMapIntensity = id === 'graphite' ? .7 : forest ? .35 : 1;
        }
      });
      const c = data.camera;
      if (c.type === 'orthographic') {
        const half = (c.orthoScale || 12) / c.aspect / 2;
        camera = new OrthographicCamera(-half * c.aspect, half * c.aspect, half, -half, c.near, c.far);
      } else camera = new PerspectiveCamera(c.fovDegrees || 35, c.aspect, c.near, c.far);
      position.fromArray(c.position); target.fromArray(c.target);
      right.set(1, 0, 0).applyQuaternion(new Quaternion().fromArray(c.quaternion));
      camera.position.copy(position); camera.lookAt(target);
      canvas.addEventListener('webglcontextlost', lost);
      window.addEventListener('pointermove', move, { passive: true });
      document.addEventListener('visibilitychange', visibility);
      observer.observe(canvas); intersection.observe(canvas);
      clearTimeout(timeout);
      ready = true; resize();
    } catch (error) {
      canvas.dataset.error = error instanceof Error ? error.message.slice(0, 240) : 'Room load failed';
      fail();
    }
  }
  void load();
  return {
    update(next) { controls = next; request(); },
    dispose() { disposed = true; abort.abort(); clearTimeout(timeout); stop(); release(); }
  };
}
