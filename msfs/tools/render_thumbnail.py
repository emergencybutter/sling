"""Render the aircraft-selection thumbnails (run inside Blender 5.x).

    blender -b ../model/sling-tsi.blend -P render_thumbnail.py -- OUT_DIR
"""
import math
import os
import sys

import bpy
from mathutils import Vector

out = sys.argv[sys.argv.index('--') + 1]
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.film_transparent = False
scene.view_settings.view_transform = 'AgX'

world = bpy.data.worlds.new('thumb') if not scene.world else scene.world
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get('Background')
bg.inputs['Color'].default_value = (0.62, 0.70, 0.80, 1)
bg.inputs['Strength'].default_value = 1.0

sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 4.0
sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
scene.collection.objects.link(sun)

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
scene.collection.objects.link(cam)
scene.camera = cam
target = Vector((0.0, 0.0, 1.1))
cam.location = Vector((9.5, -13.5, 3.6))
cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()

for name, (w, h) in (('thumbnail.jpg', (1618, 582)), ('thumbnail_small.jpg', (600, 216)),
                     ('Thumbnail.jpg', (412, 170))):
    scene.render.resolution_x, scene.render.resolution_y = w, h
    # frame the aircraft by width; every thumbnail is at least 2.4:1, so the height fits too
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.lens = 52
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 90
    scene.render.filepath = os.path.join(out, name)
    bpy.ops.render.render(write_still=True)
    print('rendered', scene.render.filepath)
