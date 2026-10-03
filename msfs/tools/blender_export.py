"""Export one LOD of the Sling TSi model as MSFS-ready glTF (run inside Blender 5.x).

    blender -b ../model/sling-tsi-high.blend -P blender_export.py -- OUT.gltf DECIMATE META.json [PART]

PART is exterior (default: everything but the cabin), interior (the cabin only) or all.

Restructures the scene for the sim (wheel spin nodes, prop blur disc, screen materials,
light meshes), moves the origin to the reference datum, turns the aircraft so the nose
points along glTF +Z with +X to the left (the MSFS convention), and writes the hinge
axes of every moving part to META.json so postprocess_gltf.py can add the animations.
"""
import bpy
import bmesh
import json
import math
import os
import sys
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index('--') + 1:]
OUT, DECIMATE, META = argv[0], float(argv[1]), argv[2]
PART = argv[3] if len(argv) > 3 else 'exterior'
CABIN = {'Cabin_floor', 'Instrument_panel', 'Display_L', 'Display_R', 'Control_stick_L', 'Control_stick_R',
         'Seat_front_L_back', 'Seat_front_L_cushion', 'Seat_front_R_back', 'Seat_front_R_cushion',
         'Seat_rear_L_back', 'Seat_rear_L_cushion', 'Seat_rear_R_back', 'Seat_rear_R_cushion'}

# Reference datum in Blender coordinates (m): root quarter chord, near the CG height.
# Every position in the .cfg files is measured from this point.
DATUM = Vector((1.06, 0.0, 0.9))

O = bpy.data.objects


def world_verts(o):
    return [o.matrix_world @ v.co for v in o.data.vertices]


def refresh():
    # matrix_world is only recomputed on a depsgraph update
    bpy.context.view_layer.update()


def reparent(child, parent):
    refresh()
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = mw
    refresh()


def new_empty(name, parent, world_loc):
    refresh()
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.parent = parent
    e.matrix_parent_inverse = parent.matrix_world.inverted()
    e.location = world_loc
    e.rotation_mode = 'QUATERNION'
    refresh()
    return e


# ---- hinge axes, measured before anything moves ------------------------------------
def hinge_axis(pivot, mesh, span_axis):
    """Unit vector along the hinge from the pivot to the far end of the surface."""
    p0 = pivot.matrix_world.translation
    vs = world_verts(O[mesh])
    far = max(abs(v[span_axis]) for v in vs)
    station = [v for v in vs if abs(abs(v[span_axis]) - far) < 1e-4]
    front = max(v.x for v in station)
    edge = [v for v in station if abs(v.x - front) < 2e-3]
    p1 = sum(edge, Vector()) / len(edge)
    return (p1 - p0).normalized()


def door_axis(pivot, mesh):
    p0 = pivot.matrix_world.translation
    vs = world_verts(O[mesh])
    rear = min(v.x for v in vs)
    edge = [v for v in vs if abs(v.x - rear) < 2e-3]
    p1 = max(edge, key=lambda v: v.z)          # hinge row runs beside the roof spine
    return (p1 - p0).normalized()


axes = {
    'Aileron_L': hinge_axis(O['Aileron_L'], 'Aileron_L_mesh', 1),
    'Aileron_R': hinge_axis(O['Aileron_R'], 'Aileron_R_mesh', 1),
    'Flap_L': hinge_axis(O['Flap_L'], 'Flap_L_mesh', 1),
    'Flap_R': hinge_axis(O['Flap_R'], 'Flap_R_mesh', 1),
    'Elevator_L': hinge_axis(O['Elevator_L'], 'Elevator_L_mesh', 1),
    'Elevator_R': hinge_axis(O['Elevator_R'], 'Elevator_R_mesh', 1),
    'Rudder': hinge_axis(O['Rudder'], 'Rudder_mesh', 2),
    'Door_L': door_axis(O['Door_L'], 'Door_L_skin'),
    'Door_R': door_axis(O['Door_R'], 'Door_R_skin'),
}
# Point every lateral hinge to the left (+Y) and the rudder hinge up, so that a positive
# right-hand rotation means: trailing edge up for wing and tail surfaces, trailing edge
# right for the rudder. Door hinges point forward (+X).
for k, a in axes.items():
    if k == 'Rudder':
        if a.z < 0: axes[k] = -a
    elif k.startswith('Door'):
        if a.x < 0: axes[k] = -a
    elif a.y < 0:
        axes[k] = -a
for k, a in axes.items():
    print(f'hinge {k}: {tuple(round(c, 4) for c in a)}')

# ---- tidy names -------------------------------------------------------------------
side_of = {'Main_wheel_L': 'L', 'Main_wheel_R': 'R', 'Nose_wheel': 'Nose'}
for o in list(O):
    base = o.name.split('.')[0]
    if base in ('Tyre', 'Hub', 'Wheel_fairing'):
        o.name = f'{base}_{side_of[o.parent.name]}'
for o in [o for o in O if o.name.startswith('Cowl_inlet')]:
    c = sum(world_verts(o), Vector()) / len(o.data.vertices)
    o.name = 'Cowl_inlet_lower' if abs(c.y) < 0.05 else ('Cowl_inlet_L' if c.y > 0 else 'Cowl_inlet_R')
O['Nose_wheel'].name = 'Nose_steer'

# ---- wheel spin nodes: tyre and hub turn, the fairing does not -------------------------
for wheel, s in (('Main_wheel_L', 'L'), ('Main_wheel_R', 'R'), ('Nose_steer', 'Nose')):
    w = O[wheel]
    spin = new_empty(f'Tire_{s}_spin', w, w.matrix_world.translation)
    for n in (f'Tyre_{s}', f'Hub_{s}'):
        reparent(O[n], spin)

# ---- propeller: blades under PROP_STILL, blur disc under PROP_BLUR -------------------------
prop = O['Propeller']
still = new_empty('PROP_STILL', prop, prop.matrix_world.translation)
for n in ('Blade_1', 'Blade_2', 'Blade_3'):
    reparent(O[n], still)
blade_x = [v.x for n in ('Blade_1',) for v in world_verts(O[n])]
tip_r = max((v - prop.matrix_world.translation).length for v in world_verts(O['Blade_1']))
disc_x = (min(blade_x) + max(blade_x)) / 2

blur_mat = bpy.data.materials.new('Prop_blur')
blur_mat.use_nodes = True
bsdf = blur_mat.node_tree.nodes['Principled BSDF']
bsdf.inputs['Base Color'].default_value = (0.02, 0.02, 0.025, 1)
bsdf.inputs['Alpha'].default_value = 0.22
bsdf.inputs['Roughness'].default_value = 0.6
blur_mat.use_backface_culling = False

me = bpy.data.meshes.new('PROP_BLUR')
bm = bmesh.new()
bmesh.ops.create_circle(bm, cap_ends=True, cap_tris=True, segments=64, radius=tip_r)
bm.to_mesh(me)
bm.free()
# circle is made in the XY plane; turn it into the propeller plane (YZ) at the blade station
me.transform(Matrix.Rotation(math.radians(90), 4, 'Y'))
me.materials.append(blur_mat)
uv = me.uv_layers.new(name='UVMap')
for loop in me.loops:
    co = me.vertices[loop.vertex_index].co
    uv.data[loop.index].uv = (0.5 + co.y / (2 * tip_r), 0.5 + co.z / (2 * tip_r))
blur = bpy.data.objects.new('PROP_BLUR', me)
bpy.context.scene.collection.objects.link(blur)
blur.parent = prop
blur.matrix_parent_inverse = prop.matrix_world.inverted()
blur.location = (disc_x, prop.matrix_world.translation.y, prop.matrix_world.translation.z)
print(f'prop disc radius {tip_r:.3f} m at x {disc_x:.3f}')

# ---- wingtip light units (exterior.py), then the light meshes named for EmMesh ---------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exterior  # noqa: E402
exterior.wing_lights(O['Sling_4_TSi'])
exterior.landing_lights(O['Sling_4_TSi'])

# ---- light meshes: named for EmMesh, emissive instead of unlit ----------------------------
def light_mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Emission Color'].default_value = (*rgb, 1)
    b.inputs['Emission Strength'].default_value = 1.0
    b.inputs['Roughness'].default_value = 0.3
    return m


for old, new, rgb in (('Nav_light_L', 'LIGHT_Nav_Red', (1.0, 0.03, 0.03)),
                      ('Nav_light_R', 'LIGHT_Nav_Green', (0.03, 1.0, 0.18)),
                      ('Strobe_L', 'LIGHT_Strobe_L', (1.0, 1.0, 1.0)),
                      ('Strobe_R', 'LIGHT_Strobe_R', (1.0, 1.0, 1.0)),
                      ('Nav_light_WL', 'LIGHT_Nav_White_L', (1.0, 1.0, 0.95)),
                      ('Nav_light_WR', 'LIGHT_Nav_White_R', (1.0, 1.0, 0.95)),
                      ('Landing_light_L', 'LIGHT_Landing_L', (1.0, 0.98, 0.92)),
                      ('Landing_light_R', 'LIGHT_Landing_R', (1.0, 0.98, 0.92)),
                      ('Taxi_light_L', 'LIGHT_Taxi_L', (1.0, 0.98, 0.92)),
                      ('Taxi_light_R', 'LIGHT_Taxi_R', (1.0, 0.98, 0.92))):
    o = O[old]
    o.name = new
    o.data.materials.clear()
    o.data.materials.append(light_mat(f'{new}_mat', rgb))

# ---- G3X Touch screens: $-named materials the panel renders into, 0..1 UVs ------------------
for obj, tex in (('Display_L', '$AS3X_Touch_1'), ('Display_R', '$AS3X_Touch_2')):
    o = O[obj]
    m = bpy.data.materials.new(tex)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (0, 0, 0, 1)
    b.inputs['Roughness'].default_value = 0.15
    o.data.materials.clear()
    o.data.materials.append(m)
    vs = [v.co for v in o.data.vertices]
    y0, y1 = min(v.y for v in vs), max(v.y for v in vs)
    z0, z1 = min(v.z for v in vs), max(v.z for v in vs)
    if not o.data.uv_layers:
        o.data.uv_layers.new(name='UVMap')
    uvl = o.data.uv_layers.active
    for loop in o.data.loops:
        co = o.data.vertices[loop.vertex_index].co
        # the pilot faces +X, so the screen's left edge is its +Y side
        uvl.data[loop.index].uv = ((y1 - co.y) / (y1 - y0), (co.z - z0) / (z1 - z0))

# ---- livery: anti-aliased repaint with arc-length UVs (exterior.py, make_livery.py) ------------
# Done for every part: the interior's cabin lining copies the fuselage UVs and the livery alpha.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exterior  # noqa: E402
exterior.cowl()
exterior.livery(os.environ.get('SLING_LIVERY_DIR') or
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'livery'))

# ---- textures: stable file names -------------------------------------------------------
tex_names = {}
for img in bpy.data.images:
    users = [m.name for m in bpy.data.materials if m.node_tree and any(
        n.type == 'TEX_IMAGE' and n.image == img for n in m.node_tree.nodes)]
    if 'Paint_livery' in users:
        img.name = 'SlingTSi_LIVERY_albd'
    elif 'Glass' in users:
        img.name = 'SlingTSi_GLASS_albd'
    tex_names[img.name] = users
print('textures', tex_names)

# ---- wings stop at the fuselage skin ---------------------------------------------------------
# The wing meshes run through the fuselage to the centreline, which shows up inside the cabin.
if PART != 'interior':
    from mathutils.bvhtree import BVHTree
    fus = O['Fuselage']
    fus_me = fus.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    hull = BVHTree.FromPolygons([fus.matrix_world @ v.co for v in fus_me.vertices],
                                [p.vertices[:] for p in fus_me.polygons])
    for name in ('Wing_L', 'Wing_R'):
        w = O[name]
        bm = bmesh.new()
        bm.from_mesh(w.data)
        inside = []
        for f in bm.faces:
            c = w.matrix_world @ f.calc_center_median()
            side = 1 if c.y >= 0 else -1
            hit = hull.ray_cast(Vector((c.x, 0, c.z)), Vector((0, side, 0)), 2.0)[0]
            if hit and abs(c.y) < abs(hit.y) - 0.002:
                inside.append(f)
        bmesh.ops.delete(bm, geom=inside, context='FACES')
        bm.to_mesh(w.data)
        bm.free()
        print(f'{name}: trimmed {len(inside)} faces inside the fuselage')

    # ---- outside door handles (POH 7.7: latch levers inside and outside, bottom centre of each door)
    # Parented to the door hinge so they swing with it; the lever sits on its own pivot and is the
    # clickable handle in SlingTSi.xml (interactive points 0 = left, 1 = right).
    dg = bpy.context.evaluated_depsgraph_get()

    def handle_box(name, parent, center, size, mat_name):
        me = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
        bm.to_mesh(me)
        bm.free()
        me.materials.append(bpy.data.materials[mat_name])
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        bpy.context.view_layer.update()
        o.parent = parent
        o.matrix_parent_inverse = parent.matrix_world.inverted()
        o.location = center
        bpy.context.view_layer.update()
        bev = o.modifiers.new('bevel', 'BEVEL')
        bev.width, bev.segments = min(size) * 0.3, 2
        return o

    for side, s in (('L', 1), ('R', -1)):
        skin = O[f'Door_{side}_skin']
        sme = skin.evaluated_get(dg).to_mesh()
        tree = BVHTree.FromPolygons([skin.matrix_world @ v.co for v in sme.vertices], [p.vertices[:] for p in sme.polygons])
        skin.evaluated_get(dg).to_mesh_clear()
        hit = tree.ray_cast(Vector((0.78, 0, 1.30)), Vector((0, s, 0)), 2.0)[0]
        if hit is None:
            raise RuntimeError(f'outside handle: no door skin found on the {side} side')
        out = Vector((0, s, 0))
        door = O[f'Door_{side}']
        handle_box(f'Door_{side}_ext_handle_plate', door, hit + out * 0.002, (0.12, 0.004, 0.035), 'Trim_black')
        piv = new_empty(f'Door_{side}_ext_handle', door, hit + out * 0.009 + Vector((-0.05, 0, 0)))
        handle_box(f'Door_{side}_ext_handle_lever', piv, hit + out * 0.009, (0.10, 0.010, 0.016), 'Metal')
        axes[f'Door_{side}_ext_handle'] = Vector((0, 1, 0))
        print(f'outside handle {side} on the door skin at {tuple(round(c, 3) for c in hit)}')

    # ---- cowling intakes, exhaust and wheel fairings (exterior.py) ----------------------------
    exterior.spinner()
    if os.path.exists(exterior.REFERENCE_SPEC):                # the reference cowl (reference/cowl.json), its own inlets
        exterior.graft_nose()
        if exterior._spec().get('inlets'):                     # a shell's inlets, cut where cowl.json puts them
            exterior.intakes(O['Sling_4_TSi'], inlets=[tuple(i) for i in exterior._spec()['inlets']])
        elif exterior._spec().get('keep_ahead_x') is not None:  # our own nose: all our inlets
            exterior.intakes(O['Sling_4_TSi'])
        elif exterior._spec().get('keep_below_h') is not None:  # our own lower cowl: its chin scoop
            exterior.intakes(O['Sling_4_TSi'], only=('Cowl_inlet_lower',))
    else:
        exterior.intakes(O['Sling_4_TSi'])
    exterior.exhaust(O['Sling_4_TSi'])
    exterior.wheel_pants()
    exterior.pitot(O['Sling_4_TSi'])

    # ---- the reference aircraft's exterior in place of the generated one (reference_exterior.py) ----------------
    import reference_exterior  # noqa: E402
    if reference_exterior.available() and not os.environ.get('SLING_GENERATED_EXTERIOR'):
        import re
        m = re.search(r'LOD(\d+)', os.path.basename(OUT))
        lod = int(m.group(1)) if m else 0
        reference_exterior.swap(O['Sling_4_TSi'], {0: 0.6, 1: 0.3, 2: 0.12, 3: 0.05}.get(lod, 0.05))

# ---- interior: the full cockpit replaces the placeholder cabin ----------------------------
if PART == 'interior':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import interior
    int_axes, int_names = interior.build(O['Sling_4_TSi'], os.path.dirname(os.path.abspath(OUT)))
    for k, a in int_axes.items():
        axes[k] = axes[k.replace('_int', '')] if a is None else a
    print(f'interior: {len(int_names)} objects')

# ---- lower LODs: collapse-decimate the dense meshes -------------------------------------
if DECIMATE < 1.0:
    for o in O:
        if o.type == 'MESH' and len(o.data.polygons) > 300 and not o.name.startswith(('LIGHT_', 'Display_', 'PROP_BLUR'))                 and not o.get('ref_decimated'):
            mod = o.modifiers.new('lod', 'DECIMATE')
            mod.ratio = DECIMATE
            mod.use_collapse_triangulate = True

# ---- datum and MSFS axes -----------------------------------------------------------------
# Blender: nose +X, left +Y, up +Z. The glTF exporter maps (x, y, z) -> (x, z, -y), so turning
# the root -90 deg about Z gives glTF nose +Z, left +X, up +Y.
root = O['Sling_4_TSi']
root.rotation_mode = 'QUATERNION'
rot = Matrix.Rotation(math.radians(-90), 4, 'Z')
root.matrix_world = Matrix.Translation(-(rot @ DATUM)) @ rot

# ---- metadata for the animation pass ---------------------------------------------------------
def to_gltf(v):
    return [v.x, v.z, -v.y]


meta = {'datum_blender': list(DATUM), 'axes': {k: to_gltf(a) for k, a in axes.items()}}
meta['axes'].update({
    'Propeller': to_gltf(Vector((1, 0, 0))),
    'Nose_steer': to_gltf(Vector((0, 0, 1))),
    'Tire_L_spin': to_gltf(Vector((0, 1, 0))),
    'Tire_R_spin': to_gltf(Vector((0, 1, 0))),
    'Tire_Nose_spin': to_gltf(Vector((0, 1, 0))),
})
with open(META, 'w') as f:
    json.dump(meta, f, indent=1)

# ---- exterior / interior split -----------------------------------------------------------
# In cockpit view the sim draws the interior model (plus the exterior, see model.cfg), so the
# cabin lives in its own model and is left out of the exterior to avoid drawing it twice.
if PART != 'all':
    for o in list(O):
        if o is root:
            continue
        keep = bool(o.get('interior')) if PART == 'interior' else o.name not in CABIN
        if not keep:
            bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.export_scene.gltf(
    filepath=OUT,
    export_format='GLTF_SEPARATE',
    export_yup=True,
    export_apply=True,
    export_animations=False,
    export_cameras=False,
    export_lights=False,
    export_extras=False,
    export_tangents=True,
    export_image_format='AUTO',
)
tris = sum(sum(len(p.vertices) - 2 for p in o.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.polygons)
           for o in O if o.type == 'MESH')
print(f'exported {OUT}: ~{tris} triangles')
