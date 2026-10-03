"""Paint the centre console texture atlas: carbon twill with printed legends and placards.

    python make_console_texture.py OUT.png

Three regions (console_layout.REGION): the flat top (throttle quadrant, brake lever, park brake
valve, headset sockets), the front slope (fuel selector) and the aft face (rear headset sockets).
Positions come from console_layout.py, the same numbers interior.py builds the parts from.
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import console_layout as C  # noqa: E402

OUT = sys.argv[1]
FONT = r'C:\Windows\Fonts\arial.ttf'
FONT_BOLD = r'C:\Windows\Fonts\arialbd.ttf'
MM = C.TEX_PX_PER_M / 1000.0

WHITE = (236, 236, 232)
GREY = (150, 150, 150)
RED = (200, 34, 30)
BLACK = (18, 18, 18)
SILVER = (196, 198, 200)


def font(size_mm, bold=True):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, max(8, int(round(size_mm * MM / 0.72))))


def carbon_tile(cell=14):
    # the panel's 2x2 twill (make_panel_texture.carbon_tile), a touch darker for the console
    n = cell * 4
    img = Image.new('RGB', (n, n))
    px = img.load()
    for j in range(n):
        for i in range(n):
            cu, cv = i // cell, j // cell
            fu, fv = (i % cell) / cell, (j % cell) / cell
            warp = ((cu + cv) // 2) % 2 == 0
            t = fv if warp else fu
            along = fu if warp else fv
            bundle = math.sin(math.pi * t)
            fibres = 0.5 + 0.5 * math.sin(2 * math.pi * (t * 7 + 0.3 * along))
            v = (0.06 if warp else 0.05) + 0.04 * bundle ** 1.6 + 0.007 * fibres
            v += 0.028 * max(0.0, bundle - 0.85) / 0.15 if warp else 0.0
            c = int(255 * min(1.0, v))
            px[i, j] = (c, c, int(c * 1.06))
    return img


class Face:
    """Drawing on one atlas region in metres: y across (left +), and the face's own 'along' coordinate."""

    def __init__(self, img, name):
        self.img, self.name = img, name
        self.d = ImageDraw.Draw(img)

    def p(self, y, a):
        kw = {'top': 'x', 'front': 's', 'rear': 'z'}[self.name]
        return C.tex_px(self.name, y, **{kw: a})

    def text(self, s, y, a, size_mm, fill=WHITE, bold=True, rot=0):
        f = font(size_mm, bold)
        if not rot:
            self.d.text(self.p(y, a), s, font=f, fill=fill, anchor='mm')
            return
        # rotated legend (rot=90 reads from aft to forward, bottom to top in the image)
        l, t, r, b = f.getbbox(s)
        tile = Image.new('RGBA', (r - l + 8, b - t + 8), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((4 - l, 4 - t), s, font=f, fill=fill + (255,))
        tile = tile.rotate(rot, expand=True, resample=Image.BICUBIC)
        cx, cy = self.p(y, a)
        self.img.paste(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)), tile)

    def line(self, y0, a0, y1, a1, w_mm=0.35, fill=WHITE):
        self.d.line((*self.p(y0, a0), *self.p(y1, a1)), fill=fill, width=max(1, int(w_mm * MM)))

    def rect(self, y0, a0, y1, a1, w_mm=0.3, fill=None, outline=GREY, r_mm=1.5):
        (c0, r0), (c1, r1) = self.p(y0, a0), self.p(y1, a1)
        box = (min(c0, c1), min(r0, r1), max(c0, c1), max(r0, r1))
        self.d.rounded_rectangle(box, radius=r_mm * MM, fill=fill, outline=outline, width=max(1, int(w_mm * MM)))

    def ring(self, y, a, r_m, w_mm=0.35, fill=GREY):
        cx, cy = self.p(y, a)
        r = r_m * C.TEX_PX_PER_M
        self.d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=fill, width=max(1, int(w_mm * MM)))

    def arc_arrow(self, y, a, r_m, start, end, w_mm=0.4, fill=WHITE):
        """Arc from angle start to end (deg, 0 = image up, clockwise) with an arrow head at `end`."""
        cx, cy = self.p(y, a)
        r = r_m * C.TEX_PX_PER_M
        self.d.arc((cx - r, cy - r, cx + r, cy + r), start - 90, end - 90, fill=fill, width=max(1, int(w_mm * MM)))
        t = math.radians(end)
        hx, hy = cx + r * math.sin(t), cy - r * math.cos(t)
        tx, ty = math.cos(t), math.sin(t)                     # clockwise tangent
        n = 1.4 * MM
        self.d.polygon([(hx + tx * n, hy + ty * n),
                        (hx - tx * n * 0.2 + math.sin(t) * n * 0.8, hy - ty * n * 0.2 - math.cos(t) * n * 0.8),
                        (hx - tx * n * 0.2 - math.sin(t) * n * 0.8, hy - ty * n * 0.2 + math.cos(t) * n * 0.8)], fill=fill)

    def placard(self, lines, y, a, w_m, h_m, style='plate'):
        """Engraved plate (silver, black text) or warning plate (red, white text), centred at (y, a)."""
        sgn = 1 if self.name == 'top' else -1              # 'along' grows toward the image top on every face
        y0, y1 = y + w_m / 2, y - w_m / 2
        a0, a1 = a + sgn * h_m / 2, a - sgn * h_m / 2
        bg, fg = (SILVER, BLACK) if style == 'plate' else (RED, WHITE)
        self.rect(y0, a0, y1, a1, w_mm=0.3, fill=bg, outline=BLACK, r_mm=1.2)
        (_, top_px), (_, bot_px) = self.p(y, a0), self.p(y, a1)
        top_px, bot_px = min(top_px, bot_px), max(top_px, bot_px)
        pitch = (bot_px - top_px) / (len(lines) + 0.4)
        cx = self.p(y, a)[0]
        for k, s in enumerate(lines):
            size = min(2.6, 0.62 * pitch / MM)
            self.d.text((cx, top_px + pitch * (k + 0.7)), s, font=font(size), fill=fg, anchor='mm')


def paint_top(f):
    # throttle quadrant: engraved outline, POWER scale beside the slot (FULL forward, IDLE aft)
    ty = C.THROTTLE_Y
    s0, s1 = C.THROTTLE_SLOT
    f.rect(ty + 0.032, s1 + 0.012, ty - 0.034, C.FRICTION[0] - 0.034, w_mm=0.35)
    f.text('THROTTLE', ty + 0.024, (s0 + s1) / 2, 2.6, rot=90)
    for i in range(11):
        x = s0 + 0.006 + (s1 - s0 - 0.012) * i / 10
        long = i % 5 == 0
        f.line(ty - 0.016, x, ty - (0.024 if long else 0.020), x, w_mm=0.35)
    f.text('FULL', ty - 0.030, s1 - 0.004, 1.9)
    f.text('IDLE', ty - 0.030, s0 + 0.004, 1.9)
    f.text('POWER', ty - 0.029, (s0 + s1) / 2, 1.6, bold=False, rot=90)
    # friction lock
    fx, fy = C.FRICTION
    f.ring(fy, fx, 0.0165, fill=GREY)
    f.arc_arrow(fy, fx, 0.0205, 200, 300)
    f.text('+', fy + 0.023, fx + 0.012, 2.0)
    f.text('FRICTION', fy, fx - 0.026, 1.8)

    # hand brake lever (POH 7.2.3.1): the throttle's smaller twin, forward = off, pull aft to brake
    by, (b0, b1) = C.BRAKE_Y, C.BRAKE_SLOT
    f.rect(by + 0.026, b1 + 0.012, by - 0.030, b0 - 0.034, w_mm=0.35)
    f.text('BRAKE', by - 0.022, (b0 + b1) / 2, 2.6, rot=90)
    for i in range(6):
        x = b0 + 0.004 + (b1 - b0 - 0.008) * i / 5
        f.line(by + 0.014, x, by + (0.021 if i in (0, 5) else 0.018), x, w_mm=0.35)
    f.text('OFF', by + 0.020, b1 + 0.004, 1.8)
    f.text('ON', by + 0.020, b0 - 0.005, 1.8, fill=RED)
    f.text('PULL', by, b0 - 0.020, 1.6, bold=False)

    # park brake valve (item 9): quarter-turn T handle, along the console = OFF, across = ON
    vx, vy = C.PARK_VALVE
    f.ring(vy, vx, 0.013, fill=GREY)
    f.text('PARK BRAKE', vy, vx + 0.032, 2.0)
    f.text('OFF', vy, vx - 0.030, 1.9)
    f.text('ON', vy + 0.030, vx, 1.9, fill=RED)
    f.arc_arrow(vy, vx, 0.024, 190, 260, fill=GREY)

    # headset sockets (item 5)
    for label, y, x_phone, x_mic in C.HEADSETS:
        side = 1 if y > 0 else -1
        f.ring(y, x_phone, 0.0095)
        f.ring(y, x_mic, 0.0075)
        f.text('PHONE', y + side * 0.024, x_phone, 1.6)
        f.text('MIC', y + side * 0.021, x_mic, 1.6)
        f.text(label, y, x_phone - 0.019, 1.9)
    px_, py_ = C.POWER_SOCKET
    f.ring(py_, px_, 0.015)
    f.text('12V', py_, px_ + 0.021, 1.6)
    f.text('SOCKET', py_, px_ - 0.021, 1.5, bold=False)


def paint_front(f):
    # fuel tank selector (POH 7.2.5): red, LEFT / RIGHT / OFF; OFF needs the release knob
    s = C.FUEL_SEL_S
    f.text('FUEL SELECTOR', 0.0, s + 0.068, 2.8)
    f.ring(0.0, s, 0.046, w_mm=0.5, fill=WHITE)
    for label, ang, col in (('LEFT', -90, WHITE), ('RIGHT', 90, WHITE), ('OFF', 180, RED)):
        a = math.radians(ang)
        r1, r2, rt = 0.047, 0.054, 0.066
        f.line(-math.sin(a) * r1, s + math.cos(a) * r1, -math.sin(a) * r2, s + math.cos(a) * r2, w_mm=0.8, fill=col)
        if label == 'OFF':
            f.text(label, 0.0, s - 0.060, 2.8, fill=col)
        else:
            f.text(label, -math.sin(a) * rt, s + 0.010, 2.6, fill=col)
            f.text('TANK', -math.sin(a) * rt, s - 0.002, 1.7, bold=False)
    ky, ks = C.FUEL_OFF_KNOB
    f.ring(ky, ks, 0.011, fill=RED)
    f.text('PUSH', ky, ks - 0.017, 1.6, fill=RED)
    f.text('FOR OFF', ky, ks - 0.022, 1.6, fill=RED)
    f.placard(['AVGAS OR MOGAS'], 0.052, 0.034, 0.05, 0.012)
    f.placard(['NO SMOKING'], 0.0, 0.212, 0.07, 0.013, style='warning')     # POH 2.17.2, seen from every seat


def paint_rear(f):
    z = C.REAR_JACK_Z
    for label, yp, ym in C.REAR_HEADSETS:
        f.ring(yp, z, 0.0095)
        f.ring(ym, z, 0.0075)
        f.text(label, (yp + ym) / 2, z + 0.017, 1.9)
        f.text('PHONE', yp, z - 0.015, 1.4)
        f.text('MIC', ym, z - 0.015, 1.4)


def paint_flag(img):
    """REMOVE BEFORE FLIGHT streamer for the parachute handle's safety pin (POH 7.2.6: red flag): red nylon
    tape with a fine weave, stitched hems along both edges, the legend twice along the length and a reinforced
    end where the grommet goes (the left end of the image is the top of the streamer)."""
    import random
    c0, r0, w, h = C.REGION['flag']
    rnd = random.Random(7)
    tape = Image.new('RGB', (w, h), (190, 20, 24))
    px = tape.load()
    for yy in range(h):
        for xx in range(w):
            weave = 10 if (xx // 2 + yy // 2) % 2 else -6
            n = rnd.randint(-5, 5)
            px[xx, yy] = (max(0, min(255, 190 + weave + n)), 20 + n // 2, 24 + n // 2)
    d = ImageDraw.Draw(tape)
    white = (244, 242, 236)
    for yy in (6, h - 7):                                        # stitched hems
        for xx in range(4, w - 4, 10):
            d.line((xx, yy, xx + 6, yy), fill=(120, 10, 12), width=2)
    d.rectangle((0, 0, 70, h - 1), fill=(176, 16, 20))           # reinforced top end
    for xx in (66, 70):
        d.line((xx, 4, xx, h - 5), fill=(120, 10, 12), width=2)
    f = font(4.6)
    for cx in (w * 0.37, w * 0.79):
        d.text((cx, h / 2), 'REMOVE BEFORE FLIGHT', font=f, fill=white, anchor='mm')
    img.paste(tape, (c0, r0))


def paint_compass_card(img):
    """Magnetic compass card rim: black, white ticks every 5 deg (long every 10), headings every 30 deg as on a
    standard card (N 3 6 E 12 15 S 21 24 W 30 33). The strip runs with 360 - heading, so read left to right on the
    card the headings fall (..., 6, 3, N, 33, 30, ...: reverse sensing) while each label reads normally."""
    c0, r0, w, h = C.REGION['compass_card']
    d = ImageDraw.Draw(img)
    d.rectangle((c0, r0, c0 + w - 1, r0 + h - 1), fill=(12, 12, 12))
    white = (240, 240, 236)
    labels = {0: 'N', 30: '3', 60: '6', 90: 'E', 120: '12', 150: '15', 180: 'S', 210: '21', 240: '24',
              270: 'W', 300: '30', 330: '33'}
    for deg in range(0, 365, 5):                       # 360 repeats N so it wraps across the seam
        x = c0 + w * (360 - deg) / 360
        deg %= 360
        long = deg % 10 == 0
        d.line((x, r0 + 2, x, r0 + (15 if long else 9)), fill=white, width=2 if long else 1)
        if deg in labels:
            d.text((x, r0 + h * 0.66), labels[deg], font=font(3.6), fill=(250, 200, 60) if deg % 90 == 0 else white,
                   anchor='mm')


def paint_quilt(img):
    """Black leather, diamond quilted (as the Sling 4 TSi seats): 40 mm diamonds, each puffed (lighter in the
    middle, darker at the seams), with a double row of stitches along every seam and a faint grain."""
    import random
    c0, r0, w, h = C.REGION['quilt']
    rnd = random.Random(3)
    tile = Image.new('RGB', (w, h))
    px = tile.load()
    d_px = int(0.040 * C.QUILT_PX_PER_M)                # diamond diagonal, px
    half = d_px / 2
    for yy in range(h):
        for xx in range(w):
            # distance to the nearest seam of a 45-degree grid
            a = ((xx + yy) % d_px) / d_px
            b = ((xx - yy) % d_px) / d_px
            edge = min(a, 1 - a, b, 1 - b) * 2            # 0 at a seam, 1 in the middle of a diamond
            v = int(18 + 22 * (edge ** 0.6)) + rnd.randint(-2, 2)
            px[xx, yy] = (v, v, int(v * 1.04))
    d = ImageDraw.Draw(tile)
    stitch = (78, 78, 80)
    for k in range(-h, w + h, d_px):                     # stitch rows either side of each seam
        for off in (-3, 3):
            for t in range(0, w + h, 7):
                x0, y0 = k + t + off, t
                if 0 <= x0 < w and 0 <= y0 < h:
                    d.line((x0, y0, x0 + 3, y0 + 3), fill=stitch, width=1)
                x1 = k + t + off
                y1 = h - 1 - t
                if 0 <= x1 < w and 0 <= y1 < h:
                    d.line((x1, y1, x1 + 3, y1 - 3), fill=stitch, width=1)
    img.paste(tile, (c0, r0))


def paint_seat_logo(img):
    """Embroidered "Sling" script with a thin underline swash, silver on black leather."""
    c0, r0, w, h = C.REGION['seat_logo']
    d = ImageDraw.Draw(img)
    d.rectangle((c0, r0, c0 + w - 1, r0 + h - 1), fill=(47, 46, 45))     # the seat leather's colour (sRGB)
    try:
        f = ImageFont.truetype(r'C:\Windows\Fonts\segoescb.ttf', 64)
    except OSError:
        f = ImageFont.truetype(r'C:\Windows\Fontsriali.ttf', 64)
    d.text((c0 + w * 0.48, r0 + h * 0.46), 'Sling', font=f, fill=(196, 198, 200), anchor='mm')
    d.arc((c0 + w * 0.18, r0 + h * 0.55, c0 + w * 0.86, r0 + h * 1.15), 200, 335, fill=(210, 80, 20), width=4)
    d.text((c0 + w * 0.8, r0 + h * 0.3), 'TSi', font=font(4.0), fill=(210, 80, 20), anchor='mm')


def main():
    img = Image.new('RGB', (C.TEX_W, C.TEX_H), (14, 14, 15))
    tile = carbon_tile()
    for y in range(0, img.height, tile.height):
        for x in range(0, img.width, tile.width):
            img.paste(tile, (x, y))
    paint_top(Face(img, 'top'))
    paint_front(Face(img, 'front'))
    paint_rear(Face(img, 'rear'))
    paint_flag(img)
    paint_compass_card(img)
    paint_quilt(img)
    paint_seat_logo(img)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    img.save(OUT)
    print(f'console texture {img.width} x {img.height} -> {OUT}')


if __name__ == '__main__':
    main()
