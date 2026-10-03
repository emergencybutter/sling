"""Write panel/panel.xml (Working Title G3X Touch configuration) for the Sling TSi.

    python make_panel_xml.py NXCUB_PANEL_XML OUT_PANEL_XML

Starts from the default CubCrafters NX Cub's panel.xml (same G3X Touch attachment) and swaps
its Lycoming O-360 markings for the Rotax 915 iS limits in config/cockpit.cfg, the 12 V system,
one nav radio, the Sling's 19.8 gal tanks and its 0/10/20/34 deg flaps. Every substitution
is checked, so a changed template fails loudly instead of producing a half-edited file.
"""
import re
import sys
import xml.dom.minidom

src, dst = sys.argv[1:3]
s = open(src, encoding='utf-8').read().replace('\r\n', '\n')


def rep(old, new, every=False):
    global s
    assert old in s, f'template changed, not found: {old[:80]!r}'
    s = s.replace(old, new) if every else s.replace(old, new, 1)


def section(start, end='</Definition>'):
    a = s.index(start)
    return a, s.index(end, a)


def set_zones(start, zones, lines=(), tag='ColorZone', indent='\t\t\t\t', end='</Definition>'):
    """Replace the colour zones and lines of one gauge definition."""
    global s
    a, b = section(start, end)
    part = re.sub(rf'\s*<{tag}>.*?</{tag}>', '', s[a:b], flags=re.S)
    if tag == 'ColorZone':
        part = re.sub(r'\s*<ColorLine>.*?</ColorLine>', '', part, flags=re.S)
    i = '\n' + indent
    z = ''.join(f'{i}<{tag}>{i}\t<Color>{c}</Color>{i}\t<Begin>{lo}</Begin>{i}\t<End>{hi}</End>{i}</{tag}>' for c, lo, hi in zones)
    z += ''.join(f'{i}<ColorLine>{i}\t<Color>{c}</Color>{i}\t<Position>{p}</Position>{i}</ColorLine>' for c, p in lines)
    anchor = part.rfind('\n' + indent + '<Value>') if '<Value>' in part else len(part.rstrip())
    part = part[:anchor] + z + part[anchor:]
    s = s[:a] + part + s[b:]


def set_range(title, lo, hi):
    rep(f'<Title>{title}</Title>', f'<Title>{title}</Title>')
    a = s.index(f'<Title>{title}</Title>')
    seg = s[a:a + 200]
    new = re.sub(r'<Minimum>[^<]*</Minimum>', f'<Minimum>{lo}</Minimum>', seg, count=1)
    new = re.sub(r'<Maximum>[^<]*</Maximum>', f'<Maximum>{hi}</Maximum>', new, count=1)
    globals()['s'] = s[:a] + new + s[a + 200:]


# The EFIS is powered through the G3X circuit (systems.cfg circuit.13), not the avionics bus.
s = s.replace('<Simvar name="CIRCUIT AVIONICS ON" unit="Boolean"/>', '<Simvar name="CIRCUIT ON:13" unit="Boolean"/>')
s = s.replace('<Simvar name="CIRCUIT AVIONICS ON" unit="Bool"/>', '<Simvar name="CIRCUIT ON:13" unit="Boolean"/>')
rep('<Radios com-count="2" nav-count="2" marker-beacon="true">', '<Radios com-count="2" nav-count="1" marker-beacon="false">')
rep('The sim version simulates the Lycoming O-360 engine option.',
    'Sling TSi: Rotax 915 iS, 141 hp at 5800 rpm, turbocharged, fuel injected. Limits as in\n\t\t\t\tconfig/cockpit.cfg: 5500 rpm continuous, 5800 rpm 5 min, oil 50-130 C, oil 0.8-7 bar,\n\t\t\t\tfuel 2.8-3.2 bar, CHT 135 C, EGT 950 C, 12 V electrical system.')
rep('RPM, oil pressure, and oil temperature gauge markings are taken from the Top Cub, which uses the same O-360 engine.', '')

set_range('MAN IN', 10, 50)
set_range('RPM', 0, 6500)
set_zones('<Definition key="rpm_partial">', [('green', 1400, 5500), ('yellow', 5500, 5800), ('red', 5800, 6500)])
set_range('OIL PSI', 0, 110)
set_zones('<Definition key="oil_psi_partial">', [('red', 0, 12), ('yellow', 12, 29), ('green', 29, 73), ('yellow', 73, 102), ('red', 102, 110)])
set_range('OIL °F', 50, 290)
set_zones('<Definition key="oil_temp_partial">', [('yellow', 50, 194), ('green', 194, 230), ('yellow', 230, 266), ('red', 266, 290)],
          lines=[('red', 266)])
set_range('GPH', 0, 12)
rep('<!-- Red lines taken from Lycoming O-360 manual. Yellow line is a guess. -->', '<!-- Rotax 915 iS: 2.8-3.2 bar (41-46 psi). -->')
set_range('FUEL PSI', 30, 55)
set_zones('<Definition key="fuel_psi_partial">', [('red', 30, 40.6), ('green', 40.6, 46.4), ('red', 46.4, 55)])

# EGT / CHT: 950 C EGT, 135 C CHT
a, b = section('<Definition key="egt_cht_gauge_partial">')
part = s[a:b]
part = part.replace('<Maximum>1816</Maximum>', '<Maximum>1800</Maximum>').replace('<ChtMaximum>640</ChtMaximum>', '<ChtMaximum>300</ChtMaximum>')
part = part.replace('<Tick>239</Tick>', '<Tick>1400</Tick>').replace('<Tick>474</Tick>', '<Tick>1600</Tick>')
for old, new in (('559', '248'), ('627', '275'), ('640', '300')):
    part = part.replace(f'>{old}<', f'>{new}<')
s = s[:a] + part + s[b:]

# 12 V electrical: volts (generator and battery) 8-16 V, amps -20..40 A
a, b = section('<ID>electrical-volt-gauge</ID>', '</Gauge>')
part = s[a:b]
part = re.sub(r'<Minimum>0</Minimum>\s*<Maximum>19.4</Maximum>', '<Minimum>8</Minimum>\n\t\t\t\t\t\t\t\t\t\t<Maximum>16</Maximum>', part)
part = re.sub(r'<Minimum2>0</Minimum2>\s*<Maximum2>23.46</Maximum2>', '<Minimum2>8</Minimum2>\n\t\t\t\t\t\t\t\t\t\t<Maximum2>16</Maximum2>', part)
part = part.replace('<Position>18.7</Position>', '<Position>15.5</Position>')
s = s[:a] + part + s[b:]
volts = [('red', 8, 11.5), ('yellow', 11.5, 12.4), ('green', 12.4, 14.8), ('yellow', 14.8, 15.5), ('red', 15.5, 16)]
for tag in ('ColorZone', 'ColorZone2'):
    a, b = section('<ID>electrical-volt-gauge</ID>', '</Gauge>')
    part = re.sub(rf'\s*<{tag}>.*?</{tag}>', '', s[a:b], flags=re.S)
    i = '\n\t\t\t\t\t\t\t\t\t\t'
    z = ''.join(f'{i}<{tag}>{i}\t<Color>{c}</Color>{i}\t<Begin>{lo}</Begin>{i}\t<End>{hi}</End>{i}</{tag}>' for c, lo, hi in volts)
    key = '<Maximum>16</Maximum>' if tag == 'ColorZone' else '<Maximum2>16</Maximum2>'
    part = part.replace(key, key + z, 1)
    s = s[:a] + part + s[b:]
rep('<Minimum>-25</Minimum>', '<Minimum>-20</Minimum>')
a, b = section('<ID>electrical-amp-gauge</ID>', '</Gauge>')
s = s[:a] + s[a:b].replace('<Maximum>100</Maximum>', '<Maximum>40</Maximum>') + s[b:]

# fuel calculator: 12 gph (POH 5.5: 11.4 gph at 100%); the template's 23 gal tank scale fits the
# POH's 23.2 gal (88 L) tanks, so fuel remaining keeps it
a, b = section('<ID>fuel-flow-gauge-calc</ID>', '</Gauge>')
s = s[:a] + s[a:b].replace('<Maximum>23</Maximum>', '<Maximum>12</Maximum>') + s[b:]
rep('<Right>65.7</Right>', '<Right>0.0</Right>')

# annunciations: oil 0.8 bar, 12 V system, 3 gal low fuel
rep('<Constant>6</Constant>', '<Constant>12</Constant>')
rep('<Constant>10</Constant>', '<Constant>12</Constant>')
rep('<Constant>37.4</Constant>', '<Constant>15.5</Constant>')
rep('<Constant>5</Constant>', '<Constant>3</Constant>', every=True)

# Backlight: the G3X's own default is Manual at 100%, which is blinding at night (the photocell
# settings only apply once the pilot picks Photo Cell). default-mode makes it power up on the
# photocell, so it dims with ambient light like the G5. The screen glow goes as level^2.2, so
# 0.85 still gives a bright daylight screen; 0.05 is dim enough for night.
rep('<Backlight>', '<Backlight default-mode="photocell">')
rep('<PhotoCell min-brightness="0.1" />', '<PhotoCell min-brightness="0.05" max-brightness="0.85" />')

# flap indicator: 0 / 10 / 20 / 34 deg (POH 7.2.10)
rep('<FlapsGauge min-flaps-value="0" max-flaps-value="46">', '<FlapsGauge min-flaps-value="0" max-flaps-value="34">')
rep('<FlapsGaugeComponent type="line" color="white" value="16"/>', '<FlapsGaugeComponent type="line" color="white" value="10"/>')
rep('<FlapsGaugeComponent type="line" color="white" value="33"/>', '<FlapsGaugeComponent type="line" color="white" value="20"/>')

s = '<!-- Sling TSi: Working Title G3X Touch configuration, adapted from the default NX Cub (tools/make_panel_xml.py). -->\n' + s
for bad in ('CIRCUIT AVIONICS', 'Lycoming', '2800', '1816', '23.46'):
    assert bad not in s, bad
xml.dom.minidom.parseString(s.encode('utf-8'))           # well-formed
with open(dst, 'w', encoding='utf-8', newline='\r\n') as f:
    f.write(s)
print('panel.xml written', dst)
