"""Sling TSi instrument panel layout, shared by the model (interior.py), the panel texture
(make_panel_texture.py) and the switch behaviours (make_interior_behaviors.py).

Plain Python, no Blender: positions are POH 7.10 panel-diagram pixels (1369 x 595 px), converted
to panel coordinates (y lateral, +left; z up, metres) by px_yz(). The panel face texture maps y and
z linearly (TEX_Y0..TEX_Y1, TEX_Z0..TEX_Z1) at TEX_PX_PER_M, so labels drawn in the texture land
exactly next to the parts the model places from the same pixel positions.
"""

PX = 0.000803                   # metres per diagram pixel (panel spans the cabin width)
PANEL_Z_TOP = 1.45              # the panel's straight top edge (diagram y = 103)

# POH 7.10 panel diagram: outer outline sampled every 38 px, as (x, top y, bottom y)
PANEL_PX = [(0, 297, 501), (38, 236, 501), (76, 171, 495), (114, 136, 488), (152, 116, 483),
            (190, 105, 481), (228, 103, 481), (304, 103, 481), (380, 103, 481), (418, 97, 481),
            (456, 88, 481), (494, 74, 481), (532, 63, 481), (570, 60, 494), (608, 60, 519),
            (646, 60, 525), (684, 60, 525), (722, 60, 525), (760, 60, 519), (798, 60, 495),
            (836, 63, 481), (874, 74, 481), (912, 88, 481), (950, 97, 481), (988, 103, 481),
            (1064, 103, 481), (1140, 103, 481), (1178, 105, 481), (1216, 116, 483), (1254, 136, 488),
            (1292, 170, 495), (1330, 235, 501), (1368, 296, 501)]


def px_yz(xp, yp):
    """POH panel diagram pixel -> (y, z) on the panel."""
    return (684.5 - xp) * PX, PANEL_Z_TOP - (yp - 103) * PX


def smooth_outline_px(iterations=4):
    """The traced outline as a closed loop in diagram pixels, corners rounded by Chaikin cutting
    (the raw 38 px samples make a visibly stepped edge)."""
    top = [(x, t) for x, t, _ in PANEL_PX]
    bot = [(x, b) for x, _, b in reversed(PANEL_PX)]
    loop = top + bot
    for _ in range(iterations):
        new = []
        n = len(loop)
        for i in range(n):
            (x0, y0), (x1, y1) = loop[i], loop[(i + 1) % n]
            new.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            new.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        loop = new
    return loop


# Panel face texture: 6144 x 2304 px over 1.12 m x 0.42 m (5486 px/m, about 5.5 px per mm)
TEX_W, TEX_H = 6144, 2304
TEX_Y0, TEX_Y1 = 0.56, -0.56            # u = 0 at the left (+y) edge
TEX_Z0 = 1.075
TEX_PX_PER_M = TEX_W / (TEX_Y0 - TEX_Y1)
TEX_Z1 = TEX_Z0 + TEX_H / TEX_PX_PER_M


def uv(y, z):
    return (TEX_Y0 - y) / (TEX_Y0 - TEX_Y1), (z - TEX_Z0) / (TEX_Z1 - TEX_Z0)


def tex_px(y, z):
    """Panel point -> texture pixel (origin top left)."""
    u, v = uv(y, z)
    return u * TEX_W, (1 - v) * TEX_H


# ---------------------------------------------------------------- switches (POH 7.2.7 / 7.10)
# name: node base name; xp, yp: diagram pixel of the toggle; label: panel legend;
# template + params: the Asobo behaviour that makes it work in the sim.
def _circuit(cid):
    return 'ASOBO_ELECTRICAL_Switch_Circuit_Template', {'CIRCUIT_ID': cid, 'ID': cid}


def _lane(side):
    """ECU lane A/B as the left/right side of engine 1's magneto selector. Asobo's magneto template
    can't do this: its uncovered ON_OFF mode reads MAGNETO_ID as the *engine* index, toggles the
    whole OFF/L/R/BOTH selector and shows the lever up only in state LEFT, so the lanes looked
    inverted. Here a click sets the selector to (this side flipped, other side kept)."""
    this, other = ('LEFT', 'RIGHT') if side == 'A' else ('RIGHT', 'LEFT')
    left = f'(A:RECIP ENG {this} MAGNETO:1, Bool) !' if side == 'A' else f'(A:RECIP ENG {other} MAGNETO:1, Bool)'
    right = f'(A:RECIP ENG {other} MAGNETO:1, Bool)' if side == 'A' else f'(A:RECIP ENG {this} MAGNETO:1, Bool) !'
    click = (f'{left} {right} 2 * + s0 '                     # 0 off, 1 left, 2 right, 3 both
             'l0 0 == if{ (&gt;K:MAGNETO1_OFF) } l0 1 == if{ (&gt;K:MAGNETO1_LEFT) } '
             'l0 2 == if{ (&gt;K:MAGNETO1_RIGHT) } l0 3 == if{ (&gt;K:MAGNETO1_BOTH) }')
    return 'ASOBO_GT_Component_Switch_Code', {
        'ANIM_CODE': f'(A:RECIP ENG {this} MAGNETO:1, Bool) 100 *',
        'LEFT_SINGLE_CODE': click,
        'WWISE_EVENT_1': 'magneto_switch_on', 'WWISE_EVENT_2': 'magneto_switch_off'}


SWITCH_ROW_Y = 432
SWITCHES = [
    # left end: lanes A/B on the red plate (item 5), master (item 2)
    ('Lane_A', 120, 262, 'LANE A', *_lane('A')),
    ('Lane_B', 150, 262, 'LANE B', *_lane('B')),
    ('Master', 108, 300, 'MASTER', 'ASOBO_ELECTRICAL_Switch_Battery_Master_Template', {'ID': 1}),
    # fuel pumps on the red plate (item 25)
    ('Pump_Main', 196, SWITCH_ROW_Y, 'MAIN', 'ASOBO_FUEL_Switch_Pump_Template', {'ID': 1}),
    ('Pump_Aux', 224, SWITCH_ROW_Y, 'AUX', *_circuit(26)),
    # switch row (item 24)
    ('EFIS', 257.0, SWITCH_ROW_Y, 'EFIS', *_circuit(13)),
    ('EFIS_Bkup', 285.5, SWITCH_ROW_Y, 'EFIS BKUP', *_circuit(23)),
    ('Avionics', 314.0, SWITCH_ROW_Y, 'AVIONICS', 'ASOBO_ELECTRICAL_Switch_Avionics_Master_Template', {'ID': 1}),
    ('Alt', 342.5, SWITCH_ROW_Y, 'ALT', 'ASOBO_ELECTRICAL_Switch_Alternator_Template', {'ID': 1}),
    ('Autopilot', 371.0, SWITCH_ROW_Y, 'AUTOPILOT', *_circuit(21)),
    ('ECU_Bkup', 399.5, SWITCH_ROW_Y, 'ECU BKUP', *_circuit(25)),
    ('Pitot', 428.0, SWITCH_ROW_Y, 'PITOT HT', 'ASOBO_DEICE_Switch_Pitot_Template', {'ID': 1}),
    ('Cabin', 456.5, SWITCH_ROW_Y, 'CABIN LT', 'ASOBO_LIGHTING_Switch_Light_Cabin_Template', {'ID': 1}),
    ('Land', 485.0, SWITCH_ROW_Y, 'LAND', 'ASOBO_LIGHTING_Switch_Light_Landing_Template', {'ID': 1}),
    # three-position ON / WIG-WAG / OFF (POH 7.15.5); logic in SlingTSi.xml Taxi_WigWag
    ('Taxi', 513.5, SWITCH_ROW_Y, 'TAXI', 'ASOBO_GT_Knob_Finite_Code', {
        'ANIM_CODE': '(L:SLING_TAXI_MODE, number) 50 *',
        'CLOCKWISE_CODE': '(L:SLING_TAXI_MODE, number) 1 + 2 min (&gt;L:SLING_TAXI_MODE, number)',
        'ANTICLOCKWISE_CODE': '(L:SLING_TAXI_MODE, number) 1 - 0 max (&gt;L:SLING_TAXI_MODE, number)',
        'COUNT': 3}),
    ('Nav', 542.0, SWITCH_ROW_Y, 'NAV', 'ASOBO_LIGHTING_Switch_Light_Navigation_Template', {'ID': 1}),
    ('Strobe', 570.5, SWITCH_ROW_Y, 'STROBE', 'ASOBO_LIGHTING_Switch_Light_Strobe_Template', {'ID': 1}),
    # propeller controller power (item 24 lists "propeller" among the row switches, POH 7.3.1 "PROP")
    ('Prop', 599.0, SWITCH_ROW_Y, 'PROP', *_circuit(24)),
    # propeller control switch (item 23, POH 7.3.2): spring-centred FINE (up) / COARSE (down). Scroll or drag:
    # in MAN it trims the pitch, in AUTO + HOLD it sets the held rpm (logic in SlingTSi.xml).
    ('Prop_pitch', 553, 300, 'PITCH', 'ASOBO_GT_Knob_Finite_Code', {
        'ANIM_CODE': '(L:SLING_PROP_PITCH_ANIM, number)',
        'CLOCKWISE_CODE': '1 (&gt;L:SLING_PROP_STEP, number)',
        'ANTICLOCKWISE_CODE': '-1 (&gt;L:SLING_PROP_STEP, number)',
        'COUNT': 3}),
]

# circuits the switches above need that the sim has no ready-made type for (systems.cfg)
EXTRA_CIRCUITS = {23: 'EFIS_Backup', 24: 'Prop_Controller', 25: 'ECU_Backup', 26: 'Aux_Fuel_Pump'}

KEY = ('Key', 150, 300)                 # master/starter key (item 3): click and hold to crank

# ---------------------------------------------------------------- printed legends
# (text, diagram x, diagram y, height mm, style) - style: 'label' white, 'red' red, 'small' white small
LEGENDS = [
    ('POWER', 80, 318, 2.2, 'small'),
    ('12V', 135, 172, 2.4, 'small'),
    ('12V', 1250, 187, 2.4, 'small'),
    ('EFIS', 515, 112, 2.4, 'small'),
    ('FUEL PUMPS', 210, 399, 2.6, 'small'),
    ('CABIN AIR', 90, 356, 2.2, 'small'),
    ('CABIN AIR', 1280, 360, 2.2, 'small'),
    ('FLAPS', 530, 376, 2.8, 'label'),
    ('CABIN HEAT', 683, 350, 2.8, 'label'),
    ('TEMP', 645, 412, 2.4, 'small'),
    ('FAN', 722, 412, 2.4, 'small'),
    ('PARACHUTE', 683, 425, 2.6, 'red'),          # above and below the handle's mount plate
    ('PULL', 683, 491, 2.6, 'red'),
    ('ELT', 1200, 265, 2.4, 'small'),
]
# flap selector positions (POH 7.2.10: UP, stage 1, stage 2, DOWN), angle clockwise from up, deg
FLAP_MARKS = [('UP', 0), ('1', 30), ('2', 60), ('DN', 90)]
FLAP_KNOB = (565, 383)

# circuit breakers (item 15): legend per breaker, left to right
BREAKERS_TOP = [('FLAP', 1205), ('TRIM', 1235), ('PROP', 1265)]
BREAKERS_ROW = ['EFIS', 'EFIS 2', 'AVN', 'COM', 'XPDR', 'AP', 'ECU A', 'ECU B', 'PUMP', 'LIGHTS', 'STROBE', '12V']
BREAKER_ROW_Y = 425
BREAKER_ROW_X0, BREAKER_ROW_DX = 852, 31.2

# placards (POH 2.17): (lines, diagram centre x, y, width px, height px, style)
PLACARDS = [
    (['OPERATE UNDER VMC ONLY',
      'MAXIMUM PERMISSIBLE AIRSPEED 155 KIAS',
      'MAXIMUM PERMISSIBLE RPM 5 800 RPM FOR 5 MINUTES',
      'MAXIMUM CONTINUOUS RPM 5 500',
      'MAXIMUM PERMISSIBLE MASS 950 KG / 2,094 LB'], 1015, 262, 250, 62, 'plate'),
    (['WARNING', 'NON-CERTIFIED AIRCRAFT',
      'THIS AIRCRAFT IS NOT REQUIRED TO COMPLY WITH ALL',
      'THE REGULATIONS FOR TYPE CERTIFIED AIRCRAFT',
      'YOU FLY IN THIS AIRCRAFT AT YOUR OWN RISK'], 1015, 340, 250, 62, 'warning'),
    (['WARNING', 'AEROBATICS AND INTENTIONAL SPINS', 'ARE PROHIBITED'], 1015, 390, 170, 30, 'warning'),
    (['NO SMOKING'], 1150, 390, 70, 18, 'plate'),
]
# red plates printed on the panel behind the lane and pump switches
RED_PLATES = [(103, 235, 168, 278, 'LANES'), (180, 410, 240, 452, '')]

# ---------------------------------------------------------------- Airmaster propeller controller (item 9)
# POH 7.3.2. The blue selector steps anticlockwise (as the pilot sees it) through the modes; its bar points
# at T.O. at PROP_KNOB_T0 degrees anticlockwise from up, PROP_KNOB_STEP degrees per mode.
PROP_CTL_PX = (583, 155)                 # controller centre, diagram pixels
PROP_CTL_R = 0.036                       # body radius, m
PROP_KNOB_OFFSET = (-0.010, -0.002)      # knob centre from the body centre (y, z), m
PROP_KNOB_T0, PROP_KNOB_STEP = 45.0, 27.0
PROP_MODES = ['T.O.', 'CLIMB', 'CRUISE', 'HOLD', 'FEATHER']
# Governed engine rpm per mode. CLIMB and CRUISE are the propeller settings in POH 5.4 (5500 / 5000 rpm);
# T.O. is the 5800 rpm take-off limit (POH 2.14.3); HOLD starts at the CRUISE value (POH 7.3.2.1 note).
PROP_MODE_RPM = [5800, 5500, 5000, None, None]
