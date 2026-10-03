"""Render review close-ups of the exported exterior (run inside Blender with --factory-startup).

    blender -b --factory-startup -P render_exterior.py -- EXTERIOR.gltf OUT_DIR [SHOT,SHOT...]

Shots are given in Blender-model coordinates (nose +X, left +Y, up +Z, metres, on the ground),
the same frame as the model files; glTF import puts the datum-relative model back into it.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
ext, out = args[0], args[1]
only = args[2].split(',') if len(args) > 2 else []
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=ext)

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.view_settings.view_transform = 'AgX'
world = bpy.data.worlds.new('sky')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.68, 0.85, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.2
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 4.0
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(150))
scene.collection.objects.link(sun)
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.9))      # ground (datum is 0.9 m up)

if os.environ.get('RENDER_SHAPE'):        # shape review: one glossy grey paint everywhere, no blades in the way
    grey = bpy.data.materials.new('shape_grey')
    grey.use_nodes = True
    bsdf = grey.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (0.55, 0.55, 0.55, 1)
    bsdf.inputs['Roughness'].default_value = 0.25
    for o in list(bpy.data.objects):
        if o.name.startswith(('Blade_', 'PROP_BLUR', 'Prop_blur', 'Propeller_composite')) or                 o.name.startswith(tuple(filter(None, os.environ.get('RENDER_HIDE', '').split(',')))):
            bpy.data.objects.remove(o, do_unlink=True)
        elif o.type == 'MESH':
            for slot in o.material_slots:
                slot.material = grey

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.resolution_x, scene.render.resolution_y = 1600, 900


def to_scene(p):
    """Blender-model point -> imported scene (datum (1.06, 0, 0.9), glTF nose +Z imported as -Y)."""
    x, y, z = p[0] - 1.06, p[1], p[2] - 0.9
    return Vector((y, -x, z))


shots = {
    'ext_nose': ((4.4, 0.9, 1.45), (3.0, 0.0, 1.05), 36),
    'ext_nose_low': ((4.0, -0.9, 0.55), (2.9, 0.0, 0.95), 36),
    'ext_exhaust': ((2.9, -1.4, 0.35), (2.15, -0.17, 0.62), 30),
    'ext_main_wheel': ((1.9, 2.3, 0.7), (0.75, 0.975, 0.22), 28),
    'ext_nose_wheel': ((3.4, 1.6, 0.6), (2.52, 0.0, 0.25), 28),
    'ext_stripe': ((1.0, 2.6, 1.15), (0.9, 0.5, 1.05), 26),
    'ext_side': ((0.4, 6.5, 1.4), (0.4, 0.0, 1.1), 40),
    'ext_top_quarter': ((4.2, 3.4, 3.6), (0.5, 0.0, 1.5), 34),
    'ext_pitot': ((1.95, 3.55, 0.42), (1.12, 2.9, 0.68), 26),
    'ext_pitot_wide': ((3.2, 5.2, 0.6), (0.9, 2.6, 0.8), 40),
    'ext_wingtip': ((0.85, 5.25, 1.3), (0.47, 4.78, 1.13), 18),
    'ext_wingtip_front': ((1.6, 5.1, 1.2), (0.47, 4.7, 1.13), 22),
    'ext_landing': ((1.95, 4.25, 1.08), (1.28, 3.85, 0.96), 16),
    'ext_cowl_q': ((4.7, 1.7, 1.75), (2.6, 0.0, 1.2), 32),
    'ext_cowl_side': ((2.6, 3.6, 1.2), (2.6, 0.0, 1.2), 30),
    'ext_cowl_photo': ((4.3, -1.0, 1.55), (2.4, 0.15, 1.2), 40),
    'ext_cowl_side_hi': ((2.5, 3.2, 1.75), (2.5, 0.0, 1.2), 30),
    'ext_cowl_build': ((3.35, -1.75, 2.0), (2.45, 0.0, 1.15), 40),
    'ext_cowl_top': ((2.2, -0.6, 2.9), (2.45, 0.0, 1.2), 34),
    'ext_cowl_seam': ((2.75, -1.45, 1.2), (2.55, -0.38, 1.08), 26),
    'ext_cowl_photo2': ((3.75, 2.35, 1.55), (2.55, 0.05, 1.12), 34),
    'ext_cowl_chin': ((3.7, 0.55, 0.7), (2.95, 0.0, 0.98), 30),
    'ext_cowl_front': ((5.5, 0.0, 1.25), (2.6, 0.0, 1.15), 22),
    'ext_photo': ((3.6, -2.7, 1.75), (1.0, -0.2, 1.45), 42),
}
for name, (eye, look, fov) in shots.items():
    if only and name not in only:
        continue
    cam.location = to_scene(eye)
    cam.rotation_euler = (to_scene(look) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.angle = math.radians(fov)
    scene.render.filepath = os.path.join(out, name + '.png')
    bpy.ops.render.render(write_still=True)
    print('rendered', scene.render.filepath)
