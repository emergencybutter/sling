"""Sample the cowling of a reference aircraft mesh into the radius table sling_shape.py builds the nose from
(run inside Blender with --factory-startup).

    blender -b --factory-startup -P meshy_cowl.py -- reference/cowl.json OUT.npz

reference/cowl.json names the reference GLB (next to it) and its landmarks in its own units: x_ring (where the
cowl starts behind the spinner or prop flange), x_fw (the firewall / cowl joint) and z_axis (the thrust line).

The reference (reference/meshy_cowling.glb, an AI-generated Sling-like aircraft: one fused mesh, nose toward -x,
z up, +y starboard, arbitrary units) has the right cowl shape but not the Sling's proportions. Its cowl, from the
nose ring to the windscreen base (the firewall), is mapped onto ours: x to X 290..1165, and the section scaled
separately above the thrust line, below it and across so it meets the cabin section exactly at the firewall. Each
station's section is then sampled as the radius about (0, hm) at polar angles about the section centre, port and
starboard averaged, and smoothed to take out the mesh's rivets and noise. The table is (X, angle) -> radius, mm.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sling_shape as S  # noqa: E402

import json  # noqa: E402

spec_path, out = sys.argv[sys.argv.index('--') + 1:][:2]
with open(spec_path) as f:
    spec = json.load(f)
src = os.path.join(os.path.dirname(os.path.abspath(spec_path)), spec['glb'])
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=src)
ob = [o for o in bpy.data.objects if o.type == 'MESH'][0]
V = np.array([ob.matrix_world @ v.co for v in ob.data.vertices])
if spec.get('forward', '-x') == '-y':                         # nose toward -y: turn it to -x (z up kept)
    V = np.stack([V[:, 1], -V[:, 0], V[:, 2]], 1)
F = [tuple(p.vertices) for p in ob.data.polygons]
raw = BVHTree.FromPolygons([Vector(v) for v in V], F)


def hit(o, d):
    h = raw.ray_cast(Vector(o), Vector(d))[0]
    return h


# ---- reference landmarks (its own units, from reference/cowl.json) ---------------------------------------------
x_tip = float(V[:, 0].min())
x_ring, x_fw, z_axis = float(spec['x_ring']), float(spec['x_fw']), float(spec['z_axis'])
# firewall section: from outside (an engine may fill the inside), the bottom from inside if a gear hangs below
xf = x_fw - 0.01
f_top = hit((xf, 0.0, 50.0), (0, 0, -1)).z
f_bot = hit((xf, 0.0, -50.0), (0, 0, 1)).z
inner = hit((xf, 0.0, z_axis), (0, 0, -1))
if inner is not None and inner.z > f_bot + 0.02:
    f_bot = inner.z
hws = []                                                     # each side from its own side (an open access panel
for side in (1, -1):                                         # lets a ray through to the far wall)
    h = hit((xf, 50.0 * side, (f_top + f_bot) / 2), (0, -side, 0))
    if h is not None and h.y * side > 0:
        hws.append(h.y * side)
f_hw = max(hws)
print(f'reference: tip {x_tip:.3f} ring {x_ring:.3f} firewall {x_fw:.3f} axis z {z_axis:.3f} '
      f'firewall top {f_top:.3f} bottom {f_bot:.3f} half-width {f_hw:.3f}')

# ---- map onto our frame (mm): X, Z (starboard), H ---------------------------------------------------------------
s0 = S.section(S.FIREWALL_X)
fw_top, fw_bot, fw_hw = float(S.fTop(S.FIREWALL_X)), float(S.fBot(S.FIREWALL_X)), float(s0['hw'])
kx = (S.FIREWALL_X - S.XN) / (x_fw - x_ring)
k_up = (fw_top - S.PROP_AXIS_H) / (f_top - z_axis)
k_dn = (S.PROP_AXIS_H - fw_bot) / (z_axis - f_bot)
k_z = fw_hw / f_hw
print(f'scales mm/unit: length {kx:.0f}, above the thrust line {k_up:.0f}, below {k_dn:.0f}, across {k_z:.0f}')
X = S.XN + (V[:, 0] - x_ring) * kx
dz = V[:, 2] - z_axis
H = S.PROP_AXIS_H + np.where(dz > 0, dz * k_up, dz * k_dn)
Zs = V[:, 1] * k_z
tree = BVHTree.FromPolygons([Vector(p) for p in np.stack([X, Zs, H], 1)], F)

# ---- sample: radius about (0, hm) at polar angle phi, both sides: the first surface met coming in from outside (so
# an engine seen through an access hole, or anything inside, is not the skin) -----------------------------------------
XG = np.arange(S.XN, S.FIREWALL_X + 0.1, 5.0)
PHI = np.linspace(-math.pi / 2, math.pi / 2, 361)
R = np.full((len(XG), len(PHI)), np.nan)
for i, x in enumerate(XG):
    hm = float(S.section(x)['hm'])
    for j, p in enumerate(PHI):
        rs = []
        for side in (1, -1):
            d = Vector((0.0, side * math.cos(p), math.sin(p)))
            h = tree.ray_cast(Vector((x, 0.0, hm)) + d * 1500.0, -d, 1500.0)[0]
            if h is not None:
                rs.append(math.hypot(h.y, h.z - hm))
        if rs:
            R[i, j] = sum(rs) / len(rs)
# misses, things hanging outside (a fused nose gear: the ray meets the wheel first) and holes (an open access door: the
# ray meets the engine inside) are filled from their neighbours round the section; with none, from the generator's
for i, x in enumerate(XG):
    Z0, H0 = S._generator_points(S.section(x), PHI)
    rg = np.hypot(Z0, H0 - float(S.section(x)['hm']))
    bad = ~np.isfinite(R[i]) | (R[i] > 1.5 * rg) | (R[i] < 0.75 * rg)
    if bad.all():
        R[i] = rg
    elif bad.any():
        R[i, bad] = np.interp(PHI[bad], PHI[~bad], R[i, ~bad])


def smooth(a, axis, n):
    k = np.ones(2 * n + 1) / (2 * n + 1)
    pad = [(0, 0), (0, 0)]
    pad[axis] = (n, n)
    ap = np.pad(a, pad, mode='edge')
    return np.apply_along_axis(lambda v: np.convolve(v, k, 'valid'), axis, ap)


# rivets, its own inlet dents and lumps: median over 45 mm along and 4.5 deg around, then a box blur (35 mm, 4 deg).
# Only the overall form is kept; the inlets and chin scoop are cut by exterior.intakes().
from numpy.lib.stride_tricks import sliding_window_view  # noqa: E402
Rp = np.pad(R, ((4, 4), (4, 4)), mode='edge')
R = np.median(sliding_window_view(Rp, (9, 9)), axis=(2, 3))
R = smooth(smooth(R, 0, 3), 1, 4)
# the underside (gear well, exhaust stubs, a ragged belly) much more along the length (about 120 mm), blended in below
# -25 deg: its outline sets the arc length the livery is painted by, so its noise would shift the paint on the sides
low = np.clip((-np.radians(25) - PHI) / np.radians(20), 0, 1)
R = R * (1 - low) + smooth(R, 0, 12) * low
# and the top (above 35-50 deg) over about 250 mm along: the reference's raised access door is not on the real cowl
high = np.clip((PHI - np.radians(35)) / np.radians(15), 0, 1)
R = R * (1 - high) + smooth(R, 0, 25) * high
np.savez(out, X=XG, phi=PHI, R=R.astype(np.float32),
         landmarks=np.array([x_tip, x_ring, x_fw, z_axis, f_top, f_bot, f_hw]),
         scales=np.array([kx, k_up, k_dn, k_z]))
print(f'cowl table {R.shape} written to {out}')

# ---- where its cheek inlets are: rays from the front that go much deeper than their neighbours --------------------
Zg = np.arange(-450, 451, 15.0)
Hg = np.arange(900, 1400, 15.0)
depth = np.full((len(Hg), len(Zg)), np.nan)
for a, h in enumerate(Hg):
    for b, z in enumerate(Zg):
        r = tree.ray_cast(Vector((-200.0, z, h)), Vector((1, 0, 0)), 3000.0)[0]
        if r is not None:
            depth[a, b] = r.x
np.save(os.path.splitext(out)[0] + '_front_depth.npy', depth)
print('front depth map (X of first hit, mm; rows H 1385 -> 900, columns Z -450 -> 450 every 15 mm):')
for a in range(len(Hg) - 1, -1, -1):
    print(f'{Hg[a]:5.0f} ' + ''.join(' ' if not np.isfinite(d) else ('#' if d > 700 else '+' if d > 520 else '-' if d > 400 else '.')
                                    for d in depth[a]))
