"""Log the live autopilot chain from the running sim over SimConnect, for debugging.

    python ap_monitor.py [SECONDS] [HZ]      (SECONDS=0: one snapshot)

Columns: attitude and heading, what the autopilot is holding (sim AP modes, bank/pitch hold refs
written by the Working Title GFC 500), the sim's own flight director, and the control outputs.
Note the sim reports PLANE BANK DEGREES positive for a left bank.
"""
import sys
import time

from SimConnect import AircraftRequests, SimConnect
from SimConnect.RequestList import Request

VARS = [
    ('bank', 'PLANE_BANK_DEGREES', 57.2958), ('pitch', 'PLANE_PITCH_DEGREES', 57.2958),
    ('hdg', 'PLANE_HEADING_DEGREES_MAGNETIC', 57.2958), ('hdg_bug', 'AUTOPILOT_HEADING_LOCK_DIR', 1),
    ('ap', 'AUTOPILOT_MASTER', 1), ('fd', 'AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE', 1),
    ('m_hdg', 'AUTOPILOT_HEADING_LOCK', 1), ('m_bank', 'AUTOPILOT_BANK_HOLD', 1),
    ('m_lvl', 'AUTOPILOT_WING_LEVELER', 1), ('m_pitch', 'AUTOPILOT_PITCH_HOLD', 1),
    ('m_att', 'AUTOPILOT_ATTITUDE_HOLD', 1), ('m_alt', 'AUTOPILOT_ALTITUDE_LOCK', 1),
    ('m_vs', 'AUTOPILOT_VERTICAL_HOLD', 1), ('m_nav', 'AUTOPILOT_NAV1_LOCK', 1),

    ('fd_bank', 'AUTOPILOT_FLIGHT_DIRECTOR_BANK', 1), ('fd_pitch', 'AUTOPILOT_FLIGHT_DIRECTOR_PITCH', 1),
    ('ail', 'AILERON_POSITION', 1), ('elev', 'ELEVATOR_POSITION', 1),
    ('ail_trim', 'AILERON_TRIM_PCT', 1), ('elev_trim', 'ELEVATOR_TRIM_POSITION', 57.2958),
    ('ias', 'AIRSPEED_INDICATED', 1), ('vs', 'VERTICAL_SPEED', 60),
    # the gyro instruments the G3X AHRS reads, and the vacuum that spins them
    ('ai_bank', 'ATTITUDE_INDICATOR_BANK_DEGREES', 57.2958), ('ai_pitch', 'ATTITUDE_INDICATOR_PITCH_DEGREES', 57.2958),
    ('hi_hdg', 'HEADING_INDICATOR', 57.2958), ('suction', 'SUCTION_PRESSURE', 1),
]


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 0
    hz = float(sys.argv[2]) if len(sys.argv) > 2 else 4
    sm = SimConnect()
    aq = AircraftRequests(sm, _time=0)
    title = aq.get('TITLE')
    print('aircraft:', title)
    # not in the library's variable list: ask for them directly, in degrees
    custom = [('bank_ref', Request((b'AUTOPILOT BANK HOLD REF', b'Degrees'), sm, _time=0)),
              ('pitch_ref', Request((b'AUTOPILOT PITCH HOLD REF', b'Degrees'), sm, _time=0))]
    print('\t'.join([n for n, _, _ in VARS] + [n for n, _ in custom]), flush=True)
    end = time.time() + seconds
    while True:
        row = []
        for name, var, scale in VARS:
            v = aq.get(var)
            row.append('-' if v is None else f'{float(v) * scale:.2f}')
        for _, req in custom:
            v = req.value
            row.append('-' if v is None else f'{float(v):.2f}')
        print('\t'.join(row), flush=True)
        if time.time() >= end:
            break
        time.sleep(1 / hz)
    sm.exit()


if __name__ == '__main__':
    main()
