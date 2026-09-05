"""Run with Blender --background --python build.py -- --scene porcelain ..."""
import argparse
import importlib
import json
from os.path import relpath
import sys
import time
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import reset

SCENES = {
    'porcelain': ('porcelain', None, 'Porcelain'),
    'graphite': ('graphite', None, 'Graphite Atelier'),
    'daylight': ('spatial', 'daylight', 'Spatial Daylight'),
    'dusk': ('spatial', 'dusk', 'Spatial Dusk'),
    'studio': ('spatial', 'studio', 'Spatial Studio'),
    'techno-forest': ('techno_forest', None, 'Techno Forest'),
}


def configure(args):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = .035
    scene.cycles.max_bounces = 10
    scene.cycles.transmission_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.volume_bounces = 1
    scene.cycles.sample_clamp_indirect = 5
    scene.cycles.seed = 20260905
    scene.render.resolution_x, scene.render.resolution_y = args.width, round(args.width * .625)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = args.threads
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
    scene.render.fps = 30
    scene.frame_end = 240
    scene.render.use_file_extension = True
    devices = []
    if args.device != 'CPU':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        try:
            prefs.compute_device_type = 'CUDA'
            prefs.get_devices()
            for d in prefs.devices:
                d.use = d.type == 'CUDA'
                if d.use:
                    devices.append(d.name)
            if devices:
                scene.cycles.device = 'GPU'
        except Exception as exc:
            print('GPU_PROBE:', repr(exc), flush=True)
    if not devices:
        scene.cycles.device = 'CPU'
        devices = ['CPU (%s threads)' % args.threads]
    # Gentle bloom is actual compositing of the rendered light, and stays editable.
    scene.use_nodes = True
    nodes = scene.node_tree.nodes
    nodes.clear()
    layers = nodes.new('CompositorNodeRLayers')
    glare = nodes.new('CompositorNodeGlare')
    glare.glare_type, glare.quality = 'FOG_GLOW', 'HIGH'
    # Blender 4.5 exposes glare controls as sockets (legacy RNA setters warn).
    for name, value in [('Threshold', 2.0), ('Size', .2), ('Strength', .07)]:
        socket = glare.inputs.get(name)
        if socket is not None and hasattr(socket, 'default_value'):
            socket.default_value = value
    output = nodes.new('CompositorNodeComposite')
    scene.node_tree.links.new(layers.outputs['Image'], glare.inputs['Image'])
    scene.node_tree.links.new(glare.outputs['Image'], output.inputs['Image'])
    for screen in bpy.data.screens:
        for region in screen.areas:
            if region.type == 'VIEW_3D':
                region.spaces.active.region_3d.view_perspective = 'CAMERA'
                region.spaces.active.clip_end = 500
    return devices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene', choices=SCENES, required=True)
    parser.add_argument('--width', type=int, default=1600)
    parser.add_argument('--samples', type=int, default=64)
    parser.add_argument('--threads', type=int, default=6)
    parser.add_argument('--device', choices=['AUTO', 'CPU'], default='AUTO')
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--no-render', action='store_true')
    parser.add_argument('--output', type=Path, default=HERE.parent)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    args.output = args.output.resolve()
    start = time.monotonic()
    reset()
    module, variant, title = SCENES[args.scene]
    importlib.import_module(module).build(variant)
    scene = bpy.context.scene
    scene.name = title
    scene['collection_title'] = 'Daedalus / Spatial studies'
    scene['asset_kind'] = 'Decorative design environment. No runtime or graph assertions.'
    scene['rebuild'] = 'blender --background --python scripts/build.py -- --scene ' + args.scene
    scene['seed'] = 20260905
    scene['authoring_version'] = 1
    devices = configure(args)
    dest = args.output / ('drafts' if args.draft else 'renders')
    dest.mkdir(parents=True, exist_ok=True)
    blend_dir = args.output / ('drafts/blend' if args.draft else 'blend')
    blend_dir.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(dest / (args.scene + '.png'))
    bpy.context.preferences.filepaths.save_version = 0
    # The source travels inside each project as well as in the package.
    for source in (HERE / 'common.py', HERE / (module + '.py'), HERE / 'build.py'):
        text = bpy.data.texts.new(source.name)
        text.use_fake_user = True
        text.write(source.read_text(encoding='utf-8'))
    notes = bpy.data.texts.new('START HERE.txt')
    notes.use_fake_user = True
    notes.write(title + '\n\nEditable scene: collections separate architecture, hero, lighting and cameras.\n'
                'Numpad 0: camera. F12: render. Materials use named Principled nodes.\n'
                'All geometry and materials are procedural; no external textures or add-ons.\n'
                'Still image only; no animation or web performance is claimed.\n')
    blend_path = blend_dir / (args.scene + '.blend')
    render_path = scene.render.filepath
    scene.render.filepath = '//' + Path(relpath(dest / (args.scene + '.png'), blend_dir)).as_posix()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)
    scene.render.filepath = render_path
    build_seconds = time.monotonic() - start
    print('SCENE_READY:', args.scene, devices, 'objects', len(scene.objects), flush=True)
    if not args.no_render:
        bpy.ops.render.render(write_still=True)
    info = {
        'scene': args.scene, 'title': title, 'blender': bpy.app.version_string,
        'objects': len(scene.objects), 'meshes': len(bpy.data.meshes),
        'vertices_base': sum(len(m.vertices) for m in bpy.data.meshes),
        'materials': len(bpy.data.materials), 'cameras': sum(o.type == 'CAMERA' for o in scene.objects),
        'devices': devices, 'resolution': [scene.render.resolution_x, scene.render.resolution_y],
        'samples_max': args.samples, 'seed': scene.cycles.seed,
        'build_seconds': round(build_seconds, 2), 'total_seconds': round(time.monotonic() - start, 2),
        'blend': str(blend_path.relative_to(args.output)),
        'render': str((dest / (args.scene + '.png')).relative_to(args.output)) if not args.no_render else None,
        'render_completed': not args.no_render,
    }
    (dest / (args.scene + '.json')).write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    print('SCENE_COMPLETE:', json.dumps(info), flush=True)


if __name__ == '__main__':
    main()
