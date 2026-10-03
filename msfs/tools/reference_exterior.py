"""Swap the generated exterior for the reference aircraft (reference/sling_meshy_full.glb, an AI-generated textured
Sling TSi), fitted to the POH by fit_reference_aircraft.py (build/reference_fit/sling_fitted_model.glb, model frame).
Run from blender_export.py on the exterior LODs, after the generated exterior is complete: its parts are the template.

- the greenhouse is ours: above the cabin sill, from the windscreen base to behind the rear windows, the reference
  is cut away and our POH-shaped canopy (frames, glass, doors) is kept, its paint charcoal like the reference's (the
  reference's glass and grey paint cannot be told apart, and its windscreen is not see-through)
- inside the cabin below the sill: the reference's own interior (faces that cannot see out) is deleted, the
  interior model draws the cockpit
- ailerons, flaps, elevators, rudder: reference faces next to our part go to a mesh under our hinge pivot, so the
  existing animations move them; our part's own mesh is removed
- propeller: the reference's spinner and blades are deleted, ours (spinner, blades, blur disc) stay
- gear: the reference's own (static, fused) gear stays; our wheels, fairings and legs are removed
- lights: reference faces over our light units are cut away so the lenses show
Our fuselage (but the greenhouse), wings, tips, tail, fillets and inlets are removed; the reference keeps its own
texture set (colour, metal-roughness, normal), renamed SlingTSi_EXT_*.
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import sling_shape as S

O = bpy.data.objects
HERE = os.path.dirname(os.path.abspath(__file__))
FITTED = os.path.join(HERE, '..', 'build', 'reference_fit', 'sling_fitted_model.glb')
SOURCE = os.path.join(HERE, '..', 'reference', 'sling_meshy_full.glb')

CABIN_X = (-0.95, 2.15)        # m: our cabin, where the reference's interior is deleted
INNER_HALF = 0.62              # m: the cabin's half-width
INNER_FLOOR = 0.70             # m: and its floor (the belly is at 0.65)
GREENHOUSE_X = (-0.80, 2.135)  # m: windscreen base to behind the rear windows
SILL_Z = 1.25                  # m: the greenhouse above it is ours (door bottom, S.DOOR_H)
OVERLAP = 0.03                 # m: our greenhouse reaches this far under the reference's skin at the cuts
CHARCOAL = (0.075, 0.077, 0.08)   # linear RGB: the reference's grey paint (sRGB 0.29)
PART_NEAR = 0.04               # m: a face this close to one of our moving parts belongs to it
SURFACES = ['Aileron_L', 'Aileron_R', 'Flap_L', 'Flap_R', 'Elevator_L', 'Elevator_R', 'Rudder']
DOORS = ['Door_L', 'Door_R']
REGION = {                     # where each kind of moving part can be: outboard of the fuselage side, off the fin
    'Aileron': lambda c: abs(c.y) > 0.70,
    'Flap': lambda c: abs(c.y) > 0.66,
    'Elevator': lambda c: abs(c.y) > 0.12,
    'Rudder': lambda c: abs(c.y) < 0.12 and c.z > 1.15,
}
REMOVE = ['Fuselage', 'Wing_L', 'Wing_R', 'Wing_L_tip', 'Wing_R_tip', 'Stabiliser_L', 'Stabiliser_R', 'Fin',
          'Dorsal_fillet', 'Tailcone_cap', 'Antenna', 'Main_gear_leg_L', 'Main_gear_leg_R', 'Nose_gear_leg',
          'Tyre_L', 'Tyre_R', 'Tyre_Nose', 'Hub_L', 'Hub_R', 'Hub_Nose', 'Wheel_fairing_L', 'Wheel_fairing_R',
          'Wheel_fairing_Nose']
REMOVE_PREFIX = ('Cowl_inlet', 'Wheel_pant')
LIGHT_PREFIX = ('LIGHT_', 'Light_lens', 'Light_base', 'Landing_lens', 'Landing_bay', 'Taxi_', 'Pitot')
TEX_NAMES = {'Base Color': 'SlingTSi_EXT_albd', 'Metallic': 'SlingTSi_EXT_comp', 'Normal': 'SlingTSi_EXT_norm'}


def available():
    return os.path.exists(FITTED) and os.path.exists(SOURCE)


def _bvh(objs, min_z=None):
    """One BVH over several objects (world space), optionally only their faces above min_z."""
    verts, polys = [], []
    for o in objs:
        mw = o.matrix_world
        base = len(verts)
        verts += [mw @ v.co for v in o.data.vertices]
        polys += [[base + i for i in p.vertices] for p in o.data.polygons
                  if min_z is None or (mw @ p.center).z > min_z]
    return BVHTree.FromPolygons(verts, polys)


def _generator_radius(X, Z, H):
    """Our generated skin's radius about (0, hm) in the direction of (Z, H) at station X (mm)."""
    s = S.section(X)
    hm = float(s['hm'])
    ag = np.linspace(-math.pi / 2, math.pi / 2, 361)
    Zg, Hg = S._generator_points(s, ag)
    return float(np.interp(math.atan2(H - hm, abs(Z)), np.arctan2(Hg - hm, Zg), np.hypot(Zg, Hg - hm))), hm


def _charcoal():
    m = bpy.data.materials.new('Canopy_paint')
    m.use_nodes = True
    bsdf = m.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*CHARCOAL, 1)
    bsdf.inputs['Roughness'].default_value = 0.45
    m.use_backface_culling = True
    return m


def _cut(bm, x0, x1, z0):
    """Bisect bm (world space) on the planes x = x0, x = x1 and z = z0, so the greenhouse cuts are clean lines."""
    for co, no in (((x0, 0, 0), (1, 0, 0)), ((x1, 0, 0), (1, 0, 0)), ((0, 0, z0), (0, 0, 1))):
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no)


def _greenhouse(paint):
    """Our fuselage's faces above the sill in the greenhouse span (a little beyond, under the reference's skin), as
    their own object, painted charcoal."""
    fus = O['Fuselage']
    fb = bmesh.new()
    fb.from_mesh(fus.data)
    fmw = fus.matrix_world
    fb.transform(fmw)
    x0, x1, z0 = GREENHOUSE_X[0] - OVERLAP, GREENHOUSE_X[1] + OVERLAP, SILL_Z - OVERLAP
    _cut(fb, x0, x1, z0)
    fb.transform(fmw.inverted())

    def inside(v):
        p = fmw @ v.co
        return x0 - 1e-4 < p.x < x1 + 1e-4 and p.z > z0 - 1e-4

    drop = [f for f in fb.faces if not all(inside(v) for v in f.verts)]
    bmesh.ops.delete(fb, geom=drop, context='FACES')
    bmesh.ops.delete(fb, geom=[v for v in fb.verts if not v.link_faces], context='VERTS')
    me = bpy.data.meshes.new('Greenhouse')
    fb.to_mesh(me)
    fb.free()
    me.materials.append(paint)
    for p in me.polygons:
        p.material_index = 0
    gh = bpy.data.objects.new('Greenhouse', me)
    bpy.context.scene.collection.objects.link(gh)
    gh.parent = fus.parent
    gh.matrix_world = fmw
    for k in DOORS:
        if f'{k}_skin' in O:
            O[f'{k}_skin'].data.materials[0] = paint
    print(f'greenhouse: {len(me.polygons)} faces of our canopy kept')


def swap(root, lod_ratio):
    before = set(O)
    bpy.ops.import_scene.gltf(filepath=FITTED)
    new = [o for o in O if o not in before]
    ref = [o for o in new if o.type == 'MESH'][0]
    for o in new:
        if o is not ref:
            bpy.data.objects.remove(o, do_unlink=True)
    ref.name = 'Airframe'
    mat = ref.data.materials[0]
    mat.name = 'SlingTSi_EXT'
    mat.use_backface_culling = True                                    # single-sided: unseen from the cockpit
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE':
            for link in mat.node_tree.links:
                if link.from_node == n:
                    sock = link.to_socket.name
                    if link.to_node.type == 'NORMAL_MAP':
                        sock = 'Normal'
                    elif link.to_node.type == 'SEPARATE_COLOR':
                        sock = 'Metallic'
                    if sock in TEX_NAMES:
                        img = n.image
                        img.name = TEX_NAMES[sock]
                        # PNG files on disk, so the glTF export writes PNG (the source's are JPEG)
                        path = os.path.join(os.path.dirname(FITTED), img.name + '.png')
                        img.filepath_raw = path
                        img.file_format = 'PNG'
                        img.save()
                        img.source = 'FILE'
                        img.filepath = path
                        img.reload()
    mw = ref.matrix_world.copy()

    bm = bmesh.new()
    bm.from_mesh(ref.data)
    bm.transform(mw)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
    _cut(bm, GREENHOUSE_X[0], GREENHOUSE_X[1], SILL_Z)
    bm.faces.ensure_lookup_table()
    uvl = bm.loops.layers.uv.active

    whole = BVHTree.FromBMesh(bm)                                      # the reference as imported, canopy and all
    ours = _bvh([O[n] for n in ('Door_L_glass', 'Door_R_glass', 'Windscreen_and_windows') if n in O],
                min_z=SILL_Z + 0.08)                                   # our glazing, in its open window holes
    dead = set()
    n_in = n_gh = 0
    for f in bm.faces:
        c = f.calc_center_median()
        # 1. the greenhouse is ours
        if GREENHOUSE_X[0] < c.x < GREENHOUSE_X[1] and c.z > SILL_Z:
            dead.add(f)
            n_gh += 1
            continue
        # 3. its spinner and blades (ours turn)
        r = math.hypot(c.y, c.z - S.PROP_AXIS_H / 1000)
        if c.x > 3.0 or (c.x > 2.7 and r > 0.47):
            dead.add(f)
    # 2. the reference's interior (seats, panel, floor, trim): faces inside the cabin that cannot see out - to the
    #    side, diagonally up or up, against the whole reference with its canopy and our glazing (its side windows
    #    are open holes). Its outer skin always can.
    dirs = [Vector((0, 1, 0)), Vector((0, 0.7, 0.7)), Vector((0, 0, 1)), Vector((0.5, 0.6, 0.6)), Vector((-0.5, 0.6, 0.6))]
    for f in bm.faces:
        if f in dead:
            continue
        c = f.calc_center_median()
        if not (CABIN_X[0] < c.x < CABIN_X[1] and abs(c.y) < INNER_HALF and c.z > INNER_FLOOR):
            continue
        side = 1.0 if c.y >= 0 else -1.0
        escapes = False
        for d in dirs:
            dd = Vector((d.x, d.y * side, d.z)).normalized()
            if whole.ray_cast(c + dd * 0.004, dd, 4.0)[0] is None and ours.ray_cast(c + dd * 0.004, dd, 4.0)[0] is None:
                escapes = True
                break
        if not escapes:
            dead.add(f)
            n_in += 1
    print(f'reference: {n_gh} greenhouse and {n_in} interior faces dropped')

    # 4. cut-outs for our light units
    lights = [o for o in O if o.type == 'MESH' and o.name.startswith(LIGHT_PREFIX) and o is not ref]
    if lights:
        lt = _bvh(lights)
        n_l = 0
        for f in bm.faces:
            if f not in dead and lt.find_nearest(f.calc_center_median(), 0.025)[0] is not None:
                dead.add(f)
                n_l += 1
        print(f'reference: {n_l} faces over our light units dropped')

    # 5. moving parts: faces next to our surfaces go to them, under our hinge pivots
    parts = {k: O[f'{k}_mesh'] for k in SURFACES if f'{k}_mesh' in O}
    trees = {k: _bvh([o]) for k, o in parts.items()}
    owner = {}
    for f in bm.faces:
        if f in dead:
            continue
        c = f.calc_center_median()
        best = None
        for k, t in trees.items():
            if (k.endswith('_L') and c.y < -0.05) or (k.endswith('_R') and c.y > 0.05):
                continue
            if not REGION[k.split('_')[0]](c):                  # never the fuselage skin round its root
                continue
            loc = t.find_nearest(c, PART_NEAR)[0]
            if loc is not None:
                d = (loc - c).length
                if best is None or d < best[1]:
                    best = (k, d)
        if best:
            owner[f] = best[0]
    counts = {}
    for k, old in parts.items():
        faces = [f for f, o in owner.items() if o == k]
        counts[k] = len(faces)
        piv = O[k]
        sub = bmesh.new()
        uv2 = sub.loops.layers.uv.new('UVMap')
        vmap = {}
        inv = piv.matrix_world.inverted()
        for f in faces:
            vs = []
            for v in f.verts:
                if v not in vmap:
                    vmap[v] = sub.verts.new(inv @ v.co)
                vs.append(vmap[v])
            try:
                nf = sub.faces.new(vs)
            except ValueError:
                continue
            nf.smooth = f.smooth
            for la, lb in zip(f.loops, nf.loops):
                lb[uv2].uv = la[uvl].uv
        me = bpy.data.meshes.new(f'{k}_ref')
        sub.to_mesh(me)
        sub.free()
        me.materials.append(mat)
        name = old.name
        bpy.data.objects.remove(old, do_unlink=True)
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        o.parent = piv
        o.matrix_parent_inverse.identity()
        dead |= set(faces)
    print('reference moving parts (faces):', counts)

    bmesh.ops.delete(bm, geom=list(dead), context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.transform(mw.inverted())
    bm.to_mesh(ref.data)
    bm.free()
    ref.parent = root
    ref.matrix_parent_inverse = root.matrix_world.inverted()
    ref.matrix_world = mw

    # 6. our greenhouse, then our replaced parts
    _greenhouse(_charcoal())
    gone = [n for n in REMOVE if n in O] + [o.name for o in O if o.name.startswith(REMOVE_PREFIX)]
    for n in gone:
        if n in O:
            bpy.data.objects.remove(O[n], do_unlink=True)

    # 7. its own level of detail: the reference is far denser than the generated parts
    if lod_ratio < 1.0:
        for o in [ref] + [O[f'{k}_mesh'] for k in SURFACES if f'{k}_mesh' in O]:
            m = o.modifiers.new('ref_lod', 'DECIMATE')
            m.ratio = lod_ratio
            m.use_collapse_triangulate = True
            o['ref_decimated'] = True
    print(f'reference exterior: {len(ref.data.polygons)} faces, removed {len(gone)} generated parts, '
          f'LOD ratio {lod_ratio}')
