/* Palette and painted textures.
 *
 * The four planes differ by VALUE and TEMPERATURE, never by four hues: code is
 * the brightest and warm, knowledge the darkest and cool, and the two in
 * between alternate so that adjacent sheets separate. Saturation stays under
 * 0.14 everywhere — the one saturated colour in the room is the emissive
 * accent, and it only ever means "this is what we are talking about" or
 * "this is running right now".
 *
 * The soft textures are painted into a canvas at startup rather than rendered
 * by a post-processing pass: an ambient-occlusion pass is exactly the kind of
 * thing that quietly does not run under software GL, and a contact shadow that
 * is missing from the picture is the difference between a placed object and a
 * grey turnaround render. */

import * as THREE from 'three';
import type { Plane } from '../data';

/** value + temperature, not four hues */
export const TINT: Record<Plane, string> = {
  code: '#E6DCCB',      // warm, brightest — nearest the eye
  type: '#B4BAC1',      // cool
  data: '#B3A899',      // warm, darker
  knowledge: '#949BA6', // cool, darkest — furthest away
};

/** the rails: the same tint, one step down, read as metal under the key light */
export const RAIL: Record<Plane, string> = {
  code: '#CCC1AD', type: '#AEB4BC', data: '#948C80', knowledge: '#787F87',
};

export const ROOM_BG = '#0A0908';   // canvas: warm near-black
export const BACKDROP = '#171410';  // the lit back wall, warm
export const FLOOR = '#0E0C0A';
export const ACCENT = '#FF9838';    // emissive only: under discussion / live
export const ACCENT_DIM = '#C4762C';
export const SELECT = '#F6F2EA';    // achromatic: selection, so it is not a second accent

let _disc: THREE.Texture | null = null;
/** A soft round falloff. Used for contact shadows and for the single allowed
 *  bloom stage, which is a sprite on emissive geometry — not a screen pass. */
export function discTexture(): THREE.Texture {
  if (_disc) return _disc;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, 'rgba(255,255,255,1)');
  r.addColorStop(0.35, 'rgba(255,255,255,0.42)');
  r.addColorStop(0.7, 'rgba(255,255,255,0.09)');
  r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r;
  g.fillRect(0, 0, 128, 128);
  _disc = new THREE.CanvasTexture(c);
  return _disc;
}

let _ellipse: THREE.Texture | null = null;
/** The per-sheet ground shadow: wide, soft, darkest under the rail. */
export function ellipseTexture(): THREE.Texture {
  if (_ellipse) return _ellipse;
  const c = document.createElement('canvas');
  c.width = 512; c.height = 128;
  const g = c.getContext('2d')!;
  g.translate(256, 64); g.scale(1, 0.25);
  const r = g.createRadialGradient(0, 0, 0, 0, 0, 256);
  r.addColorStop(0, 'rgba(255,255,255,0.95)');
  r.addColorStop(0.45, 'rgba(255,255,255,0.35)');
  r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r;
  g.fillRect(-256, -256, 512, 512);
  _ellipse = new THREE.CanvasTexture(c);
  return _ellipse;
}

let _sheet: THREE.Texture | null = null;
/** Light spilling up the glass from the lit rail beneath it. This is what
 *  makes a sheet read as a surface instead of an empty wire rectangle, and it
 *  is physically motivated: the rail is the brightest thing on the object. */
export function sheetTexture(): THREE.Texture {
  if (_sheet) return _sheet;
  const c = document.createElement('canvas');
  c.width = 8; c.height = 256;
  const g = c.getContext('2d')!;
  const grd = g.createLinearGradient(0, 256, 0, 0);
  grd.addColorStop(0, 'rgba(255,255,255,0.90)');
  grd.addColorStop(0.10, 'rgba(255,255,255,0.34)');
  grd.addColorStop(0.42, 'rgba(255,255,255,0.09)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 8, 256);
  _sheet = new THREE.CanvasTexture(c);
  return _sheet;
}

let _wall: THREE.Texture | null = null;
/** The back wall, painted with the light already on it: a warm pool behind the
 *  object falling to near-black at the frame edges. This is the thing that
 *  stops a dark 3D scene from reading as an infinite void. */
export function wallTexture(): THREE.Texture {
  if (_wall) return _wall;
  const W = 512, H = 320;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d')!;
  g.fillStyle = ROOM_BG;
  g.fillRect(0, 0, W, H);
  const r = g.createRadialGradient(W * 0.52, H * 0.42, 0, W * 0.52, H * 0.42, W * 0.66);
  r.addColorStop(0, '#241F17');
  r.addColorStop(0.34, '#191510');
  r.addColorStop(0.62, '#12100C');
  r.addColorStop(0.86, '#0C0B09');
  r.addColorStop(1, 'rgba(10,9,8,0)');
  g.fillStyle = r;
  g.fillRect(0, 0, W, H);
  _wall = new THREE.CanvasTexture(c);
  return _wall;
}
