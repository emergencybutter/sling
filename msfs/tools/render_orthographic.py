"""Orthographic side / front / top renders of the exported exterior, for overlaying the POH 3-view
(run inside Blender with --factory-startup).

    blender -b --factory-startup -P render_orthographic.py -- EXTERIOR.gltf OUT_DIR

Each view is written with a JSON sidecar giving its scale and centre, so compare_3view.py can place
the drawing on it:  pixel = centre_px + (model axis value - centre) * px_per_m  (see AXES).
Model coordinates: metres, nose +X, left +Y, up +Z, on the ground (the datum is undone on import).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Euler, Vector

ext, out = sys.argv[sys.argv.index('--') + 1:][:2]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=ext)
for o in list(bpy.data.objects):
    if o.name.startswith('PROP_BLUR'):
        bpy.data.objects.remove(o, do_unlink=True)

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new('w')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (1, 1, 1, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 2.5
sun.rotation_euler = (math.radians(45), 0, math.radians(30))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
cam.data.type = 'ORTHO'
scene.collection.objects.link(cam)
scene.camera = cam


def to_scene(p):
    return Vector((p[1], -(p[0] - 1.06), p[2] - 0.9))


# name: (model centre, ortho width m, resolution, camera offset (model), camera euler in scene,
#        image-right model axis and sign, image-down model axis and sign)
W = 2000
VIEWS = {
    # from the left side, nose to the left (as the POH side view)
    'side': ((-0.3, 0.0, 1.2), 8.0, (W, 1200), (0, 30, 0), (math.radians(90), 0, math.radians(90)), ('x', -1), ('z', -1)),
    # from ahead, the left wing on the image's right
    'front': ((0.0, 0.0, 1.2), 10.4, (W, 1000), (30, 0, 0), (math.radians(90), 0, 0), ('y', 1), ('z', -1)),
    # from above, nose down (as the POH plan view)
    'top': ((-0.3, 0.0, 0.0), 10.4, (W, 1700), (0, 0, 30), (0, 0, 0), ('y', 1), ('x', 1)),
}
os.makedirs(out, exist_ok=True)
for name, (c, width, res, off, eul, right, down) in VIEWS.items():
    scene.render.resolution_x, scene.render.resolution_y = res
    cam.data.ortho_scale = width
    cam.location = to_scene((c[0] + off[0], c[1] + off[1], c[2] + off[2]))
    cam.rotation_euler = Euler(eul)
    cam.data.clip_end = 100
    scene.render.filepath = os.path.join(out, f'ortho_{name}.png')
    bpy.ops.render.render(write_still=True)
    meta = {'px_per_m': res[0] / width, 'size': res, 'centre': dict(zip('xyz', c)), 'right': right, 'down': down}
    with open(os.path.join(out, f'ortho_{name}.json'), 'w') as f:
        json.dump(meta, f)
    print('rendered', name)
