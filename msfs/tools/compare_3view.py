"""Overlay the POH 3-view drawing (red) on orthographic renders of the model (render_orthographic.py).

    python compare_3view.py POH_PAGE_1-3.png POH_PAGE_1-4.png RENDER_DIR

Drawing references were measured on the POH rev 3.5 pages rendered at 200 dpi (pixels of those images):
- side view: spinner-tip extension line x 274, ground line y 791, fin top y 431 (2350 mm) -> scale
- front view: span extension lines x 160 / 1448 (9500 mm), lowest tyre y 1492
- top view: tailplane span lines x 590 / 982 (3095 mm), nose tip y 1176.5 (the 1912 mm dimension)
They are placed on the model's spinner tip (model x 3.3), centreline and ground.
"""
import json
import os
import sys

from PIL import Image, ImageChops

p13, p14, rdir = sys.argv[1:4]
NOSE_X = 3.3          # spinner tip, model metres

# view: page, crop box (drawing px), drawing px per metre, drawing ref point, model ref point (right, down axes)
VIEWS = {
    'side': (p13, (150, 380, 1500, 830), (791 - 431) / 2.350, (274, 791), {'x': NOSE_X, 'z': 0.0}),
    'front': (p13, (120, 1120, 1500, 1540), (1448 - 160) / 9.500, ((160 + 1448) / 2, 1492), {'y': 0.0, 'z': 0.0}),
    'top': (p14, (120, 230, 1500, 1200), (982 - 590) / 3.095, ((590 + 982) / 2, 1176.5), {'y': 0.0, 'x': NOSE_X}),
}

for name, (page, box, dpm, ref, model_ref) in VIEWS.items():
    meta = json.load(open(os.path.join(rdir, f'ortho_{name}.json')))
    render = Image.open(os.path.join(rdir, f'ortho_{name}.png')).convert('RGB')
    k = meta['px_per_m']
    W, H = meta['size']

    def to_px(axis_sign, value):
        axis, sign = axis_sign
        return sign * (value - meta['centre'][axis]) * k

    rx = W / 2 + to_px(meta['right'], model_ref[meta['right'][0]])
    ry = H / 2 + to_px(meta['down'], model_ref[meta['down'][0]])
    s = k / dpm
    draw = Image.open(page).convert('L').crop(box)
    draw = draw.resize((round(draw.width * s), round(draw.height * s)), Image.LANCZOS)
    ox = rx - (ref[0] - box[0]) * s
    oy = ry - (ref[1] - box[1]) * s
    layer = Image.new('L', render.size, 255)
    layer.paste(draw, (round(ox), round(oy)))
    # render faded to grey, drawing lines in red on top
    faded = Image.blend(render, Image.new('RGB', render.size, (255, 255, 255)), 0.45)
    ink = layer.point(lambda v: 255 if v < 150 else 0)
    red = Image.new('RGB', render.size, (220, 0, 0))
    out = Image.composite(red, faded, ink)
    out.save(os.path.join(rdir, f'compare_{name}.png'))
    print('wrote', os.path.join(rdir, f'compare_{name}.png'))
