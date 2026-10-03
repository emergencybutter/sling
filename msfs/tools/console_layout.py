"""Centre console (pedestal) layout, shared by interior.py (geometry), make_console_texture.py
(printed legends and placards) and make_interior_behaviors.py (clickable parts).

Blender world coordinates (m): nose +X, left +Y, up +Z. The console (POH 7.9 items 4, 5, 7, 9, 11,
12) has three printed faces, each a region of one texture atlas at TEX_PX_PER_M:
- TOP: the flat top, x TOP_X0..TOP_X1, read by the pilot looking down (text "up" = forward).
- FRONT: the face sloping up to the panel, carrying the fuel selector (text "up" = up the slope).
- REAR: the aft face, facing the rear seats (rear headset sockets).
Image columns always run from +Y (left) to -Y (right), so text reads left to right for everyone
sitting in the cabin.
"""
import math

TEX_PX_PER_M = 4000.0            # 4 px per mm
TEX_W, TEX_H = 2048, 4096
HALF_W = 0.088                   # printed plates' half-width (the console is +-0.095)

# console profile (interior.console): top from (0.20, 0.90) to (1.02, 0.94), then the front slope
# up to (1.20, 1.108); the aft face is x = 0.10 from the floor (0.72) up to z = 0.86.
TOP_X0, TOP_X1 = 0.215, 1.012
FRONT_A, FRONT_B = (1.02, 0.94), (1.20, 1.108)
FRONT_S0, FRONT_S1 = 0.012, 0.232          # printed part of the slope (distance up from FRONT_A)
REAR_X, REAR_Z0, REAR_Z1 = 0.10, 0.735, 0.852


def top_z(x):
    return 0.90 + (x - 0.20) * (0.94 - 0.90) / (1.02 - 0.20)


TOP_SLOPE = math.atan((0.94 - 0.90) / (1.02 - 0.20))        # rad, the top rises toward the nose
_front_len = math.hypot(FRONT_B[0] - FRONT_A[0], FRONT_B[1] - FRONT_A[1])
FRONT_DIR = ((FRONT_B[0] - FRONT_A[0]) / _front_len, (FRONT_B[1] - FRONT_A[1]) / _front_len)   # (dx, dz) up the slope

# atlas regions (px): (col0, row0, cols, rows)
_cols = int(round(2 * HALF_W * TEX_PX_PER_M))
REGION = {
    'top': (0, 0, _cols, int(round((TOP_X1 - TOP_X0) * TEX_PX_PER_M))),
    'front': (800, 0, _cols, int(round((FRONT_S1 - FRONT_S0) * TEX_PX_PER_M))),
    'rear': (800, 1100, _cols, int(round((REAR_Z1 - REAR_Z0) * TEX_PX_PER_M))),
    # parachute pin streamer (interior.chute_handle): 240 x 25 mm fabric, length along the image width
    'flag': (1040, 1700, 960, 100),
    # magnetic compass card strip (interior.compass): 360 deg of heading along the width
    'compass_card': (1040, 1830, 503, 56),
    # seat upholstery (interior.seat): diamond-quilted leather, 2 px/mm, panels map a part of it at true size,
    # and the embroidered Sling logo for the headrests
    'quilt': (0, 1950, 1000, 1800),
    'seat_logo': (1040, 1950, 400, 120),
}
QUILT_PX_PER_M = 2000.0
COMPASS_CARD_R, COMPASS_CARD_H = 0.022, 0.018      # card radius, height (m)
FLAG_SIZE = (0.240, 0.025)          # streamer length, width (m)


def _along(face, x=None, z=None, s=None):
    """Distance from the top edge of a region's image (m)."""
    if face == 'top':
        return TOP_X1 - x
    if face == 'front':
        return FRONT_S1 - s
    return REAR_Z1 - z


def tex_px(face, y, x=None, z=None, s=None):
    """Atlas pixel of a point on a face: y plus x (top), s (front, m up the slope) or z (rear)."""
    c0, r0, _, _ = REGION[face]
    return c0 + (HALF_W - y) * TEX_PX_PER_M, r0 + _along(face, x, z, s) * TEX_PX_PER_M


def uv(face, y, x=None, z=None, s=None):
    c, r = tex_px(face, y, x, z, s)
    return c / TEX_W, 1 - r / TEX_H


def front_point(y, s, proud=0.0):
    """World point on the front slope, s metres up from FRONT_A, `proud` out of the face."""
    nx, nz = -FRONT_DIR[1], FRONT_DIR[0]            # face normal, toward the cabin (aft and up)
    return (FRONT_A[0] + FRONT_DIR[0] * s + nx * proud, y, FRONT_A[1] + FRONT_DIR[1] * s + nz * proud)


FRONT_NORMAL = (-FRONT_DIR[1], 0.0, FRONT_DIR[0])
TOP_NORMAL = (-math.sin(TOP_SLOPE), 0.0, math.cos(TOP_SLOPE))

# ---------------------------------------------------------------- parts (world x, y on the top)
THROTTLE_Y = 0.045
THROTTLE_PIVOT_X = 0.95          # the lever turns +-22 deg about a pivot 5 cm under the top
THROTTLE_SLOT = (0.905, 0.995)   # slot in the quadrant cover (the arm moves +-24 mm at the top)
FRICTION = (0.872, 0.045)
# hand brake: a smaller twin of the throttle lever, pulled aft to brake (+-16 deg about a pivot 4 cm down)
BRAKE_Y = -0.052
BRAKE_PIVOT_X = 0.95
BRAKE_SLOT = (0.922, 0.978)
PARK_VALVE = (0.705, -0.028)
HEADSETS = [                     # (label, y, phone x, mic x)
    ('PILOT', 0.052, 0.600, 0.638),
    ('PASSENGER', -0.052, 0.600, 0.638),
]
POWER_SOCKET = (0.618, 0.0)      # 12 V / USB outlet between the headset pairs
ARMREST = (0.225, 0.565)         # padded lid over the storage box, aft of the headset sockets

# fuel selector (item 12) on the front slope: centre, and the OFF release knob beside it
FUEL_SEL_S = 0.105
FUEL_OFF_KNOB = (-0.058, 0.05)   # (y, s)

# rear face: two headset pairs for the back seats (item 7), high up: the rear bench cushion
# (top about z 0.88) hides the lower part of this face
REAR_HEADSETS = [('REAR LEFT', 0.058, 0.030), ('REAR RIGHT', -0.058, -0.030)]     # label, phone y, mic y
REAR_JACK_Z = 0.828

# ---------------------------------------------------------------- clickable parts
# (component id, template, params) for make_interior_behaviors.py. Node names are built by
# interior.console(); the animations by postprocess_gltf.py.
_FUEL_SEL = '(A:FUEL TANK SELECTOR:1, Enum)'           # 0 off, 2 left, 3 right
BEHAVIORS = [
    ('Throttle', 'ASOBO_ENGINE_Lever_Throttle_Template',
     {'NODE_ID': 'Throttle_knob', 'ANIM_NAME': 'throttle_lever_anim', 'ID': 1}),
    ('Hand_Brake', 'ASOBO_LANDING_GEAR_Lever_Brake_Template',
     {'NODE_ID': 'Brake_lever_grip', 'ANIM_NAME': 'brake_lever_anim'}),
    ('Park_Brake', 'ASOBO_GT_Component_Switch_Code',
     {'NODE_ID': 'Park_brake_handle', 'ANIM_NAME': 'park_brake_anim',
      'ANIM_CODE': '(A:BRAKE PARKING POSITION, Bool) 100 *',
      'LEFT_SINGLE_CODE': '(&gt;K:PARKING_BRAKES)',
      'WWISE_EVENT_1': 'parking_brake_switch_on', 'WWISE_EVENT_2': 'parking_brake_switch_off'}),
    # handle: LEFT <-> RIGHT (from OFF it goes to LEFT); anim 0 = LEFT, 50 = OFF, 100 = RIGHT
    ('Fuel_Selector', 'ASOBO_GT_Component_Switch_Code',
     {'NODE_ID': 'Fuel_selector_handle', 'ANIM_NAME': 'fuel_selector_anim',
      'ANIM_CODE': f'{_FUEL_SEL} s0 2 == if{{ 0 }} els{{ l0 3 == if{{ 100 }} els{{ 50 }} }}',
      'LEFT_SINGLE_CODE': f'{_FUEL_SEL} 2 == if{{ (&gt;K:FUEL_SELECTOR_RIGHT) }} els{{ (&gt;K:FUEL_SELECTOR_LEFT) }}'}),
    # release knob (POH 7.2.5): the only way to OFF
    ('Fuel_Selector_Off', 'ASOBO_GT_Component_Switch_Code',
     {'NODE_ID': 'Fuel_selector_off', 'ANIM_NAME': 'fuel_off_anim', 'ANIM_CODE': '0',
      'LEFT_SINGLE_CODE': '(&gt;K:FUEL_SELECTOR_OFF)'}),
]
