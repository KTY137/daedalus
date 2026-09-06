"""Graphite Atelier: editable studio sculpture, not a live project graph.

ALIGNED / Gate 1: presentation assets only. The shared driver owns scene reset,
render settings, saving and exports. All materials and geometry are procedural.
"""

import math

import bpy

from common import area, camera, collection, cube, curve, material, sphere, world


def _put(obj, collection_name):
    target = bpy.data.collections.get(collection_name)
    if target is not None:
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        target.objects.link(obj)
    return obj


def _shell(name, location, glass):
    """A closed, editable 5.5 cm glass shell with a rounded outside profile."""
    obj = cube(name, location, (2.82, 1.55, 1.36), glass, bevel=0.14)
    # Bevel is intentionally left live. The inner wall follows the outer bevel.
    for modifier in obj.modifiers:
        if modifier.type == "BEVEL":
            modifier.segments = 5
    shell = obj.modifiers.new("Glass wall · 55 mm", "SOLIDIFY")
    shell.thickness = 0.055
    shell.offset = -1
    shell.use_even_offset = True
    obj["art_direction"] = "Smoked optical glass / hollow sculptural module"
    return obj


def _ring(name, location, radius, tube, mat, face_front=False):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=48,
        minor_segments=10,
        location=location,
        rotation=(math.pi / 2, 0, 0) if face_front else (0, 0, 0),
        major_radius=radius,
        minor_radius=tube,
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    return _put(obj, "Graphite · Metal sculptures")


def _shield(name, center, mat):
    x, y, z = center
    profile = [(-0.34, 0.36), (0.34, 0.36), (0.31, -0.06),
               (0.19, -0.29), (0, -0.43), (-0.19, -0.29),
               (-0.31, -0.06)]
    n = len(profile)
    vertices = [(x + px, y + side, z + pz) for side in (-0.095, 0.095)
                for px, pz in profile]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n)
                 for i in range(n))
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("Machined edge", "BEVEL")
    bevel.width = 0.045
    bevel.segments = 3
    obj.modifiers.new("Weighted surface normals", "WEIGHTED_NORMAL")
    return _put(obj, "Graphite · Metal sculptures")


def _symbol(index, center, titanium, inset):
    x, y, z = center
    if index == 0:
        # Eight separate machined cubes; each remains independently editable.
        for ix in (-1, 1):
            for iy in (-1, 1):
                for iz in (-1, 1):
                    cube(f"01 · modular lattice · {ix} {iy} {iz}",
                         (x + ix * 0.165, y + iy * 0.165, z + iz * 0.165),
                         (0.255, 0.255, 0.255), titanium, bevel=0.026)
    elif index == 1:
        # A solid core inside a skeletal cubic cage.
        cube("02 · central core", (x, y, z), (0.38, 0.38, 0.38),
             titanium, bevel=0.045)
        d = 0.40
        for height in (-d, d):
            curve(f"02 · cage rim {height}",
                  [(x - d, y - d, z + height), (x + d, y - d, z + height),
                   (x + d, y + d, z + height), (x - d, y + d, z + height)],
                  0.018, titanium, cyclic=True)
        for ix, iy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            curve(f"02 · cage pillar {ix} {iy}",
                  [(x + ix * d, y + iy * d, z - d),
                   (x + ix * d, y + iy * d, z + d)], 0.018, titanium)
    elif index == 2:
        for i in range(3):
            cube(f"03 · memory plate {i + 1}", (x, y, z + (i - 1) * 0.225),
                 (0.88, 0.63, 0.105), titanium, bevel=0.035)
            cube(f"03 · plate inlay {i + 1}",
                 (x, y - 0.318, z + (i - 1) * 0.225),
                 (0.53, 0.011, 0.022), inset, bevel=0.006)
    elif index == 3:
        _ring("04 · upper rotor", (x, y, z + 0.20), 0.34, 0.07, titanium)
        _ring("04 · lower rotor", (x, y, z - 0.20), 0.34, 0.07, titanium)
        sphere("04 · spindle", (x, y, z), 0.18, titanium)
    elif index == 4:
        _shield("05 · shield", (x, y, z + 0.04), titanium)
        curve("05 · shield engraving",
              [(x, y - 0.102, z + 0.29), (x, y - 0.102, z - 0.25)],
              0.007, inset)
    else:
        for i, radius in enumerate((0.35, 0.255, 0.16)):
            _ring(f"06 · concentric seal {i + 1}",
                  (x, y - i * 0.028, z), radius, 0.028, titanium, True)
        sphere("06 · seal center", (x, y - 0.085, z), 0.065, inset)


def build(variant=None):
    """Populate the active scene. Called after the shared driver's reset."""
    scene = bpy.context.scene
    scene["scene_title"] = "Graphite Atelier"
    scene["scene_description"] = (
        "Six suspended smoked-glass modules, titanium sculptures and silver "
        "signal paths. Decorative art direction; no live project data."
    )
    glass = material("Graphite / optical smoke", (0.70, 0.78, 0.87),
                     roughness=0.075, transmission=1, ior=1.46)
    titanium = material("Graphite / bead-blasted titanium", (0.42, 0.49, 0.59),
                        metallic=0.92, roughness=0.235)
    silver = material("Graphite / fine brushed silver", (0.55, 0.66, 0.78),
                      metallic=0.9, roughness=0.25)
    black = material("Graphite / ceramic inserts", (0.012, 0.018, 0.026),
                     metallic=0.4, roughness=0.26)
    cyan = material("Graphite / ice-blue optical sockets", (0.19, 0.66, 1),
                    roughness=0.22, emission=(0.16, 0.61, 1), strength=3.2)
    floor = material("Graphite / satin basalt", (0.019, 0.025, 0.034),
                     metallic=0.38, roughness=0.28)

    collection("Graphite · Stage")
    cube("Seamless charcoal stage", (0, 0, -0.15), (200, 200, 0.25),
         floor, bevel=0.03)

    modules = [
        (-2.05, 2.50, 2.02), (2.02, 2.48, 1.85),
        (-2.28, -0.34, 1.58), (2.27, -0.24, 1.40),
        (-1.96, -3.17, 1.12), (2.36, -2.98, 0.94),
    ]
    collection("Graphite · Optical glass")
    for i, loc in enumerate(modules):
        _shell(f"Module {i + 1:02d} / glass shell", loc, glass)

    collection("Graphite · Metal sculptures")
    for i, loc in enumerate(modules):
        _symbol(i, loc, titanium, black)

    collection("Graphite · Connections")
    sockets = []
    for i, (x, y, z) in enumerate(modules):
        port = (x - 0.76, y - 0.783, z - 0.41)
        sockets.append(port)
        cube(f"Module {i + 1:02d} / socket housing", port,
             (0.14, 0.064, 0.13), black, bevel=0.028)
        cube(f"Module {i + 1:02d} / optical contact",
             (port[0], port[1] - 0.036, port[2]),
             (0.057, 0.016, 0.066), cyan, bevel=0.011)

    # Each route has its own editable curve. The regular bends are intentional:
    # this is a quiet physical diagram, not a mesh of decorative random wires.
    routes = [
        (0, 1, 1.55), (0, 2, -0.06), (1, 3, 0.43),
        (2, 4, -2.16), (3, 5, -2.02), (4, 5, -4.72),
    ]
    for route_index, (start, end, lane_y) in enumerate(routes):
        a, b = sockets[start], sockets[end]
        route_z = 0.22 + (route_index % 3) * 0.065
        points = [a, (a[0], a[1] - 0.12, a[2] - 0.22),
                  (a[0], lane_y, route_z),
                  ((a[0] + b[0]) / 2, lane_y, route_z),
                  (b[0], lane_y, route_z),
                  (b[0], b[1] - 0.13, b[2] - 0.22), b]
        curve(f"Silver signal route {start + 1:02d}—{end + 1:02d}",
              points, 0.012, silver)

    collection("Graphite · Studio rig")
    world((0.055, 0.069, 0.094), 0.25)
    area("Key / large silk", (-4, -3, 10), (0, 0, 1),
         1550, color=(0.90, 0.95, 1), size=8, size_y=5)
    area("Rim / ice strip", (6, 3, 6), (0, 0, 1.2),
         1100, color=(0.55, 0.73, 1), size=2, size_y=7)
    area("Edge / tall white strip", (-6, 2, 5), (0, 0, 1.5),
         1250, color=(0.95, 0.97, 1), size=1.5, size_y=7)
    area("Front / soft fill", (0, -8, 4.5), (0, 0, 1),
         400, color=(0.72, 0.82, 1), size=7, size_y=3)
    area("Top / reflected ribbon", (1, 1, 9), (0, 0, 0),
         850, color=(1, 0.96, 0.91), size=3, size_y=8)
    camera("Graphite / hero camera", (8.5, -16, 12.5),
           (0, -0.15, 1.2), lens=55, ortho=12.6)
