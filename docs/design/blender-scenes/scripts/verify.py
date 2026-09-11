"""Reopen delivered projects, verify resources, and assemble the scene library."""
import hashlib
import json
import math
import struct
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
IDS = ('porcelain', 'graphite', 'daylight', 'dusk', 'studio', 'techno-forest')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


results = []
for scene_id in IDS:
    project = ROOT / 'blend' / (scene_id + '.blend')
    preview = ROOT / 'renders' / (scene_id + '.png')
    bpy.ops.wm.open_mainfile(filepath=str(project), load_ui=False)
    scene = bpy.context.scene
    # Normalize early renders too: extracted projects save beside their own PNGs.
    scene.render.filepath = '//../renders/' + scene_id + '.png'
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(project), compress=True)
    assert scene.camera and scene.camera.type == 'CAMERA', 'Missing scene camera'
    assert len(bpy.data.meshes) > 0 and len(bpy.data.materials) > 0, 'Missing editable assets'
    assert all(math.isfinite(x) for obj in scene.objects for row in obj.matrix_world for x in row)
    missing = [im.filepath for im in bpy.data.images
               if im.source == 'FILE' and not im.packed_file and im.filepath
               and not Path(bpy.path.abspath(im.filepath)).exists()]
    assert not missing, 'Missing image files: ' + str(missing)
    assert not bpy.data.libraries, 'External linked libraries must not be required'
    assert bpy.data.texts.get('START HERE.txt'), 'Embedded instructions missing'
    header = preview.read_bytes()[:24]
    assert header[:8] == b'\x89PNG\r\n\x1a\n', 'Invalid preview PNG'
    width, height = struct.unpack('>II', header[16:24])
    assert [width, height] == [scene.render.resolution_x, scene.render.resolution_y]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_vertices = sum(len(o.evaluated_get(depsgraph).data.vertices)
                             for o in scene.objects if o.type == 'MESH')
    results.append({
        'id': scene_id, 'reopened': True, 'objects': len(scene.objects),
        'editable_meshes': len(bpy.data.meshes), 'mesh_vertices_with_modifiers': evaluated_vertices,
        'materials': len(bpy.data.materials), 'lights': sum(o.type == 'LIGHT' for o in scene.objects),
        'camera': scene.camera.name, 'external_missing': missing,
        'resolution': [width, height], 'blend_bytes': project.stat().st_size,
        'render_bytes': preview.stat().st_size, 'blend_sha256': digest(project),
        'render_sha256': digest(preview),
    })
    print('VERIFIED:', scene_id, flush=True)

# A single project lets the owner switch all six environments in Blender's Scene menu.
bpy.ops.wm.read_factory_settings(use_empty=True)
empty = bpy.context.scene
loaded = []
for scene_id in IDS:
    with bpy.data.libraries.load(str(ROOT / 'blend' / (scene_id + '.blend')), link=False) as (source, target):
        target.scenes = source.scenes
    loaded.extend(target.scenes)
assert len(loaded) == 6
bpy.context.window.scene = next(s for s in loaded if s.name.startswith('Porcelain'))
bpy.data.scenes.remove(empty)
bpy.context.preferences.filepaths.save_version = 0
for source in sorted((ROOT / 'scripts').glob('*.py')):
    text = bpy.data.texts.new(source.name)
    text.use_fake_user = True
    text.write(source.read_text(encoding='utf-8'))
notes = bpy.data.texts.new('START HERE.txt')
notes.use_fake_user = True
notes.write('Daedalus / six spatial studies\n\n'
            'Use the Scene menu at the top right to switch environments.\n'
            'Numpad 0: camera. F12: render. Materials, lighting and geometry are editable.\n'
            'All assets are local. No add-ons or automatic Python execution required.\n')
library = ROOT / 'blend' / 'Daedalus-Scene-Collection.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(library), compress=True)
bpy.ops.wm.open_mainfile(filepath=str(library), load_ui=False)
assert len(bpy.data.scenes) == 6
assert all(s.camera for s in bpy.data.scenes)
report = {
    'toolchain': bpy.app.version_string,
    'scope': 'Offline Blender projects and still renders; no runtime/UI integration claim.',
    'all_passed': True, 'scenes': results,
    'collection': {'file': 'blend/' + library.name, 'scenes': len(bpy.data.scenes),
                   'bytes': library.stat().st_size, 'sha256': digest(library)},
}
(ROOT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print('ALL_SIX_VERIFIED:', json.dumps(report), flush=True)
