"""Techno Forest — a full-scale, procedural forest corridor.

ALIGNED / Gate 1: decorative scene authoring only. Seeded geometry, no external
textures, editable curves and separate botanical meshes. The shared driver
owns reset, rendering, saves and exports.
"""

import math
import random

import bpy
from mathutils import Vector

from common import area, camera, collection, cube, material, mesh, put, world


SEED = 20260905


def _tube(name, points, radii, mat, detail=5):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = detail
    data.bevel_depth = 1
    data.bevel_resolution = 1
    data.use_fill_caps = True
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for p, co, radius in zip(spline.bezier_points, points, radii):
        p.co = co
        p.radius = radius
        p.handle_left_type = p.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return put(obj, name, mat)


def _ground_z(x, y):
    return -0.10 + 0.085 * math.sin(x * 0.67 + y * 0.23) + 0.06 * math.cos(y * 0.59)


def _path_x(y):
    return 1.05 * math.sin((y + 3) * 0.15) - 0.20


def _leaf(vertices, faces, start, tip, width, twist=0):
    start, tip = Vector(start), Vector(tip)
    axis = tip - start
    side = axis.cross(Vector((0, 0, 1)))
    if side.length < 0.001:
        side = Vector((1, 0, 0))
    side.normalize()
    side = side * math.cos(twist) + Vector((0, 0, 1)) * math.sin(twist)
    middle = start.lerp(tip, 0.48)
    ridge = middle + Vector((0, 0, width * 0.17))
    n = len(vertices)
    vertices.extend([tuple(start), tuple(middle + side * width), tuple(tip),
                     tuple(middle - side * width), tuple(ridge)])
    faces.extend([(n, n + 1, n + 4), (n + 1, n + 2, n + 4),
                  (n + 2, n + 3, n + 4), (n + 3, n, n + 4)])


def _bark_material():
    mat = material("Forest / carbon-mineral bark", (0.042, 0.064, 0.061),
                   metallic=0.42, roughness=0.39)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexNoise")
    tex.name = "Long mineral grain"
    tex.inputs["Scale"].default_value = 4.5
    tex.inputs["Detail"].default_value = 2
    coord = nodes.new("ShaderNodeTexCoord")
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = (4.5, 4.5, 0.28)
    links.new(coord.outputs["Object"], scale.inputs[0])
    links.new(scale.outputs["Vector"], tex.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.2
    ramp.color_ramp.elements[0].color = (0.013, 0.028, 0.028, 1)
    ramp.color_ramp.elements[1].position = 0.8
    ramp.color_ramp.elements[1].color = (0.105, 0.15, 0.129, 1)
    links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.29
    bump.inputs["Distance"].default_value = 0.08
    links.new(tex.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def _tree(index, x, y, height, radius, mats, rng, background=False):
    bark, foliage, foliage_light, fiber = mats
    base_z = _ground_z(x, y)
    lean = Vector((rng.uniform(-0.65, 0.65), rng.uniform(-0.65, 0.65), 0))

    def trunk_point(fraction):
        return Vector((x, y, base_z + height * fraction)) + lean * fraction

    trunk_points = [trunk_point(t) for t in (0, 0.19, 0.43, 0.73, 1)]
    _tube(f"Tree {index:02d} / living trunk", trunk_points,
          [radius * r for r in (1.35, 0.94, 0.77, 0.50, 0.05)], bark)

    # Buttress roots anchor each tree. They taper into the uneven forest floor.
    root_count = 3 if background else 5
    root_phase = rng.random() * math.tau
    for root_index in range(root_count):
        angle = root_phase + root_index * math.tau / root_count
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        extent = radius * rng.uniform(3.4, 5.3)
        root = [Vector((x, y, base_z + radius * 1.4)),
                Vector((x, y, base_z + 0.23)) + direction * extent * 0.39,
                Vector((x, y, base_z + 0.04)) + direction * extent * 0.79,
                Vector((x, y, base_z + 0.015)) + direction * extent]
        _tube(f"Tree {index:02d} / buttress {root_index + 1}", root,
              [radius * 0.48, radius * 0.28, 0.065, 0.012], bark, 4)
        if not background and root_index % 2 == 0:
            luminous_root = [p + Vector((0, 0, 0.05)) for p in root]
            _tube(f"Tree {index:02d} / root optic {root_index + 1}",
                  luminous_root, [0.018, 0.015, 0.011, 0.003], fiber, 4)

    vertices, faces = [], []
    branch_count = 3 if background else 5
    branch_phase = rng.random() * math.tau
    for branch_index in range(branch_count):
        fraction = 0.43 + branch_index * 0.082
        start = trunk_point(fraction)
        angle = branch_phase + branch_index * 2.399
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        span = height * rng.uniform(0.25, 0.36)
        end = start + direction * span + Vector((0, 0, height * 0.13))
        elbow = start + direction * span * 0.41 + Vector((0, 0, height * 0.105))
        _tube(f"Tree {index:02d} / bough {branch_index + 1}",
              [start, elbow, end], [radius * 0.44, radius * 0.18, 0.025], bark)

        # Secondary forks and leaves form a genuinely branched canopy.
        for fork in (-1, 1):
            fork_start = elbow.lerp(end, 0.30)
            fork_direction = Vector((math.cos(angle + fork * 0.78),
                                     math.sin(angle + fork * 0.78), 0.20))
            fork_end = fork_start + fork_direction * span * 0.56
            fork_middle = fork_start.lerp(fork_end, 0.5) + Vector((0, 0, 0.15))
            _tube(f"Tree {index:02d} / twig {branch_index + 1}.{fork}",
                  [fork_start, fork_middle, fork_end], [0.070, 0.038, 0.007], bark, 4)
            axis = (fork_end - fork_start).normalized()
            side = Vector((-axis.y, axis.x, 0))
            pairs = 6 if background else 9
            for leaf_index in range(pairs):
                t = (leaf_index + 1) / (pairs + 1)
                anchor = fork_start.lerp(fork_end, t)
                for sign in (-1, 1):
                    length = rng.uniform(0.40, 0.72) * (0.65 + math.sin(t * math.pi) * 0.35)
                    tip = anchor + side * sign * length + axis * 0.18
                    tip.z += rng.uniform(-0.15, 0.13)
                    _leaf(vertices, faces, anchor, tip, length * 0.15,
                          rng.uniform(-0.35, 0.35))
        # A compact terminal spray bridges the forks into a natural crown.
        for spray in range(10):
            theta = rng.random() * math.tau
            anchor = end + Vector((rng.uniform(-0.35, 0.35),
                                   rng.uniform(-0.35, 0.35), rng.uniform(-0.1, 0.2)))
            tip = anchor + Vector((math.cos(theta) * 0.66,
                                   math.sin(theta) * 0.66, rng.uniform(-0.1, 0.22)))
            _leaf(vertices, faces, anchor, tip, 0.11, rng.uniform(-0.4, 0.4))
    leaves = mesh(f"Tree {index:02d} / folded canopy leaves", vertices, faces, foliage)
    leaves.data.materials.append(foliage_light)
    for face in leaves.data.polygons:
        face.material_index = 1 if rng.random() < 0.17 else 0

    # Thin integrated filaments follow the front surface instead of floating
    # as unrelated neon poles. Foreground fibers fork at a branch junction.
    if not background:
        count = 3 if y < 8 else 1
        for filament in range(count):
            angle = -math.pi / 2 + (filament - (count - 1) / 2) * 0.31
            points = []
            for t in (0.04, 0.17, 0.31, 0.43, 0.55):
                offset = radius * (1.0 - t * 0.60)
                p = trunk_point(t) + Vector((math.cos(angle + t * 0.7) * offset,
                                            math.sin(angle + t * 0.7) * offset, 0))
                points.append(p)
            _tube(f"Tree {index:02d} / cambium fiber {filament + 1}",
                  points, [0.014, 0.020, 0.016, 0.012, 0.002], fiber, 5)


def _fern(index, x, y, size, leafmat, glowmat, rng):
    base = Vector((x, y, _ground_z(x, y) + 0.04))
    vertices, faces, glow_vertices, glow_faces = [], [], [], []
    phase = rng.random() * math.tau
    for frond in range(6):
        angle = phase + frond * math.tau / 6
        direction = Vector((math.cos(angle), math.sin(angle), 0))
        side = Vector((-direction.y, direction.x, 0))
        extent = size * rng.uniform(0.8, 1.2)
        end = base + direction * extent + Vector((0, 0, size * 0.37))
        middle = base + direction * extent * 0.46 + Vector((0, 0, size * 0.74))
        _tube(f"Fern {index:02d} / frond {frond + 1}", [base, middle, end],
              [0.016, 0.008, 0.002], leafmat, 4)
        for j in range(7):
            t = (j + 1) / 8
            anchor = base.lerp(end, t)
            anchor.z += math.sin(t * math.pi) * size * 0.42
            length = math.sin(t * math.pi) * size * 0.32
            for sign in (-1, 1):
                tip = anchor + side * sign * length + direction * size * 0.14
                tip.z -= size * 0.03
                _leaf(vertices, faces, anchor, tip, size * 0.047)
                if j in (3, 5) and index % 3 == 0:
                    _leaf(glow_vertices, glow_faces, tip.lerp(anchor, 0.18),
                          tip, size * 0.014)
    mesh(f"Fern {index:02d} / foliage", vertices, faces, leafmat)
    if glow_vertices:
        mesh(f"Fern {index:02d} / bioluminescent tips", glow_vertices, glow_faces, glowmat)


def build(variant=None):
    rng = random.Random(SEED)
    scene = bpy.context.scene
    scene["scene_title"] = "Techno Forest"
    scene["scene_description"] = (
        "A full-scale forest of branching mineral trees, quiet cyan cambium "
        "fibers, folded foliage and a winding basalt trail through blue mist."
    )
    scene["procedural_seed"] = SEED
    bark = _bark_material()
    foliage = material("Forest / jade carbon foliage", (0.026, 0.12, 0.085),
                       metallic=0.15, roughness=0.48)
    foliage_light = material("Forest / sage leaf undersides", (0.07, 0.19, 0.12),
                             metallic=0.18, roughness=0.44)
    fiber = material("Forest / cyan cambium optics", (0.035, 0.38, 0.44),
                     roughness=0.27, emission=(0.045, 0.65, 0.82), strength=2.5)
    fern_glow = material("Forest / bioluminescent fern tips", (0.07, 0.29, 0.25),
                         emission=(0.08, 0.68, 0.48), strength=1.7)
    amber = material("Forest / amber seed pods", (0.3, 0.13, 0.028),
                     emission=(1, 0.32, 0.065), strength=2.2, roughness=0.24)
    ground = material("Forest / damp mineral earth", (0.025, 0.045, 0.039),
                      metallic=0.12, roughness=0.62)
    basalt = material("Forest / wet black basalt", (0.020, 0.033, 0.038),
                      metallic=0.32, roughness=0.255)
    seam = material("Forest / recessed trail joints", (0.008, 0.014, 0.015),
                    roughness=0.7)

    collection("Forest · Terrain and trail")
    vertices, faces = [], []
    nx, ny = 38, 64
    for j in range(ny):
        y = -14 + j * 1.0
        for i in range(nx):
            x = -18.5 + i
            vertices.append((x, y, _ground_z(x, y)))
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            faces.append((a, a + 1, a + nx + 1, a + nx))
    mesh("Continuous forest floor", vertices, faces, ground)

    trail_vertices, trail_faces = [], []
    path_half_width = 1.22
    for i in range(121):
        y = -14 + i * 0.5
        x = _path_x(y)
        trail_vertices.extend([(x - path_half_width, y, 0.036),
                               (x + path_half_width, y, 0.036)])
        if i:
            a = (i - 1) * 2
            trail_faces.append((a, a + 1, a + 3, a + 2))
    mesh("Winding monolithic basalt path", trail_vertices, trail_faces, basalt)
    for j in range(37):
        y = -12 + j * 1.5
        x = _path_x(y)
        obj = cube(f"Trail / recessed stone joint {j + 1:02d}",
                   (x, y, 0.039), (2.42, 0.025, 0.007), seam, bevel=0)
        obj.rotation_euler.z = -math.atan(0.1575 * math.cos((y + 3) * 0.15))
    # Sparse guidance segments, with long quiet spaces between them.
    for sign in (-1, 1):
        for j in range(10):
            y0 = -9 + j * 4.7
            points = [(_path_x(y0 + t) + sign * 1.20, y0 + t, 0.05)
                      for t in (0, 0.35, 0.70)]
            _tube(f"Trail / embedded optic {sign}.{j}", points,
                  [0.009, 0.009, 0.009], fiber, 3)

    collection("Forest · Branching trees")
    placements = [
        (-4.2, -2.2, 11.6, 0.76), (4.0, -0.7, 12.4, 0.77),
        (-5.4, 3.0, 12.0, 0.64), (4.5, 5.0, 11.3, 0.68),
        (-3.4, 8.0, 10.9, 0.58), (5.0, 10.1, 12.6, 0.67),
        (-6.2, 12.0, 12.7, 0.60), (3.7, 14.8, 11.4, 0.61),
        (-4.5, 18.0, 12.7, 0.57), (5.2, 21.1, 12.1, 0.53),
        (-3.2, 24.2, 11.6, 0.54), (3.4, 27.6, 11.1, 0.48),
    ]
    for sign in (-1, 1):
        for j in range(8):
            placements.append((sign * rng.uniform(7.2, 11.8),
                               0.5 + j * 5.1 + rng.uniform(-1.1, 1.1),
                               rng.uniform(10.5, 14.0), rng.uniform(0.36, 0.62)))
        for j in range(3):
            placements.append((sign * rng.uniform(2.8, 6.6),
                               31 + j * 5.0, rng.uniform(10, 13), 0.4))
    for index, (x, y, height, radius) in enumerate(placements, 1):
        _tree(index, x, y, height, radius,
              (bark, foliage, foliage_light, fiber), rng, background=index > 12)

    collection("Forest · Understory")
    for i in range(48):
        y = rng.uniform(-6, 32)
        side = -1 if i % 2 else 1
        x = _path_x(y) + side * rng.uniform(1.65, 5.5)
        _fern(i + 1, x, y, rng.uniform(0.44, 0.95), foliage, fern_glow, rng)
    for i in range(22):
        y = rng.uniform(-4, 24)
        side = -1 if i % 2 else 1
        x = _path_x(y) + side * rng.uniform(1.45, 2.45)
        z = _ground_z(x, y)
        _tube(f"Amber seedling {i + 1:02d} / stem",
              [(x, y, z), (x + 0.06, y, z + 0.16), (x + 0.08, y, z + 0.27)],
              [0.013, 0.009, 0.005], bark, 3)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.075,
                                             location=(x + 0.08, y, z + 0.29))
        pod = put(bpy.context.object, f"Amber seedling {i + 1:02d} / mineral pod", amber)
        pod.scale = (0.72, 0.72, 1.25)

    collection("Forest · Atmosphere")
    fog = bpy.data.materials.new("Forest / cool aerial mist")
    fog.use_nodes = True
    nodes = fog.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    volume = nodes.new("ShaderNodeVolumePrincipled")
    volume.inputs["Density"].default_value = 0.009
    volume.inputs["Color"].default_value = (0.42, 0.62, 0.70, 1)
    volume.inputs["Anisotropy"].default_value = 0.30
    fog.node_tree.links.new(volume.outputs["Volume"], out.inputs["Volume"])
    box = cube("Single bounded mist volume", (0, 17, 8), (35, 62, 17), fog, bevel=0)
    box.display_type = "WIRE"

    collection("Forest · Light and camera rig")
    world((0.055, 0.115, 0.16), 0.35)
    area("Moon canopy / broad key", (-1, 15, 16), (0, 4, 1.2),
         6500, color=(0.52, 0.76, 1), size=9)
    area("Foreground / cool reflection", (-1, -6, 8), (0, 3, 2.8),
         1700, color=(0.38, 0.67, 0.79), size=10)
    area("Depth / silver mist", (2, 34, 10), (0, 15, 4),
         6500, color=(0.64, 0.84, 1), size=7)
    area("Warm glade / restrained amber", (5, 12, 5), (0, 8, 1),
         750, color=(1, 0.50, 0.22), size=5)
    cam = camera("Forest / immersive trail camera", (0.15, -11.5, 2.85),
                 (0.45, 14, 4.8), lens=26)
    cam.data.clip_start = 0.10
