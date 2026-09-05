"""Small offline authoring helpers for the editable Blender scene collection."""
import math
import bpy
from mathutils import Vector

_collection = None


def reset():
    global _collection
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _collection = None


def collection(name):
    global _collection
    _collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(_collection)
    return _collection


def put(obj, name, mat=None):
    obj.name = name
    if _collection:
        for parent in list(obj.users_collection):
            parent.objects.unlink(obj)
        _collection.objects.link(obj)
    if mat:
        obj.data.materials.append(mat)
    return obj


def material(name, color=(.8, .8, .8), metallic=0, roughness=.3,
             transmission=0, ior=1.45, emission=None, strength=1):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color[:3], 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color[:3], 1)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Transmission Weight'].default_value = transmission
    bsdf.inputs['IOR'].default_value = ior
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*emission[:3], 1)
        bsdf.inputs['Emission Strength'].default_value = strength
    return mat


def smooth(obj):
    if obj.type == 'MESH':
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj


def cube(name, loc, scale, mat, bevel=.08):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = put(bpy.context.object, name, mat)
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new('Machined edge radius', 'BEVEL')
        mod.width, mod.segments = bevel, 4
        normal = obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
        normal.keep_sharp = True
    return obj


def sphere(name, loc, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius, location=loc)
    return smooth(put(bpy.context.object, name, mat))


def cylinder(name, loc, radius, depth, mat):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=depth, location=loc)
    obj = smooth(put(bpy.context.object, name, mat))
    bevel = obj.modifiers.new('Soft machined edge', 'BEVEL')
    bevel.width, bevel.segments = min(.025, radius * .1), 3
    obj.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    return obj


def curve(name, points, radius, mat, cyclic=False):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions, data.resolution_u = '3D', 12
    data.bevel_depth, data.bevel_resolution = radius, 3
    data.use_fill_caps = True
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for p, co in zip(spline.bezier_points, points):
        p.co = co
        p.handle_left_type = p.handle_right_type = 'AUTO'
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return put(obj, name, mat)


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def camera(name, loc, target, lens=50, ortho=None):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    put(obj, name)
    obj.location = loc
    data.lens, data.clip_end = lens, 500
    if ortho:
        data.type, data.ortho_scale = 'ORTHO', ortho
    aim(obj, target)
    bpy.context.scene.camera = obj
    return obj


def area(name, loc, target, energy, color=(1, 1, 1), size=5, size_y=None):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy, data.color, data.shape, data.size = energy, color, 'DISK', size
    if size_y:
        data.shape, data.size_y = 'RECTANGLE', size_y
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    put(obj, name)
    obj.location = loc
    aim(obj, target)
    return obj


def world(color=(.1, .1, .1), strength=.3):
    data = bpy.data.worlds.new('Environment')
    data.use_nodes = True
    node = data.node_tree.nodes.get('Background')
    node.inputs['Color'].default_value = (*color[:3], 1)
    node.inputs['Strength'].default_value = strength
    bpy.context.scene.world = data
    return data


def mesh(name, vertices, faces, mat):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return put(obj, name, mat)
