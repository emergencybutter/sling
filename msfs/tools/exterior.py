"""Exterior fixes on the generated Sling TSi model (runs inside Blender, from blender_export.py).

- livery(): swap in the anti-aliased livery / glass textures from make_livery.py and remap the
  fuselage-shell UVs from section angle to distance around the section (sling_shape.py).
- intakes(): the generator's inlets were flat dark patches on the cowl. Cut real openings in the
  cowling, with a rounded lip and a dark duct running back into the nose (radiator core in the chin).
- exhaust(): the pipe hung under the cowling without touching it. Rebuild it as a bent tailpipe that
  comes out through the cowling floor, with a collar at the exit and an open, sooty end.
- nose_ring(), cooling_exit(), gear_well(): the cowl's details that are not skin offsets (those are in
  sling_shape.skin_point): the rolled nose ring round the spinner with a dark bulkhead behind it, the open
  cooling exit slot under the lower cowl's aft edge, and the nose gear leg's opening in the keel.
- wheel_pants(): the 381 mm main tyres poked through the top of their fairings. Grow each fairing
  (about its bottom, so the ground clearance stays) until the tyre sits inside it with a margin.

Blender-model coordinates: metres, nose +X, left +Y, up +Z, on the ground.
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sling_shape as S  # noqa: E402

O = bpy.data.objects


def refresh():
    bpy.context.view_layer.update()


def world_bvh(o):
    dg = bpy.context.evaluated_depsgraph_get()
    me = o.evaluated_get(dg).to_mesh()
    tree = BVHTree.FromPolygons([o.matrix_world @ v.co for v in me.vertices], [p.vertices[:] for p in me.polygons])
    o.evaluated_get(dg).to_mesh_clear()
    return tree


def material(name, rgb, rough, metal=0.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    return m


def new_mesh_object(name, bm, mat, parent):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    refresh()
    o.parent = parent
    o.matrix_parent_inverse = parent.matrix_world.inverted()
    refresh()
    return o


def loft(rings, facing, cap=None, closed=True):
    """Quad strips between closed rings of equal length (lists of world Vectors).

    facing(centre, j) -> the direction face j of the ring should face (MSFS draws one side only).
    cap: (ring index, direction) to close that ring with a fan facing `direction`.
    closed=False lofts open arcs instead (no quad from the last point back to the first)."""
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    faces = []
    for a, b in zip(vs, vs[1:]):
        for j in range(n if closed else n - 1):
            faces.append((bm.faces.new((a[j], a[(j + 1) % n], b[(j + 1) % n], b[j])), j))
    if cap:
        ring = vs[cap[0]]
        c = bm.verts.new(sum((v.co for v in ring), Vector()) / n)
        for j in range(n):
            f = bm.faces.new((ring[j], ring[(j + 1) % n], c))
            faces.append((f, None))
    bm.normal_update()
    for f, j in faces:
        want = cap[1] if j is None else facing(f.calc_center_median(), j)
        if f.normal.dot(want) < 0:
            f.normal_flip()
    bm.normal_update()
    return bm


# ================================ cowling ================================
def _generator_point(X, a):
    """The generator's own skin point (no cowling corrections), to recognise skin vertices."""
    s = S.section(X)
    n = np.where(np.sin(a) >= 0, S.fNU(X), s['nL'])
    c, sn = np.cos(a), np.sin(a)
    Z = s['hw'] * S.spow(c, 2 / n)
    H = np.where(sn >= 0, s['hm'] + s['up'] * np.abs(sn) ** (2 / n), s['hm'] - s['dn'] * np.abs(sn) ** (2 / n))
    return H, Z


def cowl():
    """Reshape the skin ahead of the firewall to sling_shape's corrected cowling (flat upper cowl, prop boss).
    Every livery-shell vertex there keeps its (X, a) grid place, read from the generator's UVs, and moves to
    S.skin_point(X, a); vertices off the generator's skin (by > 4 mm) are left alone. Run before livery()."""
    shells = [o for o in O if o.type == 'MESH' and o.data.materials and o.data.materials[0].name == 'Paint_livery'
              and o.data.uv_layers]
    for o in shells:
        me, mw = o.data, o.matrix_world
        inv = mw.inverted()
        uvl = me.uv_layers.active
        seen, moved = set(), 0
        for loop in me.loops:
            vi = loop.vertex_index
            if vi in seen:
                continue
            seen.add(vi)
            u, v = uvl.data[loop.index].uv
            X = S.XN + u * (S.XT - S.XN)
            if X >= S.FIREWALL_X:
                continue
            a = (1 - v) * 2 * np.pi
            w = mw @ me.vertices[vi].co
            H0, Z0 = _generator_point(X, a)
            if abs(w.x - (S.XC - X) / 1000) > 0.004 or math.hypot(w.z - H0 / 1000, -w.y - Z0 / 1000) > 0.004:
                continue
            H, Z = S.skin_point(X, a)
            me.vertices[vi].co = inv @ Vector(S.to_blender(X, float(H), float(Z)))
            moved += 1
        me.update()
        print(f'cowl: reshaped {moved} vertices of {o.name}')


# ================================ livery ================================
def livery(tex_dir):
    """Load the repainted textures into the livery and glass materials and remap the shell UVs."""
    swaps = {'Paint_livery': 'SlingTSi_LIVERY_albd.png', 'Glass': 'SlingTSi_GLASS_albd.png'}
    for mat_name, fname in swaps.items():
        img = bpy.data.images.load(os.path.join(tex_dir, fname), check_existing=True)
        for n in bpy.data.materials[mat_name].node_tree.nodes:
            if n.type == 'TEX_IMAGE':
                n.image = img
    grid = S.arc_fraction_grid()
    shells = [o for o in O if o.type == 'MESH' and o.data.materials and
              o.data.materials[0].name in swaps and o.data.uv_layers]
    for o in shells:
        uvl = o.data.uv_layers.active
        uv = np.empty(len(uvl.data) * 2)
        uvl.data.foreach_get('uv', uv)
        uv = uv.reshape(-1, 2)
        # the generator's UVs: u = (X - XN) / (XT - XN), v = 1 - a / 2pi (Blender's v is flipped)
        X = S.XN + uv[:, 0] * (S.XT - S.XN)
        a = (1 - uv[:, 1]) * 2 * np.pi
        uv[:, 1] = 1 - S.arc_fraction(X, a, grid)
        uvl.data.foreach_set('uv', uv.ravel())
    print(f'livery: remapped UVs of {", ".join(o.name for o in shells)}')


# ================================ grafted nose ================================
REFERENCE_SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'reference', 'cowl.json')


def _spec():
    import json
    with open(REFERENCE_SPEC) as f:
        return json.load(f)


def _reference_glb():
    return os.path.join(os.path.dirname(REFERENCE_SPEC), _spec()['glb'])


def _skin_radius(X, Z, H):
    """Radius about (0, hm) of our own skin, before the dome, in the direction of (Z, H) at station X."""
    a = _generator_angle(X, Z, H)
    Hs, Zs = S._skin_point_base(X, np.array([a]))              # before the dome, which is added to both afterwards
    return math.hypot(float(Zs[0]), float(Hs[0]) - float(S.section(X)['hm']))

GRAFT_X = 1170.0            # mm: the fuselage ring the grafted cowl meets (just aft of the firewall)
GRAFT_FRONT = 380.0         # mm: by here the reference's own face has taken over from our 285 mm nose ring
GRAFT_AFT = 1050.0          # mm: from here the reference is warped onto the cabin section at GRAFT_X
GRAFT_OUT = 30.0            # mm outside the smoothed cowl beyond which reference faces are dropped (gear, clutter)
GRAFT_SMOOTH = 8            # smoothing passes over the reference's surface
GRAFT_OUT_SHELL = 150.0     # mm: a clean shell has nothing hanging off it (its chin lip stands below the smoothed table)
FILL_ON_SHELL = 80.0        # mm: for a shell every hole is capped (its own inlets and tears; ours are cut after)
INLET_ZONE = 420.0          # mm behind the ring: holes there are inlets (ducts), further aft access openings (capped)
INLET_DEPTH = 90.0          # mm the inlet ducts run back
SEAM_OVERLAP = 15.0         # mm our own skin is kept above the cut, under the reference (no hairline gaps)
SEAM = 40.0                 # mm above a keep_below_h cut over which the reference is laid onto our own skin
HIDDEN = 15.0               # mm: a face is skin if a ray from ahead or from outside meets it within this
FILL_ON = 25.0              # mm: a hole whose rim lies this close to the smoothed cowl is an access opening, patched
RECESS = 30.0               # mm deeper than the surface round it, seen from ahead, on a forward-facing face: an inlet


def _polar(X, Z, H):
    """(hm, polar angle about (0, hm) on the |Z| side, radius) of a point at station X."""
    hm = float(S.section(X)['hm'])
    return hm, math.atan2(H - hm, abs(Z)), math.hypot(Z, H - hm)


_angle_cache = {}


def _generator_angle(X, Z, H):
    """The generator section angle a (0..2pi) whose skin point lies in the direction of (Z, H) from (0, hm)."""
    key = round(X)
    if key not in _angle_cache:
        s0 = S.section(float(key))
        ag = np.linspace(0, 2 * math.pi, 4097)
        Zg, Hg = S._generator_points(s0, ag)
        th = np.unwrap(np.arctan2(Hg - float(s0['hm']), Zg))
        _angle_cache[key] = (th, ag, float(s0['hm']))
    th, ag, hm = _angle_cache[key]
    t = math.atan2(H - hm, Z) % (2 * math.pi)
    return float(np.interp(t, th, ag))


def graft_nose():
    """Replace the fuselage ahead of GRAFT_X with the reference cowl (reference/cowl.json names the GLB). It is
    mapped into our frame as tools/meshy_cowl.py mapped it (landmarks and scales stored in its table), trimmed of the
    spinner or prop flange, a fused nose gear, what is hidden inside and loose bits, its access openings capped, its
    front pulled onto our nose
    ring round the spinner and its rear warped onto the cabin section at GRAFT_X, given livery UVs (arc-length space,
    as livery() makes them) and joined into the Fuselage. Its inlet recesses take the dark duct material, so
    exterior.intakes() is not run on a grafted nose."""
    for o in [o for o in O if o.name.startswith('Cowl_inlet')]:   # the generator's inlet trims
        bpy.data.objects.remove(o, do_unlink=True)
    spec = _spec()
    d = np.load(S.COWL_TABLE)
    x_tip, x_ring, x_fw, z_axis, f_top, f_bot, f_hw = (float(v) for v in d['landmarks'])
    kx, k_up, k_dn, k_z = (float(v) for v in d['scales'])
    before = set(O)
    bpy.ops.import_scene.gltf(filepath=_reference_glb())
    new = [o for o in O if o not in before]
    ref = [o for o in new if o.type == 'MESH'][0]
    bm = bmesh.new()
    bm.from_mesh(ref.data)
    mw = ref.matrix_world.copy()
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    for v in bm.verts:                                         # working frame (X, Z starboard, H), mm
        p = mw @ v.co
        if spec.get('forward', '-x') == '-y':                  # nose toward -y: turn it to -x (z up kept)
            p = Vector((p.y, -p.x, p.z))
        dz = p.z - z_axis
        v.co = Vector((S.XN + (p.x - x_ring) * kx, p.y * k_z, S.PROP_AXIS_H + dz * (k_up if dz > 0 else k_dn)))
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.5)  # glTF import splits vertices per face (flat shading)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(S.XN, 0, 0),
                           plane_no=(1, 0, 0), clear_inner=True)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(GRAFT_X, 0, 0),
                           plane_no=(1, 0, 0), clear_outer=True)
    # cowl.json keep_below_h: only the reference above this height (mm) is grafted, our own cowl is kept below it
    # (a photo-made reference whose underside, dark and cluttered in the photos, came out as junk)
    h_cut = _spec().get('keep_below_h')
    if h_cut is not None:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, h_cut),
                               plane_no=(0, 0, 1), clear_inner=True)
    # cowl.json keep_ahead_x: our own nose (sling_shape's rounded bump, our cut inlets) ahead of this station (mm)
    x_cut = _spec().get('keep_ahead_x')
    if x_cut is not None:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(x_cut, 0, 0),
                               plane_no=(1, 0, 0), clear_inner=True)

    # trim what stands off the cowl (a fused nose gear, exhaust stubs, things beside it in the photo); keep the
    # largest piece
    dead = []
    for f in bm.faces:
        c = f.calc_center_median()
        hm, phi, r = _polar(c.x, c.y, c.z)
        if r > float(S.cowl_radius(c.x, phi)) + (GRAFT_OUT_SHELL if spec.get('inlets') else GRAFT_OUT):
            dead.append(f)
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    # and what is hidden inside: an engine seen through an access hole, the shell's inner side. Skin is met first by
    # a ray from ahead or by one coming in from outside along the section radius.
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    hidden = []
    for f in bm.faces:
        c = f.calc_center_median()
        h = tree.ray_cast(Vector((S.XN - 500, c.y, c.z)), Vector((1, 0, 0)), 3000.0)[0]
        if h is not None and h.x > c.x - HIDDEN:
            continue
        hm = float(S.section(c.x)['hm'])
        dvec = Vector((0.0, c.y, c.z - hm))
        if dvec.length < 1e-6:
            continue
        dvec.normalize()
        h = tree.ray_cast(c + dvec * 1500.0, -dvec, 3000.0)[0]
        if h is not None and (h - c).length < HIDDEN:
            continue
        hidden.append(f)
    # cowl.json hollow_shell (a clean shell with real inlet holes): its inside is kept whole and shaded dark, as seen
    # through the inlets; otherwise (a scan with an engine or clutter inside) the hidden faces are deleted
    # cowl.json inlets (a hollow shell with its own inlet holes): the inside is deleted like the rest, every hole in
    # the skin is capped and our own inlets are cut where cowl.json puts them (exterior.intakes)
    shell = bool(spec.get('inlets'))
    dark = set()
    bmesh.ops.delete(bm, geom=hidden, context='FACES')
    print(f'graft: dropped {len(dead)} faces hanging below, {len(hidden)} hidden inside')
    bm.faces.ensure_lookup_table()
    seen, best = set(), []
    for f0 in bm.faces:
        if f0 in seen:
            continue
        comp, stack = [], [f0]
        seen.add(f0)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g not in seen:
                        seen.add(g)
                        stack.append(g)
        if len(comp) > len(best):
            best = comp
    keep = set(best)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')

    # access openings (an unpainted cowl's open doors): boundary loops off the two cuts whose rim lies on the smoothed
    # cowl are capped, the caps subdivided and their new vertices laid onto the smoothed cowl
    h_rim = -1e9 if h_cut is None else h_cut + 2

    x_rim = (S.XN if x_cut is None else x_cut) + 2

    def on_cut(v):
        return not (x_rim < v.co.x < GRAFT_X - 2 and v.co.z > h_rim)

    free = [e for e in bm.edges if e.is_boundary and not any(on_cut(v) for v in e.verts)]
    loops, done = [], set()
    for e0 in free:
        if e0 in done:
            continue
        comp, stack = [], [e0]
        done.add(e0)
        while stack:
            e = stack.pop()
            comp.append(e)
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2.is_boundary and e2 not in done and not any(on_cut(w) for w in e2.verts):
                        done.add(e2)
                        stack.append(e2)
        loops.append(comp)
    capped = 0
    inlet_loops = []
    for comp in loops:
        vs = {v for e in comp for v in e.verts}
        off = []
        for v in vs:
            hm, phi, r = _polar(v.co.x, v.co.y, v.co.z)
            off.append(abs(r - float(S.cowl_radius(v.co.x, phi))))
        if len(comp) < 6 or float(np.median(off)) > (FILL_ON_SHELL if shell else FILL_ON):
            continue
        res = bmesh.ops.holes_fill(bm, edges=comp, sides=0)
        faces = res['faces']
        if not faces:
            continue
        tri = bmesh.ops.triangulate(bm, faces=faces)['faces']
        inner_e = list({e for f in tri for e in f.edges if all(g in tri for g in e.link_faces) and len(e.link_faces) == 2})
        sub = bmesh.ops.subdivide_edges(bm, edges=inner_e, cuts=3, use_grid_fill=True)
        newv = [v for v in sub['geom_inner'] if isinstance(v, bmesh.types.BMVert)]
        for _ in range(3):
            for v in newv:
                hm, phi, r = _polar(v.co.x, v.co.y, v.co.z)
                rt = float(S.cowl_radius(v.co.x, phi))
                side = 1.0 if v.co.y >= 0 else -1.0
                v.co = Vector((v.co.x, side * rt * math.cos(phi), hm + rt * math.sin(phi)))
            bmesh.ops.smooth_vert(bm, verts=newv, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        capped += 1
    print(f'graft: {len(loops)} openings, {capped} capped, {len(inlet_loops)} inlets')

    # the AI mesh's rivets, panel-line ridges and lumps: a few smoothing passes (the cut edges stay)
    inner = [v for v in bm.verts if not v.is_boundary]
    co0 = [v.co.copy() for v in inner]
    for _ in range(GRAFT_SMOOTH):
        bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    moved = [(v.co - c).length for v, c in zip(inner, co0)]
    print(f'graft: smoothed {len(inner)} vertices, mean move {sum(moved) / max(len(moved), 1):.1f} mm, '
          f'max {max(moved, default=0):.1f} mm')
    # front onto our nose ring, rear onto the cabin section: radial shifts about (0, hm). The reference's ring is its
    # front edge (at the X 290 cut, or just behind it): its radius by polar angle (8 deg bins round the |Z| side, the
    # inner edge of the face).
    bins = np.linspace(-math.pi / 2, math.pi / 2, 24)
    edge = [[] for _ in bins]
    x_front = min(v.co.x for v in bm.verts) if x_cut is None else -1e9
    for v in bm.verts:
        if v.co.x < x_front + 3.0:
            hm, phi, r = _polar(v.co.x, v.co.y, v.co.z)
            if r > 100.0:                                      # not a prop hub left inside the ring
                edge[int(np.argmin(np.abs(bins - phi)))].append(r)
    ring = np.array([min(e) if e else np.nan for e in edge])
    ok = np.isfinite(ring)
    if ok.any():
        ring = np.interp(bins, bins[ok], ring[ok])
        print(f'graft: reference ring radius {ring.min():.0f}..{ring.max():.0f} mm onto {S.RING_R:.1f}')
    ag = np.linspace(-math.pi / 2, math.pi / 2, 721)
    for v in bm.verts:
        X = v.co.x
        a = 0.0 if x_cut is not None else 1 - float(S._smoothstep(S.XN, GRAFT_FRONT, X))
        b = float(S._smoothstep(GRAFT_AFT, GRAFT_X, X))
        if a <= 0 and b <= 0:
            continue
        hm, phi, r = _polar(X, v.co.y, v.co.z)
        if a > 0:
            r += (S.RING_R - float(np.interp(phi, bins, ring))) * a
        if b > 0:
            Zg, Hg = S._generator_points(S.section(X), ag)
            rg = float(np.interp(phi, np.arctan2(Hg - hm, Zg), np.hypot(Zg, Hg - hm)))
            r = rg if X > GRAFT_X - 0.5 else r + (rg - r) * b
        side = 1.0 if v.co.y >= 0 else -1.0
        v.co = Vector((X, side * r * math.cos(phi), hm + r * math.sin(phi)))

    # along the keep_below_h / keep_ahead_x cuts, lay the reference onto our own skin so the two meet
    if h_cut is not None or x_cut is not None:
        for v in bm.verts:
            th = 1.0 if h_cut is None else (v.co.z - h_cut) / SEAM
            tx = 1.0 if x_cut is None else (v.co.x - x_cut) / SEAM
            t = min(th, tx)
            if t >= 1:
                continue
            w = 1 - float(S._smoothstep(0.0, 1.0, max(t, 0.0)))
            X = v.co.x
            hm, phi, r = _polar(X, v.co.y, v.co.z)
            r += (_skin_radius(X, v.co.y, v.co.z) - r) * w
            side = 1.0 if v.co.y >= 0 else -1.0
            v.co = Vector((X, side * r * math.cos(phi), hm + r * math.sin(phi)))

    # the dome over the top of the nose and the cheeks (sling_shape.dome_lift, cheek_lift), as on our own skin; on
    # top nothing of the reference may stand above our domed skin (its raised access door is not on the real cowl)
    tops = {}
    for v in (bm.verts if S.shape_lifts() else []):
        X = v.co.x
        if X >= S.FIREWALL_X:
            continue
        key = round(X)
        if key not in tops:
            tops[key] = S.skin_top_base(float(key))
        hm, phi, r = _polar(X, v.co.y, v.co.z)
        lift = float(S.dome_lift(X, phi, tops[key])) + float(S.cheek_lift(X, phi))
        if phi > math.radians(10):
            r = min(r, _skin_radius(X, v.co.y, v.co.z) + 4.0)
        r += lift
        side = 1.0 if v.co.y >= 0 else -1.0
        v.co = Vector((X, side * r * math.cos(phi), hm + r * math.sin(phi)))

    # inlet ducts: each inlet hole's rim run back INLET_DEPTH and narrowed, then closed; shaded dark
    duct_faces = set()
    for comp in inlet_loops:
        vs = list({v for e in comp for v in e.verts})
        c = sum((v.co for v in vs), Vector()) / len(vs)
        res = bmesh.ops.extrude_edge_only(bm, edges=comp)
        new_v = [g for g in res['geom'] if isinstance(g, bmesh.types.BMVert)]
        duct_faces |= {g for g in res['geom'] if isinstance(g, bmesh.types.BMFace)}
        for v in new_v:
            v.co = v.co + Vector((INLET_DEPTH, 0, 0)) + (c - v.co) * 0.25
        rim = [g for g in res['geom'] if isinstance(g, bmesh.types.BMEdge) and g.is_boundary]
        duct_faces |= set(bmesh.ops.holes_fill(bm, edges=rim, sides=0)['faces'])

    # livery UVs (faces across the a = 0 seam, starboard at mid-height, keep their low side above 1: the texture
    # repeats) and the inlet recesses: faces in the front of the cowl lying RECESS deeper, seen from ahead, than the
    # surface 70 mm round them, and facing forward (not the top, which only looks deeper from ahead)
    bm.normal_update()
    grid = S.arc_fraction_grid()
    uvl = bm.loops.layers.uv.new('UVMap')
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    recess = set(duct_faces) | {f for f in dark if f.is_valid}
    for f in bm.faces:
        uvs = []
        for loop in f.loops:
            X, Z, H = loop.vert.co
            a = _generator_angle(X, Z, H)
            uvs.append(((X - S.XN) / (S.XT - S.XN), 1 - float(S.arc_fraction(np.array([X]), np.array([a]), grid)[0])))
        vs = [v for _, v in uvs]
        if max(vs) - min(vs) > 0.5:
            uvs = [(u, v + 1 if v < 0.5 else v) for u, v in uvs]
        for loop, uv in zip(f.loops, uvs):
            loop[uvl].uv = uv
        c = f.calc_center_median()
        if not shell and c.x < S.XN + 230 and f.normal.x < -0.4 and                 (h_cut is None or c.z > h_cut + SEAM):
            ring = []
            for k in range(8):
                t = 2 * math.pi * k / 8
                h = tree.ray_cast(Vector((S.XN - 300, c.y + 70 * math.cos(t), c.z + 70 * math.sin(t))),
                                  Vector((1, 0, 0)), 2000.0)[0]
                if h is not None:
                    ring.append(h.x)
            if len(ring) >= 5 and c.x - float(np.median(ring)) > RECESS:
                recess.add(f)

    # into the fuselage: drop its faces ahead of GRAFT_X, append the graft in its local frame
    fus = O['Fuselage']
    fm = fus.data
    names = [m.name for m in fm.materials]
    if 'Intake_duct' not in names:
        fm.materials.append(material('Intake_duct', (0.012, 0.012, 0.013), 0.7))
        names.append('Intake_duct')
    livery_i, duct_i = names.index('Paint_livery'), names.index('Intake_duct')
    mwf = fus.matrix_world
    inv = mwf.inverted()
    fb = bmesh.new()
    fb.from_mesh(fm)
    nose = [f for f in fb.faces if all(S.XC - (mwf @ v.co).x * 1000 < GRAFT_X + 0.5 for v in f.verts)
            and (h_cut is None or all((mwf @ v.co).z * 1000 > h_cut + SEAM_OVERLAP for v in f.verts))
            and (x_cut is None or all(S.XC - (mwf @ v.co).x * 1000 > x_cut + SEAM_OVERLAP for v in f.verts))]
    bmesh.ops.delete(fb, geom=nose, context='FACES')
    bmesh.ops.delete(fb, geom=[v for v in fb.verts if not v.link_faces], context='VERTS')
    fuv = fb.loops.layers.uv.active
    vmap = {v: fb.verts.new(inv @ Vector(S.to_blender(v.co.x, v.co.z, v.co.y))) for v in bm.verts}
    added = 0
    for f in bm.faces:
        try:
            nf = fb.faces.new([vmap[v] for v in f.verts])
        except ValueError:                                     # a duplicate face in the reference
            continue
        nf.material_index = duct_i if f in recess else livery_i
        nf.smooth = True
        for la, lb in zip(f.loops, nf.loops):
            lb[fuv].uv = la[uvl].uv
        added += 1
    bm.free()
    fb.normal_update()
    fb.to_mesh(fm)
    fb.free()
    fm.update()
    print(f'graft: reference nose, {added} faces in place of {len(nose)} fuselage faces ahead of X {GRAFT_X:.0f}, '
          f'{len(recess)} of them recessed inlets')


# ================================ nose ring ================================
def nose_ring(root):
    """The cowl's nose ring: its rolled leading edge, a bead of S.RING_LIP (roll radius, forward curl) round the
    285 mm opening, curling forward and in from the skin's front edge, and a dark bulkhead closing the opening behind
    the spinner backplate. The bead tapers out across the bottom, where the chin grille's lip is tucked under the
    ring, and the bulkhead stops at the grille's top edge so the grille's duct stays open."""
    white = bpy.data.materials['Paint_white']
    dark = material('Intake_duct', (0.012, 0.012, 0.013), 0.7)
    roll, fwd = S.RING_LIP
    N = 180
    th = np.linspace(0, 2 * np.pi, N, endpoint=False)             # polar angle about the thrust line, 0 = starboard
    off_bottom = np.abs(np.angle(np.exp(1j * (th + np.pi / 2))))   # angular distance from the bottom (rad)
    taper = 0.05 + 0.95 * S._smoothstep(math.radians(32), math.radians(50), off_bottom)

    def pt(x, r, t):
        return Vector(S.to_blender(x, S.PROP_AXIS_H + r * math.sin(t), r * math.cos(t)))

    rings = []
    for u in np.linspace(0, math.pi, 7):                           # u = 0 on the skin's edge, pi at the inner edge
        rings.append([pt(S.XN - fwd * k * math.sin(u), S.RING_R - roll * k * (1 - math.cos(u)), t)
                      for t, k in zip(th, taper)])
    cores = [pt(S.XN, S.RING_R - roll * k, t) for t, k in zip(th, taper)]
    new_mesh_object('Cowl_ring', loft(rings, lambda c, j: c - cores[j]), white, root)
    disc = [pt(S.XN + 2.0, S.RING_R - 1.0, t) for t in th]
    for v in disc:                                                 # flat-bottomed, above the chin grille
        v.z = max(v.z, 1050.0 / 1000)
    new_mesh_object('Cowl_ring_bulkhead', loft([disc], None, cap=(0, Vector((1, 0, 0)))), dark, root)
    print(f'cowl: nose ring, {roll:.0f} mm roll curling {fwd:.0f} mm forward, bulkhead behind it')


# ================================ cooling exit ================================
def _fuselage_stations(fus):
    """Distinct station X (mm) of the fuselage shell's vertices."""
    mw = fus.matrix_world
    return sorted({round(S.XC - (mw @ v.co).x * 1000, 1) for v in fus.data.vertices})


def _arc(X, phis, exit_lip=True, inset=0.0):
    """Skin points at station X and polar angles `phis` about (0, hm), `inset` mm inside the skin, as Vectors."""
    H, Z = S.skin_point(X, S._A, exit_lip)
    hm = float(S.section(X)['hm'])
    phi = np.arctan2(H - hm, Z)
    r = np.hypot(Z, H - hm)
    o = np.argsort(phi)
    rr = np.interp(phis, phi[o], r[o]) - inset
    return [Vector(S.to_blender(X, hm + ri * math.sin(p), ri * math.cos(p))) for ri, p in zip(rr, phis)]


def cooling_exit(root):
    """Open the cooling exit: the lower cowl's proud aft edge (S.EXIT_LIP) ends at the last cowl station as a free
    edge. The skin faces that closed it onto the fuselage belly, over the arc where the lip stands, are removed. Under
    the cowl floor a dark duct floor runs forward S.EXIT_DEPTH to a bulkhead, so the slot reads as an exit and
    nothing inside shows, and the cowl's trailing edge gets a strip of thickness."""
    fus = O['Fuselage']
    mw = fus.matrix_world
    white = bpy.data.materials['Paint_white']
    dark = material('Intake_duct', (0.012, 0.012, 0.013), 0.7)
    xs = _fuselage_stations(fus)
    x_c = max(x for x in xs if x < S.FIREWALL_X)                   # the last cowl station
    x_f = min(x for x in xs if x >= S.FIREWALL_X)                  # the first cabin station
    hm_c = float(S.section(x_c)['hm'])
    # the closing faces: between the two stations, on the arc where the lip stands clear of the belly
    bm = bmesh.new()
    bm.from_mesh(fus.data)
    dead = []
    for f in bm.faces:
        X = [S.XC - (mw @ v.co).x * 1000 for v in f.verts]
        if min(X) < x_c - 0.5 or max(X) > x_f + 0.5 or not (x_c + 1 < sum(X) / len(X) < x_f - 1):
            continue
        c = mw @ f.calc_center_median()
        Z, H = -c.y * 1000, c.z * 1000
        if (H - hm_c) / math.hypot(Z, H - hm_c) < -0.5:
            dead.append(f)
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bm.to_mesh(fus.data)
    bm.free()
    # the duct floor, 6 mm inside the floor the lip is added to, from the bulkhead forward to the cowl's edge, then
    # onto the cabin skin at the first cabin station; it reaches round past the opening, under the skin
    a0 = math.asin(0.3)
    phis = np.linspace(-math.pi + a0, -a0, 72)
    x0 = max(x_c - S.EXIT_DEPTH, S.GEAR_WELL[1] + 12)             # the bulkhead stays behind the gear well
    rings = [_arc(x0, phis)]                                       # the bulkhead's outer edge, on the skin
    for x in np.linspace(x0, x_c, 5):
        rings.append(_arc(float(x), phis, exit_lip=False, inset=6.0))
    rings.append(_arc(x_f, phis))
    xb0 = (S.XC - x0) / 1000

    def facing(c, j):
        if abs(c.x - xb0) < 1e-5:                                  # the bulkhead faces aft
            return Vector((-1, 0, 0))
        return Vector((0, c.y, c.z - hm_c / 1000))                 # the floor faces out of the section
    new_mesh_object('Cowl_exit_duct', loft(rings, facing, closed=False), dark, root)
    # the trailing edge's thickness, over the open arc
    open_ = np.sin(phis) < -0.5
    edge = [[v for v, k in zip(_arc(x_c, phis, inset=d), open_) if k] for d in (0.0, 4.0)]
    new_mesh_object('Cowl_exit_edge', loft(edge, lambda c, j: Vector((-1, 0, 0)), closed=False), white, root)
    print(f'cowl: cooling exit opened over {len(dead)} faces between X {x_c:.0f} and {x_f:.0f}, '
          f'duct {S.EXIT_DEPTH:.0f} mm deep')


# ================================ nose gear well ================================
def gear_well(root):
    """The nose gear leg's opening in the keel channel (S.GEAR_WELL): a rounded rectangle cut in the cowl floor, a
    raised flange round it that hides the cut, and a dark well above it. The generator's leg stopped short of the
    channel floor with an open top; its top is raised into the well."""
    x0, x1, hw, rc, depth = S.GEAR_WELL
    fus = O['Fuselage']
    mw = fus.matrix_world
    white = bpy.data.materials['Paint_white']
    dark = material('Intake_duct', (0.012, 0.012, 0.013), 0.7)
    cx, w, h = (x0 + x1) / 2, x1 - x0, 2 * hw
    outline, normals = rounded_rect(w, h, rc)                     # (along X, Z) round the well's centre

    def belly(X, Z, up=0.0):
        return Vector(S.to_blender(X, float(S.belly_height(X, np.array([Z]))[0]) + up, Z))

    # flange: (offset from the outline, mm, + outward; height off the skin, mm, down)
    rings = []
    for off, proud in ((10, 0.0), (5, 2.5), (0, 3.0), (-3, 1.5)):
        rings.append([belly(cx + dx + nx * off, dz + nz * off, -proud) for (dx, dz), (nx, nz) in zip(outline, normals)])
    cores = [belly(cx + dx + nx, dz + nz, 4.0) for (dx, dz), (nx, nz) in zip(outline, normals)]
    new_mesh_object('Nose_gear_well_flange', loft(rings, lambda c, j: c - cores[j]), white, root)
    # the well: from the flange's inner edge straight up, narrowing a little, closed at the top
    mouth = [belly(cx + dx - nx * 3, dz - nz * 3) for (dx, dz), (nx, nz) in zip(outline, normals)]
    well = [mouth]
    for up, shrink in ((12.0, 3.0), (depth, 8.0)):
        well.append([p + Vector((nx * shrink, nz * shrink, up)) / 1000 for p, (nx, nz) in zip(mouth, normals)])   # inward: x = -X, y = -Z
    xb_c = (S.XC - cx) / 1000
    new_mesh_object('Nose_gear_well', loft(well, lambda c, j: Vector((xb_c - c.x, -c.y, 0)),
                                           cap=(len(well) - 1, Vector((0, 0, -1)))), dark, root)
    # open the floor inside the flange
    bm = bmesh.new()
    bm.from_mesh(fus.data)
    dead = []
    for f in bm.faces:
        c = mw @ f.calc_center_median()
        X, Z, H = S.XC - c.x * 1000, -c.y * 1000, c.z * 1000
        if inside_rounded_rect(X - cx, Z, w + 8, h + 8, rc + 4) and H < float(S.section(X)['hm']):
            dead.append(f)
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bm.to_mesh(fus.data)
    bm.free()
    # the leg's top, up into the well
    leg = O.get('Nose_gear_leg')
    raised = 0
    if leg:
        lmw, lme = leg.matrix_world, leg.data
        inv = lmw.inverted()
        for v in lme.vertices:
            p = lmw @ v.co
            if p.z > 0.69:
                v.co = inv @ Vector((p.x, p.y, p.z + 0.07))
                raised += 1
        lme.update()
    print(f'cowl: gear well {w:.0f} x {h:.0f} mm at X {cx:.0f}, opened {len(dead)} faces, leg top raised ({raised} vertices)')


# ================================ intakes ================================
# Inlets: centre (H, Z), width, height, corner radius (mm; None: teardrop), duct depth (mm). The cheek inlets are
# elongated teardrops either side of the spinner, recessed behind the nose ring in their concave pockets
# (sling_shape.POCKET); the chin scoop under the spinner is a broad, low rounded trapezoid.
EGG = 0.15                                                        # the outer end this much narrower
EYE_TILT = 12.0                                                   # deg, outer tip up
# Sized and placed from the front photo (Documents/photos/images(4).jpg, the 280 mm spinner as the ruler) and the POH
# front view: the cheek inlets 112 x 76 mm eggs, centred 228 mm out and 16 mm above the thrust line, in their pockets
# (sling_shape.POCKET); under the spinner a wide radiator grille and, below its lip, a second one.
INLETS = [('Cowl_inlet_L', 1188, -232, 132, 90, None, 150),     # + the lip's inward 5 mm: 112 x 76 visible
          ('Cowl_inlet_R', 1188, 232, 132, 90, None, 150),
          ('Cowl_inlet_lower', 978, 0, 330, 112, 30, 170),       # upper grille, tucked under the nose ring (1027.5)
          ('Cowl_inlet_lower_2', 864, 0, 300, 66, 26, 120)]      # lower grille, below a 25 mm lip


# ================================ spinner ================================
SPINNER_R = 140.0           # mm, backplate radius (280 mm, Airmaster AP430 class)
SPINNER_GAP = 6.0           # mm, clear gap between the backplate and the nose ring


def spinner():
    """Scale the spinner radially to the 280 mm backplate and move it SPINNER_GAP forward of the nose ring."""
    o = O['Spinner']
    mw, me = o.matrix_world, o.data
    inv = mw.inverted()
    pts = [mw @ v.co for v in me.vertices]
    axis_z = S.PROP_AXIS_H / 1000
    rmax = max(math.hypot(p.y, p.z - axis_z) for p in pts)
    k = SPINNER_R / 1000 / rmax
    for v, p in zip(me.vertices, pts):
        v.co = inv @ Vector((p.x + SPINNER_GAP / 1000, p.y * k, axis_z + (p.z - axis_z) * k))
    me.update()
    print(f'spinner: backplate radius {rmax * 1000:.0f} -> {SPINNER_R:.0f} mm, {SPINNER_GAP:.0f} mm gap')


def rounded_rect(w, h, r, n_side=6, n_corner=8):
    """Closed outline (list of (dz, dh)) counter-clockwise seen from the front, plus outward normals."""
    pts, nrm = [], []
    corners = [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)]
    for k, (cx, cy, a0) in enumerate(corners):
        for i in range(n_corner):
            a = math.radians(a0 + 90 * i / n_corner)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            nrm.append((math.cos(a), math.sin(a)))
        # straight side to the next corner
        nx, ny = corners[(k + 1) % 4][0:2]
        a1 = math.radians(a0 + 90)
        sx, sy = cx + r * math.cos(a1), cy + r * math.sin(a1)
        ex, ey = nx + r * math.cos(a1), ny + r * math.sin(a1)
        for i in range(n_side):
            t = i / n_side
            pts.append((sx + (ex - sx) * t, sy + (ey - sy) * t))
            nrm.append((math.cos(a1), math.sin(a1)))
    return pts, nrm


def eye(w, h, outer, n=64):
    """Closed egg outline, as rounded_rect: rounded all round, fuller at the inner end, a little narrower at the outer
    end (toward `outer`, +1 / -1 in dz), rotated EYE_TILT up (photos: Documents/photos/images(4).jpg)."""
    t_ = math.radians(EYE_TILT) * outer
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        u = math.cos(t)                                           # +1 at the outer end
        x, y = outer * w / 2 * u, h / 2 * math.sin(t) * (1 - EGG * u)
        pts.append((x * math.cos(t_) - y * math.sin(t_), x * math.sin(t_) + y * math.cos(t_)))
    if outer < 0:
        pts.reverse()                                             # keep it counter-clockwise
    nrm = []
    for i in range(n):
        (ax, ay), (bx, by) = pts[i - 1], pts[(i + 1) % n]
        tx, ty = bx - ax, by - ay
        L = math.hypot(tx, ty)
        nrm.append((ty / L, -tx / L))
    return pts, nrm


def inside_polygon(x, y, poly):
    inside = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def inside_rounded_rect(dz, dh, w, h, r):
    if abs(dz) > w / 2 or abs(dh) > h / 2:
        return False
    cx = min(max(dz, -w / 2 + r), w / 2 - r)
    cy = min(max(dh, -h / 2 + r), h / 2 - r)
    return (dz - cx) ** 2 + (dh - cy) ** 2 <= r * r


def intakes(root, only=None, inlets=None):
    fus = O['Fuselage']
    hull = world_bvh(fus)
    white = bpy.data.materials['Paint_white']
    duct_mat = material('Intake_duct', (0.012, 0.012, 0.013), 0.7)
    core_mat = material('Radiator_core', (0.05, 0.05, 0.055), 0.45, metal=0.6)

    def front_hit(Z, H):
        """First cowling hit looking aft at (Z, H) mm: (point, outward normal)."""
        y, z = -Z / 1000, H / 1000
        loc, n, _, _ = hull.ray_cast(Vector((4.5, y, z)), Vector((-1, 0, 0)), 4.0)
        if loc is None:                    # inside the spinner-base ring: on the cowl's front plane
            return Vector((S.to_blender(S.XN, H, Z))), Vector((1, 0, 0))
        return loc, (n if n.x > 0 else -n)

    for o in [o for o in O if o.name.startswith('Cowl_inlet')]:
        bpy.data.objects.remove(o, do_unlink=True)

    cut_total = 0
    for name, H0, Z0, w, h, r, depth in (inlets or INLETS):
        if only and name not in only:
            continue
        outline, normals = rounded_rect(w, h, r) if r else eye(w, h, 1 if Z0 > 0 else -1)
        grown = [(dz + nz * 4, dh + nh * 4) for (dz, dh), (nz, nh) in zip(outline, normals)]
        # lip profile: (offset from the outline, mm, + outward; height off the skin along its normal, mm)
        lip = [(12, 0.6), (8, 4.0), (4, 6.5), (0, 6.5), (-3, 4.0), (-5, 0.0)]
        rings = []
        for off, proud in lip:
            ring = []
            for (dz, dh), (nz, nh) in zip(outline, normals):
                p, n = front_hit(Z0 + dz + nz * off, H0 + dh + nh * off)
                ring.append(p + n * proud / 1000)
            rings.append(ring)
        # duct: straight back (aft = -X) from the inner lip, narrowing a little
        inner = [front_hit(Z0 + dz + nz * -5, H0 + dh + nh * -5)[0] for (dz, dh), (nz, nh) in zip(outline, normals)]
        duct = [rings[-1]]
        for back, shrink in ((0.02, 6), (depth * 0.5 / 1000, 9), (depth / 1000, 12)):
            duct.append([Vector((min(p.x for p in inner) - back, p.y, p.z)) +
                         Vector((0, -nz, nh)) * (-shrink + 5) / 1000
                         for p, (nz, nh) in zip(inner, normals)])
        # the lip faces away from its core (just under the crest); the duct faces its own axis
        cores = []
        for (dz, dh), (nz, nh) in zip(outline, normals):
            p, n = front_hit(Z0 + dz + nz * 1, H0 + dh + nh * 1)
            cores.append(p - n * 0.004)
        axis = Vector((0, -Z0 / 1000, H0 / 1000))
        new_mesh_object(f'{name}_lip', loft(rings, lambda c, j: c - cores[j]), white, root)
        new_mesh_object(f'{name}_duct', loft(duct, lambda c, j: Vector((c.x, axis.y, axis.z)) - c,
                                             cap=(len(duct) - 1, Vector((1, 0, 0)))), duct_mat, root)
        if name.startswith('Cowl_inlet_lower'):               # radiator / intercooler core behind the chin
            xb = duct[-1][0].x + 0.012
            bm = bmesh.new()
            for i in range(9):
                hz = H0 - h / 2 + 30 + i * (h - 60) / 8
                c = Vector((xb, -Z0 / 1000, hz / 1000))
                geom = bmesh.ops.create_cube(bm, size=1.0)
                for v in geom['verts']:
                    v.co = c + Vector((v.co.x * 0.012, v.co.y * (w - 70) / 1000, v.co.z * 0.004))
            new_mesh_object(f'{name}_core', bm, core_mat, root)

        # open the cowling: drop the skin faces inside the outline on the front face
        bm = bmesh.new()
        bm.from_mesh(fus.data)
        mw = fus.matrix_world
        dead = []
        for f in bm.faces:
            c = mw @ f.calc_center_median()
            Z, H = -c.y * 1000, c.z * 1000
            if not (inside_rounded_rect(Z - Z0, H - H0, w + 8, h + 8, r + 4) if r else    # the lip hides the cut
                    inside_polygon(Z - Z0, H - H0, grown)):
                continue
            hit = hull.ray_cast(Vector((4.5, c.y, c.z)), Vector((-1, 0, 0)), 4.0)[0]
            if hit is not None and abs(hit.x - c.x) < 0.05:
                dead.append(f)
        bmesh.ops.delete(bm, geom=dead, context='FACES')
        bm.to_mesh(fus.data)
        bm.free()
        cut_total += len(dead)
        print(f'intake {name}: opened {len(dead)} cowling faces')
    return cut_total


# ================================ exhaust ================================
def exhaust(root):
    """Tailpipe out through the cowling floor on the right, bent aft and down (mm path, 3-view frame)."""
    hull = world_bvh(O['Fuselage'])
    old = O.get('Exhaust')
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    steel = material('Exhaust_steel', (0.32, 0.30, 0.28), 0.42, metal=1.0)
    soot = material('Exhaust_soot', (0.015, 0.014, 0.013), 0.85)
    trim = bpy.data.materials['Trim_black']
    # quadratic Bezier: from inside the cowling, down through its floor, then aft and down
    P0, P1, P2 = (Vector(S.to_blender(*p)) for p in ((1030, 860, 175), (1060, 610, 178), (1210, 590, 182)))
    R, N, SEG = 0.026, 24, 20
    path = [(1 - t) ** 2 * P0 + 2 * (1 - t) * t * P1 + t * t * P2 for t in (i / (SEG - 1) for i in range(SEG))]

    def frame(i):
        a, b = path[max(i - 1, 0)], path[min(i + 1, SEG - 1)]
        T = (b - a).normalized()
        U = T.cross(Vector((0, 1, 0))).normalized()
        return T, U, T.cross(U)

    def ring(c, U, V, r):
        return [c + (U * math.cos(2 * math.pi * k / N) + V * math.sin(2 * math.pi * k / N)) * r for k in range(N)]

    outer = [ring(p, *frame(i)[1:], R) for i, p in enumerate(path)]
    T, U, V = frame(SEG - 1)
    end = path[-1]
    lip = [ring(end + T * 0.002, U, V, R * 0.93), ring(end, U, V, R * 0.82)]         # rolled rim
    def off_axis(c):
        q = min(path, key=lambda p: (p - c).length)
        return c - q
    new_mesh_object('Exhaust', loft(outer + lip, lambda c, j: off_axis(c)), steel, root)
    inner = [ring(end - T * d, U, V, R * 0.82) for d in (0.0, 0.05)]
    new_mesh_object('Exhaust_inner', loft(inner, lambda c, j: -off_axis(c), cap=(1, T.copy())), soot, root)
    # where it leaves the cowling: a dark collar in the cutout
    start, d = path[0], (path[-1] - path[0]).normalized()
    hit = None
    for i in range(SEG - 1):
        seg = path[i + 1] - path[i]
        h = hull.ray_cast(path[i], seg.normalized(), seg.length)
        if h[0] is not None:
            hit, j = h[0], i
            break
    if hit is None:
        raise RuntimeError('exhaust: the pipe never crosses the cowling')
    T, U, V = frame(j)
    collar = [ring(hit + T * s, U, V, R * 1.35) for s in (-0.012, 0.008)]
    new_mesh_object('Exhaust_collar', loft(collar, lambda c, j: off_axis(c)), trim, root)
    print(f'exhaust: leaves the cowling at {tuple(round(c, 3) for c in hit)}')


# ================================ wheel pants ================================
def wheel_pants(margin=0.015, slot=0.035):
    """Scale each fairing about its lowest point until its tyre is inside with `margin`, except the
    part of the tyre within `slot` of the fairing bottom (the opening the tyre runs through)."""
    for side in ('L', 'R', 'Nose'):
        pant, tyre = O[f'Wheel_fairing_{side}'], O[f'Tyre_{side}']
        if pant.data.users > 1:
            pant.data = pant.data.copy()
        refresh()
        base = pant.data.copy()
        pw = [pant.matrix_world @ v.co for v in base.vertices]
        z0 = min(p.z for p in pw)
        axle = tyre.matrix_world.translation
        pivot = Vector((axle.x, axle.y, z0))
        tv = [tyre.matrix_world @ v.co for v in tyre.data.vertices]
        tv = [p for p in tv if p.z > max(z0 + slot, axle.z - 0.05)]    # the lower tyre runs through the slot

        def fits(k):
            pts = [pivot + (p - pivot) * k for p in pw]
            tree = BVHTree.FromPolygons(pts, [p.vertices[:] for p in base.polygons])
            for p in tv:
                d = p - axle
                d.y = 0
                out = d.normalized() if d.length > 1e-6 else Vector((0, 0, 1))
                probe = p + out * margin
                if tree.ray_cast(probe, Vector((0, 0, 1)), 2.0)[0] is None:
                    return False
                side_dir = Vector((0, 1 if p.y > axle.y else -1, 0))
                if tree.ray_cast(p + side_dir * margin, side_dir, 2.0)[0] is None:
                    return False
            return True

        if fits(1.0):
            print(f'wheel pant {side}: tyre already inside')
            bpy.data.meshes.remove(base)
            continue
        lo, hi = 1.0, 1.6
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if fits(mid) else (mid, hi)
        k = hi
        mw = pant.matrix_world
        S_ = Matrix.Translation(pivot) @ Matrix.Scale(k, 4) @ Matrix.Translation(-pivot)
        pant.data.transform(mw.inverted() @ S_ @ mw)
        bpy.data.meshes.remove(base)
        print(f'wheel pant {side}: scaled x{k:.3f} about its bottom')


# ================================ pitot / AOA probe ================================
def pitot(root, span_y=2.9):
    """Heated pitot / AOA probe under the left wing (POH 7.8: "below the left wing ... a second hole for the
    measurement of the angle of attack", a Garmin GAP 26 type). The spanwise station is not published [GUESS:
    mid-span, inboard of the aileron]. A streamlined mast drops from the lower skin at ~15% chord and carries an
    L-shaped tube whose tip sits just ahead of the leading edge."""
    wing = O['Wing_L']
    tree = world_bvh(wing)
    metal = bpy.data.materials['Metal']
    dark = material('Pitot_hole', (0.01, 0.01, 0.01), 0.8)
    # wing chord at this station (index.html wingStation): leading and trailing edge, Blender x
    f = min(max((span_y * 1000 - 972) / 3528, 0), 1)
    xle = (3300 - (1908 + 136 * f)) / 1000
    chord = (1512 - 424 * f) / 1000
    x_mast = xle - 0.15 * chord

    def lower_skin(x):
        hit = tree.ray_cast(Vector((x, span_y, -1.0)), Vector((0, 0, 1)), 5.0)[0]
        if hit is None:
            raise RuntimeError(f'pitot: no wing at x {x:.3f}, y {span_y}')
        return hit

    top = lower_skin(x_mast)
    depth, mast_chord, mast_t = 0.115, 0.055, 0.013
    # mast: streamlined (lens) sections lofted from just inside the skin down to the tube
    sections = []
    for k, dz in enumerate((0.006, -0.004, -depth * 0.5, -depth)):
        c = mast_chord * (1.0 if k < 2 else 0.85 if k == 2 else 0.7)
        t = mast_t * (1.0 if k < 2 else 0.9 if k == 2 else 0.8)
        ring = []
        for j in range(16):
            a = 2 * math.pi * j / 16
            ring.append(Vector((top.x + 0.5 * c * math.cos(a) - 0.1 * c, span_y + 0.5 * t * math.sin(a) * (1 - 0.3 * max(0, -math.cos(a))),
                                top.z + dz)))
        sections.append(ring)
    centre = Vector((top.x - 0.1 * mast_chord, span_y, top.z))
    new_mesh_object('Pitot_mast', loft(sections, lambda c, j: Vector((c.x - centre.x, c.y - centre.y, 0)),
                                       cap=(len(sections) - 1, Vector((0, 0, -1)))), metal, root)
    # doubler plate where the mast meets the skin
    plate = [[Vector((top.x + 0.04 * math.cos(2 * math.pi * j / 20) - 0.006, span_y + 0.016 * math.sin(2 * math.pi * j / 20),
                      top.z + dz)) for j in range(20)] for dz in (0.0025, -0.0005)]
    new_mesh_object('Pitot_plate', loft(plate, lambda c, j: Vector((c.x - top.x, c.y - span_y, -0.2)),
                                        cap=(1, Vector((0, 0, -1)))), metal, root)
    # tube: from behind the mast forward to just ahead of the leading edge, tapering to the tip
    z_t = top.z - depth + 0.006
    x0, x1 = top.x - 0.045, xle + 0.035
    r_tube = 0.0095
    rings, n = [], 18
    for x, r in ((x0, r_tube * 0.8), (x0 + 0.01, r_tube), (x1 - 0.05, r_tube), (x1 - 0.012, r_tube * 0.8), (x1, r_tube * 0.55)):
        rings.append([Vector((x, span_y + r * math.cos(2 * math.pi * j / n), z_t + r * math.sin(2 * math.pi * j / n)))
                      for j in range(n)])
    new_mesh_object('Pitot_tube', loft(rings, lambda c, j: Vector((0, c.y - span_y, c.z - z_t)),
                                       cap=(0, Vector((-1, 0, 0)))), metal, root)
    # pitot hole in the tip, and the AOA port on the underside of the nose
    hole = [[Vector((x1 + 0.0004, span_y + 0.0028 * math.cos(2 * math.pi * j / 12), z_t + 0.0028 * math.sin(2 * math.pi * j / 12)))
             for j in range(12)]]
    hole.append([p + Vector((0.0002, 0, 0)) for p in hole[0]])
    new_mesh_object('Pitot_hole', loft(hole, lambda c, j: Vector((1, 0, 0)), cap=(1, Vector((1, 0, 0)))), dark, root)
    aoa_c = Vector((x1 - 0.022, span_y, z_t - r_tube * 0.97))
    aoa = [[aoa_c + Vector((0.0022 * math.cos(2 * math.pi * j / 12), 0.0022 * math.sin(2 * math.pi * j / 12), dz))
            for j in range(12)] for dz in (0.0, -0.0004)]
    new_mesh_object('Pitot_aoa_port', loft(aoa, lambda c, j: Vector((0, 0, -1)), cap=(1, Vector((0, 0, -1)))), dark, root)
    print(f'pitot: mast at x {top.x:.3f} (15% chord), tip at x {x1:.3f}, y {span_y}, {depth * 1000:.0f} mm below the skin')


# ================================ wingtip nav / strobe units ================================
def wing_lights(root):
    """Combined wingtip light units (Whelen / Aveo style): a clear lens fairing on the outer face of each tip over a
    red (left) or green (right) nav LED, a white strobe tube and an aft-facing white position light, on a black base
    with a reflector. Replaces the generator's 24 mm spheres; the emitters keep the names blender_export.py turns
    into LIGHT_* EmMesh nodes (systems.cfg [LIGHTS])."""
    for n in ('Nav_light_L', 'Nav_light_R', 'Strobe_L', 'Strobe_R'):
        if n in O:
            bpy.data.objects.remove(O[n], do_unlink=True)
    lens_mat = bpy.data.materials.get('Light_lens') or bpy.data.materials.new('Light_lens')
    lens_mat.use_nodes = True
    b = lens_mat.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (0.92, 0.94, 0.96, 1)
    b.inputs['Roughness'].default_value = 0.05
    b.inputs['Alpha'].default_value = 0.22
    lens_mat.surface_render_method = 'BLENDED'
    base_mat = material('Light_base', (0.015, 0.015, 0.016), 0.55)
    refl_mat = bpy.data.materials['Metal']
    emit = material('Light_emitter_placeholder', (1, 1, 1), 0.3)        # blender_export swaps in the light colours
    placed = {}
    for side, s, wing, nav in (('L', 1, 'Wing_L_tip', 'Nav_light_L'), ('R', -1, 'Wing_R_tip', 'Nav_light_R')):
        tree = world_bvh(O[wing])
        hit, n = None, None
        for zz in (1.13, 1.12, 1.14, 1.10, 1.16):
            h = tree.ray_cast(Vector((0.47, 6.0 * s, zz)), Vector((0, -s, 0)), 6.0)
            if h[0] is not None:
                hit, n = h[0], h[1]
                break
        if hit is None:
            raise RuntimeError(f'wing lights: no {wing} surface found')
        n = Vector((0, s, 0))                                   # face straight outboard
        ax = Vector((1, 0, 0))
        up = Vector((0, 0, 1))
        c = hit - n * 0.002
        L_, H_, D_ = 0.060, 0.018, 0.026                       # lens half-length, half-height, depth (m)

        def dome(name, centre, rx, rz, depth, mat, segs=24):
            """Outer half of an ellipsoid on the plane through `centre` normal to n."""
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(8, segs // 2), radius=1.0)
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0),
                                   plane_no=(0, 1, 0), clear_inner=True)
            for v in bm.verts:
                v.co = centre + ax * (v.co.x * rx) + n * (max(v.co.y, 0.0) * depth) + up * (v.co.z * rz)
            bm.normal_update()
            for f in bm.faces:
                if f.normal.dot(f.calc_center_median() - centre) < 0:
                    f.normal_flip()
            return new_mesh_object(name, bm, mat, root)

        dome(f'Light_lens_{side}', c, L_, H_, D_, lens_mat, segs=40)
        # black bezel: an oval plate a little larger than the lens, on the tip surface
        ring = [[c + ax * ((L_ + 0.005) * math.cos(2 * math.pi * k / 40)) + up * ((H_ + 0.004) * math.sin(2 * math.pi * k / 40))
                 + n * d for k in range(40)] for d in (0.0, 0.0025)]
        new_mesh_object(f'Light_base_{side}', loft(ring, lambda p, j: n.copy(), cap=(1, n.copy())), base_mat, root)
        # polished reflector tray inside the lens
        refl = [[c + n * 0.0028 + ax * ((L_ - 0.008) * math.cos(2 * math.pi * k / 32))
                 + up * ((H_ - 0.005) * math.sin(2 * math.pi * k / 32)) for k in range(32)]]
        refl.append([p + n * 0.0006 for p in refl[0]])
        new_mesh_object(f'Light_reflector_{side}', loft(refl, lambda p, j: n.copy(), cap=(1, n.copy())), refl_mat, root)
        # emitters (named for EmMesh): domed LED cluster forward, capsule strobe tube, small white aft light
        base = c + n * 0.0034
        e_nav = base + ax * 0.034
        e_str = base - ax * 0.004
        e_pos = base - ax * 0.044
        dome(nav, e_nav, 0.013, 0.010, 0.009, emit, segs=20)
        axis_c = e_str + n * 0.0035
        tube = [[axis_c + ax * xx + (n * math.sin(2 * math.pi * k / 16) + up * math.cos(2 * math.pi * k / 16)) * 0.0035 * rr
                 for k in range(16)] for xx, rr in ((-0.016, 0.4), (-0.014, 1.0), (0.014, 1.0), (0.016, 0.4))]
        new_mesh_object(f'Strobe_{side}', loft(tube, lambda p, j: p - (axis_c + ax * (p - axis_c).dot(ax)),
                                               cap=(3, ax.copy())), emit, root)
        dome(f'Nav_light_W{side}', e_pos, 0.008, 0.008, 0.007, emit, segs=16)
        placed[side] = {'nav': e_nav, 'strobe': e_str, 'white': e_pos}
    for side, p in placed.items():
        print(f'wing lights {side}: ' + ', '.join(f'{k} {tuple(round(v, 3) for v in xyz)}' for k, xyz in p.items()))
    return placed


# ================================ landing / taxi lights ================================
def landing_lights(root, span_y=3.85):
    """Landing / taxi light unit in each wing's leading edge, toward the tip (POH walk-around: "Taxi/Landing Light
    Lens" on each wing between the nav light and the leading edge): a clear lens following the leading edge over two
    chrome reflector cups, landing (inboard, straight ahead) and taxi (outboard, toed out), in a black bezel.
    Emitters are named for blender_export.py's LIGHT_* EmMesh nodes. Spanwise station [GUESS]."""
    lens_mat = bpy.data.materials['Light_lens']
    base_mat = bpy.data.materials['Light_base']
    chrome = material('Light_chrome', (0.85, 0.86, 0.88), 0.08, metal=1.0)
    emit = bpy.data.materials['Light_emitter_placeholder']
    placed = {}
    for side, s, wing in (('L', 1, 'Wing_L'), ('R', -1, 'Wing_R')):
        tree = world_bvh(O[wing])
        y0 = s * span_y

        def hit_at(y, z):
            h = tree.ray_cast(Vector((3.5, y, z)), Vector((-1, 0, 0)), 4.0)
            return h[0], h[1]
        # the leading edge: the most forward point of the section, scanning height
        best = None
        for k in range(61):
            z = 0.85 + 0.30 * k / 60
            p, n = hit_at(y0, z)
            if p is not None and (best is None or p.x > best[0].x):
                best = (p, n, z)
        if best is None:
            raise RuntimeError(f'landing lights: no leading edge on {wing}')
        z_le = best[2]
        half_span, half_h, n_y, n_z = 0.085, 0.024, 13, 9
        grid = []
        for i in range(n_y):
            row = []
            for j in range(n_z):
                y = y0 + half_span * (2 * i / (n_y - 1) - 1)
                z = z_le + half_h * (2 * j / (n_z - 1) - 1)
                p, n = hit_at(y, z)
                if p is None:
                    raise RuntimeError('landing lights: wing surface missing')
                n = n if n.x > 0 else -n
                row.append((p, n, (2 * i / (n_y - 1) - 1), (2 * j / (n_z - 1) - 1)))
            grid.append(row)
        # lens: a shallow dome over the patch, meeting the skin at its rim
        bm = bmesh.new()
        vs = [[bm.verts.new(p + n * (0.0012 + 0.007 * max(0.0, 1 - u * u) ** 0.5 * max(0.0, 1 - v * v) ** 0.5))
               for p, n, u, v in row] for row in grid]
        for i in range(n_y - 1):
            for j in range(n_z - 1):
                bm.faces.new((vs[i][j], vs[i + 1][j], vs[i + 1][j + 1], vs[i][j + 1]))
        bm.normal_update()
        for f in bm.faces:
            if f.normal.x < 0:
                f.normal_flip()
        new_mesh_object(f'Landing_lens_{side}', bm, lens_mat, root)
        # black bezel / recess behind the lens: the same patch just proud of the skin
        bm = bmesh.new()
        vs = [[bm.verts.new(p + n * 0.0008) for p, n, u, v in row] for row in grid]
        for i in range(n_y - 1):
            for j in range(n_z - 1):
                bm.faces.new((vs[i][j], vs[i + 1][j], vs[i + 1][j + 1], vs[i][j + 1]))
        bm.normal_update()
        for f in bm.faces:
            if f.normal.x < 0:
                f.normal_flip()
        new_mesh_object(f'Landing_bay_{side}', bm, base_mat, root)
        # reflector cups and LED emitters: landing inboard (straight ahead), taxi outboard (toed out 12 deg)
        le = grid[n_y // 2][n_z // 2][0]
        for name, dy, toe in (('Landing', -s * 0.038, 0.0), ('Taxi', s * 0.038, s * 12.0)):
            c = Vector((le.x, y0 + dy, z_le))
            p, n = hit_at(c.y, c.z)
            axis = Vector((math.cos(math.radians(toe)), math.sin(math.radians(toe)), 0))
            cup = [[p + axis * (0.0012 + 0.004 * (1 - rr)) + (Vector((0, 1, 0)) * math.cos(a) + Vector((0, 0, 1)) * math.sin(a)) * (0.017 * rr)
                    for a in [2 * math.pi * kk / 20 for kk in range(20)]] for rr in (1.0, 0.6, 0.25)]
            new_mesh_object(f'{name}_reflector_{side}', loft(cup, lambda q, j, axis=axis: axis.copy(),
                                                               cap=(2, axis.copy())), chrome, root)
            led = [[p + axis * 0.0055 + (Vector((0, 1, 0)) * math.cos(a) + Vector((0, 0, 1)) * math.sin(a)) * 0.006
                    for a in [2 * math.pi * kk / 16 for kk in range(16)]]]
            led.append([q + axis * 0.0008 for q in led[0]])
            new_mesh_object(f'{name}_light_{side}', loft(led, lambda q, j, axis=axis: axis.copy(), cap=(1, axis.copy())),
                            emit, root)
            placed[f'{name}_{side}'] = p
    for k, p in placed.items():
        print(f'landing lights {k}: {tuple(round(c, 3) for c in p)}')
    return placed
