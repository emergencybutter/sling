"""Paint the instrument panel face texture: carbon twill, red plates, printed legends and placards.

    python make_panel_texture.py OUT.png

Everything is placed from panel_layout.py (POH 7.10 diagram pixels), so the legends line up with
the switches, knobs and breakers that interior.py places from the same positions. Placard texts are
the POH 2.17 limitation placards. Fonts: Windows Arial / Arial Bold.
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_layout as L  # noqa: E402

OUT = sys.argv[1]
FONT = r'C:\Windows\Fonts\arial.ttf'
FONT_BOLD = r'C:\Windows\Fonts\arialbd.ttf'
MM = L.TEX_PX_PER_M / 1000.0                     # texture pixels per millimetre


def at(xp, yp):
    return L.tex_px(*L.px_yz(xp, yp))


def font(size_mm, bold=True):
    # cap height of Arial is about 0.72 of the em size
    return ImageFont.truetype(FONT_BOLD if bold else FONT, max(8, int(round(size_mm * MM / 0.72))))


# ---------------------------------------------------------------- carbon twill
def carbon_tile(cell=14):
    """2x2 twill: tows alternate over two and under two, each tow shaded as a rounded bundle with a
    thin highlight, so the weave reads at a glance and catches the eye like real carbon."""
    n = cell * 4
    img = Image.new('RGB', (n, n))
    px = img.load()
    for j in range(n):
        for i in range(n):
            cu, cv = i // cell, j // cell
            fu, fv = (i % cell) / cell, (j % cell) / cell
            warp = ((cu + cv) // 2) % 2 == 0
            t = fv if warp else fu                       # across the tow
            along = fu if warp else fv
            bundle = math.sin(math.pi * t)
            fibres = 0.5 + 0.5 * math.sin(2 * math.pi * (t * 7 + 0.3 * along))
            base = (0.068 if warp else 0.058) + 0.045 * bundle ** 1.6 + 0.008 * fibres
            sheen = 0.03 * max(0.0, bundle - 0.85) / 0.15 if warp else 0.0
            v = base + sheen
            c = int(255 * min(1.0, v))
            px[i, j] = (c, c, int(c * 1.06))
    return img


def paint_carbon(img):
    tile = carbon_tile()
    for y in range(0, img.height, tile.height):
        for x in range(0, img.width, tile.width):
            img.paste(tile, (x, y))


# ---------------------------------------------------------------- printing helpers
def text(d, s, centre, size_mm, fill, bold=True, anchor='mm'):
    d.text(centre, s, font=font(size_mm, bold), fill=fill, anchor=anchor)


def rounded_rect(d, box, r, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


WHITE = (236, 236, 232)
RED = (196, 32, 28)
BLACK = (18, 18, 18)
SILVER = (196, 198, 200)
YELLOW = (230, 196, 40)


def main():
    img = Image.new('RGB', (L.TEX_W, L.TEX_H))
    paint_carbon(img)
    d = ImageDraw.Draw(img)

    # red plates behind the lane and fuel pump switches
    for x0, y0, x1, y1, title in L.RED_PLATES:
        (a, b), (c, e) = at(x0, y0), at(x1, y1)
        rounded_rect(d, (a, b, c, e), 1.5 * MM, RED, outline=(120, 16, 14), width=int(0.4 * MM))

    # switch legends: name above, and a small ON/OFF pair beside the lane and master switches
    for name, xp, yp, label, _tpl, _prm in L.SWITCHES:
        x, y = at(xp, yp)
        size = 2.1 if len(label) > 6 else 2.4
        onoff = name in ('Lane_A', 'Lane_B', 'Master', 'Prop_pitch')
        text(d, label, (x, y - (14.0 if name == 'Prop_pitch' else 12.5 if onoff else 9.5) * MM), size, WHITE)
        if onoff:                                   # clear of the 6.4 mm hex nut
            up_, down_ = ('FINE', 'COARSE') if name == 'Prop_pitch' else ('ON', 'OFF')
            text(d, up_, (x, y - 8.6 * MM), 1.8, WHITE)
            text(d, down_, (x, y + 8.6 * MM), 1.8, WHITE)

    # the taxi switch's middle position (POH 7.15.5: ON / WIG WAG / OFF)
    tx = next((xp, yp) for name, xp, yp, *_ in L.SWITCHES if name == 'Taxi')
    x_t, y_t = at(*tx)
    text(d, 'WIG-WAG', (x_t + 11.5 * MM, y_t), 1.25, WHITE, bold=False)

    # ON / OFF scale beside the switch row
    row_end = at(L.SWITCHES[-2][1], L.SWITCH_ROW_Y)
    text(d, 'ON', (row_end[0] + 17 * MM, row_end[1] - 5 * MM), 2.2, WHITE)
    text(d, 'OFF', (row_end[0] + 17 * MM, row_end[1] + 5 * MM), 2.2, WHITE)
    # thin line under the row
    x0 = at(L.SWITCHES[5][1] - 12, L.SWITCH_ROW_Y)[0]            # from EFIS, clear of the pump plate
    x1 = at(L.SWITCHES[-2][1] + 12, L.SWITCH_ROW_Y)[0]
    yl = at(0, L.SWITCH_ROW_Y)[1] + 9 * MM
    d.line((x0, yl, x1, yl), fill=WHITE, width=max(1, int(0.35 * MM)))

    # key switch positions
    kx, ky = at(L.KEY[1], L.KEY[2])
    r = 16 * MM                                     # outside the 11 mm key barrel
    for s, ang in (('OFF', -80), ('ON', -35), ('START', 32)):
        a = math.radians(ang)
        text(d, s, (kx + r * math.sin(a), ky - r * math.cos(a)), 1.9, WHITE)

    # flap selector scale (UP / 1 / 2 / DN, 30 deg steps clockwise)
    fx, fy = at(*L.FLAP_KNOB)
    for s, ang in L.FLAP_MARKS:
        a = math.radians(ang)
        tick_in, tick_out, lab = 15 * MM, 18 * MM, 23 * MM
        d.line((fx + tick_in * math.sin(a), fy - tick_in * math.cos(a), fx + tick_out * math.sin(a),
                fy - tick_out * math.cos(a)), fill=WHITE, width=max(1, int(0.45 * MM)))
        text(d, s, (fx + lab * math.sin(a), fy - lab * math.cos(a)), 2.0, WHITE)

    # other legends
    for s, xp, yp, h, style in L.LEGENDS:
        text(d, s, at(xp, yp), h, RED if style == 'red' else WHITE, bold=style != 'small')

    # circuit breaker legends
    for s, xp in L.BREAKERS_TOP:
        x, y = at(xp, 298)
        text(d, s, (x, y - 8.5 * MM), 1.7, WHITE)
    for i, s in enumerate(L.BREAKERS_ROW):
        x, y = at(L.BREAKER_ROW_X0 + i * L.BREAKER_ROW_DX, L.BREAKER_ROW_Y)
        text(d, s, (x, y - 8.5 * MM), 1.6, WHITE)
    x0 = at(L.BREAKER_ROW_X0 - 12, 0)[0]
    x1 = at(L.BREAKER_ROW_X0 + (len(L.BREAKERS_ROW) - 1) * L.BREAKER_ROW_DX + 12, 0)[0]
    y = at(0, L.BREAKER_ROW_Y)[1]
    text(d, 'CIRCUIT BREAKERS', ((x0 + x1) / 2, y + 9 * MM), 2.0, WHITE)

    # placards (POH 2.17)
    for lines, cx, cy, w, h, style in L.PLACARDS:
        (a, b), (c, e) = at(cx - w / 2, cy - h / 2), at(cx + w / 2, cy + h / 2)
        bg = YELLOW if style == 'warning' else SILVER
        rounded_rect(d, (a, b, c, e), 1.2 * MM, bg, outline=BLACK, width=max(1, int(0.3 * MM)))
        n = len(lines)
        pitch = (e - b) / (n + 0.6)
        for k, s in enumerate(lines):
            bold = k == 0 or style == 'plate'
            size = min(2.3, 0.65 * pitch / MM)
            if style == 'warning' and k == 0:
                size = min(2.8, 0.75 * pitch / MM)
            text(d, s, ((a + c) / 2, b + pitch * (k + 0.8)), size, BLACK, bold=bold)

    # Airmaster controller face (interior.prop_controller maps this patch onto its front disc)
    cy, cz = L.px_yz(*L.PROP_CTL_PX)

    def ctl(dy, dz):
        return L.tex_px(cy + dy, cz + dz)

    (x0, y0), (x1, y1) = ctl(0.0335, 0.0335), ctl(-0.0335, -0.0335)
    d.ellipse((x0, y0, x1, y1), fill=(24, 25, 27), outline=(70, 72, 76), width=max(1, int(0.4 * MM)))
    text(d, 'FINE', ctl(0.012, 0.0168), 1.5, WHITE)
    text(d, 'COARSE', ctl(-0.012, 0.0168), 1.5, WHITE)
    text(d, 'AUTO', ctl(0.022, 0.0085), 1.5, WHITE)
    text(d, 'MAN', ctl(0.022, -0.0085), 1.5, WHITE)
    ky, kz = L.PROP_KNOB_OFFSET
    for k, mode in enumerate(L.PROP_MODES):
        a = math.radians(L.PROP_KNOB_T0 + k * L.PROP_KNOB_STEP)
        sy, sz = math.sin(a), math.cos(a)
        d.line((*ctl(ky + sy * 0.0168, kz + sz * 0.0168), *ctl(ky + sy * 0.0195, kz + sz * 0.0195)),
               fill=WHITE, width=max(1, int(0.35 * MM)))
        tx, ty = ctl(ky + sy * 0.0205, kz + sz * 0.0205)
        d.text((tx, ty), mode, font=font(1.4), fill=WHITE, anchor='rm')

    # a very light blur softens the printed edges the way silk-screen ink does
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    img.save(OUT)
    print(f'panel texture {img.width} x {img.height} -> {OUT}')


if __name__ == '__main__':
    main()
