"""Editable spatial architecture, with daylight, dusk, and studio art direction.

Offline design asset only.  No application state or runtime connections.
All surfaces, plants, horizon, and lighting are authored in Blender.
"""

import math
import random

import bpy
from mathutils import Vector

from common import area, camera, collection, cube, curve, cylinder, material, put, sphere


def _stone(name, color, roughness=0.5, scale=90, relief=0.012):
    mat = material(name, color=color, roughness=roughness)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    coordinates = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = "Fine mineral grain"
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 2.0
    links.new(coordinates.outputs["Object"], noise.inputs["Vector"])
    mineral = nodes.new("ShaderNodeTexNoise")
    mineral.name = "Quiet broad mineral variation"
    mineral.inputs["Scale"].default_value = 1.8
    mineral.inputs["Detail"].default_value = 3.0
    links.new(coordinates.outputs["Object"], mineral.inputs["Vector"])
    tint = nodes.new("ShaderNodeValToRGB")
    tint.color_ramp.elements[0].color = (*[c * 0.87 for c in color[:3]], 1)
    tint.color_ramp.elements[1].color = (*[min(c * 1.045, 1) for c in color[:3]], 1)
    links.new(mineral.outputs["Fac"], tint.inputs["Fac"])
    links.new(tint.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = relief
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def _arch(name, y, radius, spring, width, height, thickness, mat):
    """One solid extruded wall, including the curved inner reveal, open at floor."""
    contour = [(-width / 2, 0), (-width / 2, height), (width / 2, height),
               (width / 2, 0), (radius, 0), (radius, spring)]
    for i in range(1, 97):
        theta = i / 96 * math.pi
        contour.append((radius * math.cos(theta), spring + radius * math.sin(theta)))
    contour.append((-radius, 0))
    n = len(contour)
    verts = [(x, depth, z) for depth in (y, y + thickness) for x, z in contour]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    mesh = bpy.data.meshes.new(name + " solid mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    put(obj, name)
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("Soft architectural arris", "BEVEL")
    bevel.width = 0.045
    bevel.segments = 3
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = math.radians(25)
    # The reveal is a smooth curve; broad wall faces retain planar shading.
    for index in range(7, min(len(mesh.polygons), 103)):
        mesh.polygons[index].use_smooth = True
    return obj


def _sky(variant):
    palette = {
        "daylight": [(0.67, 0.80, 0.96, 1), (0.40, 0.62, 0.88, 1), (0.16, 0.32, 0.62, 1)],
        "dusk": [(0.97, 0.47, 0.21, 1), (0.30, 0.27, 0.49, 1), (0.09, 0.14, 0.30, 1)],
        "studio": [(0.75, 0.82, 0.91, 1), (0.64, 0.72, 0.85, 1), (0.47, 0.58, 0.78, 1)],
    }[variant]
    wrld = bpy.data.worlds.new("Spatial / " + variant + " atmosphere")
    bpy.context.scene.world = wrld
    wrld.use_nodes = True
    nodes = wrld.node_tree.nodes
    links = wrld.node_tree.links
    nodes.clear()
    coord = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    altitude = nodes.new("ShaderNodeMath")
    altitude.operation = "MULTIPLY"
    altitude.inputs[1].default_value = -1
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "Editable horizon and zenith colors"
    ramp.color_ramp.elements[0].position = 0
    ramp.color_ramp.elements[0].color = palette[0]
    ramp.color_ramp.elements[1].position = 0.8
    ramp.color_ramp.elements[1].color = palette[2]
    ramp.color_ramp.elements.new(0.22).color = palette[1]
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.34 if variant != "dusk" else 0.20
    output = nodes.new("ShaderNodeOutputWorld")
    links.new(coord.outputs["Normal"], separate.inputs["Vector"])
    # A world normal faces the incoming ray: negate Z to obtain sky altitude.
    links.new(separate.outputs["Z"], altitude.inputs[0])
    links.new(altitude.outputs[0], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])


def _sun(name, position, target, color, strength, angle):
    data = bpy.data.lights.new(name, "SUN")
    data.color = color
    data.energy = strength
    data.angle = math.radians(angle)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    put(obj, name)
    obj.location = position
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def _olive(name, location, seed=12):
    rng = random.Random(seed)
    base = Vector(location)
    planter = _stone(name + " chalk planter", (0.70, 0.72, 0.68), 0.58, 110)
    bark = material(name + " silver bark", color=(0.18, 0.16, 0.12), roughness=0.68)
    soil = material(name + " soil", color=(0.022, 0.025, 0.020), roughness=0.95)
    greens = [material(name + " olive leaf " + str(i), color=c, roughness=0.52)
              for i, c in enumerate([(0.18, 0.25, 0.13), (0.28, 0.34, 0.18), (0.36, 0.40, 0.25)])]
    cylinder(name + " vessel", base + Vector((0, 0, 0.34)), 0.45, 0.68, planter)
    cylinder(name + " planting bed", base + Vector((0, 0, 0.683)), 0.399, 0.018, soil)
    trunk = [base + Vector(p) for p in [(0, 0, 0.65), (0.05, 0, 1.1), (-0.03, 0.035, 1.65),
                                       (0.12, 0.02, 2.12), (0.16, 0.09, 2.75)]]
    curve(name + " trunk", trunk, 0.029, bark)
    leaf_mesh = bpy.data.meshes.new(name + " linked leaf blade")
    leaf_mesh.from_pydata([(0, 0, 0), (0.14, -0.035, 0.018), (0.29, 0, 0.005),
                          (0.14, 0.035, 0.018), (0.14, 0, 0.043)], [],
                         [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
    leaf_mesh.update()
    for mat in greens:
        leaf_mesh.materials.append(mat)
    for k in range(14):
        theta = k * 2.399
        z = rng.uniform(1.5, 2.6)
        length = rng.uniform(0.55, 1.0) * (1 if z < 2.35 else 0.7)
        start = base + Vector((0.05, 0.03, z))
        end = start + Vector((math.cos(theta) * length, math.sin(theta) * length, rng.uniform(0.18, 0.38)))
        middle = start.lerp(end, 0.55) + Vector((0, 0, 0.06))
        curve(name + " branch " + str(k), [start, middle, end], 0.008, bark)
        for j in range(9):
            t = 0.24 + j * 0.087
            loc = start.lerp(end, t) + Vector((0, 0, 0.04 * math.sin(t * math.pi)))
            leaf = bpy.data.objects.new(name + " leaf %02d.%02d" % (k, j), leaf_mesh)
            bpy.context.collection.objects.link(leaf)
            put(leaf, leaf.name)
            leaf.location = loc
            direction = Vector((math.cos(theta + (1 if j % 2 else -1) * 1.0),
                                math.sin(theta + (1 if j % 2 else -1) * 1.0), rng.uniform(-0.2, 0.4)))
            leaf.rotation_euler = direction.to_track_quat("X", "Z").to_euler()
            leaf.scale = (rng.uniform(0.75, 1.2),) * 3


def build(variant="daylight"):
    if variant not in {"daylight", "dusk", "studio"}:
        raise ValueError("Spatial variant must be daylight, dusk, or studio")
    scene = bpy.context.scene
    scene["asset_family"] = "Spatial Architecture"
    scene["lighting_variant"] = variant
    scene["design_intent"] = "Sculptural arch, quiet horizon, natural materials; room for a future UI overlay."
    _sky(variant)

    collection("01 / Honed stone architecture")
    ivory = _stone("Architecture / warm mineral plaster", (0.79, 0.70, 0.56) if variant != "studio" else (0.79, 0.80, 0.79), 0.70, 95, 0.012)
    floor = _stone("Floor / honed limestone", (0.59, 0.56, 0.48) if variant != "studio" else (0.60, 0.64, 0.67), 0.29, 64, 0.006)
    bench_mat = _stone("Furniture / ivory travertine", (0.74, 0.69, 0.60), 0.40, 75, 0.009)
    joint = material("Architecture / recessed shadow joints", color=(0.40, 0.36, 0.30), roughness=0.8)
    brass = material("Detail / brushed champagne", color=(0.46, 0.38, 0.25), metallic=0.78, roughness=0.33)

    # Tall opening is intentionally generous; both physical jambs remain editable.
    _arch("Monolithic arch / continuous solid reveal", 3.2, 4.5, 3.0, 26, 12, 1.25, ivory)
    cube("Terrace / substantial stone slab",
         (0, 7.5 if variant == "studio" else -0.5, -0.22),
         (30, 42 if variant == "studio" else 26, 0.44), floor, bevel=0.035)
    cube("Left return wall", (-10.4, -0.6, 5.8), (0.9, 8.5, 11.6), ivory, bevel=0.05)
    cube("Roof / quiet left canopy", (-8.4, 0.8, 10.6), (6.0, 5.4, 0.5), ivory, bevel=0.055)

    collection("02 / Stone details and sculptural bench")
    for x in [-9, -6, -3, 0, 3, 6, 9]:
        cube("Stone joint / longitudinal %s" % x, (x, -1.0, 0.003), (0.006, 24, 0.004), joint, bevel=0)
    for y in [-9, -5, -1, 3, 7, 11]:
        cube("Stone joint / transverse %s" % y, (0, y, 0.003), (28, 0.006, 0.004), joint, bevel=0)
    # Asymmetric stone furniture anchors the architecture without filling the center.
    cube("Bench / hovering stone seat", (5.9, 1.9, 0.70), (3.7, 0.91, 0.21), bench_mat, bevel=0.095)
    for x in [4.75, 7.05]:
        cube("Bench / stone pedestal", (x, 1.9, 0.32), (0.40, 0.66, 0.64), bench_mat, bevel=0.035)
        cube("Bench / recessed bronze shoe", (x, 1.9, 0.034), (0.34, 0.60, 0.065), brass, bevel=0.01)
    cube("Opening / champagne threshold", (0, 3.74, 0.008), (8.97, 0.017, 0.015), brass, bevel=0.004)

    collection("03 / Distant environment")
    if variant != "studio":
        ocean = _stone("Horizon / calm water", (0.16, 0.31, 0.43) if variant == "daylight" else (0.18, 0.15, 0.23), 0.22, 0.62, 0.045)
        cube("Ocean / quiet continuous horizon", (0, 271, -0.38), (1500, 520, 0.16), ocean, bevel=0)
        # A low parapet gives the terrace a convincing physical edge.
        cube("Terrace / distant parapet cap", (0, 11.4, 0.17), (27, 0.35, 0.34), ivory, bevel=0.045)
        if variant == "dusk":
            sun_material = material("Horizon / setting sun", color=(1, 0.43, 0.17), roughness=1,
                                    emission=(1, 0.36, 0.09), strength=4)
            sphere("Setting sun / physical disc sphere", (-53, 240, 7.8), 3.8, sun_material)
    else:
        # A second gallery provides layered depth; no photographic backdrop is used.
        back = _stone("Gallery / cool chalk", (0.59, 0.65, 0.70), 0.65, 95, 0.015)
        _arch("Gallery / inner arch", 10.6, 3.7, 2.75, 24, 11, 0.65, ivory)
        cube("Gallery / rear wall", (0, 18.0, 5.3), (30, 0.7, 10.6), back, bevel=0.10)
        cube("Gallery / ceiling", (0, 13, 10.55), (22, 11, 0.5), ivory, bevel=0.1)
        collection("04 / Architectural planting")
        _olive("Olive / foreground", (-3.25, 1.3, 0), 22)
        _olive("Olive / inner gallery", (1.8, 12.7, 0), 37)

    collection("05 / Lighting and camera")
    if variant == "daylight":
        _sun("Sun / warm late morning", (-12, 22, 16), (2, -2, 0), (1.0, 0.84, 0.63), 5.5, 1.2)
        area("Opening / broad sky bounce", (0, 7, 7), (0, -1, 1.3), 550, (0.65, 0.81, 1.0), 9)
        area("Front / warm reflected sunlight", (-6, -5, 7), (2, 3, 3), 1000, (1.0, 0.86, 0.67), 6)
    elif variant == "dusk":
        # The visible emissive sphere supplies the single reflected sunset.
        # Its directional companion illuminates the room from the same bearing;
        # reflection-disabled fills avoid a second artificial sun on the water.
        sunset = _sun("Sun / low amber", (-53, 240, 7.8), (0, 0, 0),
                      (1.0, 0.49, 0.21), 2.1, 1.8)
        dusk_fill = area("Front / dusk bounce", (0, -6, 6), (0, 3, 2),
                         250, (0.45, 0.53, 1.0), 9)
        amber_fill = area("Opening / amber sky bounce", (-3, 9, 4), (2, 0, 1),
                          420, (1.0, 0.48, 0.23), 7)
        for light in (sunset, dusk_fill, amber_fill):
            light.data.specular_factor = 0.0
            light.visible_glossy = False
        warm = material("Cove / concealed amber", color=(1, 0.48, 0.17), roughness=0.4,
                        emission=(1.0, 0.44, 0.13), strength=3.0)
        # Thin strips sit below the bench and on the back of the reveals.
        cube("Bench / concealed amber strip", (5.9, 1.84, 0.58), (3.30, 0.025, 0.025), warm, bevel=0.007)
        arch_points = [(4.5 * math.cos(t), 4.48, 3 + 4.5 * math.sin(t))
                       for t in [i / 96 * math.pi for i in range(97)]]
        curve("Arch / recessed cove filament", arch_points, 0.012, warm)
        cove_fill = area("Bench / cove spill", (5.9, 1.8, 0.55), (5.9, 1.7, 0),
                         18, (1, 0.46, 0.14), 2.5, 0.2)
        cove_fill.data.specular_factor = 0.0
        cove_fill.visible_glossy = False
    else:
        _sun("Gallery / skylight sun", (-5, 8, 13), (2, -4, 0), (0.90, 0.95, 1), 1.65, 3.5)
        area("Gallery / large skylight", (-3, 7, 9), (0, 0, 1), 1550, (0.86, 0.92, 1), 7)
        area("Gallery / back skylight", (-3, 14, 8), (1, 11, 1), 1800, (0.95, 0.97, 1), 5)
        area("Gallery / front silk", (0, -8, 8), (0, 3, 2), 800, (1, 0.96, 0.88), 9)

    camera("Spatial / architectural composition", (5.8, -9.8, 2.7), (0.15, 6.0, 3.0), lens=40)
    # Comfortable open view of the actual scene when the .blend is opened.
    for screen in bpy.data.screens:
        for space_area in screen.areas:
            if space_area.type == "VIEW_3D":
                space_area.spaces.active.region_3d.view_perspective = "CAMERA"
