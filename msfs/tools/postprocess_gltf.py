"""Make a Blender-exported glTF ready for the MSFS package tool, and add its animations.

    python postprocess_gltf.py IN.gltf META.json OUT.gltf

- drops extensions the sim doesn't read (clearcoat), keeps images referenced by file name only
- screen materials ($AS3X_Touch_n) become emissive render targets, like the SDK samples
- appends one glTF animation per <Animation name> in SlingTSi.xml, using the hinge axes
  that blender_export.py measured. Keyframe times run over 100 frames at 60 fps; the sim
  maps each animation's AnimLength (100) onto that span.
"""
import json
import math
import os
import struct
import sys

src, meta_path, dst = sys.argv[1:4]
g = json.load(open(src))
meta = json.load(open(meta_path))
bin_src = os.path.join(os.path.dirname(src), g['buffers'][0]['uri'])
data = bytearray(open(bin_src, 'rb').read())

# ---- materials ---------------------------------------------------------------------------
for m in g['materials']:
    m.pop('extensions', None)
    if m['name'].startswith('$'):
        # Same setup as the SDK WasmAircraft screens; SlingTSi.xml scales it with cockpit light.
        g['materials'][g['materials'].index(m)] = {'name': m['name'], 'emissiveFactor': [2000.0] * 3}
g['extensionsUsed'] = [e for e in g.get('extensionsUsed', []) if not e.startswith('KHR_materials')]
if not g['extensionsUsed']:
    del g['extensionsUsed']
for img in g.get('images', []):
    img['uri'] = os.path.basename(img['uri'])

# ---- animations ----------------------------------------------------------------------------
node_index = {n['name']: i for i, n in enumerate(g['nodes'])}
FPS = 60.0


def quat(axis, deg):
    h = math.radians(deg) / 2
    s = math.sin(h)
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h)]


def add_accessor(values, comps):
    """Append float data to the buffer and return a new accessor index."""
    while len(data) % 4:
        data.append(0)
    offset = len(data)
    flat = [c for v in values for c in (v if comps > 1 else [v])]
    data.extend(struct.pack(f'<{len(flat)}f', *flat))
    g['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': 4 * len(flat)})
    acc = {'bufferView': len(g['bufferViews']) - 1, 'componentType': 5126, 'count': len(values),
           'type': {1: 'SCALAR', 3: 'VEC3', 4: 'VEC4'}[comps]}
    if comps == 1:
        acc['min'], acc['max'] = [min(values)], [max(values)]
    g['accessors'].append(acc)
    return len(g['accessors']) - 1


def rotation_anim(name, tracks):
    """tracks: list of (node name, [(frame, degrees), ...]) turning about that node's hinge."""
    anim = {'name': name, 'channels': [], 'samplers': []}
    tracks = [(n, k) for n, k in tracks if n in node_index]    # the interior has no moving parts
    if not tracks:
        return
    for node, keys in tracks:
        axis = meta['axes'][node]
        t = add_accessor([f / FPS for f, _ in keys], 1)
        q = add_accessor([quat(axis, d) for _, d in keys], 4)
        anim['samplers'].append({'input': t, 'output': q, 'interpolation': 'LINEAR'})
        anim['channels'].append({'sampler': len(anim['samplers']) - 1,
                                 'target': {'node': node_index[node], 'path': 'rotation'}})
    g.setdefault('animations', []).append(anim)


def translation_anim(name, node, keys):
    """Slide `node` along its meta axis: keys [(frame, metres), ...] from its rest position."""
    if node not in node_index:
        return
    axis = meta['axes'][node]
    base = g['nodes'][node_index[node]].get('translation', [0.0, 0.0, 0.0])
    t = add_accessor([f / FPS for f, _ in keys], 1)
    v = add_accessor([[base[i] + axis[i] * d for i in range(3)] for _, d in keys], 3)
    g.setdefault('animations', []).append({
        'name': name, 'samplers': [{'input': t, 'output': v, 'interpolation': 'LINEAR'}],
        'channels': [{'sampler': 0, 'target': {'node': node_index[node], 'path': 'translation'}}]})


def spin(deg_per_100):
    # 0..100 is one full turn; keys every 90 deg so slerp can't take the short way round
    return [(f, deg_per_100 * f / 100) for f in (0, 25, 50, 75, 100)]


# Hinge axes point left (lateral hinges), up (rudder) or forward (doors); positive = trailing
# edge up / trailing edge right. POH 1.4.5 travel: ailerons +-24, elevator 32 up / 22 down,
# rudder +-20, flaps 34.
rotation_anim('elevator_percent_key', [(n, [(0, -22), (50, 0), (100, 32)]) for n in ('Elevator_L', 'Elevator_R')])
rotation_anim('l_aileron_percent_key', [('Aileron_L', [(0, 24), (50, 0), (100, -24)])])
rotation_anim('r_aileron_percent_key', [('Aileron_R', [(0, -24), (50, 0), (100, 24)])])
rotation_anim('rudder_percent_key', [('Rudder', [(0, -20), (50, 0), (100, 20)])])
rotation_anim('l_flap_percent_key', [('Flap_L', [(0, 0), (100, -34)])])
rotation_anim('r_flap_percent_key', [('Flap_R', [(0, 0), (100, -34)])])
rotation_anim('prop_anim', [('Propeller', spin(360))])          # clockwise seen from the cockpit
rotation_anim('c_tire_anim', [('Tire_Nose_spin', spin(360))])
rotation_anim('l_tire_anim', [('Tire_L_spin', spin(360))])
rotation_anim('r_tire_anim', [('Tire_R_spin', spin(360))])
rotation_anim('c_wheel', [('Nose_steer', [(0, 30), (50, 0), (100, -30)])])   # 0 = full left
rotation_anim('door_l_anim', [(n, [(0, 0), (100, 80)]) for n in ('Door_L', 'Door_L_int')])    # gull-wing, 80 deg
rotation_anim('door_r_anim', [(n, [(0, 0), (100, -80)]) for n in ('Door_R', 'Door_R_int')])

# Cockpit (interior model). Stick pitch hinges point left: pulling back tips the top aft (negative).
# Roll hinges point forward: right roll tips the top right (positive). Pedals and levers hinge
# about a leftward axis, so positive tips their tops forward.
rotation_anim('stick_pitch_anim', [(n, [(0, 14), (50, 0), (100, -14)]) for n in ('Stick_L_pitch', 'Stick_R_pitch')])
rotation_anim('stick_roll_anim', [(n, [(0, -12), (50, 0), (100, 12)]) for n in ('Stick_L_roll', 'Stick_R_roll')])
rotation_anim('rudder_pedal_anim',
              [(n, [(0, 12), (50, 0), (100, -12)]) for n in ('Pedal_L_1', 'Pedal_L_2')] +
              [(n, [(0, -12), (50, 0), (100, 12)]) for n in ('Pedal_R_1', 'Pedal_R_2')])
rotation_anim('throttle_lever_anim', [('Throttle_lever', [(0, -22), (100, 22)])])
# panel switches (interior): one animation per switch in panel_layout.SWITCHES, driven by the Asobo
# switch templates as state x 100 (0 = off, lever down; 100 = on, lever up). The key turns 40 deg
# clockwise (seen by the pilot; its axis points at the pilot) to START.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_layout  # noqa: E402
for _name, *_ in panel_layout.SWITCHES:
    rotation_anim(f'sw_{_name.lower()}_anim', [(f'SW_{_name}_pivot', [(0, -22), (100, 22)])])
rotation_anim('key_anim', [('Key_pivot', [(0, 0), (100, -40)])])
rotation_anim('door_l_ext_handle_anim', [('Door_L_ext_handle', [(0, 0), (100, 25)])])   # outside lever: front pops out
rotation_anim('door_r_ext_handle_anim', [('Door_R_ext_handle', [(0, 0), (100, 25)])])
rotation_anim('door_l_latch_anim', [('Door_L_latch', [(0, 0), (100, -35)])])      # front end lifts
rotation_anim('door_r_latch_anim', [('Door_R_latch', [(0, 0), (100, -35)])])
rotation_anim('brake_lever_anim', [('Brake_lever', [(0, 16), (100, -16)])])         # off forward, pulled aft to brake
# rotary flap selector, positions 0/1/2/3 at 30 deg steps clockwise (its axis points at the pilot)
rotation_anim('flap_knob_anim', [('Flap_knob', [(0, 0), (100, -90)])])
# centre console (console_layout.BEHAVIORS). The park brake T handle turns a quarter turn (axis up out of
# the console top) from along the console (OFF) to across it (ON). The fuel selector's axis points at
# the pilot; its pointer rests on OFF (down), LEFT is 90 deg clockwise from there, RIGHT 90 anticlockwise.
rotation_anim('park_brake_anim', [('Park_brake', [(0, 0), (100, 90)])])
rotation_anim('fuel_selector_anim', [('Fuel_selector', [(0, -90), (50, 0), (100, 90)])])
rotation_anim('fuel_off_anim', [('Fuel_selector_off_pivot', [(0, 0), (100, 0)])])     # push knob: no travel
# Airmaster controller: the mode knob steps 27 deg anticlockwise per mode (axis at the pilot: + = anticlockwise),
# AUTO/MAN and feather toggles throw like the panel switches (0 = down, 100 = up)
rotation_anim('prop_mode_anim', [('Prop_ctl_knob_pivot', [(0, 0), (100, 4 * panel_layout.PROP_KNOB_STEP)])])
rotation_anim('prop_automan_anim', [('Prop_ctl_automan_pivot', [(0, -22), (100, 22)])])
rotation_anim('prop_feather_anim', [('Prop_ctl_feather_pivot', [(0, -22), (100, 22)])])
# rescue parachute handle: slides 12 cm out of the panel when pulled (interior.CHUTE_PULL)
translation_anim('brs_handle_anim', 'Chute_handle_slide', [(0, 0.0), (100, 0.12)])
rotation_anim('brs_pin_anim', [('Chute_pin_group', [(0, 0), (100, 0)])])     # click spots only: no travel
# magnetic compass card: one turn over 0..100 (heading / 3.6), anticlockwise seen from above as the aircraft turns right
rotation_anim('compass_card_anim', [('Compass_card_pivot', spin(360))])

# cabin lining: window openings come from the paint's alpha, so clip rather than blend
for m in g['materials']:
    if m['name'] == 'Lining':
        m['alphaMode'], m['alphaCutoff'] = 'MASK', 0.5
        m['doubleSided'] = False

# ---- write -----------------------------------------------------------------------------------
bin_name = os.path.splitext(os.path.basename(dst))[0] + '.bin'
g['buffers'] = [{'uri': bin_name, 'byteLength': len(data)}]
os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
with open(os.path.join(os.path.dirname(os.path.abspath(dst)), bin_name), 'wb') as f:
    f.write(data)
with open(dst, 'w') as f:
    json.dump(g, f, indent=1)
print(f'{dst}: {len(g["nodes"])} nodes, {len(g.get("animations", []))} animations, {len(data) / 1e6:.1f} MB bin')
