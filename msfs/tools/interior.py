"""Procedural cockpit and cabin for the Sling TSi, fitted to the fuselage (runs inside Blender).

blender_export.py calls build() for the interior model. Everything is placed in Blender world
coordinates (m): nose +X, left +Y, up +Z, before the root is turned to MSFS axes. Parts fit the
hull by ray-casting the fuselage and door skins, so they follow the model if it changes.

The layout comes from the POH (DC-POH-001-X-F-3.5):
- 7.10 "Instruments and Avionics" panel diagram. Its outline was traced (PANEL_TOP_PX /
  PANEL_BOT_PX) and every item is placed from its pixel position with panel_px(). The panel
  spans the cabin width at 0.803 mm per diagram pixel, which makes the GDU 460 0.277 m wide
  (the real unit is about 0.285 m).
- 7.9 "Cockpit Layout" plan view: seats at +-0.31 m, a 0.19 m centre console carrying the
  throttle, brake lever, park brake valve and headset jacks, the fuel selector at the front of the
  console, a full-width rear bench, rudder pedals just ahead of the firewall.
- 7.2.1 stick grip (round head: PTT, trim, A/P disconnect), 7.3.2 Airmaster prop controller,
  7.2.10 four-position rotary flap knob, 7.7 door latch levers at the bottom centre of each door.

The G3X, GMC 307 and com radio are the sim's SimAttachment instruments on attach points
(Attach_Point_G3X / _AP / _Radio); the G5 screen runs the built-in AS5 gauge.

Every object it makes has the custom property interior=1. Moving parts sit under their own pivot
empties; build() returns their hinge axes for the animation pass.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

FLOOR_Z = 0.72                  # cabin floor (the belly skin is at 0.648)
FIREWALL_X = 1.95
BULKHEAD_X = -1.15              # aft wall of the baggage compartment
PANEL_BOTTOM_X, PANEL_TILT = 1.26, 0.20     # panel face x at z = PANEL_Z0, dx/dz lean (about 11 deg)
PANEL_Z0 = 1.11
SEAT_Y = 0.31                   # seat centre lines (POH 7.9), +Y is the pilot (left) side
CONSOLE_W = 0.095               # console half-width
LINING_INSET = 0.012            # lining sits this far inside the skin

import os
import panel_layout as layout                       # positions shared with the texture and behaviours
from panel_layout import PANEL_PX, PANEL_Z_TOP, PX, px_yz   # noqa: F401

O = bpy.data.objects
_root = None
_made = []


# ================================ helpers ================================
def refresh():
    bpy.context.view_layer.update()


def tag(o, parent=None):
    bpy.context.scene.collection.objects.link(o)
    o['interior'] = 1
    o.parent = parent or _root
    _made.append(o)
    return o


def empty(name, loc, parent=None):
    e = tag(bpy.data.objects.new(name, None), parent)
    e.rotation_mode = 'QUATERNION'
    refresh()
    e.matrix_world = Matrix.Translation(Vector(loc))
    refresh()
    return e


def mesh_object(name, bm, mat, parent=None, smooth=False, world=Matrix()):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    me.materials.append(mat)
    o = tag(bpy.data.objects.new(name, me), parent)
    refresh()
    o.matrix_world = world
    refresh()
    return o


def material(name, rgb, rough, metal=0.0, emission=None, image=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if emission:
        b.inputs['Emission Color'].default_value = (*emission, 1)
        b.inputs['Emission Strength'].default_value = 1.0
    if image:
        t = m.node_tree.nodes.new('ShaderNodeTexImage')
        t.image = image
        m.node_tree.links.new(t.outputs['Color'], b.inputs['Base Color'])
    return m


def add_bevel(o, width, segments=2):
    if width <= 0:
        return
    mod = o.modifiers.new('bevel', 'BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    mod.harden_normals = True
    for p in o.data.polygons:
        p.use_smooth = True


def _euler(rot):
    return Euler([math.radians(a) for a in rot], 'XYZ')


def box(name, center, size, mat, rot=(0, 0, 0), bevel=0.003, seg=2, subsurf=0, parent=None):
    """Box of size (dx, dy, dz), turned by rot (deg, XYZ) about its centre."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    world = Matrix.Translation(Vector(center)) @ _euler(rot).to_matrix().to_4x4()
    o = mesh_object(name, bm, mat, parent, world=world)
    add_bevel(o, bevel, seg)
    if subsurf:
        s = o.modifiers.new('subsurf', 'SUBSURF')
        s.levels = s.render_levels = subsurf
        for p in o.data.polygons:
            p.use_smooth = True
    return o


def cylinder(name, p0, p1, r0, mat, r1=None, segs=20, bevel=0.0, parent=None):
    """Cylinder (or cone, with r1) from p0 to p1."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                          radius1=r0, radius2=r0 if r1 is None else r1, depth=axis.length)
    rot = Vector((0, 0, 1)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    o = mesh_object(name, bm, mat, parent, smooth=True, world=Matrix.Translation((p0 + p1) / 2) @ rot)
    add_bevel(o, bevel, 2)
    return o


def prism(name, profile_xz, y0, y1, mat, bevel=0.004, parent=None):
    """Extrude a side profile (list of (x, z)) between y0 and y1."""
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new((x, y1, z)) for x, z in profile_xz])
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    for v in [e for e in ext['geom'] if isinstance(e, bmesh.types.BMVert)]:
        v.co.y = y0
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = mesh_object(name, bm, mat, parent)
    add_bevel(o, bevel, 2)
    return o


def slab_from_outline(name, outline_yz, x_of_z, thickness, mat, bevel=0.0, uv_scale=None):
    """Plate whose rear face is the (y, z) outline at x = x_of_z(z), `thickness` deep in +X."""
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new((x_of_z(z), y, z)) for y, z in outline_yz])
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    for v in [e for e in ext['geom'] if isinstance(e, bmesh.types.BMVert)]:
        v.co.x += thickness
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    if uv_scale:
        uv = bm.loops.layers.uv.new('UVMap')
        for f in bm.faces:
            for loop in f.loops:
                loop[uv].uv = uv_scale(loop.vert.co.y, loop.vert.co.z)
    o = mesh_object(name, bm, mat)
    add_bevel(o, bevel, 2)
    return o


# ================================ hull and panel geometry ================================
_hull = None


def build_hull():
    global _hull
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for n in ('Fuselage', 'Door_L_skin', 'Door_R_skin'):
        o = O[n]
        me = o.evaluated_get(dg).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons]
        o.evaluated_get(dg).to_mesh_clear()
    _hull = BVHTree.FromPolygons(verts, polys)


def half_width(x, z, margin=0.01):
    hit = _hull.ray_cast(Vector((x, 0, z)), Vector((0, 1, 0)), 2.0)[0]
    return (hit.y if hit else 0.3) - margin


def roof(x, y):
    hit = _hull.ray_cast(Vector((x, y, 1.2)), Vector((0, 0, 1)), 2.0)[0]
    return hit.z if hit else None


def panel_x(z):
    return PANEL_BOTTOM_X + (z - PANEL_Z0) * PANEL_TILT


TILT = math.atan(PANEL_TILT)
PANEL_N = Vector((-math.cos(TILT), 0, math.sin(TILT)))       # panel face normal, toward the cabin
PANEL_ROT = (0, math.degrees(TILT), 0)                        # top leans forward


def on_panel(y, z, proud=0.0):
    """Point on the panel face, `proud` metres toward the pilot."""
    return Vector((panel_x(z), y, z)) + PANEL_N * proud


def at(xp, yp, proud=0.0):
    return on_panel(*px_yz(xp, yp), proud)


def panel_outline():
    """Outer outline of the panel in (y, z), counter-clockwise, clipped to the hull. The traced
    diagram samples are rounded off first (panel_layout.smooth_outline_px), then kept inside the
    fuselage."""
    out = []
    for y, z in (px_yz(x, t) for x, t in layout.smooth_outline_px()):
        lim = half_width(panel_x(z) + 0.01, z, 0.014)
        out.append((max(-lim, min(lim, y)), z))
    return out


def inset(loop, d):
    """Offset a counter-clockwise (y, z) loop inward by d."""
    n = len(loop)
    res = []
    for i in range(n):
        p0, p1, p2 = Vector(loop[i - 1]), Vector(loop[i]), Vector(loop[(i + 1) % n])
        e0, e1 = (p1 - p0).normalized(), (p2 - p1).normalized()
        n0, n1 = Vector((-e0.y, e0.x)), Vector((-e1.y, e1.x))
        m = (n0 + n1)
        m = m.normalized() if m.length > 1e-6 else n1
        res.append(tuple(p1 + m * d))
    return res


def panel_top_z(y, outline):
    """Height of the panel's top edge at y: the highest crossing of the outline at that y."""
    best = None
    n = len(outline)
    for i in range(n):
        (y0, z0), (y1, z1) = outline[i], outline[(i + 1) % n]
        if min(y0, y1) <= y <= max(y0, y1) and y0 != y1:
            z = z0 + (z1 - z0) * (y - y0) / (y1 - y0)
            best = z if best is None else max(best, z)
    return best if best is not None else max(z for _, z in outline)


# ================================ textures ================================
def panel_texture():
    """The painted panel face (carbon, legends, placards) from make_panel_texture.py."""
    path = os.environ.get('SLING_PANEL_TEXTURE') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'panel', 'SlingTSi_PANEL_albd.png')
    if not os.path.exists(path):
        raise RuntimeError(f'panel texture missing: run make_panel_texture.py first ({path})')
    img = bpy.data.images.load(os.path.abspath(path))
    img.name = 'SlingTSi_PANEL_albd'
    return img


def console_texture():
    """The printed console atlas (legends, placards) from make_console_texture.py."""
    path = os.environ.get('SLING_CONSOLE_TEXTURE') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'panel', 'SlingTSi_CONSOLE_albd.png')
    if not os.path.exists(path):
        raise RuntimeError(f'console texture missing: run make_console_texture.py first ({path})')
    img = bpy.data.images.load(os.path.abspath(path))
    img.name = 'SlingTSi_CONSOLE_albd'
    return img


def lining(livery_img, out_dir):
    """Fabric shell inside the fuselage and doors, windows cut by the livery's alpha."""
    w, h = livery_img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    livery_img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    px[:, 0:3] = (0.30, 0.30, 0.31)          # stored (sRGB) grey
    img = bpy.data.images.new('SlingTSi_LINING_albd', w, h, alpha=True)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = f'{out_dir}/SlingTSi_LINING_albd.png'
    img.file_format = 'PNG'
    img.save()

    m = bpy.data.materials.new('Lining')
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = img
    nt.links.new(t.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(t.outputs['Alpha'], b.inputs['Alpha'])
    b.inputs['Roughness'].default_value = 0.9
    m.use_backface_culling = True

    def shell(src, name, keep):
        me = src.data.copy()
        me.transform(src.matrix_world)
        bm = bmesh.new()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(f.calc_center_median())], context='FACES')
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        for v in bm.verts:
            c = Vector((v.co.x, 0, 1.2))
            v.co += (c - v.co).normalized() * LINING_INSET
        bm.normal_update()
        outward = [f for f in bm.faces
                   if f.normal.dot(f.calc_center_median() - Vector((f.calc_center_median().x, 0, 1.2))) > 0]
        bmesh.ops.reverse_faces(bm, faces=outward)
        return mesh_object(name, bm, m, smooth=True)

    shell(O['Fuselage'], 'Cabin_lining',
          lambda c: BULKHEAD_X - 0.02 < c.x < FIREWALL_X + 0.01 and c.z > FLOOR_Z - 0.02)
    pivots = {}
    for side in ('L', 'R'):
        piv = empty(f'Door_{side}_int', O[f'Door_{side}'].matrix_world.translation)
        lin = shell(O[f'Door_{side}_skin'], f'Door_{side}_lining', lambda c: True)
        mw = lin.matrix_world.copy()
        lin.parent = piv
        lin.matrix_parent_inverse = piv.matrix_world.inverted()
        lin.matrix_world = mw
        pivots[side] = piv
    return pivots


# ================================ cabin structure ================================
def floor_and_walls(mats):
    xs = [BULKHEAD_X + i * (FIREWALL_X - BULKHEAD_X) / 31 for i in range(32)]
    left = [(half_width(x, FLOOR_Z + 0.015, 0.004), x) for x in xs]
    outline = [(x, y) for y, x in left] + [(x, -y) for y, x in reversed(left)]
    bm = bmesh.new()
    f = bm.faces.new([bm.verts.new((x, y, FLOOR_Z)) for x, y in outline])
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    for v in [e for e in ext['geom'] if isinstance(e, bmesh.types.BMVert)]:
        v.co.z -= 0.012
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    mesh_object('Cabin_floor', bm, mats['carpet'])

    # firewall / footwell front, up to the glareshield
    zs = [FLOOR_Z + i * (1.37 - FLOOR_Z) / 14 for i in range(15)]
    side = [(half_width(FIREWALL_X - 0.02, z, 0.004), z) for z in zs]
    outline = [(y, z) for y, z in side] + [(-y, z) for y, z in reversed(side)]
    slab_from_outline('Firewall', outline, lambda z: FIREWALL_X - 0.02, 0.01, mats['carpet'])

    # aft wall of the baggage compartment
    top_z = roof(BULKHEAD_X + 0.02, 0) - 0.015
    zs = [FLOOR_Z + i * (top_z - FLOOR_Z) / 16 for i in range(17)]
    side = [(half_width(BULKHEAD_X + 0.02, z, 0.004), z) for z in zs]
    outline = [(max(y, 0.02), z) for y, z in side] + [(-max(y, 0.02), z) for y, z in reversed(side)]
    slab_from_outline('Baggage_bulkhead', outline, lambda z: BULKHEAD_X, 0.012, mats['lining_plain'])

    # adjustable red interior light, behind and between the front seats' heads (POH 7.9)
    rz = roof(0.25, 0)
    cylinder('Interior_light_base', (0.25, 0, rz - 0.004), (0.25, 0, rz - 0.018), 0.03, mats['panel'], segs=24, bevel=0.003)
    cylinder('Interior_light_lens', (0.25, 0, rz - 0.018), (0.25, 0, rz - 0.026), 0.018, mats['lamp_red'], segs=20)


def glareshield(mats, outline):
    x_r = panel_x(PANEL_Z_TOP) + 0.004
    xs = [x_r + i * (FIREWALL_X - x_r) / 13 for i in range(14)]
    ny = 31
    rows = []
    for x in xs:
        hw = half_width(x, 1.30, 0.012)
        row = []
        for j in range(ny):
            y = hw * (2 * j / (ny - 1) - 1)
            cap = panel_top_z(y, outline) + 0.012 - (x - x_r) * 0.17
            r = roof(x, y)
            z = cap if r is None else min(cap, r - 0.018)
            row.append(Vector((x, y, max(z, 1.26))))
        rows.append(row)
    rows.insert(0, [Vector((v.x - 0.018, v.y, v.z - 0.03)) for v in rows[0]])     # rolled lip
    bm = bmesh.new()
    grid = [[bm.verts.new(v) for v in row] for row in rows]
    for i in range(len(grid) - 1):
        for j in range(ny - 1):
            bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    if bm.faces[len(bm.faces) // 2].normal.z < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    o = mesh_object('Glareshield', bm, mats['suede'], smooth=True)
    s = o.modifiers.new('thick', 'SOLIDIFY')
    s.thickness = 0.008
    # the magnetic compass on the centre line is compass()


# ================================ instrument panel (POH 7.10) ================================
def panel(mats, face_mat):
    outer = panel_outline()
    inner = inset(outer, 0.017)
    # painted carbon face (texture laid out by panel_layout.uv), then the raised black surround
    slab_from_outline('Panel_face', outer, panel_x, 0.02, face_mat, uv_scale=layout.uv)
    bm = bmesh.new()
    n = len(outer)
    back_o = [bm.verts.new(on_panel(y, z, 0.0)) for y, z in outer]
    back_i = [bm.verts.new(on_panel(y, z, 0.0)) for y, z in inner]
    front_o = [bm.verts.new(on_panel(y, z, 0.014)) for y, z in outer]
    front_i = [bm.verts.new(on_panel(y, z, 0.014)) for y, z in inner]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((front_o[i], front_o[j], front_i[j], front_i[i]))      # face
        bm.faces.new((back_o[i], back_o[j], front_o[j], front_o[i]))        # outer wall
        bm.faces.new((front_i[i], front_i[j], back_i[j], back_i[i]))        # inner wall
    bm.normal_update()
    o = mesh_object('Panel_surround', bm, mats['panel'])
    bmesh_fix = o.modifiers.new('bevel', 'BEVEL')
    bmesh_fix.width, bmesh_fix.segments, bmesh_fix.limit_method = 0.004, 3, 'ANGLE'
    for p in o.data.polygons:
        p.use_smooth = True
    # panel screws along the middle of the surround, about every 95 mm
    mid = inset(outer, 0.0085)
    run, k = 0.0, 0
    for i in range(len(mid)):
        a, b = Vector(mid[i]), Vector(mid[(i + 1) % len(mid)])
        run += (b - a).length
        if run >= 0.095:
            run = 0.0
            y, z = b
            cylinder(f'Panel_screw_{k}', on_panel(y, z, 0.014), on_panel(y, z, 0.0156), 0.0028, mats['screw'],
                     r1=0.0022, segs=12)
            k += 1
    return outer


TOGGLE_PIVOTS = []


def bat_lever(name, start, end, r0, r1, ball_r, mat, parent):
    """One mesh: tapered shaft from start to end with a ball tip (the clickable switch node)."""
    start, end = Vector(start), Vector(end)
    axis = end - start
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12, radius1=r0, radius2=r1, depth=axis.length)
    ball = bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=ball_r)
    for v in ball['verts']:
        v.co.z += axis.length / 2
    rot = Vector((0, 0, 1)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    return mesh_object(name, bm, mat, parent, smooth=True, world=Matrix.Translation((start + end) / 2) @ rot)


def toggle(name, xp, yp, mats):
    """Bat-handle toggle: hex nut and collar on the panel, the lever on a pivot so the switch
    template can throw it (sw_<name>_anim: 0 = off, lever down; 100 = on, lever up)."""
    y, z = px_yz(xp, yp)
    cylinder(f'SW_{name}_nut', on_panel(y, z, 0), on_panel(y, z, 0.003), 0.0064, mats['metal'], segs=6, bevel=0.0004)
    cylinder(f'SW_{name}_collar', on_panel(y, z, 0.003), on_panel(y, z, 0.0065), 0.0043, mats['chrome'], segs=16)
    piv = empty(f'SW_{name}_pivot', on_panel(y, z, 0.0065))
    bat_lever(f'SW_{name}', on_panel(y, z, 0.0065), on_panel(y, z, 0.0225), 0.0024, 0.0017, 0.0028, mats['chrome'], piv)
    TOGGLE_PIVOTS.append(f'SW_{name}_pivot')


def lamp(name, xp, yp, mat, r=0.004):
    cylinder(name, at(xp, yp, 0), at(xp, yp, 0.006), r, mat, segs=14, bevel=0.001)


def knob(name, xp, yp, r, depth, mat, pointer=None, parent=None):
    cylinder(name, at(xp, yp, 0), at(xp, yp, depth), r, mat, segs=24, bevel=0.0015, parent=parent)
    if pointer:
        box(f'{name}_pointer', at(xp, yp, depth + 0.001) + Vector((0, 0, r * 0.45)),
            (0.003, 0.003, r * 0.9), pointer, rot=PANEL_ROT, bevel=0.0005, parent=parent)


def attach_point(name, y, z):
    """Empty the sim hangs a SimAttachment instrument on (see presets/sling/SlingTSi/config/attached_objects.cfg).
    Attachment instruments are built facing aft with their origin on the panel surface, so the
    point only needs the panel's tilt."""
    e = empty(name, on_panel(y, z, 0.0))
    # Attachments are authored in the MSFS frame (nose +Z, left +X, up +Y). blender_export later
    # turns the root -90 deg about Z to reach that frame, so undo that turn here; the panel tilt
    # (top leaning forward) is then a rotation about the lateral axis, which is X in both frames.
    rot = Matrix.Rotation(math.radians(90), 4, 'Z') @ Matrix.Rotation(TILT, 4, 'X')
    refresh()
    e.matrix_world = Matrix.Translation(on_panel(y, z, 0.0)) @ rot
    refresh()
    return e


def screen_quad(name, mat, center, w, h):
    """Flat screen on the panel face with 0..1 UVs, for a $-named render target."""
    bm = bmesh.new()
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    bm.faces.new([bm.verts.new((0, cy, cz)) for cy, cz in corners])
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    if bm.faces[0].normal.x > 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    uv = bm.loops.layers.uv.new('UVMap')
    for loop in bm.faces[0].loops:
        cy, cz = loop.vert.co.y, loop.vert.co.z
        # the pilot faces +X: the screen's left edge is its +Y side; v up
        loop[uv].uv = ((w / 2 - cy) / w, (cz + h / 2) / h)
    world = Matrix.Translation(center) @ _euler(PANEL_ROT).to_matrix().to_4x4()
    return mesh_object(name, bm, mat, world=world)


def avionics(mats, g5_screen):
    """Avionics from POH 7.10. The GDU 460 (item 7), GMC 307 (item 18) and com radio (item 11) are
    the sim's own working SimAttachment instruments, hung on attach points; sizes measured from
    the attachment models (G3X 0.275 x 0.20 m, origin 0.052 m above its bottom edge; GMC 307
    0.142 x 0.052 m and G225 0.16 x 0.042 m, both centred). The sim has no GTR 200 attachment:
    the Garmin G225 is the same size and does the same job. The G5 (item 10) attachment ships no
    model XML, so the G5 is modelled here and its screen runs the built-in AS5 gauge."""
    y, z = px_yz(352, 272)                       # GDU 460 centre
    attach_point('Attach_Point_G3X', y, z - 0.10 + 0.052)
    attach_point('Attach_Point_Radio', *px_yz(687, 241))
    attach_point('Attach_Point_AP', *px_yz(687, 297))
    # Garmin G5: bezel, 3.5 in screen (512 x 350 render target), knob lower right
    y, z = px_yz(684, 157)
    box('G5_face', on_panel(y, z, 0.015), (0.03, 0.086, 0.092), mats['bezel'], rot=PANEL_ROT, bevel=0.005, seg=3)
    screen_quad('G5_Screen', g5_screen, on_panel(y, z + 0.009, 0.0305), 0.07, 0.048)
    cylinder('G5_knob', on_panel(y - 0.03, z - 0.033, 0.03), on_panel(y - 0.03, z - 0.033, 0.042), 0.008, mats['knob'], segs=18, bevel=0.001)
    box('G5_power_button', on_panel(y + 0.03, z - 0.035, 0.031), (0.004, 0.01, 0.007), mats['button'], rot=PANEL_ROT, bevel=0.001)




def prop_controller(mats, face_mat):
    """Airmaster AP430 controller (item 9, POH 7.3.2): FINE / COARSE lamps, AUTO/MAN toggle, blue mode
    selector (T.O. / CLIMB / CRUISE / HOLD / FEATHER) and the feather engage toggle. Its face is a disc
    carrying the panel texture, where make_panel_texture.py prints the legends."""
    y, z = px_yz(*layout.PROP_CTL_PX)
    up = Vector((math.sin(TILT), 0, math.cos(TILT)))
    left = Vector((0, 1, 0))
    cylinder('Prop_ctl_body', on_panel(y, z, 0), on_panel(y, z, 0.012), layout.PROP_CTL_R, mats['bezel'], segs=40, bevel=0.003)
    # printed face: a disc whose UVs map the panel texture at its own (y, z)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    ring = [(y + 0.0335 * math.cos(2 * math.pi * k / 48), z + 0.0335 * math.sin(2 * math.pi * k / 48)) for k in range(48)]
    vs = [bm.verts.new(on_panel(a_, b_, 0.0122)) for a_, b_ in ring]
    c = bm.verts.new(on_panel(y, z, 0.0122))
    for k in range(48):
        f = bm.faces.new((vs[k], vs[(k + 1) % 48], c))
        for loop in f.loops:
            co = loop.vert.co
            loop[uvl].uv = layout.uv(co.y, z if loop.vert is c else ring[vs.index(loop.vert)][1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    for f in bm.faces:
        if f.normal.dot(PANEL_N) < 0:
            f.normal_flip()
    mesh_object('Prop_ctl_face', bm, face_mat)
    # blue mode selector on its own pivot (prop_mode_anim turns it anticlockwise through the modes)
    ky, kz = y + layout.PROP_KNOB_OFFSET[0], z + layout.PROP_KNOB_OFFSET[1]
    knob_piv = empty('Prop_ctl_knob_pivot', on_panel(ky, kz, 0.0122))
    cylinder('Prop_ctl_knob', on_panel(ky, kz, 0.0122), on_panel(ky, kz, 0.028), 0.0135, mats['blue'], segs=28,
             bevel=0.003, parent=knob_piv)
    a = math.radians(layout.PROP_KNOB_T0)
    d = up * math.cos(a) + left * math.sin(a)                       # bar towards T.O.
    obox('Prop_ctl_knob_bar', on_panel(ky, kz, 0.029), (0.026, 0.0055, 0.004), (d, PANEL_N.cross(d), PANEL_N),
         mats['blue'], bevel=0.0012, parent=knob_piv)
    obox('Prop_ctl_knob_mark', on_panel(ky, kz, 0.031) + d * 0.0085, (0.008, 0.0016, 0.001), (d, PANEL_N.cross(d), PANEL_N),
         mats['switch'], bevel=0.0003, parent=knob_piv)
    # AUTO/MAN (left) and feather engage (bottom) toggles: bat levers on pivots, thrown up/down
    for name, dy, dz in (('Prop_ctl_automan', 0.022, 0.0), ('Prop_ctl_feather', 0.012, -0.025)):
        cylinder(f'{name}_nut', on_panel(y + dy, z + dz, 0.012), on_panel(y + dy, z + dz, 0.015), 0.0042, mats['metal'],
                 segs=6, bevel=0.0003)
        piv = empty(f'{name}_pivot', on_panel(y + dy, z + dz, 0.015))
        bat_lever(f'{name}_bat', on_panel(y + dy, z + dz, 0.015), on_panel(y + dy, z + dz, 0.027), 0.0018, 0.0013,
                  0.0021, mats['chrome'], piv)
    # FINE / COARSE lamps, lit by the controller logic (emissive amber)
    for name, dy in (('Prop_ctl_fine', 0.012), ('Prop_ctl_coarse', -0.012)):
        cylinder(name, on_panel(y + dy, z + 0.024, 0.012), on_panel(y + dy, z + 0.024, 0.016), 0.0045, mats['prop_lamp'],
                 segs=14, bevel=0.0008)
    return {'Prop_ctl_knob_pivot': PANEL_N.copy(), 'Prop_ctl_automan_pivot': Vector((0, 1, 0)),
            'Prop_ctl_feather_pivot': Vector((0, 1, 0))}


def panel_items(mats):
    # --- left end: lane A/B (items 4, 5), master (2) with power light (1), key switch (3), 12 V port (6)
    # every switch in panel_layout.SWITCHES (lanes, master, pumps, the switch row, prop power);
    # the red plates and all legends are painted on the panel face
    for name, xp, yp, _label, _tpl, _prm in layout.SWITCHES:
        toggle(name, xp, yp, mats)
    lamp('Lane_A_light', 118, 225, mats['lamp_red'])
    lamp('Lane_B_light', 150, 225, mats['lamp_red'])
    lamp('Power_light', 80, 300, mats['lamp_red'])
    # master / starter key (item 3): barrel on the panel, the key turns on a pivot (key_anim)
    _, kx, ky = layout.KEY
    y, z = px_yz(kx, ky)
    cylinder('Key_barrel', on_panel(y, z, 0), on_panel(y, z, 0.008), 0.011, mats['chrome'], segs=32, bevel=0.002)
    cylinder('Key_slot_face', on_panel(y, z, 0.008), on_panel(y, z, 0.0095), 0.008, mats['knob'], segs=24)
    key = empty('Key_pivot', on_panel(y, z, 0.0095))
    box('Key_shank', on_panel(y, z, 0.013), (0.008, 0.0025, 0.009), mats['metal'], rot=PANEL_ROT, bevel=0.0008, parent=key)
    box('Key_head', on_panel(y, z, 0.021), (0.012, 0.004, 0.020), mats['knob'], rot=PANEL_ROT, bevel=0.003, seg=3, parent=key)
    for name, xp, yp in (('Power_port_L', 135, 190), ('Power_port_R', 1250, 205)):
        cylinder(name, at(xp, yp, 0), at(xp, yp, 0.01), 0.013, mats['knob'], segs=24, bevel=0.002)
        cylinder(f'{name}_cap', at(xp, yp, 0.01), at(xp, yp, 0.014), 0.009, mats['rubber'], segs=20)
    # --- EFIS warning light (8), GDU, prop controller, centre stack
    lamp('EFIS_warning_light', 515, 127, mats['lamp_red'], r=0.007)
    # --- flap selector (22), cabin heat knobs (19, 21); the chute handle (20) is chute_handle()
    y, z = px_yz(565, 383)
    flap = empty('Flap_knob', on_panel(y, z, 0))
    knob('Flap_knob_body', 565, 383, 0.013, 0.016, mats['knob'], pointer=mats['switch'], parent=flap)
    knob('Heat_temp_knob', 645, 383, 0.019, 0.022, mats['knob'], pointer=mats['switch'])
    knob('Heat_fan_knob', 722, 383, 0.019, 0.022, mats['knob'], pointer=mats['switch'])
    # --- right side: RAM mount (12), cubby (13), ELT display (14), breakers (15)
    y, z = px_yz(957, 165)
    box('RAM_plate', on_panel(y, z, 0.002), (0.004, 0.06, 0.034), mats['metal'], rot=PANEL_ROT, bevel=0.004)
    box('RAM_ball', on_panel(y, z, 0.014), (0.026, 0.026, 0.026), mats['rubber'], bevel=0.012, seg=4)
    # the cubby area (item 13) carries the POH 2.17 placards, painted on the panel face
    y, z = px_yz(1200, 230)
    box('ELT_display', on_panel(y, z, 0.008), (0.016, 0.024, 0.052), mats['bezel'], rot=PANEL_ROT, bevel=0.003)
    lamp('ELT_light', 1200, 215, mats['lamp_red'], r=0.003)
    for i, xp in enumerate((1205, 1235, 1265)):
        cylinder(f'CB_top_{i}', at(xp, 298, 0), at(xp, 298, 0.004), 0.0065, mats['metal'], segs=14)
        cylinder(f'CB_top_{i}_cap', at(xp, 298, 0.004), at(xp, 298, 0.012), 0.0048, mats['knob'], segs=14)
    for i in range(12):
        xp = 852 + i * 31.2
        cylinder(f'CB_{i}', at(xp, 425, 0), at(xp, 425, 0.004), 0.0065, mats['metal'], segs=14)
        cylinder(f'CB_{i}_cap', at(xp, 425, 0.004), at(xp, 425, 0.012), 0.0048, mats['knob'], segs=14)
    # --- air vents (16) in the lower corners, cabin air knobs (17)
    for s, xp in (('L', 100), ('R', 1269)):
        cylinder(f'Vent_{s}_ring', at(xp, 420, 0), at(xp, 420, 0.014), 0.034, mats['bezel'], segs=32, bevel=0.004)
        cylinder(f'Vent_{s}_ball', at(xp, 420, 0.006), at(xp, 420, 0.024), 0.025, mats['metal'], r1=0.02, segs=28)
    for s, xp in (('L', 90), ('R', 1280)):
        cylinder(f'Cabin_air_{s}_stem', at(xp, 342, 0), at(xp, 342, 0.012), 0.003, mats['metal'], segs=8)
        cylinder(f'Cabin_air_{s}_knob', at(xp, 342, 0.012), at(xp, 342, 0.02), 0.008, mats['switch'], segs=16, bevel=0.002)


# ================================ console, controls, seats (POH 7.2, 7.9) ================================
import console_layout as CL                         # console positions shared with its texture and behaviours

CONSOLE_FRONT = [CL.FRONT_A, CL.FRONT_B]            # sloped front face, from the top up to the panel
console_top_z = CL.top_z


def obox(name, center, size, axes, mat, bevel=0.002, seg=2, parent=None):
    """Box of size (along axes[0], axes[1], axes[2]) centred at `center`, axes given as world vectors."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    m = Matrix((axes[0], axes[1], axes[2])).transposed().to_4x4()
    o = mesh_object(name, bm, mat, parent, world=Matrix.Translation(Vector(center)) @ m)
    add_bevel(o, bevel, seg)
    return o


def printed_plate(name, face, mat, a0, a1, point, thickness=0.0012):    # parts mount 0.3 mm above it
    """Thin plate over a console face, its outer side mapped to that face's atlas region.
    point(y, a, proud) -> world point; a runs a0..a1 along the face."""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    kw = {'top': 'x', 'front': 's', 'rear': 'z'}[face]
    ys, as_ = (CL.HALF_W, -CL.HALF_W), (a0, a1)
    vs = {(i, j, k): bm.verts.new(point(ys[i], as_[j], k * thickness)) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    quads = [[(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)],
             [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],
             [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)], [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]]
    for q in quads:
        f = bm.faces.new([vs[k] for k in q])
        for loop, k in zip(f.loops, q):
            loop[uvl].uv = CL.uv(face, ys[k[0]], **{kw: as_[k[1]]})
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return mesh_object(name, bm, mat)


def top_point(y, x, proud=0.0):
    return Vector((x, y, console_top_z(x))) + Vector(CL.TOP_NORMAL) * proud


def front_point(y, s, proud=0.0):
    return Vector(CL.front_point(y, s, proud))


def rear_point(y, z, proud=0.0):
    return Vector((CL.REAR_X - proud, y, z))


def screw(name, p, n, mats, r=0.0026):
    cylinder(name, p, p + n * 0.0012, r, mats['screw'], segs=10)


def jack(name, p, n, r, mats):
    """Headset socket: chrome nut with a dark hole."""
    cylinder(f'{name}_nut', p, p + n * 0.003, r, mats['chrome'], segs=6)
    cylinder(f'{name}_hole', p + n * 0.003, p + n * 0.0034, r * 0.5, mats['glass_dark'], segs=12)


def console(mats, face_mat):
    """Centre console (POH 7.9): printed carbon plates, throttle quadrant, hand brake, park brake
    valve, headset sockets, fuel selector, armrest. Returns the hinge axes of its rotary parts."""
    prof = [(0.10, FLOOR_Z), (1.27, FLOOR_Z), (1.27, 1.108), (1.20, 1.108), (1.02, 0.94), (0.20, 0.90), (0.10, 0.86)]
    prism('Console', prof, -CONSOLE_W, CONSOLE_W, mats['panel'], bevel=0.01)
    TN, FN, RN = Vector(CL.TOP_NORMAL), Vector(CL.FRONT_NORMAL), Vector((-1, 0, 0))
    fwd = Vector((math.cos(CL.TOP_SLOPE), 0, math.sin(CL.TOP_SLOPE)))      # along the top, toward the nose
    up_slope = Vector((CL.FRONT_DIR[0], 0, CL.FRONT_DIR[1]))
    Y = Vector((0, 1, 0))

    # printed carbon plates: top, front slope, aft face
    printed_plate('Console_plate_top', 'top', face_mat, CL.TOP_X0, CL.TOP_X1, top_point)
    printed_plate('Console_plate_front', 'front', face_mat, CL.FRONT_S0, CL.FRONT_S1, front_point)
    printed_plate('Console_plate_rear', 'rear', face_mat, CL.REAR_Z0, CL.REAR_Z1, rear_point)
    sy = CL.HALF_W - 0.007
    for i, x in enumerate(np.arange(0.60, CL.TOP_X1, 0.095)):
        for s in (1, -1):
            screw(f'Console_screw_top_{i}_{s > 0}', top_point(s * sy, x, 0.0015), TN, mats)
    for i, (y, a) in enumerate(((sy, CL.FRONT_S0 + 0.008), (-sy, CL.FRONT_S0 + 0.008),
                                (sy, CL.FRONT_S1 - 0.008), (-sy, CL.FRONT_S1 - 0.008))):
        screw(f'Console_screw_front_{i}', front_point(y, a, 0.0015), FN, mats)
    for i, (y, z) in enumerate(((sy, CL.REAR_Z0 + 0.008), (-sy, CL.REAR_Z0 + 0.008),
                                (sy, CL.REAR_Z1 - 0.008), (-sy, CL.REAR_Z1 - 0.008))):
        screw(f'Console_screw_rear_{i}', rear_point(y, z, 0.0015), RN, mats)
    for i, x in enumerate(np.arange(0.18, 1.18, 0.12)):                  # side panel fasteners
        for s in (1, -1):
            screw(f'Console_screw_side_{i}_{s > 0}', Vector((x, s * CONSOLE_W, FLOOR_Z + 0.05)), Vector((0, s, 0)), mats)

    # padded armrest over the storage box, with piping and a lid latch
    x0, x1 = CL.ARMREST
    c = top_point(0, (x0 + x1) / 2, 0.0015 + 0.018)
    obox('Console_armrest', c, (x1 - x0, 2 * CL.HALF_W, 0.036), (fwd, Y, TN), mats['leather'], bevel=0.012, seg=3)
    for s in (1, -1):
        obox(f'Console_armrest_piping_{s > 0}', c + TN * 0.017 + Y * s * (CL.HALF_W - 0.012),
             (x1 - x0 - 0.03, 0.004, 0.004), (fwd, Y, TN), mats['leather_insert'], bevel=0.0015)
    obox('Console_armrest_latch', top_point(0, x1 + 0.003, 0.0015 + 0.02), (0.008, 0.04, 0.012), (fwd, Y, TN),
         mats['chrome'], bevel=0.002)

    # throttle quadrant (item 11): brushed cover with a brush-sealed slot, friction lock aft of it
    ty, (s0, s1) = CL.THROTTLE_Y, CL.THROTTLE_SLOT
    sc = top_point(ty, (s0 + s1) / 2, 0.0015)
    obox('Throttle_cover', sc + TN * 0.002, (s1 - s0 + 0.024, 0.026, 0.004), (fwd, Y, TN), mats['metal'], bevel=0.0015)
    for s in (1, -1):
        obox(f'Throttle_brush_{s > 0}', sc + TN * 0.0045 + Y * s * 0.0025, (s1 - s0, 0.004, 0.0015), (fwd, Y, TN),
             mats['rubber'], bevel=0.0005)
    for i, x in enumerate((s0 - 0.007, s1 + 0.007)):
        for s in (1, -1):
            screw(f'Throttle_cover_screw_{i}_{s > 0}', top_point(ty + s * 0.009, x, 0.0055), TN, mats, r=0.0018)
    xt = CL.THROTTLE_PIVOT_X
    zt = console_top_z(xt)
    thr = empty('Throttle_lever', (xt, ty, zt - 0.05))
    cylinder('Throttle_arm', (xt, ty, zt - 0.03), (xt - 0.004, ty, zt + 0.10), 0.0058, mats['metal'], r1=0.0045, segs=14,
             parent=thr)
    cylinder('Throttle_collar', (xt - 0.004, ty, zt + 0.098), (xt - 0.0045, ty, zt + 0.106), 0.0085, mats['chrome'],
             segs=20, bevel=0.001, parent=thr)
    # the knob is the drag handle (ASOBO_ENGINE_Lever_Throttle_Template): a flared grip with a domed cap
    cylinder('Throttle_knob', (xt - 0.0045, ty, zt + 0.104), (xt - 0.005, ty, zt + 0.132), 0.0135, mats['knob'],
             r1=0.0175, segs=28, bevel=0.002, parent=thr)
    box('Throttle_knob_cap', (xt - 0.005, ty, zt + 0.136), (0.036, 0.036, 0.014), mats['knob'], bevel=0.0065, seg=4,
        parent=thr)
    fx, fy = CL.FRICTION
    fp = top_point(fy, fx, 0.0015)
    cylinder('Throttle_friction_base', fp, fp + TN * 0.003, 0.0125, mats['chrome'], segs=24)
    cylinder('Throttle_friction_knob', fp + TN * 0.003, fp + TN * 0.015, 0.0105, mats['knob'], segs=18)
    for i in range(12):                                            # knurled grip
        a = 2 * math.pi * i / 12
        d = fwd * math.cos(a) + Y * math.sin(a)
        obox(f'Throttle_friction_rib_{i}', fp + TN * 0.009 + d * 0.0105, (0.0022, 0.0022, 0.011), (d, TN.cross(d), TN),
             mats['knob'], bevel=0.0006)
    cylinder('Throttle_friction_cap', fp + TN * 0.015, fp + TN * 0.016, 0.006, mats['chrome'], segs=16)

    # hand brake lever (item 4): the throttle's smaller twin in its own slot, pulled aft to brake
    by, (b0, b1) = CL.BRAKE_Y, CL.BRAKE_SLOT
    bc = top_point(by, (b0 + b1) / 2, 0.0015)
    obox('Brake_cover', bc + TN * 0.002, (b1 - b0 + 0.02, 0.022, 0.004), (fwd, Y, TN), mats['metal'], bevel=0.0015)
    for s in (1, -1):
        obox(f'Brake_brush_{s > 0}', bc + TN * 0.0045 + Y * s * 0.0022, (b1 - b0, 0.0035, 0.0015), (fwd, Y, TN),
             mats['rubber'], bevel=0.0005)
    for i, x in enumerate((b0 - 0.006, b1 + 0.006)):
        for s in (1, -1):
            screw(f'Brake_cover_screw_{i}_{s > 0}', top_point(by + s * 0.0075, x, 0.0055), TN, mats, r=0.0016)
    xb = CL.BRAKE_PIVOT_X
    zb = console_top_z(xb)
    brk = empty('Brake_lever', (xb, by, zb - 0.04))
    cylinder('Brake_lever_arm', (xb, by, zb - 0.025), (xb - 0.003, by, zb + 0.082), 0.005, mats['metal'], r1=0.004,
             segs=14, parent=brk)
    cylinder('Brake_lever_collar', (xb - 0.003, by, zb + 0.080), (xb - 0.0035, by, zb + 0.087), 0.0072, mats['chrome'],
             segs=20, bevel=0.001, parent=brk)
    # the knob is the drag handle (ASOBO_LANDING_GEAR_Lever_Brake_Template)
    cylinder('Brake_lever_grip', (xb - 0.0035, by, zb + 0.085), (xb - 0.004, by, zb + 0.108), 0.011, mats['knob'],
             r1=0.014, segs=28, bevel=0.002, parent=brk)
    box('Brake_lever_cap', (xb - 0.004, by, zb + 0.111), (0.029, 0.029, 0.011), mats['knob'], bevel=0.0052, seg=4,
        parent=brk)

    # park brake shut-off valve (item 9): brass body, red quarter-turn T handle (along the console = OFF)
    vx, vy = CL.PARK_VALVE
    vp = top_point(vy, vx, 0.0015)
    cylinder('Park_brake_valve_nut', vp, vp + TN * 0.006, 0.0115, mats['brass'], segs=6, bevel=0.0008)
    cylinder('Park_brake_valve_stem', vp + TN * 0.006, vp + TN * 0.012, 0.0035, mats['brass'], segs=12)
    pb = empty('Park_brake', vp + TN * 0.012)
    cylinder('Park_brake_hub', vp + TN * 0.011, vp + TN * 0.02, 0.0065, mats['red'], segs=18, bevel=0.0015, parent=pb)
    obox('Park_brake_handle', vp + TN * 0.0165, (0.044, 0.009, 0.008), (fwd, Y, TN), mats['red'], bevel=0.003, seg=3,
         parent=pb)

    # headset sockets (item 5) and the 12 V socket
    for label, y, x_phone, x_mic in CL.HEADSETS:
        jack(f'Headset_{label}_phone', top_point(y, x_phone, 0.0015), TN, 0.0075, mats)
        jack(f'Headset_{label}_mic', top_point(y, x_mic, 0.0015), TN, 0.0058, mats)
    px_, py_ = CL.POWER_SOCKET
    pp = top_point(py_, px_, 0.0015)
    cylinder('Power_socket_ring', pp, pp + TN * 0.004, 0.0115, mats['chrome'], segs=24, bevel=0.001)
    cylinder('Power_socket_hole', pp + TN * 0.004, pp + TN * 0.0044, 0.0085, mats['glass_dark'], segs=20)
    cylinder('Power_socket_pin', pp + TN * 0.0044, pp + TN * 0.0056, 0.0022, mats['metal'], segs=10)

    # fuel tank selector (item 12, POH 7.2.5): red pointer handle on a dark base; OFF only through the
    # release knob beside it. The pointer rests down the slope (OFF); LEFT/RIGHT are -+90 deg.
    fc = front_point(0.0, CL.FUEL_SEL_S, 0.0015)
    cylinder('Fuel_selector_base', fc, fc + FN * 0.004, 0.034, mats['bezel'], segs=40, bevel=0.0015)
    for i in range(4):
        a = math.pi / 4 + i * math.pi / 2
        d = up_slope * math.cos(a) + Y * math.sin(a)
        screw(f'Fuel_selector_screw_{i}', fc + FN * 0.004 + d * 0.028, FN, mats, r=0.0022)
    sel = empty('Fuel_selector', fc + FN * 0.004)
    down = -up_slope
    cylinder('Fuel_selector_hub', fc + FN * 0.004, fc + FN * 0.014, 0.015, mats['red'], segs=28, bevel=0.002, parent=sel)
    # the fin is the click spot (make_interior_behaviors.py): LEFT <-> RIGHT
    obox('Fuel_selector_handle', fc + FN * 0.02 + down * 0.008, (0.078, 0.009, 0.026), (down, -Y, FN), mats['red'],
         bevel=0.004, seg=3, parent=sel)
    cylinder('Fuel_selector_pointer', fc + FN * 0.008 + down * 0.02, fc + FN * 0.008 + down * 0.043, 0.008,
             mats['red'], r1=0.0015, segs=16, parent=sel)
    obox('Fuel_selector_pointer_line', fc + FN * 0.0335 + down * 0.02, (0.05, 0.0025, 0.0012), (down, -Y, FN),
         mats['switch'], bevel=0.0004, parent=sel)
    ky, ks = CL.FUEL_OFF_KNOB
    kp = front_point(ky, ks, 0.0015)
    cylinder('Fuel_selector_off_collar', kp, kp + FN * 0.003, 0.0085, mats['chrome'], segs=20, bevel=0.0008)
    offp = empty('Fuel_selector_off_pivot', kp + FN * 0.003)
    cylinder('Fuel_selector_off', kp + FN * 0.003, kp + FN * 0.012, 0.0065, mats['red'], segs=20, bevel=0.002,
             parent=offp)

    # rear headset sockets (item 7) on the aft face
    for label, yp, ym in CL.REAR_HEADSETS:
        n = label.replace(' ', '_')
        jack(f'Headset_{n}_phone', rear_point(yp, CL.REAR_JACK_Z, 0.0015), RN, 0.0075, mats)
        jack(f'Headset_{n}_mic', rear_point(ym, CL.REAR_JACK_Z, 0.0015), RN, 0.0058, mats)
    return {'Fuel_selector': FN.copy(), 'Park_brake': TN.copy(), 'Fuel_selector_off_pivot': FN.copy()}


def stick(side, y, mats):
    """Control stick (item 3) with the round grip head of POH 7.2.1."""
    base = Vector((0.98, y, FLOOR_Z))
    pitch = empty(f'Stick_{side}_pitch', base)
    roll = empty(f'Stick_{side}_roll', base, parent=pitch)
    cylinder(f'Stick_{side}_boot', base, base + Vector((0, 0, 0.09)), 0.05, mats['rubber'], r1=0.018, segs=20, parent=roll)
    top = base + Vector((-0.035, 0, 0.29))
    cylinder(f'Stick_{side}_shaft', base, top, 0.011, mats['metal'], segs=16, parent=roll)
    grip = top + Vector((-0.008, 0, 0.09))
    cylinder(f'Stick_{side}_grip', top, grip, 0.017, mats['knob'], r1=0.02, segs=24, bevel=0.004, parent=roll)
    head_n = Vector((-0.35, 0, 1)).normalized()                 # the head faces up and a little aft
    cylinder(f'Stick_{side}_head', grip, grip + head_n * 0.022, 0.026, mats['knob'], segs=32, bevel=0.007, parent=roll)
    face = grip + head_n * 0.022
    u = Vector((0, 1, 0))
    v = head_n.cross(u).normalized()
    for i, (du, dv, mat) in enumerate(((0, 0.009, 'button'), (0.011, 0.002, 'red'), (-0.011, 0.002, 'button'),
                                        (0, -0.011, 'button'), (0.0, 0.0, 'knob'))):
        p = face + u * du + v * dv
        cylinder(f'Stick_{side}_btn_{i}', p, p + head_n * 0.004, 0.0045, mats[mat], segs=12, parent=roll)
    return pitch, roll


def pedals(mats):
    out = {}
    px_ = 1.90
    bar = half_width(px_, FLOOR_Z + 0.04, 0.03)                 # the footwell narrows toward the floor
    cylinder('Pedal_bar', (px_, bar, FLOOR_Z + 0.04), (px_, -bar, FLOOR_Z + 0.04), 0.012, mats['metal'], segs=16)
    for seat, sy in (('1', SEAT_Y), ('2', -SEAT_Y)):
        for side, dy in (('L', 0.09), ('R', -0.09)):
            y = sy + dy
            piv = empty(f'Pedal_{side}_{seat}', (px_, y, FLOOR_Z + 0.04))
            cylinder(f'Pedal_{side}_{seat}_arm', (px_, y, FLOOR_Z + 0.04), (px_ - 0.05, y, FLOOR_Z + 0.2),
                     0.008, mats['metal'], segs=12, parent=piv)
            box(f'Pedal_{side}_{seat}_plate', (px_ - 0.055, y, FLOOR_Z + 0.17), (0.012, 0.075, 0.13), mats['metal'],
                rot=(0, -18, 0), bevel=0.003, parent=piv)
            box(f'Pedal_{side}_{seat}_grip', (px_ - 0.062, y, FLOOR_Z + 0.17), (0.004, 0.06, 0.11), mats['rubber'],
                rot=(0, -18, 0), bevel=0.001, parent=piv)
            out[f'Pedal_{side}_{seat}'] = piv
    return out


def uv_box(name, center, size, rot_y, mat, region, axes=(1, 2), bevel=0.004, subsurf=1, parent=None):
    """Box of size (dx, dy, dz) tilted rot_y deg about Y, its UVs a planar projection on two local axes (`axes`)
    into an atlas `region` at QUILT_PX_PER_M, so a printed pattern keeps its true size on any panel."""
    c0, r0, w, h = CL.REGION[region]
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    uvl = bm.loops.layers.uv.new('UVMap')
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    k = CL.QUILT_PX_PER_M
    for f in bm.faces:
        for loop in f.loops:
            co = loop.vert.co
            a, b = co[axes[0]] + size[axes[0]] / 2, co[axes[1]] + size[axes[1]] / 2
            loop[uvl].uv = ((c0 + min(a * k, w - 1)) / CL.TEX_W, 1 - (r0 + h - min(b * k, h - 1)) / CL.TEX_H)
    world = Matrix.Translation(Vector(center)) @ _euler((0, rot_y, 0)).to_matrix().to_4x4()
    o = mesh_object(name, bm, mat, parent, world=world)
    add_bevel(o, bevel, 2)
    if subsurf:
        s = o.modifiers.new('subsurf', 'SUBSURF')
        s.levels = s.render_levels = subsurf
        for p in o.data.polygons:
            p.use_smooth = True
    return o


def logo_patch(name, center, fwd, width, mat):
    """Embroidered Sling logo: a thin quad facing `fwd`, mapped to the atlas seat_logo region."""
    c0, r0, w, h = CL.REGION['seat_logo']
    Yv = Vector((0, 1, 0))
    upv = fwd.cross(Yv).normalized()                    # up along the seat back
    hgt = width * h / w
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    # seen from in front of the seat (looking aft) the seat's left (+Y) is on the viewer's right: text starts at -Y
    corners = [(-Yv * (width / 2) + upv * (hgt / 2), (c0, r0)), (Yv * (width / 2) + upv * (hgt / 2), (c0 + w, r0)),
               (Yv * (width / 2) - upv * (hgt / 2), (c0 + w, r0 + h)), (-Yv * (width / 2) - upv * (hgt / 2), (c0, r0 + h))]
    vs = [bm.verts.new(Vector(center) + d) for d, _ in corners]
    f = bm.faces.new(vs)
    for loop, (_, (px_, py_)) in zip(f.loops, corners):
        loop[uvl].uv = (px_ / CL.TEX_W, 1 - py_ / CL.TEX_H)
    bm.normal_update()
    if f.normal.dot(fwd) < 0:
        f.normal_flip()
    return mesh_object(name, bm, mat)


def smoothstep(e0, e1, v):
    t = min(max((v - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def upholstered(name, origin, along, lat, out, length, width, centre, bolster, depth, mats, quilt_mat,
                quilt_t=(0.04, 0.96), drop=None, n_along=28, piping=True, dome=None):
    """One sculpted upholstered piece (a seat cushion or back) as a single shell, as the Sling seats are made:
    a quilted centre panel stitched along a seam to side bolsters that rise out of the same surface and roll over
    the outer edges. The cross-section, across `lat`, is swept `length` along `along`; width(t), centre(t) and
    bolster(t) (half-width, centre-panel half-width, bolster rise, m) shape it along the piece (t 0..1), `depth` is
    its thickness along `out`, drop(t) lowers the section (the cushion's front roll). Two materials: plain leather
    on the shell, quilted leather (atlas 'quilt', true size) on the centre panel. Returns the seam and outer-edge
    polylines (for the stitching and piping)."""
    along, lat, out = Vector(along), Vector(lat), Vector(out)
    n_c, n_b, n_side, n_back = 12, 12, 4, 6
    TUCK = 0.020                                         # how far the padded roll swells past the shell's edge
    rings, faces_meta = [], []
    seam_l, seam_r, edge_l, edge_r = [], [], [], []

    def section(t):
        W, Wc, B, D = width(t), centre(t), bolster(t), depth
        dz = drop(t) if drop else 0.0
        pts = []                                         # (y, F, kind) front left -> right, then round the back
        # padded bolster: an inflated roll from the seam, swelling over the edge and tucking back under at the
        # piping, fullest half way along the piece
        B_eff = B * (0.85 + 0.15 * math.sin(math.pi * t))
        Rh = (W + TUCK - Wc) / 2

        def roll(th):                                    # th 0 at the seam .. pi at the tuck
            return Wc + Rh * (1 - math.cos(th)), D + B_eff * math.sin(th) ** 0.7
        dm = dome(t) if dome else 0.0
        for i in range(n_b):                             # left roll, tuck to seam
            yy, ff = roll(math.pi * (1 - i / n_b))
            pts.append((yy, ff, 'b'))
        pts.append((Wc, D - 0.006, 's'))                 # seam groove
        for i in range(1, n_c):                          # dished, quilted centre (a pillow dome on the headrest)
            y = Wc - 2 * Wc * i / n_c
            q = 1 - (y / Wc) ** 2
            pts.append((y, D - 0.004 * q + dm * q ** 0.6, 'c'))
        pts.append((-Wc, D - 0.006, 's'))
        for i in range(1, n_b + 1):                      # right roll, seam to tuck
            yy, ff = roll(math.pi * i / n_b)
            pts.append((-yy, ff, 'b'))
        for i in range(1, n_side + 1):                   # under the tuck, the side curves in to the back
            a = math.pi / 2 * i / n_side
            pts.append((-W - TUCK * math.cos(a) * 0.9, D * math.cos(a) * 0.95, 'e'))
        for i in range(1, n_back):                       # flat back
            pts.append((-W + 2 * W * i / n_back, -0.002, 'k'))
        for i in range(n_side):                          # left side back up to the tuck
            a = math.pi / 2 * (n_side - i) / n_side
            pts.append((W + TUCK * math.cos(a) * 0.9, D * math.cos(a) * 0.95, 'e'))
        base = Vector(origin) + along * (length * t) + out * dz
        return [(base + lat * yy + out * ff, yy, ff, kind) for yy, ff, kind in pts], W, Wc, D, B, base

    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    c0, r0, w, h = CL.REGION['quilt']
    k = CL.QUILT_PX_PER_M
    vrows = []
    for i in range(n_along + 1):
        t = i / n_along
        sec, W, Wc, D, B, base = section(t)
        vrows.append([(bm.verts.new(p), yy, kind, t) for p, yy, ff, kind in sec])
        seam_l.append(base + lat * Wc + out * (D - 0.005))
        seam_r.append(base - lat * Wc + out * (D - 0.005))
        edge_l.append(base + lat * (W + TUCK + 0.002) + out * (D - 0.001))     # piping in the tuck seam
        edge_r.append(base - lat * (W + TUCK + 0.002) + out * (D - 0.001))
    m = len(vrows[0])
    for i in range(n_along):
        a, b = vrows[i], vrows[i + 1]
        for j in range(m):
            q = (a[j], a[(j + 1) % m], b[(j + 1) % m], b[j])
            f = bm.faces.new([v[0] for v in q])
            ys = [v[1] for v in q]
            centre_face = all(v[2] in ('c', 's') for v in q) and quilt_t[0] <= a[j][3] <= quilt_t[1]
            f.material_index = 1 if centre_face else 0
            for loop, v in zip(f.loops, q):
                u = (c0 + (0.25 - v[1]) * k) / CL.TEX_W
                vv = 1 - (r0 + h - min(v[3] * length * k, h - 1)) / CL.TEX_H
                loop[uvl].uv = (u, vv)
    for row, cap_dir in ((vrows[0], -along), (vrows[-1], along)):   # close both ends
        c = bm.verts.new(sum((v[0].co for v in row), Vector()) / m)
        for j in range(m):
            f = bm.faces.new((row[j][0], row[(j + 1) % m][0], c))
            f.material_index = 0
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mats['leather'])
    me.materials.append(quilt_mat)
    o = tag(bpy.data.objects.new(name, me))
    refresh()
    sub = o.modifiers.new('subsurf', 'SUBSURF')
    sub.levels = sub.render_levels = 1
    # (the centre's quilting is the texture only; quilt_panel() can add puffy diamonds at ~5 k tris a panel)
    if piping:
        for side, pts_ in (('L', edge_l), ('R', edge_r)):
            tube(f'{name}_piping_{side}', pts_, 0.0036, mats['orange'])
    for side, pts_ in (('L', seam_l), ('R', seam_r)):
        tube(f'{name}_stitch_{side}', pts_[1:-1], 0.0013, mats['stitch'])
    return o


QUILT_PUFF = 0.0055                      # how far each quilted diamond swells between its seams (m)


def quilt_panel(name, origin, along, lat, out, length, centre, depth, drop, quilt_t, mat, step=0.0067):
    """Puffy quilted centre panel laid over an upholstered shell: a dense grid on the shell's dished centre
    surface, each 40 mm diamond swelling QUILT_PUFF between the stitched seams. The diamond grid is the one the
    quilt texture is painted with (make_console_texture.paint_quilt, same UVs as the shell), so the printed
    stitches sit in the valleys. The puff fades out toward the panel's edge, where it meets the seam groove."""
    c0, r0, w, h = CL.REGION['quilt']
    k = CL.QUILT_PX_PER_M
    d_px = 0.040 * k
    t0, t1 = quilt_t
    n_t = max(4, int((t1 - t0) * length / step))
    n_y = 36
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    grid = []
    for i in range(n_t + 1):
        t = t0 + (t1 - t0) * i / n_t
        Wc = centre(t) * 0.97
        base = Vector(origin) + along * (length * t) + out * (drop(t) if drop else 0.0)
        row = []
        for j in range(n_y + 1):
            y = Wc * (2 * j / n_y - 1)
            xx, yy = (0.25 - y) * k, h - t * length * k
            fa, fb = ((xx + yy) % d_px) / d_px, ((xx - yy) % d_px) / d_px
            e = min(fa, 1 - fa, fb, 1 - fb) * 2                       # 0 on a seam, 1 mid-diamond
            to_edge = min(Wc - abs(y), (t - t0) * length, (t1 - t) * length)
            fade = min(1.0, to_edge / 0.010)
            f = depth - 0.004 * (1 - (y / max(Wc, 1e-6)) ** 2) + 0.0012 + QUILT_PUFF * e ** 0.55 * fade
            v = bm.verts.new(base + lat * y + out * f)
            row.append((v, ((c0 + xx) / CL.TEX_W, 1 - (r0 + yy) / CL.TEX_H)))
        grid.append(row)
    for i in range(n_t):
        for j in range(n_y):
            q = (grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j])
            fc = bm.faces.new([v for v, _ in q])
            for loop, (_, uv) in zip(fc.loops, q):
                loop[uvl].uv = uv
    bm.normal_update()
    out_v = Vector(out)
    for fc in bm.faces:
        if fc.normal.dot(out_v) < 0:
            fc.normal_flip()
    return mesh_object(name, bm, mat, smooth=True)


def tube(name, pts, r, mat, segs=8):
    """Round tube through a polyline (piping, stitch lines)."""
    bm = bmesh.new()
    rings = []
    for i, p in enumerate(pts):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        tng = (b - a).normalized()
        u = tng.orthogonal().normalized()
        v = tng.cross(u)
        rings.append([bm.verts.new(p + (u * math.cos(2 * math.pi * k / segs) + v * math.sin(2 * math.pi * k / segs)) * r)
                      for k in range(segs)])
    for a, b in zip(rings, rings[1:]):
        for k in range(segs):
            bm.faces.new((a[k], a[(k + 1) % segs], b[(k + 1) % segs], b[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return mesh_object(name, bm, mat, smooth=True)


def seat(name, x, y, mats, quilt_mat, width=0.43, back_tilt=14, places=(0,), headrests=True, clearance=0.025):
    """Seat as on the Sling 4 TSi: each seating place a sculpted cushion and a high back, black leather with a
    diamond-quilted centre panel stitched to rolled side bolsters, orange piping along the outer edges and, on the
    front seats, an integrated headrest with the embroidered logo. The rear bench is two such places on one frame,
    without headrests (the roof is too low there). Every piece is narrowed where the hull is, keeping `clearance`
    from the skin."""
    cz = FLOOR_Z + 0.115
    hw_seat = min(width / len(places), 0.43) / 2         # half-width of one seating place
    # frame / seat pan under the cushions, clipped to the hull at its narrowest (bottom, ends)
    hw_f = min(half_width(xx, FLOOR_Z + 0.005, clearance) for xx in (x - 0.2, x, x + 0.2))
    lo, hi = max(y - (width - 0.08) / 2, -hw_f), min(y + (width - 0.08) / 2, hw_f)
    box(f'{name}_frame', (x, (lo + hi) / 2, FLOOR_Z + 0.04), (0.40, hi - lo, 0.08), mats['panel'], bevel=0.01)
    t_rad = math.radians(back_tilt)
    up = Vector((-math.sin(t_rad), 0, math.cos(t_rad)))
    fwd = Vector((math.cos(t_rad), 0, math.sin(t_rad)))
    back_len = 0.80 if headrests else 0.58
    for i, hy in enumerate(places):
        py = y + hy
        # cushion: rear edge under the back, the front rolls down (waterfall)
        def cush_w(t, py=py):
            # the hull narrows toward the floor: fit at the cushion's bottom, margin for the rolled edge and piping
            return max(0.08, min(hw_seat - 0.02, half_width(x - 0.25 + 0.5 * t, FLOOR_Z + 0.075, clearance) - abs(py) - 0.026))

        upholstered(f'{name}_cushion_{i}', (x - 0.25, py, FLOOR_Z + 0.075), (1, 0, 0), (0, 1, 0), (0, 0, 1), 0.50,
                    width=cush_w, centre=lambda t, cush_w=cush_w: cush_w(t) * 0.56,
                    bolster=lambda t: 0.050 * (1 - smoothstep(0.8, 1.0, t)) + 0.012,
                    depth=0.07, mats=mats, quilt_mat=quilt_mat, quilt_t=(0.06, 0.82),
                    drop=lambda t: -0.03 * smoothstep(0.82, 1.0, t))
        # back: shoulders, then a neck into the integrated headrest; narrowed to the hull at every height
        origin = Vector((x - 0.29, py, cz - 0.01))

        def hull_w(t, origin=origin, py=py):
            p = origin + up * (back_len * t)
            return half_width(p.x - 0.03, p.z, clearance) - abs(py) - 0.026

        def back_w(t, hull_w=hull_w):
            if headrests:
                W = (hw_seat - 0.02) - (hw_seat - 0.02 - 0.115) * smoothstep(0.60, 0.70, t)   # + 2 cm roll
                W *= 1 - 0.25 * smoothstep(0.95, 1.0, t)          # rounded top
            else:
                W = (hw_seat - 0.02) * (1 - 0.15 * smoothstep(0.93, 1.0, t))
            return max(0.06, min(W, hull_w(t)))

        def back_centre(t, back_w=back_w):
            return back_w(t) * (0.56 if t < 0.6 else 0.60)

        def back_bolster(t):
            if headrests:
                return 0.070 * (1 - smoothstep(0.55, 0.68, t)) + 0.016
            return 0.05 * (1 - smoothstep(0.9, 1.0, t)) + 0.012

        upholstered(f'{name}_back_{i}', origin, up, (0, 1, 0), fwd, back_len, width=back_w, centre=back_centre,
                    bolster=back_bolster, depth=0.075, mats=mats, quilt_mat=quilt_mat,
                    quilt_t=(0.05, 0.62 if headrests else 0.80),
                    dome=(lambda t: 0.016 * smoothstep(0.64, 0.74, t) * (1 - smoothstep(0.95, 1.0, t))) if headrests else None)
        # embroidered logo: on the headrest, or at the top of the rear backs
        t_logo = 0.84 if headrests else 0.89
        logo_patch(f'{name}_logo_{i}', origin + up * (back_len * t_logo) + fwd * 0.0755, fwd, 0.10 if headrests else 0.09,
                   quilt_mat)


def check_clearance(skip=('Cabin_lining', 'Door_', 'Panel_', 'Glareshield', 'Cabin_floor', 'Firewall',
                          'Baggage_bulkhead', 'Interior_light', 'Console')):
    """Report cabin parts with any vertex outside the fuselage skin (lining and the hull-fitted
    panels are skipped; they sit on the skin by design)."""
    refresh()
    dg = bpy.context.evaluated_depsgraph_get()
    bad = []
    for o in _made:
        if o.type != 'MESH' or o.name.startswith(skip):
            continue
        me = o.evaluated_get(dg).to_mesh()
        worst = 0.0
        for v in me.vertices:
            p = o.matrix_world @ v.co
            if not (BULKHEAD_X < p.x < FIREWALL_X) or p.z < FLOOR_Z:
                continue
            hit = _hull.ray_cast(Vector((p.x, 0, p.z)), Vector((0, 1 if p.y >= 0 else -1, 0)), 2.0)[0]
            if hit:
                worst = max(worst, abs(p.y) - abs(hit.y) + LINING_INSET)   # must stay inside the lining
        o.evaluated_get(dg).to_mesh_clear()
        if worst > 0.001:
            bad.append((o.name, worst))
    for name, w in sorted(bad, key=lambda t: -t[1]):
        print(f'clearance: {name} crosses the lining by {w * 1000:.0f} mm')
    print(f'clearance check: {len(bad)} parts outside the lining')
    return bad


def door_latches(mats, doors):
    """Latch levers at the centre of each door's bottom edge (POH 7.7)."""
    for side, piv in doors.items():
        s = 1 if side == 'L' else -1
        y = half_width(0.78, 1.29, 0.03)
        box(f'Door_{side}_latch_base', (0.78, s * y, 1.285), (0.07, 0.012, 0.03), mats['bezel'], bevel=0.004, parent=piv)
        # the lever pivots at its aft end and is the clickable door handle (SlingTSi_Interior.xml)
        latch = empty(f'Door_{side}_latch', (0.735, s * (y - 0.012), 1.29), parent=piv)
        box(f'Door_{side}_latch_lever', (0.78, s * (y - 0.012), 1.29), (0.09, 0.012, 0.014), mats['metal'], bevel=0.004, parent=latch)


# ================================ magnetic compass (POH 6.2) ================================
def compass(mats, card_mat, outline):
    """Glareshield whiskey compass on the centre line: black housing on a mounting foot, a bezel frame round a clear
    window with the lubber line, the two compensator screws (N-S, E-W) and the card. The card rim carries the
    console-atlas strip (make_console_texture.paint_compass_card) and turns on Compass_card_pivot (compass_card_anim,
    WISKEY COMPASS INDICATION DEGREES). Reverse sensing, as a real card: the label facing the pilot is the heading,
    so it is printed 180 deg from where it points, and E shows left of the lubber line when heading north."""
    x_r = panel_x(PANEL_Z_TOP) + 0.004
    cz = panel_top_z(0, outline) + 0.012 - 0.12 * 0.17
    xc, zc = x_r + 0.12, cz + 0.024                      # housing centre
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    aft = xc - 0.026                                      # window face, towards the pilot
    # mounting foot with two screws, then the housing
    obox('Compass_foot', (xc + 0.004, 0, cz + 0.0015), (0.05, 0.07, 0.004), (X, Y, Z), mats['bezel'], bevel=0.0012)
    for s in (0.029, -0.029):
        screw(f'Compass_foot_screw_{s > 0}', Vector((xc + 0.004, s, cz + 0.0035)), Z, mats, r=0.0022)
    box('Compass_body', (xc + 0.003, 0, zc), (0.046, 0.062, 0.044), mats['bezel'], bevel=0.009, seg=3)
    # bezel frame round the window (top, bottom, sides), slightly proud of the housing
    win_w, win_h = 0.046, 0.022
    for name, cy, cz_, sy, sz in (('top', 0, zc + win_h / 2 + 0.004, win_w + 0.016, 0.008),
                                  ('bottom', 0, zc - win_h / 2 - 0.006, win_w + 0.016, 0.012),
                                  ('left', win_w / 2 + 0.004, zc, 0.008, win_h + 0.004),
                                  ('right', -win_w / 2 - 0.004, zc, 0.008, win_h + 0.004)):
        obox(f'Compass_bezel_{name}', (aft - 0.001, cy, cz_), (0.006, sy, sz), (X, Y, Z), mats['knob'], bevel=0.0015)
    # dark interior behind the card window
    obox('Compass_well', (aft + 0.049, 0, zc), (0.002, win_w + 0.004, win_h + 0.008), (X, Y, Z), mats['glass_dark'], bevel=0)
    # card: rim printed from the atlas, black top; centre of rotation on the vertical axis
    R_, H_ = CL.COMPASS_CARD_R, CL.COMPASS_CARD_H
    centre = Vector((aft + 0.004 + R_, 0, zc))
    piv = empty('Compass_card_pivot', centre)
    c0, r0, w, h = CL.REGION['compass_card']
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    n = 72
    rings = []
    for zz, v in ((H_ / 2, r0), (-H_ / 2, r0 + h)):
        ring = []
        for k in range(n + 1):
            phi = 2 * math.pi * k / n                     # anticlockwise from the nose, seen from above
            ring.append((bm.verts.new(centre + X * (R_ * math.cos(phi)) + Y * (R_ * math.sin(phi)) + Z * zz), k, v))
        rings.append(ring)
    for k in range(n):
        quad = (rings[0][k], rings[0][k + 1], rings[1][k + 1], rings[1][k])
        f = bm.faces.new([q[0] for q in quad])
        # strip coordinate (360 - heading shown on this side) rises with k, left to right as the pilot sees the
        # aft side; a face across the 0/360 wrap takes 1 on its k+1 side instead of 0
        u_k = ((360.0 * k / n + 180.0) % 360.0) / 360.0
        u_k1 = ((360.0 * (k + 1) / n + 180.0) % 360.0) / 360.0
        if u_k1 < u_k - 0.5:
            u_k1 += 1.0
        for loop, (_, kk, v) in zip(f.loops, quad):
            u = u_k if kk == k else u_k1
            loop[uvl].uv = ((c0 + w * u) / CL.TEX_W, 1 - v / CL.TEX_H)
    top = [bm.verts.new(centre + X * (R_ * math.cos(2 * math.pi * k / n)) + Y * (R_ * math.sin(2 * math.pi * k / n))
                        + Z * (H_ / 2)) for k in range(n)]
    hub = bm.verts.new(centre + Z * (H_ / 2 + 0.002))
    for k in range(n):
        bm.faces.new((top[k], top[(k + 1) % n], hub))
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-7)
    bm.normal_update()
    for f in bm.faces:
        if f.normal.dot(f.calc_center_median() - centre) < 0:
            f.normal_flip()
    mesh_object('Compass_card', bm, card_mat, piv, smooth=False)
    # window glass and the lubber line on it
    obox('Compass_glass', (aft - 0.0006, 0, zc), (0.0012, win_w + 0.002, win_h + 0.002), (X, Y, Z), mats['glass_clear'],
         bevel=0)
    obox('Compass_lubber', (aft + 0.001, 0, zc), (0.0008, 0.0016, win_h - 0.002), (X, Y, Z), mats['lubber'], bevel=0)
    # compensator screws in the lower bezel
    for name, s in (('NS', 0.012), ('EW', -0.012)):
        p = Vector((aft - 0.004, s, zc - win_h / 2 - 0.006))
        cylinder(f'Compass_comp_{name}', p, p - X * 0.0015, 0.0028, mats['chrome'], segs=14)
        obox(f'Compass_comp_{name}_slot', p - X * 0.0016, (0.0006, 0.0036, 0.0007), (X, Y, Z), mats['glass_dark'], bevel=0)
    return {'Compass_card_pivot': Z.copy()}


# ================================ ballistic parachute handle (POH 7.2.6, 9.5.2) ================================
CHUTE_PX = (683, 458)                    # item 20, bottom centre of the panel
CHUTE_PULL = 0.12                        # handle travel when pulled (m)


def torus(name, center, axis, R, r, mat, parent=None, nu=24, nv=10):
    """Ring of radius R and tube radius r around `axis` through `center`."""
    axis = Vector(axis).normalized()
    a = axis.orthogonal().normalized()
    b = axis.cross(a)
    bm = bmesh.new()
    grid = []
    for i in range(nu):
        t = 2 * math.pi * i / nu
        radial = a * math.cos(t) + b * math.sin(t)
        grid.append([bm.verts.new(Vector(center) + radial * (R + r * math.cos(2 * math.pi * j / nv)) +
                                  axis * (r * math.sin(2 * math.pi * j / nv))) for j in range(nv)])
    for i in range(nu):
        for j in range(nv):
            bm.faces.new((grid[i][j], grid[(i + 1) % nu][j], grid[(i + 1) % nu][(j + 1) % nv], grid[i][(j + 1) % nv]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return mesh_object(name, bm, mat, parent, smooth=True)


def chute_handle(mats, flag_mat):
    """BRS / Magnum rescue parachute activation handle: black mount with chrome guide bosses, red T-handle on a
    slide (Chute_handle_slide, pulled CHUTE_PULL out along the panel normal), a steel cable that shows once it is
    pulled, and the safety pin with its ring and REMOVE BEFORE FLIGHT streamer (Chute_pin_group, hidden when the
    pin is out). Interactions in SlingTSi_Interior.xml."""
    y, z = px_yz(*CHUTE_PX)
    up = Vector((math.sin(TILT), 0, math.cos(TILT)))
    Y = Vector((0, 1, 0))
    N = PANEL_N
    # mount plate (also the click spot to put the pin back), four screws
    obox('Chute_mount', on_panel(y, z, 0.002), (0.112, 0.044, 0.004), (Y, up, N), mats['bezel'], bevel=0.0015)
    for dy in (0.048, -0.048):
        for dz in (0.015, -0.015):
            screw(f'Chute_mount_screw_{dy > 0}_{dz > 0}', on_panel(y + dy, z + dz, 0.004), N, mats, r=0.002)
    for s_, dy in (('L', 0.030), ('R', -0.030)):
        cylinder(f'Chute_boss_{s_}', on_panel(y + dy, z, 0.004), on_panel(y + dy, z, 0.016), 0.0068, mats['chrome'],
                 segs=20, bevel=0.0012)
    # the cable that follows the handle out (visible once pulled)
    cylinder('Chute_cable', on_panel(y, z, 0.004), on_panel(y, z, 0.004 + CHUTE_PULL + 0.01), 0.0016, mats['metal'],
             segs=8)
    # T-handle on its slide
    slide = empty('Chute_handle_slide', on_panel(y, z, 0.004))
    for s_, dy in (('L', 0.030), ('R', -0.030)):
        cylinder(f'Chute_stem_{s_}', on_panel(y + dy, z, 0.012), on_panel(y + dy, z, 0.030), 0.0036, mats['red'],
                 segs=14, parent=slide)
    cylinder('Chute_handle_hub', on_panel(y, z, 0.026), on_panel(y, z, 0.031), 0.006, mats['red'], segs=16,
             bevel=0.001, parent=slide)
    # the grip is the click spot: a 100 mm red bar with rounded ends and finger ridges
    cylinder('Chute_handle', on_panel(y + 0.050, z, 0.036), on_panel(y - 0.050, z, 0.036), 0.0095, mats['red'],
             segs=24, bevel=0.0045, parent=slide)
    for i in range(7):
        dy = -0.036 + i * 0.012
        cylinder(f'Chute_handle_ridge_{i}', on_panel(y + dy + 0.0015, z, 0.036), on_panel(y + dy - 0.0015, z, 0.036),
                 0.0102, mats['red_dark'], segs=24, parent=slide)
    # safety pin through the left boss, ring and streamer
    pin = empty('Chute_pin_group', on_panel(y + 0.030, z, 0.010))
    cylinder('Chute_pin', on_panel(y + 0.030, z + 0.012, 0.010), on_panel(y + 0.030, z - 0.012, 0.010), 0.0016,
             mats['chrome'], segs=10, parent=pin)
    ring_c = on_panel(y + 0.030, z - 0.012 - 0.008, 0.010)
    torus('Chute_pin_ring', ring_c, Y, 0.008, 0.0012, mats['chrome'], parent=pin)
    # streamer: 240 x 25 mm red tape (as the default SF50's pin tags: long, softly bent, grommeted), printed
    # from the console atlas. It drapes aft and to the left of the console (it hangs right above it), with a gentle
    # S-bend and twist, two-sided with a thin edge.
    L_, W_ = CL.FLAG_SIZE
    top = ring_c - up * 0.008
    aft = Vector((N.x, 0, 0)).normalized()
    down = Vector((0, 0, -1))

    def path(t):
        return (top + aft * (0.075 * math.sqrt(t)) + Y * (0.12 * t ** 0.6) + down * (0.20 * t)
                + Y * (0.007 * math.sin(3 * math.pi * t)) + aft * (0.006 * math.sin(2 * math.pi * t)))

    n_seg = 32
    ts = [i / n_seg for i in range(n_seg + 1)]
    pts = [path(t) for t in ts]
    lengths = [0.0]
    for p0, p1 in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + (p1 - p0).length)
    scale = L_ / lengths[-1]                                       # stretch the path to the streamer length
    pts = [top + (p - top) * scale for p in pts]
    lengths = [l_ * scale for l_ in lengths]
    for p in pts:                                                  # keep clear of the console
        if abs(p.y) < CONSOLE_W + 0.01 and 0.10 < p.x < 1.28:
            top_z = 1.108 if p.x > 1.20 else console_top_z(p.x) if p.x < 1.02 else 0.94 + (p.x - 1.02) * 0.168 / 0.18
            if p.z < top_z + 0.01:
                print(f'chute streamer: point {tuple(round(c, 3) for c in p)} inside the console')
    c0, r0, w, h = CL.REGION['flag']
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    rows = []
    for i, p in enumerate(pts):
        tan = (pts[min(i + 1, n_seg)] - pts[max(i - 1, 0)]).normalized()
        wdir = tan.cross(aft).normalized()
        twist = 0.35 * math.sin(math.pi * ts[i])
        wdir = (wdir * math.cos(twist) + tan.cross(wdir) * math.sin(twist)).normalized()
        nrm = wdir.cross(tan).normalized()
        u = (c0 + w * lengths[i] / L_) / CL.TEX_W
        rows.append([(p + wdir * (W_ / 2) * k + nrm * 0.0005 * side, (u, 1 - (r0 + h * (0.5 - 0.5 * k)) / CL.TEX_H))
                     for side in (1, -1) for k in (1, -1)])
    verts = [[bm.verts.new(co) for co, _ in row] for row in rows]
    for i in range(n_seg):
        a0, a1 = verts[i], verts[i + 1]
        for quad, uv_idx in (((a0[0], a0[1], a1[1], a1[0]), (0, 1, 1, 0)),      # front face
                             ((a0[3], a0[2], a1[2], a1[3]), (3, 2, 2, 3)),      # back face
                             ((a0[1], a0[3], a1[3], a1[1]), (1, 3, 3, 1)),      # edges
                             ((a0[2], a0[0], a1[0], a1[2]), (2, 0, 0, 2))):
            f = bm.faces.new(quad)
            for loop, j, row in zip(f.loops, uv_idx, (i, i, i + 1, i + 1)):
                loop[uvl].uv = rows[row][j][1]
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh_object('Chute_pin_flag', bm, flag_mat, pin, smooth=True)
    # grommet through which the ring runs
    g_tan = (pts[2] - pts[0]).normalized()
    g_nrm = g_tan.cross(aft).normalized().cross(g_tan).normalized()
    torus('Chute_pin_grommet', pts[0] + g_tan * 0.008, g_nrm, 0.0042, 0.0011, mats['chrome'], parent=pin)
    return {'Chute_handle_slide': N.copy(), 'Chute_pin_group': Y.copy()}


# ================================ entry point ================================
PLACEHOLDERS = ('Cabin_floor', 'Instrument_panel', 'Display_L', 'Display_R', 'Control_stick_L', 'Control_stick_R',
                'Seat_front_L_back', 'Seat_front_L_cushion', 'Seat_front_R_back', 'Seat_front_R_cushion',
                'Seat_rear_L_back', 'Seat_rear_L_cushion', 'Seat_rear_R_back', 'Seat_rear_R_cushion')


def build(root, out_dir):
    """Replace the placeholder cabin with the full interior. Returns ({pivot: axis}, [object names])."""
    global _root
    _root = root
    for n in PLACEHOLDERS:
        if n in O:
            bpy.data.objects.remove(O[n], do_unlink=True)
    build_hull()

    mats = {
        'carpet': material('Carpet', (0.018, 0.018, 0.02), 0.97),
        'lining_plain': material('Lining_plain', (0.075, 0.075, 0.08), 0.9),
        'panel': material('Panel_black', (0.012, 0.012, 0.013), 0.5),
        'suede': material('Glareshield_suede', (0.008, 0.008, 0.009), 0.98),
        'bezel': material('Avionics_bezel', (0.02, 0.02, 0.022), 0.35),
        'glass_dark': material('Avionics_glass', (0.004, 0.005, 0.006), 0.05),
        'lcd': material('Avionics_lcd', (0.004, 0.006, 0.006), 0.08, emission=(0.012, 0.012, 0.014)),
        'button': material('Avionics_button', (0.05, 0.05, 0.055), 0.45),
        'knob': material('Knob_black', (0.015, 0.015, 0.016), 0.4),
        'switch': material('Switch_white', (0.6, 0.6, 0.6), 0.4),
        'red': material('Knob_red', (0.55, 0.02, 0.02), 0.35),
        'red_dark': material('Knob_red_dark', (0.3, 0.01, 0.01), 0.6),
        'blue': material('Knob_blue', (0.02, 0.12, 0.6), 0.35),
        'lamp_red': material('Lamp_red', (0.3, 0.01, 0.01), 0.1, emission=(0.05, 0.0, 0.0)),
        'lamp_amber': material('Lamp_amber', (0.35, 0.15, 0.01), 0.1),
        'prop_lamp': material('Prop_lamp_amber', (0.35, 0.15, 0.01), 0.1, emission=(1.0, 0.42, 0.04)),
        'metal': material('Brushed_metal', (0.55, 0.56, 0.58), 0.35, metal=1.0),
        'chrome': material('Chrome', (0.8, 0.8, 0.82), 0.12, metal=1.0),
        'glass_clear': material('Glass_clear', (0.9, 0.92, 0.94), 0.03),
        'lubber': material('Compass_lubber', (0.95, 0.45, 0.05), 0.4),
        'brass': material('Brass', (0.62, 0.45, 0.2), 0.3, metal=1.0),
        'screw': material('Screw_black', (0.03, 0.03, 0.032), 0.35, metal=0.6),
        'rubber': material('Rubber_black', (0.01, 0.01, 0.01), 0.85),
        'leather': material('Leather', (0.028, 0.026, 0.025), 0.5),
        'leather_insert': material('Leather_insert', (0.16, 0.15, 0.14), 0.55),
        'orange': material('Leather_orange', (0.62, 0.17, 0.02), 0.5),
        'stitch': material('Stitch_grey', (0.32, 0.32, 0.33), 0.7),
    }
    panel_face = material('Panel_face', (1, 1, 1), 0.28, image=panel_texture())
    gb = mats['glass_clear'].node_tree.nodes['Principled BSDF']           # compass window: clear, see-through
    gb.inputs['Alpha'].default_value = 0.12
    mats['glass_clear'].surface_render_method = 'BLENDED'
    console_face = material('Console_face', (1, 1, 1), 0.32, image=console_texture())
    # seat leather: the same atlas (quilting, logo), semi-matte like the real upholstery
    seat_leather = material('Seat_leather', (1, 1, 1), 0.6,
                            image=next(n.image for n in console_face.node_tree.nodes if n.type == 'TEX_IMAGE'))
    g5_screen = material('$G5_Screen', (0, 0, 0), 0.15)     # render target for the AS5 (G5) gauge

    livery = next(n.image for n in bpy.data.materials['Paint_livery'].node_tree.nodes if n.type == 'TEX_IMAGE')
    doors = lining(livery, out_dir)
    door_latches(mats, doors)
    floor_and_walls(mats)
    TOGGLE_PIVOTS.clear()
    outline = panel(mats, panel_face)
    glareshield(mats, outline)
    avionics(mats, g5_screen)
    prop_axes = prop_controller(mats, panel_face)
    panel_items(mats)
    console_axes = console(mats, console_face)
    chute_axes = chute_handle(mats, console_face)
    compass_axes = compass(mats, console_face, outline)
    stick('L', SEAT_Y, mats)
    stick('R', -SEAT_Y, mats)
    peds = pedals(mats)
    seat('Seat_front_L', 0.70, SEAT_Y, mats, seat_leather)
    seat('Seat_front_R', 0.70, -SEAT_Y, mats, seat_leather)
    # rear bench: the roof is too low there for headrests (about 1.62 m at the back top)
    seat('Seat_rear', -0.18, 0.0, mats, seat_leather, width=0.94, back_tilt=18, places=(0.25, -0.25), headrests=False)
    check_clearance()

    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    axes = {'Door_L_int': None, 'Door_R_int': None,
            'Throttle_lever': Y, 'Brake_lever': Y, 'Flap_knob': PANEL_N.copy(), 'Door_L_latch': Y, 'Door_R_latch': Y,
            'Stick_L_pitch': Y, 'Stick_R_pitch': Y, 'Stick_L_roll': X, 'Stick_R_roll': X}
    axes.update({k: Y for k in peds})
    axes.update(console_axes)
    axes.update(prop_axes)
    axes.update(chute_axes)
    axes.update(compass_axes)
    axes.update({k: Y for k in TOGGLE_PIVOTS})           # switch levers throw up/down
    axes['Key_pivot'] = PANEL_N.copy()                  # the key turns in the panel plane
    refresh()
    return axes, [o.name for o in _made]
