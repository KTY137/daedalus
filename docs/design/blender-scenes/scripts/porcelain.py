"""Porcelain: a continuous solid glass ribbon in a sunlit cyclorama."""
import math
import bpy
from mathutils import Quaternion, Vector
from common import material, cube, curve, mesh, smooth, camera, area, world, collection


def build(variant=None):
    collection('01 | Porcelain architecture')
    porcelain = material('Porcelain / warm mineral', (.78, .77, .735), roughness=.27)
    stone = material('Plinth / honed ivory', (.7, .705, .69), roughness=.26)
    cube('Continuous pale floor', (0, 0, -.2), (200, 200, .4), porcelain, .06)
    # Real bent wall, a quarter cyclorama curve extruded across the room.
    profile = [(4 + 3 * math.sin(t), 3 - 3 * math.cos(t))
               for t in [i * math.pi / 2 / 40 for i in range(41)]]
    profile += [(7, 12)]
    vertices = [(x, y, z) for x in (-18, 18) for y, z in profile]
    n = len(profile)
    faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
    smooth(mesh('Sweeping studio wall', vertices, faces, porcelain))
    # Raised oval surface catches a crisp, believable contact shadow.
    plinth = cube('Monolithic floating-edge plinth', (0, 0, .055), (4.8, 2.45, .16), stone, .075)
    plinth.rotation_euler.z = math.radians(-7)

    collection('02 | Solid crystal ribbon')
    glass = material('Crystal / faint glacier tint', (.83, .955, .985), roughness=.065,
                     transmission=1, ior=1.46)
    glass['control_note'] = 'Base Color = tint; Roughness = polish; IOR = optical density.'
    # A swept rounded rectangle, not a tube. Two continuous lobes cross in depth.
    steps, sides = 288, 16
    centers = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        centers.append(Vector((1.65 * math.sin(t), .51 * math.cos(t),
                               .42 + 2.05 * math.sin(t) ** 2 + .16 * math.sin(t))))
    # Parallel-transport frames avoid pinches when the path turns toward Y.
    tangents = [(centers[(i + 1) % steps] - centers[(i - 1) % steps]).normalized()
                for i in range(steps)]
    frames = [Vector((0, 1, 0))]
    for i in range(1, steps):
        frames.append(tangents[i - 1].rotation_difference(tangents[i]) @ frames[-1])
    closing = tangents[-1].rotation_difference(tangents[0]) @ frames[-1]
    twist = math.atan2(tangents[0].dot(closing.cross(frames[0])), closing.dot(frames[0]))
    verts = []
    for i, center in enumerate(centers):
        tangent = tangents[i]
        width_axis = Quaternion(tangent, twist * i / steps) @ frames[i]
        normal = tangent.cross(width_axis).normalized()
        for j in range(sides):
            a = 2 * math.pi * j / sides
            # Superellipse gives a flat optical face with gently rounded edges.
            c, s = math.cos(a), math.sin(a)
            w = .37 * math.copysign(abs(c) ** .32, c)
            h = .075 * math.copysign(abs(s) ** .32, s)
            verts.append(tuple(center + width_axis * w + normal * h))
    faces = []
    for i in range(steps):
        for j in range(sides):
            faces.append((i * sides + j, ((i + 1) % steps) * sides + j,
                          ((i + 1) % steps) * sides + (j + 1) % sides,
                          i * sides + (j + 1) % sides))
    ribbon = smooth(mesh('Ribbon / continuous swept crystal', verts,
                         [tuple(reversed(f)) for f in faces], glass))
    sub = ribbon.modifiers.new('Optical surface continuity', 'SUBSURF')
    sub.levels = sub.render_levels = 1
    ribbon['design'] = 'Closed solid ribbon. Mesh can be edited; subdivision remains live.'
    # Small glass foot locates the continuous sculpture on the plinth.
    cube('Crystal foot', (0, -.02, .205), (1.85, 1.2, .15), glass, .065)

    collection('03 | Window and reflection rig')
    dark = material('Reflection flags / charcoal', (.014, .025, .034), roughness=.6)
    flag = cube('Left reflection flag', (-5, 1, 3), (.1, 4, 6), dark, 0)
    flag.visible_camera = False
    flag.visible_shadow = False
    area('Key / tall softbox', (-3.6, -4, 6.5), (0, 0, 1), 950, (1, .94, .83), 4.5, 6)
    area('Rim / blue sky', (4, 1.5, 5), (0, 0, 1.2), 1100, (.68, .86, 1), 3, 5)
    area('Top / narrow crystal highlight', (0, 2.5, 6.5), (0, 0, 1), 850, (1, 1, 1), 4, 1)
    sun_data = bpy.data.lights.new('Morning sun', 'SUN')
    sun_data.energy, sun_data.angle, sun_data.color = 1.6, .085, (1, .92, .78)
    sun = bpy.data.objects.new('Morning sun', sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(25), math.radians(-35), math.radians(-30))
    # Architectural mullions generate genuine long window shadows.
    for i in range(4):
        blocker = cube('Window mullion %02d' % i, (-4.9 + i * .85, -3, 4.5), (.11, .16, 7), porcelain, .01)
        blocker.visible_camera = False
    world((.73, .84, .94), .4)
    collection('04 | Cameras')
    camera('Porcelain / hero', (6.5, -10.8, 5.5), (0, 0, 1.08), lens=58)
    camera('Porcelain / detail', (4.4, -6.5, 3.2), (0, 0, 1.3), lens=65)
    bpy.context.scene.camera = bpy.data.objects['Porcelain / hero']
