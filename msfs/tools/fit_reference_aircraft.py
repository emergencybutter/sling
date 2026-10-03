"""Fit the reference aircraft (reference/sling_meshy_full.glb, an AI-generated textured Sling TSi) to the POH and
export it in the scene frame render_orthographic.py / compare_3view.py use (run inside Blender).

    blender -b --factory-startup -P fit_reference_aircraft.py -- reference/sling_meshy_full.glb OUT.glb [--model-frame]

--model-frame writes the build's Blender frame (x forward, spinner tip at x 3.3, y left, z up from the ground), for
exterior.reference_exterior(); without it, the frame render_orthographic.py / compare_3view.py read.

One uniform scale and a pitch rotation put two landmarks on the POH side view, the spinner tip and the bottom aft
tip of the rudder (the user's choice). Along the length it is then warped piecewise, those two fixed: the nose is
squeezed so its windscreen base (where the canopy meets the fuselage) lands on the POH's, and the tail stretched so
its wing root leading edge does too. The wings are stretched in span, from the fuselage side outward, to the POH span.
"""
import math
import sys

import bpy
import numpy as np
from mathutils import Vector

src, out = sys.argv[sys.argv.index('--') + 1:][:2]

# POH side view (page 1-3 at 200 dpi: spinner tip x 274, ground y 791, 153.19 px/m) in our model frame (x forward
# from the tail, spinner tip at x 3.3; z up from the ground)
POH_TIP = (3.3, 1.250)
POH_RUDDER = (3.3 - (1320 - 274) / 153.19, (791 - 636.7) / 153.19)     # bottom aft tip of the rudder
POH_SPAN = 9.5
WING_ROOT = 0.55            # m: the wing stretch starts at the fuselage side
WING_X = (-1.2, 2.2)        # m: the wing (and main gear) lies between these stations; tail and prop are not stretched
POH_WINDSCREEN_X = 2.135    # m: windscreen base (cowl top meets the canopy), firewall station X 1165
POH_WING_LE_X = 1.392       # m: wing leading edge 0.8 m out (our POH-matched wing)
POH_CANOPY_TOP = 1.810      # m: top of the canopy (our POH-matched fuselage, fTop max)
POH_FIN_TOP = 2.350         # m: fin top (POH height)
SILL_H, TAIL_H = 1.30, 1.45 # m: heights above which the cabin / the fin are squeezed (the sill, the tail cone top)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=src)
ob = [o for o in bpy.data.objects if o.type == 'MESH'][0]
me = ob.data
mw = ob.matrix_world.copy()
P = np.array([mw @ v.co for v in me.vertices])
P = np.stack([-P[:, 0], -P[:, 1], P[:, 2]], 1)                      # nose to +x (turned 180 deg about z)

# its landmarks: the spinner tip, and the rudder trailing edge's lowest point on the centreline
tip = np.array([P[:, 0].max(), P[P[:, 0] > P[:, 0].max() - 0.004, 2].mean()])
c = P[np.abs(P[:, 1]) < 0.02]
c = c[c[:, 0] < P[:, 0].min() + 0.35]
zs = np.arange(c[:, 2].max(), c[:, 2].min(), -0.005)
te = [(z, c[np.abs(c[:, 2] - z) < 0.004, 0].min()) for z in zs if (np.abs(c[:, 2] - z) < 0.004).any()]
bottom = te[0]
for z, x in te:                                                     # follow the trailing edge down until it turns
    if x > bottom[1] + 0.008:                                       # sharply forward (the rudder's lower corner)
        break
    bottom = (z, x)
rud = np.array([bottom[1], bottom[0]])

dr = rud - tip
dp = np.array(POH_RUDDER) - np.array(POH_TIP)
k = np.hypot(*dp) / np.hypot(*dr)
th = math.atan2(dp[1], dp[0]) - math.atan2(dr[1], dr[0])
print(f'landmarks (its units): tip {tip.round(4)}, rudder bottom tip {rud.round(4)}; scale {k:.4f} m/unit, '
      f'pitch {math.degrees(th):+.2f} deg')
cs, sn = math.cos(th), math.sin(th)
rel = P[:, [0, 2]] - tip
X = POH_TIP[0] + k * (rel[:, 0] * cs - rel[:, 1] * sn)
Z = POH_TIP[1] + k * (rel[:, 0] * sn + rel[:, 1] * cs)
Y = k * (P[:, 1] - (P[:, 1].max() + P[:, 1].min()) / 2)
print(f'lowest point z {Z.min():.3f} m (ground 0); span before the wing stretch {Y.max() - Y.min():.3f} m')

# the wings stretched in span to the POH's, from the fuselage side outward
half = (Y.max() - Y.min()) / 2
s = (POH_SPAN / 2 - WING_ROOT) / (half - WING_ROOT)
wing = (X > WING_X[0]) & (X < WING_X[1]) & (np.abs(Y) > WING_ROOT)
Y = np.where(wing, np.sign(Y) * (WING_ROOT + (np.abs(Y) - WING_ROOT) * s), Y)
print(f'wing span stretch x{s:.3f} beyond |y| {WING_ROOT} m')

# its windscreen base: going aft along the centreline, where the top rises 40 mm above the cowl's level
cl = np.abs(Y) < 0.05
bins = np.arange(2.3, 0.4, -0.02)                                # aft of the cowl's own steep front
top = np.array([Z[cl & (np.abs(X - b) < 0.01)].max() if (cl & (np.abs(X - b) < 0.01)).any() else np.nan for b in bins])
cowl = float(np.nanmedian(top[(bins <= 2.3) & (bins >= 1.8)]))     # the cowl's level top, behind its front
ws = float(next(b for b, t in zip(bins, top) if b < 1.8 and t > cowl + 0.04)) + 0.03   # where the canopy rises off it
# its wing root leading edge, 0.8 m out (clear of the fuselage side)
root = (np.abs(np.abs(Y) - 0.8) < 0.03) & (Z > 0.5) & (Z < 1.2) & (X > -0.8) & (X < 2.4)
le = float(X[root].max())
print(f'its windscreen base x {ws:.3f} -> {POH_WINDSCREEN_X}, wing root LE x {le:.3f} -> {POH_WING_LE_X}')
xr_tail = POH_RUDDER[0]
XR = [X.min() - 0.01, xr_tail, le, ws, POH_TIP[0], X.max() + 0.01]
XT = [X.min() - 0.01, xr_tail, POH_WING_LE_X, POH_WINDSCREEN_X, POH_TIP[0], X.max() + 0.01]
XR, XT = zip(*sorted(zip(XR, XT)))
X = np.interp(X, XR, XT)

# heights: squeezed above the cabin sill so the canopy top, and above the tail cone so the fin top, are the POH's;
# the two factors blended along the length (the gear, the belly and the fuselage sides below stay as fitted)
cab = cl & (X > 0.3) & (X < 1.6)
canopy_top = float(Z[cab].max())
fin_top = float(Z[X < -2.5].max())
s_cab = (POH_CANOPY_TOP - SILL_H) / (canopy_top - SILL_H)
s_fin = (POH_FIN_TOP - TAIL_H) / (fin_top - TAIL_H)
print(f'canopy top {canopy_top:.3f} -> {POH_CANOPY_TOP} (x{s_cab:.3f} above {SILL_H}), '
      f'fin top {fin_top:.3f} -> {POH_FIN_TOP} (x{s_fin:.3f} above {TAIL_H})')
w = np.clip((X - (-2.6)) / (-1.2 - (-2.6)), 0, 1)              # 0 at the fin, 1 forward of the cabin's rear
h0 = TAIL_H + (SILL_H - TAIL_H) * w
sz = s_fin + (s_cab - s_fin) * w
Z = np.where(Z > h0, h0 + (Z - h0) * sz, Z)

# plan view, against our POH-matched planform (tools/data/poh_planform.json, measured on our exterior): the cabin
# inflated to the POH width station by station, then the wings and the tailplane remapped chordwise onto the POH's
# leading and trailing edges along the span, and stretched to its spans
import json, os  # noqa: E401,E402
PF = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'poh_planform.json')))


def runmed(a, n=2):
    a = np.asarray(a, float)
    return np.array([np.nanmedian(a[max(i - n, 0):i + n + 1]) for i in range(len(a))])


rows = sorted(r for r in PF['fus_hw'] if -2.4 < r[0] < 2.95)       # ascending x (np.interp)
fx = np.array([r[0] for r in rows])
fw = np.array([r[1] for r in rows])
band = (Z > 0.9) & (Z < 1.4) & (np.abs(Y) < 0.8)              # as measured on ours
rw = np.array([np.abs(Y[band & (np.abs(X - x) < 0.04)]).max() if (band & (np.abs(X - x) < 0.04)).any() else np.nan
               for x in fx])
ok = np.isfinite(rw)
rw = np.interp(fx, fx[ok], rw[ok])
kk = np.clip(runmed(fw / rw), 0.8, 1.6)
order = np.argsort(fx)
fxs, kks, rws = fx[order], kk[order], rw[order]
k_at = np.interp(X, fxs, kks, left=1.0, right=kks[-1])
k_at = np.where(X < -2.4, 1 + (np.interp(-2.4, fxs, kks) - 1) * np.clip((X + 2.9) / 0.5, 0, 1), k_at)
hw_at = np.interp(X, fxs, rws)
ay = np.abs(Y)
gear = (Z < 0.5) & (ay > hw_at)                                       # the main gear: placed on the track below
Y = np.sign(Y) * np.where(ay < hw_at, ay * k_at, np.where(gear, ay, ay + hw_at * (k_at - 1)))
print('cabin inflated: width x' + ', '.join(f'{x:+.1f}:{k:.2f}' for x, k in zip(fxs[::6], kks[::6])))


def remap(sel, ys, table, root, tip_t, ramp):
    """Chordwise and spanwise remap of the selected points (a wing or the tailplane) onto table [y, LE, TE]."""
    global X, Y
    ty = np.array([r[0] for r in table]); tle = np.array([r[1] for r in table]); tte = np.array([r[2] for r in table])
    ay = np.abs(Y)
    tip_r = float(ay[sel].max())
    span = np.where(sel, root + (ay - root) * (tip_t - root) / (tip_r - root), ay)
    le_r, te_r = [], []
    for y in ys:                                                       # its edges, at its own span
        m = sel & (np.abs(ay - y) < 0.03)
        le_r.append(X[m].max() if m.any() else np.nan); te_r.append(X[m].min() if m.any() else np.nan)
    le_r, te_r = runmed(le_r), runmed(te_r)
    ok = np.isfinite(le_r) & np.isfinite(te_r)
    ys_t = root + (np.asarray(ys) - root) * (tip_t - root) / (tip_r - root)
    LEr, TEr = np.interp(ay, np.asarray(ys)[ok], le_r[ok]), np.interp(ay, np.asarray(ys)[ok], te_r[ok])
    LEt, TEt = np.interp(span, ty, tle), np.interp(span, ty, tte)
    xn = TEt + (X - TEr) * (LEt - TEt) / np.maximum(LEr - TEr, 1e-3)
    w = np.clip((ay - ramp[0]) / (ramp[1] - ramp[0]), 0, 1) * sel
    X = X + (xn - X) * w
    Y = np.sign(Y) * (ay + (span - ay) * w)
    return tip_r


ay = np.abs(Y)
wing = (X > -1.4) & (X < 2.3) & (Z > 0.52) & (Z < 1.45) & (ay > 0.6)
t = remap(wing, np.arange(0.65, float(ay[wing].max()), 0.05), PF['wing'], 0.6, POH_SPAN / 2, (0.62, 0.8))
print(f'wings: tip {t:.3f} -> {POH_SPAN / 2}, edges onto the POH planform')
ay = np.abs(Y)
tail = (X < -2.2) & (Z > 1.0) & (Z < 1.75) & (ay > 0.08)
t = remap(tail, np.arange(0.12, float(ay[tail].max()), 0.04), PF['tail'], 0.08, 3.095 / 2, (0.09, 0.2))
print(f'tailplane: tip {t:.3f} -> {3.095 / 2}, edges onto the POH planform')

# main gear track onto the POH's 2050 mm: wheels and fairings moved out whole, the legs bent to follow
ay = np.abs(Y)
wheels = (Z < 0.35) & (ay > 0.6) & (X > -0.5) & (X < 1.5)
trk = 2 * float(np.median(ay[wheels]))
legs = (Z < 0.55) & (ay > 0.45) & (X > -0.6) & (X < 1.6)
shift = (1.025 - trk / 2) * np.clip((ay - 0.45) / (trk / 2 - 0.25 - 0.45), 0, 1)   # legs bent, wheels moved whole
Y = np.where(legs, np.sign(Y) * (ay + shift), Y)
print(f'main gear track {trk:.3f} -> 2.050')

MODEL_FRAME = '--model-frame' in sys.argv                          # the build's frame, else render_orthographic's
for v, x, y, z in zip(me.vertices, X, Y, Z):
    v.co = Vector((x, y, z)) if MODEL_FRAME else Vector((y, -(x - 1.06), z - 0.9))
ob.matrix_world = ob.matrix_world.__class__.Identity(4)
me.update()
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB')
print('written', out)
