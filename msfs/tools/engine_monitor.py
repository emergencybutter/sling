"""Log the engine-start chain from the running sim over SimConnect, for debugging.

    python engine_monitor.py [SECONDS] [HZ]      (SECONDS=0: one snapshot)

Columns: starter, RPM, combustion, both magnetos (the ECU lanes), selector, fuel pump switch and
pressure, fuel flow, throttle and mixture, and the electrical bus.
"""
import sys
import time

from SimConnect import SimConnect
from SimConnect.RequestList import Request

VARS = [
    ('starter', 'GENERAL ENG STARTER:1', 'Bool'),
    ('starter_on', 'GENERAL ENG STARTER ACTIVE:1', 'Bool'),
    ('rpm', 'GENERAL ENG RPM:1', 'Rpm'),
    ('comb', 'GENERAL ENG COMBUSTION:1', 'Bool'),
    ('magL', 'RECIP ENG LEFT MAGNETO:1', 'Bool'),
    ('magR', 'RECIP ENG RIGHT MAGNETO:1', 'Bool'),
    ('fsel', 'FUEL TANK SELECTOR:1', 'Enum'),
    ('pump_sw', 'GENERAL ENG FUEL PUMP SWITCH:1', 'Bool'),
    ('pump_on', 'GENERAL ENG FUEL PUMP ON:1', 'Bool'),
    ('fuel_psi', 'GENERAL ENG FUEL PRESSURE:1', 'Psi'),
    ('ff_gph', 'ENG FUEL FLOW GPH:1', 'Gallons per hour'),
    ('fuel_L', 'FUEL TANK LEFT MAIN QUANTITY', 'Gallons'),
    ('fuel_R', 'FUEL TANK RIGHT MAIN QUANTITY', 'Gallons'),
    ('thr', 'GENERAL ENG THROTTLE LEVER POSITION:1', 'Percent'),
    ('mix', 'GENERAL ENG MIXTURE LEVER POSITION:1', 'Percent'),
    ('bus_v', 'ELECTRICAL MAIN BUS VOLTAGE', 'Volts'),
    ('batt', 'ELECTRICAL MASTER BATTERY', 'Bool'),
    ('starter_circ', 'CIRCUIT ON:5', 'Bool'),
    ('pump_circ', 'CIRCUIT ON:2', 'Bool'),
]


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 0
    hz = float(sys.argv[2]) if len(sys.argv) > 2 else 4
    sm = SimConnect()
    reqs = [(n, Request((v.encode(), u.encode()), sm, _time=0)) for n, v, u in VARS]
    print('\t'.join(n for n, _ in reqs), flush=True)
    end = time.time() + seconds
    while True:
        row = []
        for _, r in reqs:
            v = r.value
            row.append('-' if v is None else f'{float(v):.1f}')
        print('\t'.join(row), flush=True)
        if time.time() >= end:
            break
        time.sleep(1 / hz)
    sm.exit()


if __name__ == '__main__':
    main()
