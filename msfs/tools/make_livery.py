"""Paint the fuselage livery and window-glass textures (run inside Blender, for numpy).

    blender -b --factory-startup -P make_livery.py -- OUT_DIR [ACCENT_HEX]

Repaints what the generator (../model/index.html, paintSkin) drew: white skin, the accent side stripe
and pin stripe, dark window surrounds, door and cowling seams, the baggage door, and the window
openings (livery alpha; the glass texture's alpha is its inverse), plus the cowl's panel details: the
split line between its halves with its row of quarter-turn fasteners, the fastener row along the firewall
joint, and the oil door with its cam-locks. Two differences:
- v runs by distance around the section (sling_shape.arc_fraction) instead of the section angle,
  which gave the side stripe about 7 mm per texel and visibly stepped edges;
- every texel is the mean of 2 x 3 samples, so edges are anti-aliased.
Texel rows are Blender's (bottom first): row r is v = (r + 0.5) / TH, arc fraction 1 - v.
"""
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sling_shape as S  # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
OUT = args[0]
ACCENT = args[1] if len(args) > 1 else '#1f4fa8'          # the generator's first livery, Cobalt
TW = TH = 4096
SUB_X, SUB_V = 2, 3

WHITE = np.array([243, 244, 245], float)
DARK = np.array([27, 31, 35], float)
SEAM = np.array([150, 156, 162], float)
LOCK = np.array([110, 114, 118], float)
COWL_SPLIT_H = S.COWL_SPLIT_H          # mm, the cowl halves' split line (just under the cheek inlets)
SPLIT_LOCKS = np.linspace(360.0, 1120.0, 9)   # X of the quarter-turn fasteners along the lower half's flange
JOINT_LOCKS = (1148.0, 55.0, 110.0)    # X, first and pitch (mm of arc from the roof centreline) along the firewall joint
LOCK_R = 5.5                           # mm, a fastener's painted radius
OIL_DOOR = (905.0, 1065.0, 70.0, 200.0)   # X range, port |Z| range (mm): just forward of the windscreen base
ACC = np.array([int(ACCENT[i:i + 2], 16) for i in (1, 3, 5)], float)


def cover(d):
    return np.clip(d / 5 + 0.5, 0, 1)


def round_rect(X, H, x0, x1, h0, h1, r):
    inside = (X >= x0) & (X <= x1) & (H >= h0) & (H <= h1)
    cx = np.clip(X, x0 + r, x1 - r)
    ch = np.clip(H, h0 + r, h1 - r)
    return inside & ((X - cx) ** 2 + (H - ch) ** 2 <= r * r)


# Windows are laid out on the skin itself: X along the fuselage and q, the distance around the section
# from the roof centreline (mm). Rounded rectangles in (X, q) keep their round corners and an even
# frame when they wrap over the curved cabin top; drawn in side-view height they came out kinked.
# The door windows are the gull-wing doors (X 2030..3020, hinge beside the spine at |Z| 75, lower
# edge at H 1250) inset by a white frame, as on the aircraft.
FRAME_TOP, SILL_H = 60, 1310              # frame below the hinge line; window sill height (POH 3-view)


def round_join(a, b, r):
    """Rounded intersection of two inside-positive distance fields (sign is what matters)."""
    return np.minimum(np.minimum(a, b), r - np.hypot(np.maximum(r - a, 0), np.maximum(r - b, 0)))


def window_at(X, H, Z, q, upper, geo, grow=0.0):
    az = np.abs(Z)
    base = 1356 + 600 * np.minimum(1, az / 570) ** 2.2
    # windscreen: forward edge on the cowl line, aft edge at the door pillar, lower edge at H 1300 on the
    # skin; all corners rounded (inside-positive distances in mm, combined as a rounded intersection)
    d_fwd, d_aft = X - base + grow, 2000 + grow - X
    d_low = geo['q_screen'] - q + grow
    screen = upper & (round_join(round_join(d_fwd, d_low, 90), d_aft, 90) > 0)
    q0, q1 = geo['q_spine'] + FRAME_TOP - grow, geo['q_sill'] + grow
    # edges and corner radii measured on the POH rev 3.5 side view (tools/compare_3view.py)
    front = upper & round_rect(X, q, 2065 - grow, 2930 + grow, q0, q1, 80 + grow)
    rear_end = 3440 + (H - SILL_H) * 0.2
    rear = upper & round_rect(X, q, 3045 - grow, rear_end + grow, q0 + 10, q1, 80 + grow)
    return screen | front | rear


def section_geometry(X, H, Z, cum):
    """Arc positions (mm) at station X: the roof centreline, the door hinge line and the window sill."""
    k4 = S.K // 4                                           # a = pi/2, top centre
    s_top = cum[k4]
    s_spine = np.interp(S.SPINE, Z[k4::-1], cum[k4::-1])     # starboard upper quarter: Z falls, H rises
    s_sill = np.interp(SILL_H, H[:k4 + 1], cum[:k4 + 1])
    s_screen = np.interp(1300, H[:k4 + 1], cum[:k4 + 1])
    return {'s_top': s_top, 'q_spine': s_top - s_spine, 'q_sill': s_top - s_sill, 'q_screen': s_top - s_screen}


def paint(X, H, Z, sn, q, geo):
    """Colour (n, 3) and window mask (n,) for skin points at station X (scalar)."""
    mid = 985 + 0.068 * (X - 1165)
    w = 36 + 0.024 * (X - 290)
    pin = mid - w - 38
    band = np.maximum(cover(w - np.abs(H - mid)), cover(9 - np.abs(H - pin)))
    col = WHITE + (ACC - WHITE) * band[:, None]
    upper = sn >= 0
    col[window_at(X, H, Z, q, upper, geo, 30)] = DARK
    win = window_at(X, H, Z, q, upper, geo)
    on_door = (H > S.DOOR_H - 4) & (np.abs(Z) > S.SPINE - 4)
    if abs(X - S.DOOR_X0) < 4 or abs(X - S.DOOR_X1) < 4:
        col[on_door] = SEAM
    if S.DOOR_X0 < X < S.DOOR_X1:
        col[(np.abs(H - S.DOOR_H) < 4) & (sn > 0)] = SEAM
    if abs(X - 1165) < 3:
        col[H < 1380] = SEAM                                   # firewall / cowling joint
    if 296 < X < 1163:                                         # upper / lower cowl split, near the thrust line
        col[(np.abs(H - COWL_SPLIT_H) < 2.5) & (np.abs(Z) > 60)] = SEAM
        for cx in SPLIT_LOCKS:                                 # its fasteners, on the lower half just under the line
            if abs(X - cx) < LOCK_R + 1:
                col[((X - cx) ** 2 + (H - (COWL_SPLIT_H - 12)) ** 2 < LOCK_R ** 2) & (np.abs(Z) > 60)] = LOCK
    jx, j0, jp = JOINT_LOCKS                                   # fasteners along the cowl's aft edge, by arc length
    if abs(X - jx) < LOCK_R + 1:
        m = (q - j0) % jp
        near = np.minimum(m, jp - m)
        col[((X - jx) ** 2 + near ** 2 < LOCK_R ** 2) & (sn > -0.5) & (H < 1380)] = LOCK
    x0, x1, z0, z1 = OIL_DOOR                                  # oil door on the port upper cowl, cam-locks
    if x0 - 8 < X < x1 + 8:
        zz = -Z
        inside = (sn > 0) & (zz > z0) & (zz < z1) & (x0 < X < x1)
        edge = np.minimum(np.minimum(X - x0, x1 - X), np.minimum(zz - z0, z1 - zz))
        col[inside & (edge < 3)] = SEAM
        for cx in (x0 + 12, x1 - 12):
            for cz in (z0 + 12, z1 - 12):
                col[(sn > 0) & ((X - cx) ** 2 + (zz - cz) ** 2 < 5.5 ** 2)] = LOCK
    if 3460 < X < 3920:                                        # baggage door (POH 2.17.3; 3-view position)
        bag = (sn > -0.2) & (H > 963) & (H < 1288)
        edge = np.minimum(np.minimum(X - 3460, 3920 - X), np.minimum(H - 963, 1288 - H))
        col[bag & (edge < 5)] = SEAM
        if abs(X - 3875) < 22:
            col[bag & (np.abs(H - 1125) < 45)] = DARK          # latch
    return col, win.astype(float)


def main():
    rgb = np.zeros((TH, TW, 3), np.float32)
    mask = np.zeros((TH, TW), np.float32)
    # arc fraction of each sub-sample row (Blender rows run bottom to top: v up, arc fraction 1 - v)
    v = (np.arange(TH)[:, None] + (np.arange(SUB_V)[None, :] + 0.5) / SUB_V) / TH
    t = (1 - v).ravel()
    for px in range(TW):
        col_acc = np.zeros((TH, 3))
        win_acc = np.zeros(TH)
        for k in range(SUB_X):
            X = S.XN + (px + (k + 0.5) / SUB_X) / TW * (S.XT - S.XN)
            H, Z, sn = S.ring_points(X)
            cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(H), np.diff(Z)))])
            frac = cum / cum[-1]
            Hs, Zs, ss = np.interp(t, frac, H), np.interp(t, frac, Z), np.interp(t, frac, sn)
            geo = section_geometry(X, H, Z, cum)
            q = np.abs(t * cum[-1] - geo['s_top'])
            col, win = paint(X, Hs, Zs, ss, q, geo)
            col_acc += col.reshape(TH, SUB_V, 3).mean(axis=1)
            win_acc += win.reshape(TH, SUB_V).mean(axis=1)
        rgb[:, px] = col_acc / SUB_X / 255.0
        mask[:, px] = win_acc / SUB_X
        if px % 512 == 0:
            print(f'livery column {px}/{TW}', flush=True)
    os.makedirs(OUT, exist_ok=True)
    for name, colour, alpha in (('SlingTSi_LIVERY_albd', rgb, 1 - mask),
                                ('SlingTSi_GLASS_albd', np.ones_like(rgb), mask)):
        img = bpy.data.images.new(name, TW, TH, alpha=True)
        px = np.concatenate([colour, alpha[..., None]], axis=2).astype(np.float32)
        img.pixels.foreach_set(px.ravel())
        img.filepath_raw = os.path.join(OUT, name + '.png')
        img.file_format = 'PNG'
        img.save()
        print('texture written', img.filepath_raw)


main()
