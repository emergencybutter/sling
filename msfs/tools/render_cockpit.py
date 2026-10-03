"""Render review shots of the exported cockpit (run inside Blender with --factory-startup).

    blender -b --factory-startup -P render_cockpit.py -- EXTERIOR.gltf INTERIOR.gltf OUT_DIR

Imports the glTF files the sim gets, so what you see is what was exported. glTF import maps the
MSFS frame (nose +Z, left +X, up +Y, origin at the datum) to Blender as nose -Y, left +X, up +Z.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ext, inn, out = sys.argv[sys.argv.index('--') + 1:]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for f in (ext, inn):
    bpy.ops.import_scene.gltf(filepath=f)

# Hang the sim's attachment instruments on their attach points, as the sim will (read from the
# VFS projection; skipped if it isn't there).
VFS = os.path.expandvars(r'%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalState\VFSProjection'
                         r'\simattachments\instruments')
ATTACH = {'Attach_Point_G3X': 'asobo_mpa_g3x_touch/model/mfd_grm3x_lod00.gltf',
          'Attach_Point_AP': 'asobo_autopilot_g307_noyawdamper/model/grm307_noyawdamper_lod00.gltf',
          'Attach_Point_Radio': 'asobo_radio_com_g225/model/comnav_g225_lod00.gltf'}
for node, rel in ATTACH.items():
    point = bpy.data.objects.get(node)
    path = os.path.join(VFS, rel)
    if not point or not os.path.exists(path):
        print('attachment skipped', node)
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    for o in set(bpy.data.objects) - before:
        if o.parent is None:
            o.parent = point
            o.matrix_parent_inverse.identity()
    print('attached', node)

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.view_settings.view_transform = 'AgX'
world = bpy.data.worlds.new('sky')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.68, 0.85, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.4
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 3.5
sun.rotation_euler = (math.radians(40), math.radians(15), math.radians(200))
scene.collection.objects.link(sun)

# stand-in for the sim's screen render targets
for m in bpy.data.materials:
    if m.name.startswith('$'):
        b = m.node_tree.nodes.get('Principled BSDF')
        if b:
            b.inputs['Emission Color'].default_value = (0.05, 0.15, 0.35, 1)
            b.inputs['Emission Strength'].default_value = 1.0

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.resolution_x, scene.render.resolution_y = 1600, 900


def to_scene(p):
    """Blender-model point (nose +X, left +Y, up +Z; datum (1.06, 0, 0.9)) -> imported scene."""
    x, y, z = p[0] - 1.06, p[1], p[2] - 0.9
    return Vector((y, -x, z))


shots = {
    'panel_straight': ((0.35, 0.0, 1.30), (1.3, 0.0, 1.30), 50),
    'pilot_forward': ((0.53, 0.31, 1.58), (1.6, 0.18, 1.32), 60),
    'pilot_console': ((0.53, 0.31, 1.58), (1.0, -0.02, 0.92), 45),
    'rear_bench': ((0.75, 0.0, 1.55), (-0.45, 0.0, 1.05), 60),
    'rear_seat': ((-0.35, -0.2, 1.5), (1.3, 0.1, 1.15), 55),
    'door_handle_left': ((0.9, 1.3, 1.35), (0.78, 0.59, 1.30), 25),
    'closeup_switches': ((1.0, 0.24, 1.26), (1.28, 0.24, 1.18), 22),
    'closeup_prop': ((1.05, 0.06, 1.36), (1.32, 0.082, 1.408), 18),
    'closeup_chute': ((1.05, 0.10, 1.25), (1.271, 0.0, 1.165), 22),
    'chute_wide': ((0.85, -0.12, 1.28), (1.2, 0.08, 1.04), 40),
    'closeup_compass': ((1.15, 0.06, 1.58), (1.43, 0.0, 1.475), 20),
    'seats_photo': ((0.98, 0.52, 1.5), (0.5, -0.05, 1.02), 60),
    'seat_close': ((1.05, 0.3, 1.2), (0.45, 0.31, 1.05), 45),
    'closeup_prop_panel': ((0.9, 0.09, 1.2), (1.28, 0.09, 1.17), 30),
    'closeup_left_end': ((1.0, 0.42, 1.33), (1.29, 0.43, 1.28), 20),
    'closeup_placards': ((1.0, -0.26, 1.31), (1.3, -0.26, 1.27), 24),
    'outside_rear_quarter': ((-2.2, 2.4, 1.9), (-0.4, 0.0, 1.2), 40),
    'console_top': ((0.50, 0.12, 1.40), (0.84, 0.0, 0.93), 34),
    'console_front': ((0.72, 0.22, 1.24), (1.12, 0.0, 1.02), 30),
    'console_throttle': ((0.78, 0.20, 1.10), (0.95, 0.03, 0.98), 26),
    'console_rear': ((-0.12, 0.12, 1.22), (0.10, 0.0, 0.79), 34),
}
only = [n for n in os.environ.get('RENDER_SHOTS', '').split(',') if n]       # e.g. RENDER_SHOTS=console_top,console_front
for name, (eye, look, fov) in shots.items():
    if only and name not in only:
        continue
    cam.location = to_scene(eye)
    cam.rotation_euler = (to_scene(look) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.angle = math.radians(fov + 20)
    scene.render.filepath = os.path.join(out, name + '.png')
    bpy.ops.render.render(write_still=True)
    print('rendered', scene.render.filepath)
