"""Derive flight_model.cfg, engines.cfg and cameras.cfg for the Sling TSi, and document every number.

The SDK SimpleAircraft sample supplies the file layout and the generic tables; this script overrides
every value that describes the aircraft. Each such value carries its source:

    POH      read from the Pilot Operating Handbook DC-POH-001-X-F-3.5 (section given)
    DERIVED  calculated from POH figures (the working is in the note)
    MODEL    measured on the 3D model (../model, built from the POH 3-view)
    GUESS    no source; a typical value for the class
    TUNE     a starting value to adjust against the POH in the sim

The tag and note go into the .cfg as a comment, and docs/FLIGHT_MODEL.md lists them all.

Positions are in feet from the cfg reference datum (Blender point (1.06, 0, 0.9) m: root quarter
chord), ordered longitudinal (+ forward), lateral (+ right), vertical (+ up), as the .cfg files expect.

    python make_configs.py SAMPLE_CONFIG_DIR OUT_CONFIG_DIR
"""
import os
import re
import sys

src, dst = sys.argv[1:3]
FT = 3.28084
DATUM = (1.06, 0.0, 0.9)
DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'FLIGHT_MODEL.md')

# POH weight-and-balance datum (POH 2.9: 52 mm aft of the propeller flange face). The flange sits at the
# spinner base, 290 mm aft of the spinner tip, so the POH datum is 345 mm aft of the tip. Check: the POH
# arms put the main wheels at 2214 mm (model 2207) and the MAC leading edge at 1602 mm (model ~1605).
POH_DATUM_AFT_OF_TIP = 345.0
CFG_DATUM_AFT_OF_TIP = (3.300 - DATUM[0]) * 1000         # 2240 mm


def poh_arm(mm):
    """POH arm (mm aft of the POH datum) -> cfg longitudinal feet (+ forward of the cfg datum)."""
    return (CFG_DATUM_AFT_OF_TIP - (POH_DATUM_AFT_OF_TIP + mm)) / 304.8


def pos(x, y, z):
    """Blender metres (nose +X, left +Y, up +Z) -> cfg feet (lon, lat right+, vert)."""
    return f'{(x - DATUM[0]) * FT:.2f}, {-y * FT:.2f}, {(z - DATUM[2]) * FT:.2f}'


def arm_pos(arm_mm, y, z):
    """POH arm (mm) + Blender lateral/vertical metres -> cfg feet."""
    return f'{poh_arm(arm_mm):.2f}, {-y * FT:.2f}, {(z - DATUM[2]) * FT:.2f}'


SOURCES = []           # (file, section, key, value, tag, note)
FILE = ''


def S(value, tag, note=''):
    return (value, tag, note)


def edit(text, section, values, drop=()):
    """Replace or add key = value lines inside [section]; drop keys matching a prefix.
    A value given as S(value, tag, note) is written with its source as the comment and recorded."""
    lines = text.split('\n')
    start = next(i for i, l in enumerate(lines) if l.strip().lower() == f'[{section.lower()}]')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('[')), len(lines))
    body = lines[start + 1:end]
    body = [l for l in body if not any(l.strip().startswith(d) for d in drop)]

    def render(k, v, old_comment=''):
        if isinstance(v, tuple):
            value, tag, note = v
            SOURCES.append((FILE, section, k, value, tag, note))
            return f'{k} = {value} ; [{tag}] {note}'.rstrip()
        return f'{k} = {v}' + (f' {old_comment}' if old_comment else '')

    done = set()
    for i, l in enumerate(body):
        m = re.match(r'\s*([\w.\- ]+?)\s*=', l)
        if m and m.group(1) in values:
            k = m.group(1)
            comment = l[l.index(';'):] if ';' in l else ''
            body[i] = render(k, values[k], comment)
            done.add(k)
    while body and not body[-1].strip():
        body.pop()
    body += [render(k, v) for k, v in values.items() if k not in done] + ['']
    return '\n'.join(lines[:start + 1] + body + lines[end:])


def read(name):
    return open(f'{src}/{name}', encoding='utf-8', errors='replace').read()


def write(name, text):
    with open(f'{dst}/{name}', 'w', encoding='utf-8') as f:
        f.write(text)


# ================================ flight_model.cfg ================================
FILE = 'flight_model.cfg'
fm = read('flight_model.cfg')
MTOW_LB, EMPTY_LB = 2094, 1102
fm = edit(fm, 'WEIGHT_AND_BALANCE', {
    'max_gross_weight': S(MTOW_LB, 'POH 1.4.12', '950 kg'),
    'empty_weight': S(EMPTY_LB, 'POH 1.4.13', '500 kg standard empty weight, 915 iS + Airmaster'),
    'reference_datum_position': '0, 0, 0',
    'empty_weight_CG_position': S(f'{poh_arm(1873):.3f}, 0, 0.16', 'POH 6.7 / GUESS',
                                  'arm 1873 mm (POH example empty CG); height guessed 5 cm above the datum'),
    'CG_forward_limit': S(0.18, 'POH 2.9', '1847 mm = 18% MAC'),
    'CG_aft_limit': S(0.33, 'POH 2.9', '2043 mm = 33% MAC'),
    # Roskam's typical radii of gyration for single-engine props (Rx 0.248 b, Ry 0.338 L, Rz 0.462 (b+L)/2)
    # at the 500 kg empty mass (34.2 slug), b = 31.2 ft, L = 23.6 ft.
    'empty_weight_pitch_MOI': S(544, 'DERIVED', 'Roskam Ry 0.338 L at empty mass (slug ft2)'),
    'empty_weight_roll_MOI': S(513, 'DERIVED', 'Roskam Rx 0.248 b at empty mass (slug ft2)'),
    'empty_weight_yaw_MOI': S(1371, 'DERIVED', 'Roskam Rz 0.462 (b+L)/2 at empty mass (slug ft2)'),
    'max_number_of_stations': 6,
    'station_load.0': S(f'170, {arm_pos(1902, 0.31, 1.0)}, Pilot', 'POH 6.3 / GUESS',
                        'front seat arm 1902 mm; 170 lb pilot and seat height guessed'),
    'station_load.1': S(f'0, {arm_pos(1902, -0.31, 1.0)}, Front passenger', 'POH 6.3', 'front seat arm 1902 mm'),
    'station_load.2': S(f'0, {arm_pos(2948, 0.25, 1.02)}, Rear passenger left', 'POH 6.3', 'rear seat arm 2948 mm'),
    'station_load.3': S(f'0, {arm_pos(2948, -0.25, 1.02)}, Rear passenger right', 'POH 6.3', 'rear seat arm 2948 mm'),
    'station_load.4': S(f'0, {arm_pos(3288, 0.0, 0.95)}, Baggage', 'POH 6.3', 'arm 3288 mm, max 35 kg (POH 2.8)'),
    'station_load.5': S(f'0, {arm_pos(3762, 0.0, 1.0)}, Baggage extension', 'POH 6.3', 'arm 3762 mm, max 3 kg (POH 2.8)'),
}, drop=('station_load',))

gear_z = 0.0
fm = edit(fm, 'CONTACT_POINTS', {
    'static_pitch': 0,
    'static_cg_height': S(f'{(0.95 - gear_z) * FT:.2f}', 'GUESS', 'CG about 0.95 m above the ground on the gear'),
    'gear_system_type': 4,                   # fixed gear
    'tailwheel_lock': 0,
    'max_number_of_points': 11,
    # class, lon, lat, vert, damage threshold, brake map, wheel radius (ft), steer angle,
    # static compression, max/static ratio, damping, ext/retract time, retract time,
    # sound type, airspeed limit, damage airspeed
    'point.0': S(f'Name:Nose#Properties:1, {pos(2.52, 0, gear_z)}, 1000, 0, {0.178 * FT:.2f}, 30, 0.12, 1.8, 0.75, 0, 0, 0, 0, 0',
                 'MODEL', 'nose axle 435 mm aft of the POH datum (POH 6.3: 464); 5.00-5 tyre (POH 1.4.4); steering 30 deg GUESS'),
    'point.1': S(f'Name:MainLeft#Properties:1, {pos(0.748, 0.975, gear_z)}, 1400, 1, {0.19 * FT:.2f}, 0, 0.12, 2.0, 0.75, 0, 0, 2, 0, 0',
                 'MODEL', 'axle arm 2207 mm (POH 6.3: 2214); track 1.95 m on the model vs 2.05 m (POH 1.4.4); 15x6.00-6'),
    'point.2': S(f'Name:MainRight#Properties:1, {pos(0.748, -0.975, gear_z)}, 1400, 2, {0.19 * FT:.2f}, 0, 0.12, 2.0, 0.75, 0, 0, 3, 0, 0',
                 'MODEL', 'as MainLeft'),
    'point.3': f'Name:WingtipLeft#Properties:2, {pos(0.7, 4.77, 1.13)}, 350, 0, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0',
    'point.4': f'Name:WingtipRight#Properties:2, {pos(0.7, -4.77, 1.13)}, 350, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0',
    'point.5': f'Name:Tailcone#Properties:2, {pos(-3.2, 0, 0.97)}, 500, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0',
    'point.6': f'Name:Spinner#Properties:2, {pos(3.3, 0, 1.17)}, 350, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0',
    'point.7': f'Name:Belly#Properties:2, {pos(0.8, 0, 0.65)}, 500, 0, 0, 0, 0, 0, 0, 0, 0, 8, 0, 0',
    'point.8': f'Name:FinTop#Properties:2, {pos(-3.87, 0, 2.41)}, 350, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0',
    'point.9': f'Name:AftBelly#Properties:2, {pos(-1.6, 0, 0.84)}, 500, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0',
    'point.10': f'Name:PropTip#Properties:2, {pos(3.06, 0, 0.255)}, 200, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0',
}, drop=('point.',))

fm = edit(fm, 'FUEL', {
    # Two main wing tanks. The POH lists 2 x 88 L and 2 x 99 L options; this is the 88 L (176 L) version.
    'LeftMain': S(f'{arm_pos(1800, 1.5, 0.72)}, 23.2, 0.5', 'POH 1.4.8 / 6.3 / GUESS',
                  '88 L (23.2 gal), 86 L usable; arm 1800 mm; 1.5 m outboard guessed, wing height MODEL'),
    'RightMain': S(f'{arm_pos(1800, -1.5, 0.72)}, 23.2, 0.5', 'POH 1.4.8 / 6.3 / GUESS', 'as LeftMain'),
    'fuel_type': S(4, 'POH 1.4.8', 'MOGAS EN 228 or AVGAS 100LL; auto gas selected'),
    'number_of_tank_selectors': 1,
    'electric_pump': S(1, 'POH 7.4', 'electric main and aux pumps only'),
    'engine_driven_pump': S(0, 'POH 7.4', 'no engine-driven pump on the 915 iS'),
    'default_fuel_tank_selector': S(2, 'POH 7.2.5', 'LEFT; the selector has LEFT / RIGHT / OFF'),
})

fm = edit(fm, 'AIRPLANE_GEOMETRY', {
    'wing_area': S(127.55, 'POH 1.4.1', '11.85 m2'),
    'wing_span': S(31.17, 'POH 1.4.1', '9.50 m'),
    'wing_root_chord': S(4.99, 'POH 1.3', '1520 mm, 3-view plan dimension'),
    'wing_camber': S(2, 'GUESS', 'airfoil not published; the model uses NACA 2413'),
    'wing_thickness_ratio': S(0.13, 'GUESS', 'airfoil not published; the model uses NACA 2413'),
    'wing_dihedral': S(4.5, 'POH 1.4.1'),
    'wing_incidence': S(1.5, 'GUESS', 'root incidence, not published'),
    'wing_twist': S(-1.5, 'POH 1.4.1', 'tip washout 1.5 deg'),
    'oswald_efficiency_factor': S(0.75, 'GUESS / DERIVED',
                                  'with CD0 0.026 gives L/D 12.6 at 72 KIAS vs POH 3.2 glide ratio 12:1'),
    'wing_sweep': S(0.4, 'MODEL', 'quarter-chord line, 1.5 deg leading-edge sweep on the taper'),
    'wing_pos_apex_lon': S(f'{(1.392 - DATUM[0]) * FT:.2f}', 'MODEL', 'root leading edge'),
    'wing_pos_apex_vert': S(f'{(0.75 - DATUM[2]) * FT:.2f}', 'MODEL'),
    'htail_area': S(24.80, 'DERIVED', 'POH 1.4.3: stabiliser 1.14 + elevator 1.164 m2'),
    'htail_span': S(10.15, 'POH 1.4.3', '3.095 m'),
    'htail_pos_lon': S(f'{(-2.79 - DATUM[0]) * FT:.2f}', 'MODEL', 'quarter chord'),
    'htail_pos_vert': S(f'{(1.15 - DATUM[2]) * FT:.2f}', 'MODEL'),
    'htail_incidence': S(-0.1, 'POH 1.4.3'),
    'htail_sweep': S(5, 'MODEL'),
    'htail_thickness_ratio': S(0.1, 'MODEL', 'NACA 0010 on the model'),
    'vtail_area': S(12.19, 'DERIVED', 'POH 1.4.3: fin 0.532 + rudder 0.600 m2'),
    'vtail_span': S(4.82, 'POH 1.4.3', '1.470 m'),
    'vtail_sweep': S(35, 'MODEL'),
    'vtail_pos_lon': S(f'{(-3.3 - DATUM[0]) * FT:.2f}', 'MODEL'),
    'vtail_pos_vert': S(f'{(1.7 - DATUM[2]) * FT:.2f}', 'MODEL'),
    'fuselage_length': S(20.41, 'POH 1.4.2', '6.220 m fuselage (7.2 m overall)'),
    'fuselage_diameter': S(3.90, 'POH 1.4.2', '1.188 m width'),
    'fuselage_center_pos': S(f'{(-0.1 - DATUM[0]) * FT:.2f}, 0, {(1.23 - DATUM[2]) * FT:.2f}', 'MODEL'),
    'elevator_area': S(12.53, 'POH 1.4.3', '1.164 m2'),
    'aileron_area': S(8.3, 'MODEL', 'both ailerons, 3.29 m to 4.5 m, hinge at X 2904-2920 mm'),
    'rudder_area': S(6.46, 'POH 1.4.3', '0.600 m2'),
    'elevator_up_limit': S(32, 'POH 1.4.5'),
    'elevator_down_limit': S(22, 'POH 1.4.5'),
    'aileron_up_limit': S(24, 'POH 1.4.5'),
    'aileron_down_limit': S(24, 'POH 1.4.5'),
    'rudder_limit': S(20, 'POH 1.4.5'),
    'elevator_trim_limit': S(15, 'GUESS', 'trim tab 5 up / 25 down (POH 1.4.5) has no direct cfg equivalent'),
    'positive_g_limit_flaps_up': S(3.8, 'POH 2.7'),
    'positive_g_limit_flaps_down': S(2.5, 'POH 2.7'),
    'negative_g_limit_flaps_up': S(-1.9, 'POH 2.7'),
    'negative_g_limit_flaps_down': S(-1.0, 'POH 2.7'),
    # Modern flight model geometry, as the default NX Cub sets it. The ailerons run from 3.29 m to the
    # tip of the 4.77 m semi-span (model/index.html), so they start at 0.69; without this key the
    # sim's autopilot roll servo drove the ailerons the wrong way (logged 2026-09-29).
    'aileron_span_outboard': S(0.69, 'MODEL', 'aileron inboard end / semi-span'),
    'aileron_to_elevator_gain': 0,
    'rudder_trim_limit': 0,
    'air_spoiler_limit': 0,
    'spoiler_disabled_by_flaps': 0,
    'auto_spoiler_auto_retracts': 1,
    'auto_spoiler_min_speed': 0,
    'load_g_limiter_g': S(5.7, 'DERIVED', '3.8 g limit (POH 2.7) x 1.5 ultimate'),
    'fly_by_wire_from_flaps': 0,
    'controls_reactivity_scalar': 1,
})

# Stall: at 950 kg (9320 N), 11.85 m2 and sea level, Vs 55 KIAS (= CAS, POH 5.6) needs CL 1.60 and Vs0
# 48 KIAS CL 2.10, so full flap adds 0.50. The table's zero-alpha lift and slope are the generic ones.
fm = edit(fm, 'AERODYNAMICS', {
    'lift_coef_flaps': S(0.50, 'DERIVED', 'CL 2.10 at Vs0 48 KIAS minus 1.60 at Vs 55 KIAS (POH 2.2)'),
    # Drag from the POH cruise: 75% (90 kW, POH 2.14.3) gives 130 KTAS at MSL (POH 5.4). With a guessed
    # 0.80 prop efficiency that is CD 0.033, CD0 0.029; 95% power at 145 KTAS gives CD0 0.024. Total 0.026,
    # split between the airframe and the fixed gear. Checks: Vy climb ~880 fpm (POH 5.3: 800).
    'drag_coef_zero_lift': S(0.020, 'DERIVED', 'total CD0 0.026 from POH 5.4 cruise (prop efficiency 0.80 GUESS)'),
    'drag_coef_gear': S(0.006, 'GUESS', 'faired fixed gear share of the 0.026 total'),
    'drag_coef_flaps': S(0.09, 'GUESS', 'full flap'),
    'lift_coef_aoa_table': S('-3.142:0, -2.356:0.5, -1.571:0, -0.334:-1.078, -0.072:0, 0:0.36, 0.227:1.55, '
                             '0.262:1.60, 0.297:1.53, 0.332:1.1, 1.571:0, 2.356:-0.5, 3.142:0',
                             'DERIVED / TUNE', 'CLmax 1.60 from Vs 55 KIAS at MTOW (POH 2.2); check the stall in the sim'),
    # modern flight model inputs, NX Cub values
    'lift_coef_at_drag_zero': 0.05,
    'lift_coef_at_drag_zero_flaps': 0.05,
    'lift_coef_air_spoilers': 0,
    'drag_coef_air_spoilers': 0,
    'elevator_lift_coef': 5,
    'rudder_lift_coef': 5,
    'fuselage_lateral_cx': 0.4,
    'CFD_EnableSimulation': 1,
    'CFD_ReinjectBody': 1,
    'CFD_ReinjectRotors': 0,
})

fm = edit(fm, 'FLIGHT_TUNING', {
    # modern flight model only, as the default NX Cub; the remaining values are its defaults
    'modern_fm_only': 1,
    'elevator_maxangle_scalar': 0.8,
    'rudder_maxangle_scalar': 1,
    'pitch_gyro_stability': 0,
    'roll_gyro_stability': 0,
    'yaw_gyro_stability': 0,
    'rudder_engine_wash_on_roll': 0.33,
    'stall_coef_at_min_weight': 0.5,
    'empty_CG_deviation_limit': 10000,
    'icing_scalar': 1,
    'wingflex_scalar': 1,
    'wingflex_offset': 0,
    'predicted_moi_density_scalar_fuselage': 1,
    'predicted_moi_density_scalar_wings': 1,
    'elevator_chordangle_scalar': -1,
    'htail_maxangle_scalar': -1,
    'rudder_chordangle_scalar': -1,
    'vtail_maxangle_scalar': -1,
    'gyro_precession_on_pitch': 1,
    'enable_high_accuracy_integration': 1,
})

fm = edit(fm, 'REFERENCE SPEEDS', {
    'full_flaps_stall_speed': S(48, 'POH 2.2', 'Vs0'),
    'flaps_up_stall_speed': S(55, 'POH 2.2', 'Vs'),
    'cruise_speed': S(130, 'POH 5.4', '75% power, 5000 rpm, sea level'),
    'max_mach': 0.3,
    'max_indicated_speed': S(155, 'POH 2.2', 'Vne'),
    'max_flaps_extended': S(85, 'POH 2.2', 'Vfe'),
    'normal_operating_speed': S(135, 'POH 2.2', 'Vno'),
    'airspeed_indicator_max': S(180, 'GUESS', 'top of the G3X tape scale'),
    'rotation_speed_min': S(55, 'POH 4.5', 'rotate 55 KIAS'),
    'climb_speed': S(75, 'POH 5.3', 'Vy'),
    'cruise_alt': S(8500, 'GUESS'),
    'takeoff_speed': S(60, 'GUESS', 'between rotate (55) and Vx (65)'),
})

fm = edit(fm, 'FLAPS.0', {
    'system_type': 0,
    'span-outboard': S(0.68, 'MODEL', 'flaps end at 3.25 m of the 4.77 m semi-span'),
    'extending-time': S(8, 'GUESS', 'electric flap, stage to stage'),
    'damaging-speed': S(95, 'GUESS', 'Vfe 85 + 10'),
    'blowout-speed': S(130, 'GUESS'),
    'max_on_ground_position': 3,
    'flaps-position.0': S('0, -1', 'POH 7.2.10', 'UP'),
    'flaps-position.1': S('10, 85', 'POH 7.2.10 / 2.2', 'stage 1, Vfe 85'),
    'flaps-position.2': S('20, 85', 'POH 7.2.10 / 2.2', 'stage 2, Vfe 85'),
    'flaps-position.3': S('34, 85', 'POH 7.2.10 / 2.2', 'full, Vfe 85'),
})
# Gull-wing doors (POH 7.7). MSFS 2024 doors are interactive points: the door handles set
# INTERACTIVE POINT GOAL and the sim moves INTERACTIVE POINT OPEN at the first property's rate
# (fraction per second, 0.35: about 3 s to open), which drives the door animations.
fm = fm.rstrip() + '''

[INTERACTIVE POINTS]
interactive_point.0 = Name:Door_Left#Properties:0.35,0,0,0,0,0,0,0,0,0,0,0,0,0,0
interactive_point.1 = Name:Door_Right#Properties:0.35,0,0,0,0,0,0,0,0,0,0,0,0,0,0
'''
# Ballistic rescue parachute (POH 9.5.2, BRS SLTSCM-08): MSFS 2024's built-in parachute, as the default SF50 uses
# for CAPS. The sim deploys it when PARACHUTE OPEN is set to 1 (SlingTSi.xml BRS_Deploy does that once the handle
# is pulled). Position order is lateral, vertical, longitudinal (ft from the datum), as in the SF50's
# "0, 4, -13.43". Attached on the roof just above the CG so the aircraft hangs level.
BRS_POS = f'0, {(1.60 - DATUM[2]) * FT:.2f}, {poh_arm(1931):.2f}'
BRS_SIZE = 55
SOURCES.append((FILE, 'OBJ_EA1_PARACHUTE', 'position', BRS_POS, 'MODEL / GUESS',
                'roof (H 1.60 m) over the CG at the POH example arm 1931 mm; axis order from the SF50'))
SOURCES.append((FILE, 'OBJ_EA1_PARACHUTE', 'size', BRS_SIZE, 'DERIVED / TUNE',
                'SF50 uses 100 at ~2700 kg; x sqrt(950/2700) = 59, a bit smaller for the POH 9.4 m/s descent'))
fm = fm.rstrip() + f'''

[OBJ_EA1_PARACHUTE]
position = {BRS_POS} ; [MODEL / GUESS] lateral, vertical, longitudinal (ft): roof above the CG
size = {BRS_SIZE} ; [DERIVED / TUNE] canopy radius (ft); POH 9.5.2: 9.4 m/s descent at 950 kg
'''
write('flight_model.cfg', fm)

# ================================== engines.cfg ==================================
FILE = 'engines.cfg'
en = read('engines.cfg')
en = edit(en, 'GENERALENGINEDATA', {
    'fuel_flow_scalar': S(1, 'TUNE', 'target 43 L/h at 100%, 27 L/h at 75% (POH 5.5)'),
    'master_ignition_switch': 0,
    'starter_type': 0,
    'Engine.0': S(pos(2.5, 0, 1.1), 'MODEL', 'engine bay'),
})
en = edit(en, 'PISTON_ENGINE', {
    # Rotax 915 iS: 1352 cc flat four, turbocharged, electronic fuel injection with automatic mixture.
    'cylinder_displacement': S(20.6, 'POH 1.4.6', '1352 cc / 4 cylinders, cubic inches each'),
    'compression_ratio': S(9.0, 'GUESS', 'Rotax figure, not in the POH'),
    'number_of_cylinders': S(4, 'POH 1.4.6'),
    'max_rated_rpm': S(5800, 'POH 2.14.3', 'max take-off, 5 minutes'),
    'max_rated_hp': S(141, 'POH 2.14.3', '105 kW at 5800 rpm'),
    'min_cruise_rpm': S(5000, 'POH 2.14.3', 'cruise 5000-5400 rpm'),
    'max_cruise_rpm': S(5500, 'POH 2.14.3', 'max continuous'),
    'max_indicated_rpm': S(5800, 'POH 2.14.3'),
    'fuel_metering_type': 0,
    'cooling_type': S(1, 'POH 1.4.10', 'mixed air / liquid'),
    'turbocharged': S(1, 'POH 1.4.6'),
    'max_design_mp': S(51, 'POH 2.14.3', 'max manifold pressure 51 inHg'),
    'min_design_mp': S(10, 'TUNE', 'idle manifold pressure: sets idle rpm (POH idle >= 1400 rpm)'),
    'critical_altitude': S(15000, 'GUESS', 'Rotax rating altitude; POH 5.3 shows climb nearly flat to 18,000 ft'),
    'fuel_air_auto_mixture': S(1, 'POH 1.4.6', 'FADEC'),
    'BestPowerSpecificFuelConsumption': S(0.50, 'DERIVED', '43 L/h at 104 kW (POH 5.5) = 0.31 kg/kWh'),
    'egt_peak_temperature': S(2110, 'GUESS', '1650 F; POH max EGT 950 C'),
    'engine_mechanical_efficiency_table': S('0:0.77, 1600:0.77, 4300:0.67, 4800:0.6, 5800:0.58', 'TUNE'),
    'engine_friction_table': S('-300:-6, 300:6, 1000:6, 5800:8', 'TUNE', 'with min_design_mp, sets the idle'),
    'fuel_press_max': S(6192, 'POH 2.14.3', '43 psi in psf; limits 2.8-3.2 bar (40.6-46.4 psi)'),
    # The 915 iS has only electric fuel pumps (POH 7.4), so pressure doesn't depend on engine rpm.
    'rpm_to_fuel_pressure_table': S('0:1, 5800:1', 'POH 7.4', 'electric pumps: full pressure at any rpm'),
}, drop=('radiator_temp_',))   # not piston_engine keys in MSFS 2024
en = edit(en, 'PROPELLER', {
    'thrust_scalar': S(1, 'TUNE', 'check 130 KTAS at 75% (POH 5.4) and 800 fpm at Vy (POH 5.3)'),
    'propeller_type': S(0, 'POH 1.4.7', 'Airmaster constant speed'),
    'propeller_diameter': S(6.0, 'POH 1.4.7', 'AP430CTF-WWR72B, 72 in (the performance basis, POH 5.1)'),
    'propeller_blades': S(3, 'POH 1.4.7'),
    'propeller_moi': S(1.6, 'GUESS'),
    'beta_max': S(34, 'GUESS'),
    'beta_min': S(11, 'GUESS'),
    'min_gov_rpm': S(1650, 'GUESS', 'propeller rpm'),
    'gear_reduction_ratio': S(2.54, 'POH 1.4.6'),
    'fixed_pitch_beta': 20,
})
write('engines.cfg', en)

# ================================== cameras.cfg ==================================
cam = read('cameras.cfg')
cam = edit(cam, 'VIEWS', {'eyepoint': f'{pos(0.53, 0.31, 1.58)}'})
blocks = re.split(r'(?=^\[CAMERADEFINITION\.\d+\])', cam, flags=re.M)
out = [blocks[0]]
for b in blocks[1:]:
    title = re.search(r'^Title = "([^"]*)"', b, re.M).group(1)
    origin = re.search(r'^Origin = "([^"]*)"', b, re.M).group(1)
    if origin == 'Virtual Cockpit':
        # Cockpit views sit on the eyepoint; PFD looks at the GDU 460, MFD at the G5/radio stack.
        xyz = {'Pilot': '0, 0, 0', 'Close_Pilot': '0, 0, 0.1', 'Copilot': '-0.49, 0, 0'}.get(title, '0, 0, 0')
        if 'PFD' in title or 'Instrument' in title:
            xyz = '0.04, -0.12, 0.42'
        if 'MFD' in title:
            xyz = '0.31, -0.12, 0.42'
        b = re.sub(r'^InitialXyz = [^;]*', f'InitialXyz = {xyz} ', b, flags=re.M)
    else:
        # external views were placed around a larger airframe; pull them in to fit a 9.5 m span
        def shrink(m):
            v = [float(c) * 0.72 for c in m.group(1).split(',')]
            return 'InitialXyz = ' + ', '.join(f'{c:.3f}' for c in v) + ' '
        b = re.sub(r'^InitialXyz = ([^;]*)', shrink, b, flags=re.M)
    out.append(b)
write('cameras.cfg', ''.join(out))

# ================================== docs/FLIGHT_MODEL.md ==================================
TARGETS = [
    ('Stall, clean, MTOW, idle', '55 KIAS', 'POH 2.2'),
    ('Stall, full flap (34 deg), MTOW', '48 KIAS', 'POH 2.2'),
    ('Rotate', '55 KIAS', 'POH 4.5'),
    ('Take-off run / over 50 ft, MSL', '220 m / 350 m', 'POH 5.2.1'),
    ('Best angle / best rate', 'Vx 65 / Vy 75 KIAS', 'POH 4.5'),
    ('Climb at Vy, 5500 rpm, MSL / 10,000 ft', '800 / 730 fpm', 'POH 5.3'),
    ('Cruise 75%, 5000 rpm, MSL / 8000 ft', '130 / 141 KTAS', 'POH 5.4'),
    ('Cruise 95%, 5500 rpm, MSL', '145 KTAS', 'POH 5.4'),
    ('Max level speed', 'VH 140 KIAS', 'POH 2.2'),
    ('Fuel burn 100% / 95% / 75%', '43 / 39 / 27 L/h', 'POH 5.5'),
    ('Best glide', '72 KIAS, 12:1', 'POH 3.2'),
    ('Landing roll with braking, MSL', '150 m', 'POH 5.2.2'),
    ('Idle', '>= 1400 rpm (engine)', 'POH 2.14.3'),
    ('Fuel pressure', '2.8-3.2 bar (40.6-46.4 psi)', 'POH 2.14.3'),
]
doc = ['# Sling TSi flight model: where every number comes from', '',
       'Generated by `tools/make_configs.py` from the POH (DC-POH-001-X-F-3.5). Tags:', '',
       '- **POH**: read from the handbook (section given)',
       '- **DERIVED**: calculated from POH figures (working in the note)',
       '- **MODEL**: measured on the 3D model (built from the POH 3-view)',
       '- **GUESS**: no source, a typical value for the class',
       '- **TUNE**: a starting value to adjust in the sim against the targets below', '',
       'POH arms (mm aft of the POH datum, 52 mm aft of the propeller flange) are converted with the POH datum',
       f'{POH_DATUM_AFT_OF_TIP:.0f} mm aft of the spinner tip [DERIVED: flange at the spinner base, 290 mm, + 52 mm];',
       'checked against the model: main axles 2207 mm (POH 2214), MAC leading edge ~1605 mm (POH 1602).', '']
counts = {}
for *_, tag, _n in SOURCES:
    for t in tag.replace('/', ' ').split():
        if t.isupper():
            counts[t] = counts.get(t, 0) + 1
doc += ['Values by source: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())), '']
for f in dict.fromkeys(s[0] for s in SOURCES):
    doc += [f'## {f}', '', '| Section | Key | Value | Source | Note |', '|---|---|---|---|---|']
    for ff, sec, k, v, tag, note in SOURCES:
        if ff == f:
            doc.append(f'| {sec} | `{k}` | `{v}` | {tag} | {note} |')
    doc.append('')
doc += ['## Targets to check in the sim (all at 950 kg MTOW unless stated)', '',
        '| Test | POH value | Source |', '|---|---|---|']
doc += [f'| {a} | {b} | {c} |' for a, b, c in TARGETS]
doc += ['', 'Guesses most likely to matter: prop efficiency (0.80, inside the CD0 derivation), Oswald factor, '
        'wing incidence, the idle settings, and moments of inertia (Roskam class averages).', '']
os.makedirs(os.path.dirname(DOC), exist_ok=True)
with open(DOC, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(doc))
print('configs written to', dst, '| flight model sources in', os.path.normpath(DOC))
