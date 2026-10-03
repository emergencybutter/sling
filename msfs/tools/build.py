"""Build the Sling TSi MSFS 2024 package sources from ../model, then (optionally) the package.

    python tools/build.py            # export LODs, textures, configs, thumbnails
    python tools/build.py --package  # ... and run fspackagetool to produce Packages/

Needs Blender 5.x (BLENDER env var, or the default install path) and the MSFS 2024 SDK.
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL = os.path.join(os.path.dirname(ROOT), 'model')
BLENDER = os.environ.get('BLENDER', r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe')
LAYOUT_GENERATOR = os.environ.get('MSFS_LAYOUT_GENERATOR', r'C:\Users\arnau\Downloads\MSFSLayoutGenerator.exe')
SDK = os.environ.get('MSFS2024_SDK', r'C:\MSFS 2024 SDK')
SAMPLE = os.path.join(SDK, r'Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft\PackageSources'
                           r'\SimObjects\Airplanes\MyCompany_Simple_Aircraft\common\config')
AIRCRAFT = os.path.join(ROOT, r'PackageSources\SimObjects\Airplanes\SlingTSi')
BUILD = os.path.join(ROOT, 'build')

# Output name, source model, decimate ratio, part. The high-detail model (954k triangles) is
# only for close-ups; the cabin is a separate interior model (see common/model/model.cfg).
LODS = [
    ('SlingTSi_LOD00', 'sling-tsi-high.blend', 1.0, 'exterior'),
    ('SlingTSi_LOD01', 'sling-tsi.blend', 1.0, 'exterior'),
    ('SlingTSi_LOD02', 'sling-tsi.blend', 0.3, 'exterior'),
    ('SlingTSi_LOD03', 'sling-tsi.blend', 0.08, 'exterior'),
    ('SlingTSi_Interior_LOD00', 'sling-tsi.blend', 1.0, 'interior'),   # cockpit built by interior.py
]
BITMAP_SLOTS = {
    'SlingTSi_LIVERY_albd.png': 'MTL_BITMAP_DECAL0',
    'SlingTSi_GLASS_albd.png': 'MTL_BITMAP_DECAL0',
}
REFERENCE = os.path.join(ROOT, 'reference', 'sling_meshy_full.glb')     # the reference exterior, if present
REF_SLOTS = {                     # its texture set (reference_exterior.py), from LOD00's export
    'SlingTSi_EXT_albd.png': 'MTL_BITMAP_DECAL0',
    'SlingTSi_EXT_comp.png': 'MTL_BITMAP_METAL_ROUGH_AO',
    'SlingTSi_EXT_norm.png': 'MTL_BITMAP_NORMAL',
}


def run(cmd):
    print('>', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    keep = [l for l in (r.stdout + r.stderr).splitlines()
            if any(k in l for k in ('hinge', 'exported', 'prop disc', 'Error', 'error', 'Traceback',
                                    'nodes,', 'rendered', 'configs written', 'texture', 'clearance', 'written to', 'intake', 'exhaust', 'wheel pant', 'livery:', 'cowl:', 'spinner:', 'graft:', 'reference', 'greenhouse', 'pitot:', 'wing lights', 'landing lights'))]
    print('\n'.join(keep), flush=True)
    if r.returncode:
        print(r.stdout[-4000:], r.stderr[-4000:])
        sys.exit(f'failed: {cmd[0]}')


def sim_running():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq FlightSimulator2024.exe', '/NH'],
                         capture_output=True, text=True).stdout
    return 'FlightSimulator2024.exe' in out


def run_package_tool(cmd):
    """fspackagetool starts the sim as a builder and waits for it, but sometimes keeps waiting
    after the builder has exited. Stop it once the builder is gone and has written its report."""
    report = os.path.join(ROOT, r'_PackageInt\_RPTErrors.xml')
    started = time.time()
    proc = subprocess.Popen(cmd)
    seen_builder = False
    while proc.poll() is None:
        time.sleep(5)
        if sim_running():
            seen_builder = True
        elif seen_builder and os.path.exists(report) and os.path.getmtime(report) > started:
            time.sleep(10)
            if proc.poll() is None:
                print('fspackagetool kept waiting after the builder exited; stopping it')
                proc.kill()
            break
    # The builder is started through the sim's GameLaunchHelper.exe, which can outlive it. The next
    # fspackagetool run then "attaches" to that stale helper and exits 43 without building anything.
    subprocess.run(['taskkill', '/F', '/IM', 'GameLaunchHelper.exe'], capture_output=True)


def main():
    model_dir = os.path.join(AIRCRAFT, r'common\model')
    tex_dir = os.path.join(AIRCRAFT, r'common\texture')
    os.makedirs(tex_dir, exist_ok=True)

    # panel and console textures (read by interior.py) and the panel switch behaviours
    run([sys.executable, os.path.join(HERE, 'make_panel_texture.py'), os.path.join(BUILD, 'panel', 'SlingTSi_PANEL_albd.png')])
    run([sys.executable, os.path.join(HERE, 'make_console_texture.py'), os.path.join(BUILD, 'panel', 'SlingTSi_CONSOLE_albd.png')])
    run([sys.executable, os.path.join(HERE, 'make_interior_behaviors.py'),
         os.path.join(AIRCRAFT, 'common', 'model', 'SlingTSi_Interior.xml')])

    # fuselage livery and window glass, repainted in arc-length UV space (tools/make_livery.py)
    run([BLENDER, '-b', '--factory-startup', '--python-exit-code', '1', '-P', os.path.join(HERE, 'make_livery.py'),
         '--', os.path.join(BUILD, 'livery')])

    # the reference aircraft fitted to the POH, in the export's frame (fit_reference_aircraft.py)
    if os.path.exists(REFERENCE) and not os.environ.get('SLING_GENERATED_EXTERIOR'):
        fitted = os.path.join(BUILD, 'reference_fit', 'sling_fitted_model.glb')
        os.makedirs(os.path.dirname(fitted), exist_ok=True)
        run([BLENDER, '-b', '--factory-startup', '--python-exit-code', '1', '-P',
             os.path.join(HERE, 'fit_reference_aircraft.py'), '--', REFERENCE, fitted, '--model-frame'])

    for lod, blend, ratio, part in LODS:
        work = os.path.join(BUILD, lod)
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        raw, meta = os.path.join(work, f'raw_{lod}.gltf'), os.path.join(work, 'meta.json')
        run([BLENDER, '-b', os.path.join(MODEL, blend), '--python-exit-code', '1',
             '-P', os.path.join(HERE, 'blender_export.py'), '--', raw, str(ratio), meta, part])
        run([sys.executable, os.path.join(HERE, 'postprocess_gltf.py'), raw, meta,
             os.path.join(model_dir, f'{lod}.gltf')])
        if part == 'interior':          # textures interior.py uses: cabin lining, carbon panel and console
            for png in ('SlingTSi_LINING_albd.png', 'SlingTSi_PANEL_albd.png', 'SlingTSi_CONSOLE_albd.png'):
                shutil.copy(os.path.join(work, png), os.path.join(tex_dir, png))
                with open(os.path.join(tex_dir, png + '.xml'), 'w') as f:
                    f.write('<BitmapConfiguration><BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot></BitmapConfiguration>')
        if lod == 'SlingTSi_LOD00':     # 4096 px paint from the high-detail model serves every LOD
            for png, slot in REF_SLOTS.items():
                if os.path.exists(os.path.join(work, png)):
                    shutil.copy(os.path.join(work, png), os.path.join(tex_dir, png))
                    with open(os.path.join(tex_dir, png + '.xml'), 'w') as f:
                        f.write(f'<BitmapConfiguration><BitmapSlot>{slot}</BitmapSlot></BitmapConfiguration>')
            for png, slot in BITMAP_SLOTS.items():
                if not os.path.exists(os.path.join(work, png)):     # the livery: unused under the reference
                    continue
                shutil.copy(os.path.join(work, png), os.path.join(tex_dir, png))
                with open(os.path.join(tex_dir, png + '.xml'), 'w') as f:
                    f.write(f'<BitmapConfiguration><BitmapSlot>{slot}</BitmapSlot></BitmapConfiguration>')

    run([sys.executable, os.path.join(HERE, 'make_configs.py'), SAMPLE, os.path.join(AIRCRAFT, r'common\config')])
    # G3X Touch configuration, from the default NX Cub's panel.xml (copied from the sim's VFS)
    run([sys.executable, os.path.join(HERE, 'make_panel_xml.py'), os.path.join(HERE, 'templates', 'nxcub_panel.xml'),
         os.path.join(AIRCRAFT, 'common', 'panel', 'panel.xml')])

    thumbs = os.path.join(BUILD, 'thumbs')
    os.makedirs(thumbs, exist_ok=True)
    run([BLENDER, '-b', os.path.join(MODEL, 'sling-tsi.blend'), '-P', os.path.join(HERE, 'render_thumbnail.py'), '--', thumbs])
    livery = os.path.join(AIRCRAFT, r'liveries\sling\factory\texture.exterior')
    for n in ('thumbnail.jpg', 'thumbnail_small.jpg'):
        shutil.copy(os.path.join(thumbs, n), os.path.join(livery, n))
    shutil.copy(os.path.join(thumbs, 'Thumbnail.jpg'),
                os.path.join(ROOT, r'PackageDefinitions\arnaud-aircraft-sling-tsi\ContentInfo\Thumbnail.jpg'))

    if '--package' in sys.argv:
        tool = os.path.join(SDK, r'Tools\bin\fspackagetool.exe')
        # fspackagetool exits 67 even on a clean build, so judge by the builder's reports instead:
        # _RPTErrors.xml lists errors, and BuilderLogError.txt is only rewritten when something is logged.
        log = os.path.join(os.environ['LOCALAPPDATA'],
                           r'Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\BuilderLogError.txt')
        before = os.path.getmtime(log) if os.path.exists(log) else 0
        run_package_tool([tool, os.path.join(ROOT, 'SlingTSiProject.xml'), '-nopause', '-rebuild'])
        errors = open(os.path.join(ROOT, r'_PackageInt\_RPTErrors.xml')).read()
        if '<RPTErrors/>' not in errors:
            sys.exit('package build errors:\n' + errors)
        if os.path.exists(log) and os.path.getmtime(log) > before:
            text = open(log, encoding='utf-8', errors='replace').read()
            print(text[-3000:])
            if 'failed' in text.lower():
                sys.exit(f'package build failed, see {log}')
        # refresh layout.json (file list and sizes the sim checks) for the compiled package
        package = os.path.join(ROOT, r'Packages\arnaud-aircraft-sling-tsi')
        subprocess.run([LAYOUT_GENERATOR, r'.\layout.json'], cwd=package, check=True)


if __name__ == '__main__':
    main()
