"""Fuselage shape of the Sling TSi model, ported from ../model/index.html (numpy; runs in Blender's Python).

Drawing coordinates in millimetres, as in the generator: X aft of the spinner tip, H height above the
ground, Z outboard to starboard. Blender-model coordinates are x = (XC - X) / 1000, y = -Z / 1000,
z = H / 1000. Sections are superellipses: angle a (0 = starboard side, pi/2 = top) gives

    Z = hw * spow(cos a, 2/n),   H = hm + up * sin(a)^(2/n) (upper) or hm - dn * (-sin a)^(2/n) (lower)

The generator mapped the fuselage texture's v straight to a, which crowds the whole side stripe into a
few texels (the lower half is boxy, n = 4, so H moves like sqrt(a) near the sides). arc_fraction()
gives the distance around the section instead; blender_export.py remaps the UVs with it and
make_livery.py paints in that space.
"""
import math
import os

import numpy as np

XC = 3300.0
XN, XT = 290.0, 6514.0                  # spinner base to tail-cone end: the texture's u range
DOOR_X0, DOOR_X1, DOOR_H, SPINE = 2030.0, 3020.0, 1250.0, 75.0


class Smooth:
    """Monotone cubic (Fritsch-Carlson) through (x, y) pairs, as the generator's smoothFn."""

    def __init__(self, pts):
        xs = np.array([p[0] for p in pts], float)
        ys = np.array([p[1] for p in pts], float)
        d = np.diff(ys) / np.diff(xs)
        m = np.empty_like(ys)
        m[0], m[-1] = d[0], d[-1]
        for i in range(1, len(xs) - 1):
            m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2
        for i in range(len(xs) - 1):
            if d[i] == 0:
                m[i] = m[i + 1] = 0.0
                continue
            a, b = m[i] / d[i], m[i + 1] / d[i]
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[i], m[i + 1] = t * a * d[i], t * b * d[i]
        self.xs, self.ys, self.m = xs, ys, m

    def __call__(self, x):
        x = np.asarray(x, float)
        xs, ys, m = self.xs, self.ys, self.m
        xc = np.clip(x, xs[0], xs[-1])
        i = np.clip(np.searchsorted(xs, xc, side='right') - 1, 0, len(xs) - 2)
        h = xs[i + 1] - xs[i]
        t = (xc - xs[i]) / h
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h * m[i]
                + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h * m[i + 1])


fTop = Smooth([[290, 1295], [513, 1325], [754, 1356], [1048, 1376], [1165, 1382], [1356, 1395],
               [1636, 1532], [1930, 1660], [2071, 1745], [2362, 1797], [2658, 1810], [2952, 1795], [3304, 1752],
               [3596, 1690], [4096, 1607], [4385, 1553], [4738, 1492], [5100, 1445], [5450, 1400], [5850, 1347],
               [6200, 1302], [6514, 1255]])
fBot = Smooth([[290, 1045], [400, 955], [530, 866], [760, 790], [1000, 722], [1165, 662],
               [1400, 648], [3470, 648], [3600, 663], [4100, 715], [4740, 781], [5450, 855], [6200, 933], [6514, 966]])
fHW = Smooth([[290, 130], [400, 240], [530, 336], [760, 402], [1000, 458], [1165, 480],
              [1360, 502], [1640, 530], [1930, 560], [2070, 575], [2360, 594], [2950, 594], [3300, 585],
              [3600, 526], [4100, 452], [4390, 398], [4740, 336], [5100, 278], [5450, 218], [5850, 155],
              [6200, 118], [6514, 70]])
fNU = Smooth([[290, 2], [700, 2.4], [1200, 2.6], [1700, 2.1], [2400, 2], [3500, 2], [5000, 2.2], [6514, 2.2]])
fNL = Smooth([[290, 2], [700, 2.6], [1200, 3.3], [2000, 4], [3400, 4], [4500, 3], [6514, 2.4]])


def spow(v, e):
    return np.sign(v) * np.abs(v) ** e


# ---- cowling (composite cowl around the Rotax 915/916 iS; the user's description and POH stations) ---------------
# Smooth, crease-free sections lofted through four stations (spacing scaled to the POH cowl length, spinner base at
# X 290 to the firewall at X 1165):
#   station 0, X 290   the nose ring: a true circle, 285 mm across, round the 280 mm spinner backplate
#   station 1, X 475   aft of the inlets: a soft inverted trapezoid, narrow top, wide cheeks
#   station 2, X 700   mid cowl: the cheeks at their widest
#   station 3, X 1165  the firewall: the cabin's own section (the generator's), blended in from X 1000
# Each section is a "trapezoidal superellipse": the upper half runs from the cheek line (Wc at height Hc) to the top
# Ht with its half-width scale narrowing (quadratically, so the cheek line stays smooth) to Wt * Wc, the lower
# half likewise down to Hb (Wb * Wc), exponents n_up and n_dn. The top line droops from the windscreen base down
# to the spinner (COWL_HT, close to the generator's fTop).
# On top: shallow concave pockets round the cheek inlets, a channel along the keel for the nose gear leg, and the
# lower cowl's aft edge standing proud of the belly as a rearward-facing cowl-flap exit.
# (The Meshy-derived cowl variants of October 2026 are in reference/disabled and tools/data/disabled.)
FIREWALL_X = 1165.0
PROP_AXIS_H = 1170.0
RING_R = 142.5                                   # mm, nose ring radius (285 mm), spinner backplate 140 mm
COWL_HC = Smooth([[290, PROP_AXIS_H], [475, 1150], [700, 1115], [1000, 1060]])
COWL_WC = Smooth([[290, RING_R], [475, 330], [700, 425], [1000, 462]])
COWL_HT = Smooth([[290, PROP_AXIS_H + RING_R], [475, 1330], [700, 1352], [1000, 1373]])
COWL_HB = Smooth([[290, PROP_AXIS_H - RING_R], [475, 900], [700, 800], [1000, 722]])
COWL_WT = Smooth([[290, 1.0], [475, 0.45], [700, 0.55], [1000, 0.75]])
COWL_WB = Smooth([[290, 1.0], [475, 0.70], [700, 0.72], [1000, 0.80]])
COWL_NU = Smooth([[290, 2.0], [475, 2.6], [700, 2.7], [1000, 2.8]])
COWL_ND = Smooth([[290, 2.0], [475, 2.4], [700, 3.0], [1000, 3.6]])
# the scoops round the cheek inlets: a recess at the intake (centre |Z|, H there, mm) that runs aft along the cheek as
# a groove, tapering in width and depth (photos: Documents/photos/maxresdefault.jpg, images(5).jpg)
POCKET = (232.0, 1188.0)
SCOOP_DEPTH = Smooth([[300, 0], [370, 30], [430, 30], [600, 14], [780, 0]])          # mm
SCOOP_WIDTH = Smooth([[300, 0.30], [430, 0.26], [600, 0.16], [780, 0.10]])          # rad (sigma, polar angle)
GEAR_CHANNEL = (720.0, 820.0, 70.0, 22.0)        # X start, X full, half-width, depth (mm)
EXIT_LIP = (1000.0, 1150.0, 18.0)                # X start, X full, outward step of the lower cowl's aft edge (mm)
# the crown: a raised band along the top between two edges that run from beside the spinner up and out to the
# windscreen corners (POH front and plan views; the photos' top contours). Half-width (mm) by station, height, and the
# width of the rounded edge.
CROWN_HW = Smooth([[290, 95], [500, 150], [800, 210], [1165, 250]])
CROWN_H, CROWN_EDGE = 20.0, 34.0
CROWN_X = (330.0, 760.0, 1100.0, 1165.0)         # rises gently aft of the spinner, fades into the windscreen base
fNU_cowl = Smooth([[290, 2], [450, 2.5], [600, 3.2], [950, 3.2], [1165, 2.6]])


def nU(X):
    X = np.asarray(X, float)
    w = np.clip((X - 1000) / (FIREWALL_X - 1000), 0, 1)       # blend into the generator's exponent at the firewall
    return np.where(X < FIREWALL_X, fNU_cowl(X) * (1 - w) + fNU(X) * w, fNU(X))


def _smoothstep(e0, e1, v):
    t = np.clip((v - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def section(X):
    top, bot = fTop(X), fBot(X)
    hm = (top + bot) / 2
    return {'hm': hm, 'up': top - hm, 'dn': hm - bot, 'hw': fHW(X), 'nU': nU(X), 'nL': fNL(X)}


def _generator_points(s, a):
    c, sn = np.cos(a), np.sin(a)
    upper = sn >= 0
    n = np.where(upper, s['nU'], s['nL'])
    Z = s['hw'] * spow(c, 2 / n)
    H = np.where(upper, s['hm'] + s['up'] * np.abs(sn) ** (2 / n), s['hm'] - s['dn'] * np.abs(sn) ** (2 / n))
    return Z, H


def cowl_section(X, s=None):
    """Polar table (angle about (0, hm), radius) of the cowl section at X, starboard half, angle -pi/2..pi/2."""
    hm = float(section(X)['hm']) if s is None else float(s['hm'])
    hc, wc, ht, hb = float(COWL_HC(X)), float(COWL_WC(X)), float(COWL_HT(X)), float(COWL_HB(X))
    wt, wb, nu, nd = float(COWL_WT(X)), float(COWL_WB(X)), float(COWL_NU(X)), float(COWL_ND(X))
    th = np.linspace(0, np.pi / 2, 400)
    t, u = np.sin(th) ** (2 / nu), np.cos(th) ** (2 / nu)
    Zu, Hu = wc * (1 + (wt - 1) * t * t) * u, hc + (ht - hc) * t      # t^2: no kink at the cheek line
    t, u = np.sin(th) ** (2 / nd), np.cos(th) ** (2 / nd)
    Zd, Hd = wc * (1 + (wb - 1) * t * t) * u, hc - (hc - hb) * t
    Z = np.concatenate([Zd[::-1], Zu[1:]])
    H = np.concatenate([Hd[::-1], Hu[1:]])
    ang = np.arctan2(H - hm, Z)
    rad = np.hypot(Z, H - hm)
    o = np.argsort(ang)
    return ang[o], rad[o]


def skin_point(X, a):
    """Skin point (H, Z) mm at station X (scalar) and section angle(s) a, with the cowling."""
    s = section(X)
    Z, H = _generator_points(s, a)
    if X >= FIREWALL_X:
        return H, Z
    hm = float(s['hm'])
    phi = np.arctan2(H - hm, np.abs(Z))
    r0 = np.hypot(Z, H - hm)
    ang, rad = cowl_section(X, s)
    w = 1 - float(_smoothstep(1000.0, FIREWALL_X, X))
    r = r0 + (np.interp(phi, ang, rad) - r0) * w
    Zr, Hr = r * np.cos(phi), hm + r * np.sin(phi)
    # the scoops: pushed in along the section radius, centred on the intake's polar angle
    depth = float(SCOOP_DEPTH(min(X, 780.0)))
    if depth > 0.05:
        phc = math.atan2(POCKET[1] - float(section(370.0)['hm']), POCKET[0])
        sg = float(SCOOP_WIDTH(min(X, 780.0)))
        r = r - depth * np.exp(-((phi - phc) / sg) ** 2)
    # nose gear channel along the keel, and the cowl-flap exit lip at the lower cowl's aft edge
    gx0, gx1, gw, gd = GEAR_CHANNEL
    wg = float(_smoothstep(gx0, gx1, X))
    if wg > 0:
        r = r - gd * wg * np.clip(1 - (Zr / gw) ** 2, 0, 1) * (np.sin(phi) < 0)
    lx0, lx1, lo = EXIT_LIP
    wl = float(_smoothstep(lx0, lx1, X))
    if wl > 0:
        r = r + lo * wl * _smoothstep(-0.35, -0.7, np.sin(phi))
    # the crown on top
    c0, c1, c2, c3 = CROWN_X
    wc = float(_smoothstep(c0, c1, X) * (1 - _smoothstep(c2, c3, X)))
    if wc > 0:
        hw = float(CROWN_HW(X))
        band = _smoothstep(hw + CROWN_EDGE / 2, hw - CROWN_EDGE / 2, np.abs(Zr)) * (np.sin(phi) > 0.3)
        r = r + CROWN_H * wc * band
    Z = np.sign(Z) * r * np.cos(phi)
    H = hm + r * np.sin(phi)
    return H, Z


# angle samples for the arc-length tables: fine enough that a chord is under a millimetre
K = 32768
_A = np.linspace(0.0, 2 * np.pi, K + 1)
_C, _S = np.cos(_A), np.sin(_A)


def ring_points(X):
    """(H, Z, sin a) at the K+1 table angles of the section at X (scalar)."""
    H, Z = skin_point(X, _A)
    return H, Z, _S


def arc_table(X):
    """Cumulative arc fraction (0..1) at the table angles, and the section points."""
    H, Z, S = ring_points(X)
    seg = np.hypot(np.diff(H), np.diff(Z))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum / cum[-1], H, Z, S


def arc_fraction_grid(nx=512):
    """Arc fraction over a grid of X (nx columns spanning XN..XT) x the table angles."""
    Xs = np.linspace(XN, XT, nx)
    return Xs, np.stack([arc_table(X)[0] for X in Xs]).astype(np.float32)


def arc_fraction(X, a, grid=None):
    """Arc fraction at stations X and angles a (arrays), bilinear in the precomputed grid."""
    Xs, T = grid or arc_fraction_grid()
    fx = np.clip((np.asarray(X) - Xs[0]) / (Xs[1] - Xs[0]), 0, len(Xs) - 1.000001)
    fa = np.clip(np.asarray(a) / (2 * np.pi) * K, 0, K - 0.000001)
    ix, ia = fx.astype(int), fa.astype(int)
    tx, ta = fx - ix, fa - ia
    ix1 = np.minimum(ix + 1, len(Xs) - 1)
    v00, v01 = T[ix, ia], T[ix, ia + 1]
    v10, v11 = T[ix1, ia], T[ix1, ia + 1]
    return (v00 * (1 - ta) + v01 * ta) * (1 - tx) + (v10 * (1 - ta) + v11 * ta) * tx


def to_blender(X, H, Z):
    return ((XC - X) / 1000.0, -Z / 1000.0, H / 1000.0)
