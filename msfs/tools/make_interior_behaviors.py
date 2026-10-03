"""Write the panel switch behaviours into the interior model XML.

    python make_interior_behaviors.py SlingTSi_Interior.xml

Replaces everything between the BEGIN/END generated-switches markers with one component per switch
in panel_layout.SWITCHES (Asobo switch templates: they make the lever clickable, drive the sim
function and play sw_<name>_anim), plus the master/starter key. Node and animation names match what
interior.py and postprocess_gltf.py build.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import console_layout as CL  # noqa: E402
import panel_layout as L  # noqa: E402

BEGIN = '<!-- BEGIN generated switches (tools/make_interior_behaviors.py) -->'
END = '<!-- END generated switches -->'


def component(cid, template, params, node=None):
    head = f'\t\t<Component ID="{cid}" Node="{node}">' if node else f'\t\t<Component ID="{cid}">'
    lines = [head, f'\t\t\t<UseTemplate Name="{template}">']
    lines += [f'\t\t\t\t<{k}>{v}</{k}>' for k, v in params.items()]
    lines += ['\t\t\t</UseTemplate>', '\t\t</Component>']
    return '\n'.join(lines)


def block():
    out = [f'\t\t{BEGIN}',
           '\t\t<!-- Panel switches (POH 7.2.7 / 7.10): click to toggle; legends are painted on the panel. -->']
    for name, _xp, _yp, label, template, params in L.SWITCHES:
        p = {'NODE_ID': f'SW_{name}', 'ANIM_NAME': f'sw_{name.lower()}_anim', **params}
        out.append(f'\t\t<!-- {label} -->')
        # the generic knob templates take their node from the component
        node = f'SW_{name}' if template.startswith('ASOBO_GT_Knob') else None
        out.append(component(f'Switch_{name}', template, p, node=node))
    out.append('\t\t<!-- master / starter key (item 3): click and hold to crank the engine -->')
    out.append(component('Key_Starter', 'ASOBO_ENGINE_Push_Starter_Template',
                         {'NODE_ID': 'Key_head', 'ANIM_NAME': 'key_anim', 'ID': 1}))
    # rotary flap selector (POH 7.2.10): UP / 1 (10 deg) / 2 (20 deg) / DOWN (34 deg). Asobo has no flap knob
    # template, so the generic finite knob: wheel or drag clockwise for more flap, and the knob shows the
    # flap handle position (0..3 -> 0..100 of flap_knob_anim, 30 deg steps).
    out.append('\t\t<!-- flap selector knob: scroll or drag, clockwise = flaps down -->')
    out.append(component('Flap_Knob', 'ASOBO_GT_Knob_Finite_Code', {
        'ANIM_NAME': 'flap_knob_anim',
        'ANIM_CODE': '(A:FLAPS HANDLE INDEX, number) 100 * 3 /',
        'CLOCKWISE_CODE': '(&gt;K:FLAPS_INCR)',
        'ANTICLOCKWISE_CODE': '(&gt;K:FLAPS_DECR)',
        'COUNT': 4,
    }, node='Flap_knob_body'))
    # Airmaster propeller controller (POH 7.3.2). The controls only set L:vars; the governing logic that turns
    # them into a propeller lever position lives in SlingTSi.xml (Airmaster_Logic), so it runs in every view.
    out.append('\t\t<!-- Airmaster controller: mode selector (scroll; anticlockwise T.O. -> CLIMB -> CRUISE -> HOLD -> FEATHER) -->')
    out.append(component('Prop_Mode_Knob', 'ASOBO_GT_Knob_Finite_Code', {
        'ANIM_NAME': 'prop_mode_anim',
        'ANIM_CODE': '(L:SLING_PROP_MODE, number) 25 *',
        'CLOCKWISE_CODE': '(L:SLING_PROP_MODE, number) 1 - 0 max (&gt;L:SLING_PROP_MODE, number)',
        'ANTICLOCKWISE_CODE': '(L:SLING_PROP_MODE, number) 1 + 4 min (&gt;L:SLING_PROP_MODE, number)',
        'COUNT': 5,
    }, node='Prop_ctl_knob'))
    out.append('\t\t<!-- Airmaster controller: AUTO (up) / MAN (down); MAN starts from the current pitch -->')
    out.append(component('Prop_AutoMan', 'ASOBO_GT_Component_Switch_Code', {
        'NODE_ID': 'Prop_ctl_automan_bat', 'ANIM_NAME': 'prop_automan_anim',
        'ANIM_CODE': '(L:SLING_PROP_MAN, number) ! 100 *',
        'LEFT_SINGLE_CODE': '(L:SLING_PROP_MAN, number) ! (&gt;L:SLING_PROP_MAN, number) '
                            '(L:SLING_PROP_MAN, number) if{ (A:GENERAL ENG PROPELLER LEVER POSITION:1, percent) '
                            '(&gt;L:SLING_PROP_MAN_PCT, number) }'}))
    out.append('\t\t<!-- Airmaster controller: feather engage (acts with the selector on FEATHER, in AUTO) -->')
    out.append(component('Prop_Feather', 'ASOBO_GT_Component_Switch_Code', {
        'NODE_ID': 'Prop_ctl_feather_bat', 'ANIM_NAME': 'prop_feather_anim',
        'ANIM_CODE': '(L:SLING_PROP_FEATHER, number) 100 *',
        'LEFT_SINGLE_CODE': '(L:SLING_PROP_FEATHER, number) ! (&gt;L:SLING_PROP_FEATHER, number)'}))
    for lamp, var in (('Prop_ctl_fine', 'SLING_PROP_FINE_LIT'), ('Prop_ctl_coarse', 'SLING_PROP_COARSE_LIT')):
        out.append(f'\t\t<Component ID="{lamp}_Lamp" Node="{lamp}">\n\t\t\t<Material>\n\t\t\t\t<EmissiveFactor>\n'
                   f'\t\t\t\t\t<Parameter><Code>(L:{var}, number) 0 &gt; (A:CIRCUIT ON:24, Bool) and</Code></Parameter>\n'
                   f'\t\t\t\t</EmissiveFactor>\n\t\t\t</Material>\n\t\t</Component>')
    # rescue parachute (POH 7.2.6, 9.5.2): the handle pulls only with the safety pin out; once pulled it stays out
    # (on the ground a second click resets it). Click the streamer to remove the pin, the mount plate to refit it.
    out.append('\t\t<!-- rescue parachute activation handle (item 20) and its safety pin -->')
    out.append(component('BRS_Handle', 'ASOBO_GT_Component_Switch_Code', {
        'NODE_ID': 'Chute_handle', 'ANIM_NAME': 'brs_handle_anim',
        'ANIM_CODE': '(L:SLING_BRS_PULLED, number) 100 *',
        'LEFT_SINGLE_CODE': '(L:SLING_BRS_PULLED, number) if{ (A:SIM ON GROUND, Bool) if{ 0 (&gt;L:SLING_BRS_PULLED, number) } } '
                            'els{ (L:SLING_BRS_PIN_OUT, number) if{ 1 (&gt;L:SLING_BRS_PULLED, number) } }'}))
    out.append(component('BRS_Pin', 'ASOBO_GT_Component_Switch_Code', {
        'NODE_ID': 'Chute_pin_flag', 'ANIM_NAME': 'brs_pin_anim', 'ANIM_CODE': '0',
        'LEFT_SINGLE_CODE': '1 (&gt;L:SLING_BRS_PIN_OUT, number)'}))
    out.append(component('BRS_Pin_Refit', 'ASOBO_GT_Component_Switch_Code', {
        'NODE_ID': 'Chute_mount', 'ANIM_NAME': 'brs_pin_anim', 'ANIM_CODE': '0',
        'LEFT_SINGLE_CODE': '(L:SLING_BRS_PULLED, number) ! if{ 0 (&gt;L:SLING_BRS_PIN_OUT, number) }'}))
    for node, code in (('Chute_pin_group', '(L:SLING_BRS_PIN_OUT, number) !'), ('Chute_cable', '(L:SLING_BRS_PULLED, number)')):
        out.append(f'\t\t<Component ID="{node}_Visibility" Node="{node}">\n\t\t\t<Visibility>\n'
                   f'\t\t\t\t<Parameter><Code>{code}</Code></Parameter>\n\t\t\t</Visibility>\n\t\t</Component>')
    out.append('\t\t<!-- centre console (POH 7.9): throttle, hand brake, park brake valve, fuel selector -->')
    for cid, template, params in CL.BEHAVIORS:
        out.append(component(f'Console_{cid}', template, params))
    out.append(f'\t\t{END}')
    return '\n'.join(out)


def main():
    path = sys.argv[1]
    s = open(path, encoding='utf-8').read()
    new = block()
    if BEGIN in s:
        a = s.index(BEGIN)
        a = s.rfind('\n', 0, a) + 1
        b = s.index(END) + len(END)
        s = s[:a] + new + s[b:]
    else:
        a = s.index('\t</Behaviors>')
        s = s[:a] + new + '\n' + s[a:]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(s)
    print(f'{len(L.SWITCHES)} switches, key and {len(CL.BEHAVIORS)} console parts written to {path}')


if __name__ == '__main__':
    main()
