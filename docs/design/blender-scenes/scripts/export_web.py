"""Export bounded, offline GLBs without changing the authoritative .blend files.

Run: blender --background --python scripts/export_web.py -- --scene all
ALIGNED / Gate 1. These are decorative derivatives; source projects retain
editable geometry, procedural shaders, lighting and Cycles render settings.
"""

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parents[2]
OUTPUT = REPO / "apps" / "web" / "public" / "scenes"
IDS = ("porcelain", "graphite", "daylight", "dusk", "studio", "techno-forest")
TARGETS = {
    "porcelain": (0, 0, 1.08), "graphite": (0, -0.15, 1.2),
    "daylight": (0.15, 6, 3), "dusk": (0.15, 6, 3),
    "studio": (0.15, 6, 3), "techno-forest": (0.45, 14, 4.8),
}
Y_UP = Matrix.Rotation(-math.pi / 2, 4, "X")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vec(values):
    return [round(float(value), 7) for value in values]


def spatial_transform(obj):
    matrix = Y_UP @ obj.matrix_world
    location, rotation, _ = matrix.decompose()
    target = matrix @ Vector((0, 0, -10))
    return {"position": vec(location),
            "quaternion": vec((rotation.x, rotation.y, rotation.z, rotation.w)),
            "target": vec(target)}


def environment_metadata(scene):
    result = {"color": [0.1, 0.1, 0.1], "strength": 0.3}
    if not scene.world or not scene.world.use_nodes:
        return result
    for node in scene.world.node_tree.nodes:
        if node.type == "BACKGROUND":
            result["color"] = vec(node.inputs["Color"].default_value[:3])
            result["strength"] = float(node.inputs["Strength"].default_value)
        if node.type == "VALTORGB":
            result["gradient"] = [{"position": float(e.position),
                                   "color": vec(e.color[:3])}
                                  for e in node.color_ramp.elements]
            result["color"] = result["gradient"][0]["color"]
    # Node order is not significant; a linked Background's socket default is
    # not the actual horizon color when a procedural gradient drives it.
    if result.get("gradient"):
        result["color"] = result["gradient"][0]["color"]
    return result


def rig_metadata(scene):
    lights = []
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        data = obj.data
        item = {"name": obj.name, "type": data.type.lower(),
                "color": vec(data.color), "power": float(data.energy),
                **spatial_transform(obj)}
        if data.type == "AREA":
            item["width"] = float(data.size)
            item["height"] = float(data.size_y if data.shape in {"RECTANGLE", "ELLIPSE"} else data.size)
        if data.type == "SUN":
            item["angle"] = float(data.angle)
        lights.append(item)
    return lights


def flatten_procedural_shaders():
    changed = []
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            continue
        if bsdf.inputs["Base Color"].is_linked:
            for link in list(bsdf.inputs["Base Color"].links):
                mat.node_tree.links.remove(link)
            bsdf.inputs["Base Color"].default_value = mat.diffuse_color
            changed.append(mat.name)
        # Procedural bump nodes are not glTF textures. The original scene keeps
        # them, while this derivative carries smooth normals and authored PBR.
        for link in list(bsdf.inputs["Normal"].links):
            mat.node_tree.links.remove(link)
    return changed


def prepare_geometry(scene, scene_id):
    active_camera = scene.camera
    removed = []
    for obj in list(scene.objects):
        is_volume = any(mat and mat.use_nodes and any(n.type == "PRINCIPLED_VOLUME"
                        for n in mat.node_tree.nodes) for mat in getattr(obj.data, "materials", []))
        if (obj.hide_render or not getattr(obj, "visible_camera", True) or is_volume
                or obj.type == "LIGHT" or obj.type == "CAMERA" and obj != active_camera):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    # Keep a useful floor around the authored camera, with bounded scene extents.
    for name in ("Continuous pale floor", "Seamless charcoal stage"):
        obj = bpy.data.objects.get(name)
        if obj:
            obj.dimensions.x = obj.dimensions.y = 42
    ocean = bpy.data.objects.get("Ocean / quiet continuous horizon")
    if ocean:
        ocean.dimensions.x, ocean.dimensions.y = 240, 320
        ocean.location.y = 171
    for obj in scene.objects:
        if obj.type == "CURVE":
            if scene_id == "techno-forest":
                obj.data.resolution_u = min(obj.data.resolution_u, 3)
                # Tiny fern twigs and fibers need fewer radial segments. The
                # main organic trunks and boughs keep their eight-sided sweep.
                if any(token in obj.name.lower() for token in ("fern", "fiber", "optic", "seedling")):
                    obj.data.bevel_resolution = 0
            else:
                obj.data.resolution_u = min(obj.data.resolution_u, 6)
                obj.data.bevel_resolution = min(obj.data.bevel_resolution, 2)
    bpy.ops.object.select_all(action="DESELECT")
    geometry = [obj for obj in scene.objects if obj.type in {"MESH", "CURVE", "SURFACE", "FONT"}]
    for obj in geometry:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = geometry[0]
    bpy.ops.object.convert(target="MESH")
    # Join by original collection and material signature to reduce draw calls.
    # Each glass block and the porcelain ribbon retain their own node identity.
    groups = defaultdict(list)
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        materials = tuple(mat.name if mat else "" for mat in obj.data.materials)
        transparent = any(mat and mat.use_nodes and any(
            n.type == "BSDF_PRINCIPLED" and n.inputs["Transmission Weight"].default_value > 0
            for n in mat.node_tree.nodes) for mat in obj.data.materials)
        key = (obj.users_collection[0].name if obj.users_collection else "Geometry", materials,
               obj.name if transparent else "")
        groups[key].append(obj)
    for (group, materials, _), objects in groups.items():
        if len(objects) < 2:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
        bpy.context.object.name = group + " / " + (materials[0] if materials else "surface")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in scene.objects:
        if obj.type in {"MESH", "CAMERA"}:
            obj.select_set(True)
    return removed


def read_glb(path):
    data = path.read_bytes()
    magic, version, size = struct.unpack_from("<4sII", data)
    assert magic == b"glTF" and version == 2 and size == len(data), "Invalid GLB header"
    json_size, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A, "Missing GLB JSON chunk"
    document = json.loads(data[20:20 + json_size])
    assert not any("uri" in value for key in ("images", "buffers")
                   for value in document.get(key, [])), "External GLB resource"
    assert len(document.get("cameras", [])) == 1, "Expected one hero camera"
    return document


def glb_metrics(document):
    vertices = triangles = primitives = 0
    bounds_min, bounds_max = Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
    accessors = document.get("accessors", [])
    cameras = []

    def walk(index, parent):
        nonlocal vertices, triangles, primitives
        node = document["nodes"][index]
        if "matrix" in node:
            raw = node["matrix"]
            local = Matrix([[raw[c * 4 + r] for c in range(4)] for r in range(4)])
        else:
            from mathutils import Quaternion
            q = node.get("rotation", [0, 0, 0, 1])
            local = Matrix.LocRotScale(Vector(node.get("translation", [0, 0, 0])),
                                      Quaternion((q[3], q[0], q[1], q[2])),
                                      Vector(node.get("scale", [1, 1, 1])))
        transform = parent @ local
        if "camera" in node:
            cameras.append((node, transform))
        if "mesh" in node:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                assert primitive.get("mode", 4) == 4, "Only triangles are expected"
                position = accessors[primitive["attributes"]["POSITION"]]
                vertices += position["count"]
                count = accessors[primitive["indices"]]["count"] if "indices" in primitive else position["count"]
                triangles += count // 3
                primitives += 1
                for x in (position["min"][0], position["max"][0]):
                    for y in (position["min"][1], position["max"][1]):
                        for z in (position["min"][2], position["max"][2]):
                            point = transform @ Vector((x, y, z))
                            for i in range(3):
                                bounds_min[i] = min(bounds_min[i], point[i])
                                bounds_max[i] = max(bounds_max[i], point[i])
        for child in node.get("children", []):
            walk(child, transform)

    for root_node in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(root_node, Matrix.Identity(4))
    assert vertices and triangles and len(cameras) == 1
    assert all(math.isfinite(value) for value in (*bounds_min, *bounds_max))
    return {"vertices": vertices, "triangles": triangles, "primitives": primitives,
            "bounds": {"min": vec(bounds_min), "max": vec(bounds_max)}}, cameras[0]


def export_scene(scene_id):
    start = time.monotonic()
    source = ROOT / "blend" / (scene_id + ".blend")
    source_hash = sha256(source)
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    scene = bpy.context.scene
    cam = scene.camera
    camera_metadata = {"name": cam.name,
                       "type": "orthographic" if cam.data.type == "ORTHO" else "perspective",
                       **spatial_transform(cam), "target": vec(Y_UP @ Vector(TARGETS[scene_id])),
                       "near": float(cam.data.clip_start), "far": float(cam.data.clip_end),
                       "aspect": 1.6, "fovDegrees": math.degrees(cam.data.angle_y)}
    if cam.data.type == "ORTHO":
        camera_metadata["orthoScale"] = float(cam.data.ortho_scale)
    result = {"id": scene_id, "url": "/scenes/" + scene_id + ".glb",
              "camera": camera_metadata, "environment": environment_metadata(scene),
              "lights": rig_metadata(scene), "fog": None, "sourceSha256": source_hash}
    if scene_id == "techno-forest":
        result["fog"] = {"color": [0.18, 0.33, 0.40], "density": 0.018}
    result["flattenedProceduralMaterials"] = flatten_procedural_shaders()
    result["excludedRenderHelpers"] = prepare_geometry(scene, scene_id)
    path = OUTPUT / (scene_id + ".glb")
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB",
        use_selection=True, export_cameras=True, export_lights=False,
        export_extras=False, export_yup=True, export_apply=True,
        export_animations=False, export_texcoords=False, export_normals=True,
        export_tangents=False, export_draco_mesh_compression_enable=False)
    document = read_glb(path)
    metrics, (camera_node, camera_matrix) = glb_metrics(document)
    position, rotation, _ = camera_matrix.decompose()
    # Take the exported camera as the source for viewer metadata, eliminating
    # any dependency on the exporter's transform implementation details.
    camera_metadata["position"] = vec(position)
    camera_metadata["quaternion"] = vec((rotation.x, rotation.y, rotation.z, rotation.w))
    exported_camera = document["cameras"][camera_node["camera"]]
    if exported_camera["type"] == "perspective":
        camera_metadata["fovDegrees"] = math.degrees(exported_camera["perspective"]["yfov"])
    else:
        camera_metadata["xmag"] = exported_camera["orthographic"]["xmag"]
        camera_metadata["ymag"] = exported_camera["orthographic"]["ymag"]
    result.update(metrics)
    result.update({"bytes": path.stat().st_size, "sha256": sha256(path),
                   "seconds": round(time.monotonic() - start, 2),
                   "extensions": document.get("extensionsUsed", [])})
    assert sha256(source) == source_hash, "Authoritative Blender source changed"
    assert result["bytes"] <= 6_000_000, "Web scene exceeds six MB budget"
    print("WEB_SCENE_READY:", json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", choices=("all", *IDS), default="all")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "version": 1, "coordinateSystem": "Y_UP", "scenes": {}}
    for scene_id in IDS if args.scene == "all" else (args.scene,):
        manifest["scenes"][scene_id] = export_scene(scene_id)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("WEB_EXPORT_COMPLETE:", list(manifest["scenes"]), flush=True)


if __name__ == "__main__":
    main()
