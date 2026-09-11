import { useEffect, useRef, useState } from 'react';
import { useThemes } from '../theme/ThemeProvider';
import { useReducedMotionPref } from '../motion';
import './SpatialScene.css';

const VERTEX = `attribute vec2 position; void main(){gl_Position=vec4(position,0.,1.);}`;
// Signed-distance geometry: two intersecting glass orbits and a suspended core.
// This is an ambient sculpture, never a representation of project evidence.
const FRAGMENT = `
precision highp float;
uniform vec2 resolution;
uniform vec2 pointer;
uniform float time;
uniform float light;
uniform vec3 accent;
mat2 rotate(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}
float torus(vec3 p, vec2 r){return length(vec2(length(p.xy)-r.x,p.z))-r.y;}
float shape(vec3 p){
  p.xz=rotate(.28+sin(time*.13)*.18+pointer.x*.12)*p.xz;
  p.yz=rotate(-.26+pointer.y*.1)*p.yz;
  vec3 a=p; a.yz=rotate(.48)*a.yz;
  vec3 b=p; b.xz=rotate(1.08)*b.xz; b.xy=rotate(.62)*b.xy;
  float rings=min(torus(a,vec2(1.12,.205)),torus(b,vec2(1.12,.125)));
  return min(rings,length(p)-.49);
}
vec3 normalAt(vec3 p){vec2 e=vec2(.002,0.);return normalize(vec3(
  shape(p+e.xyy)-shape(p-e.xyy),shape(p+e.yxy)-shape(p-e.yxy),shape(p+e.yyx)-shape(p-e.yyx)));}
vec3 environment(vec3 d){
  vec3 c=mix(vec3(.035,.045,.10),vec3(.34,.43,.65),smoothstep(-.7,.8,d.y));
  c+=vec3(.78,.86,1.)*pow(max(0.,dot(d,normalize(vec3(-.5,.8,1.)))),18.)*2.;
  c+=accent*pow(max(0.,dot(d,normalize(vec3(.9,-.3,.3)))),5.)*1.8;
  c+=vec3(.62,.35,.9)*pow(max(0.,dot(d,normalize(vec3(-.8,-.4,.2)))),8.);
  c+=vec3(.9,.94,1.)*pow(max(0.,1.-abs(d.y-.52)),65.)*.75;
  return c;
}
void main(){
  vec2 uv=(gl_FragCoord.xy*2.-resolution)/resolution.y;
  vec3 origin=vec3(0.,0.,4.6);
  vec3 ray=normalize(vec3(uv,-3.1));
  float travel=0.; float distance=0.;
  for(int i=0;i<72;i++){distance=shape(origin+ray*travel);if(distance<.0015||travel>7.)break;travel+=distance*.82;}
  if(travel>7.){gl_FragColor=vec4(0.);return;}
  vec3 p=origin+ray*travel; vec3 n=normalAt(p);
  float fresnel=pow(1.-max(0.,dot(n,-ray)),2.4);
  vec3 reflected=environment(reflect(ray,n));
  vec3 refracted=environment(refract(ray,n,.69));
  vec3 color=mix(refracted*.48,reflected,.35+fresnel*.65);
  color+=accent*.09+vec3(.12,.14,.21);
  color+=pow(max(0.,dot(reflect(ray,n),normalize(vec3(-.4,.8,1.)))),90.)*vec3(1.4);
  color=mix(color,color*.78+vec3(.18),light);
  color=pow(color,vec3(.85));
  gl_FragColor=vec4(color,.86+fresnel*.14);
}`;

function rgb(value: string): [number, number, number] {
  // Canvas normalizes every CSS color accepted by the theme editor, including
  // named colors, rgb(), hsl() and wide-gamut values, without DOM measurements.
  const context = document.createElement('canvas').getContext('2d');
  if (!context) return [.5, .65, 1];
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const data = context.getImageData(0, 0, 1, 1).data;
  return [data[0] / 255, data[1] / 255, data[2] / 255];
}

/** One bounded renderer; no network, project state or new dependencies. */
export function SpatialScene({ compact = false }: { compact?: boolean }) {
  const { theme } = useThemes();
  const reduced = useReducedMotionPref();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [generation, setGeneration] = useState(0);
  const [available, setAvailable] = useState(false);
  const enabled = theme.scene?.enabled ?? false;
  const intensity = Math.max(0, Math.min(1, theme.scene?.intensity ?? .7));
  const speed = Math.max(0, Math.min(1, theme.scene?.speed ?? .5));

  useEffect(() => {
    const element = canvas.current;
    if (!element || !enabled || intensity === 0) return;
    const gl = element.getContext('webgl', { alpha: true, antialias: false, depth: false, powerPreference: 'low-power' });
    if (!gl) return;
    let frame = 0;
    let previous = 0;
    let elapsed = 0;
    let intersecting = true;
    let lost = false;
    const cursor = [0, 0];
    const shaders: WebGLShader[] = [];
    const program = gl.createProgram();
    const buffer = gl.createBuffer();
    if (!program || !buffer) { gl.deleteProgram(program); gl.deleteBuffer(buffer); return; }
    for (const [type, source] of [[gl.VERTEX_SHADER, VERTEX], [gl.FRAGMENT_SHADER, FRAGMENT]] as const) {
      const shader = gl.createShader(type);
      if (!shader) continue;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      gl.attachShader(program, shader);
      shaders.push(shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      shaders.forEach((s) => gl.deleteShader(s));
      gl.deleteProgram(program); gl.deleteBuffer(buffer);
      return;
    }
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    const attribute = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(attribute);
    gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);
    const uniforms = Object.fromEntries(['resolution','pointer','time','light','accent'].map((key) => [key, gl.getUniformLocation(program,key)]));
    gl.uniform3f(uniforms.accent, ...rgb(theme.colors.accent));
    gl.uniform1f(uniforms.light, theme.base === 'light' ? 1 : 0);
    const draw = (stamp: number) => {
      frame = 0;
      if (document.hidden || !intersecting || lost) return;
      if (stamp - previous >= 1000 / 24 || previous === 0) {
        elapsed += previous ? Math.min(stamp - previous, 100) * .001 * speed : 0;
        previous = stamp;
        gl.viewport(0, 0, element.width, element.height);
        gl.uniform2f(uniforms.resolution, element.width, element.height);
        gl.uniform2f(uniforms.pointer, reduced ? 0 : cursor[0], reduced ? 0 : cursor[1]);
        gl.uniform1f(uniforms.time, reduced ? 0 : elapsed);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
        setAvailable(true);
      }
      if (!reduced && speed > 0) frame = requestAnimationFrame(draw);
    };
    const schedule = () => { if (!frame) { previous = 0; frame = requestAnimationFrame(draw); } };
    const resize = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      // Ambient graphics never need a full-resolution desktop framebuffer.
      const ratio = Math.min(devicePixelRatio || 1, 1.25, 800 / Math.max(width, height, 1));
      element.width = Math.max(1, Math.round(width * ratio));
      element.height = Math.max(1, Math.round(height * ratio));
      schedule();
    });
    resize.observe(element);
    const visibility = new IntersectionObserver(([entry]) => { intersecting = entry.isIntersecting; if (intersecting) schedule(); });
    visibility.observe(element);
    const move = (event: PointerEvent) => { cursor[0] = event.clientX / innerWidth - .5; cursor[1] = event.clientY / innerHeight - .5; };
    const onLost = (event: Event) => { event.preventDefault(); lost = true; cancelAnimationFrame(frame); frame = 0; setAvailable(false); };
    const restore = () => setGeneration((value) => value + 1);
    window.addEventListener('pointermove', move, { passive: true });
    document.addEventListener('visibilitychange', schedule);
    element.addEventListener('webglcontextlost', onLost);
    element.addEventListener('webglcontextrestored', restore);
    schedule();
    return () => {
      cancelAnimationFrame(frame); resize.disconnect(); visibility.disconnect();
      window.removeEventListener('pointermove', move);
      document.removeEventListener('visibilitychange', schedule);
      element.removeEventListener('webglcontextlost', onLost);
      element.removeEventListener('webglcontextrestored', restore);
      shaders.forEach((shader) => gl.deleteShader(shader));
      gl.deleteBuffer(buffer); gl.deleteProgram(program);
    };
  }, [enabled, intensity, speed, reduced, theme.colors.accent, theme.base, generation]);

  if (!enabled || intensity === 0) return null;
  return (
    <div className={`spatial-scene${compact ? ' compact' : ''}`} aria-hidden="true" style={{ opacity: intensity }} data-renderer={available ? 'webgl' : 'ambient'}>
      <canvas ref={canvas} />
    </div>
  );
}
