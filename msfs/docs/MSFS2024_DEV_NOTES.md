# MSFS 2024 aircraft development: field notes

Everything learned while building the Sling TSi package in this repo (September 2026, MSFS 2024
v1.8.16.0, SDK 1.6.9). It's written for an agent picking the work up cold. Each finding says how sure it is:

- **[verified-sim]**: observed in the running sim (live SimConnect log, screenshot or user test).
- **[verified-file]**: read directly from SDK, sim or default-aircraft files.
- **[inferred]**: reasoned from evidence but not confirmed. Treat with care.

Start with section 1 (environment) and section 3 (build pitfalls). Most of the lost time went there.

---

## 1. Environment on this machine

| What | Where |
| --- | --- |
| MSFS 2024 (MS Store build, `Microsoft.Limitless`) | `C:\Program Files\WindowsApps\Microsoft.Limitless_1.8.16.0_x64__8wekyb3d8bbwe\FlightSimulator2024.exe` |
| User data, Community folder | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community` (`InstalledPackagesPath` in `LocalCache\UserCfg.opt`) |
| Base packages on disk (html_ui gauges, WT avionics, ModelBehaviorDefs) | `C:\XboxGames\Microsoft Flight Simulator 2024\Content\Packages\` (e.g. `asobo-vcockpits-instruments-navsystems`, `workingtitle-instruments-g3xtouch-v2`) |
| Streamed content (default aircraft, SimAttachments) | Not on disk. Only readable through the **VFS projection** (next row) |
| VFS projection | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalState\VFSProjection` (exists only while the sim runs with the projector enabled) |
| SDK | `C:\MSFS 2024 SDK` (env `MSFS2024_SDK`). Tools in `Tools\bin`, behaviour templates in `ModelBehaviorDefs\Asobo`, samples in `Samples\DevmodeProjects\SimObjects\Aircraft` |
| Builder error log | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\BuilderLogError.txt` |
| Layout generator (user requirement: run after every build) | `C:\Users\arnau\Downloads\MSFSLayoutGenerator.exe .\layout.json`, run inside the package folder |
| Blender | 5.2 (needed: the source `.blend` files are 5.x) and 4.3 in `C:\Program Files\Blender Foundation\` |

- **The VFS projection is slow.** It fetches files on demand, so a recursive `grep`/`find` across it runs for minutes and
  times out. Go straight to known paths (`simobjects/airplanes/asobo_nxcub/...`,
  `simattachments/instruments/...`). Some files there are encrypted and unreadable. [verified-sim]
- **The official folders on disk are empty.** `LocalCache\Packages\Official2024\OneStore` is empty on this machine (everything streams), so don't
  look for default aircraft there. [verified-file]
- **Community install is a junction.** `Community\arnaud-aircraft-sling-tsi` is a directory junction to `msfs\Packages\arnaud-aircraft-sling-tsi`,
  so a rebuild is installed immediately. Don't also open the project in Developer Mode, or the sim loads the
  package twice. [verified-file]

---

## 2. Package and project layout (modular SimObject)

Copied from the SDK `SimpleAircraft` sample. The working tree is `msfs\`.

```
SlingTSiProject.xml                         project (lists the package definition)
PackageDefinitions\arnaud-aircraft-sling-tsi.xml   (+ ContentInfo\Thumbnail.jpg)
PackageSources\SimObjects\Airplanes\SlingTSi\
  common\config\*.cfg                       aircraft, flight_model, engines, systems, cameras, cockpit, ai, gameplay
  common\model\model.cfg, *.xml, *.gltf/.bin
  common\panel\panel.cfg, panel.xml         panel.xml = Working Title G3X config
  common\texture\*.png + *.png.xml          bitmap slot configs
  common\sound, soundAI, flt
  liveries\sling\factory\texture.exterior\  texture.cfg (fallback ..\..\common\texture), thumbnails
  presets\sling\SlingTSi\config\aircraft.cfg          [MODULAR_MERGE] auto = true + FLTSIM title
  presets\sling\SlingTSi\config\attached_objects.cfg  SimAttachments MUST live here (see 5.1)
```

- **The asset group type must be `ModularSimObject`.** Also give the package definition `<PackageOrderHint>CUSTOM_SIMOBJECTS</PackageOrderHint>`, because the builder
  rejects an empty `package_order_hint` ("Package Validation failed"). [verified-sim]
- **Preset config files are generated stubs.** The builder writes one for each common config: `; generated file` + `[MODULAR_MERGE] auto = true`.
  At runtime they merge in `common\config\*.cfg`, so an empty-looking preset `systems.cfg` is fine. [verified-file]
- **`attached_objects.cfg` is not merged from common.** If it isn't in the preset folder, the builder writes an empty one and no attachments load.
  The SDK `DA62_Mod` sample keeps it in the preset. [verified-file]
- **Texture files are plain PNGs.** Put them next to a `.png.xml` like `<BitmapConfiguration><BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot></BitmapConfiguration>`
  (albedo with alpha; `MTL_BITMAP_METAL_ROUGH_AO` + `<ForceNoAlpha>` for comp maps). The builder converts them to `.KTX2`.
  glTF image URIs only need the file name. [verified-sim]

---

## 3. Building with fspackagetool: every pitfall hit

`tools\build.py --package` handles all of these now. When running it by hand:

1. **The sim must be closed.** `fspackagetool` launches `FlightSimulator2024.exe -I ; BuildAssetPackages ...` as
   the builder. If the sim is running it quietly builds nothing. [verified-sim]
2. **There's no `-h` flag.** Any argument is taken as a project path, and the tool starts a builder on it. [verified-sim]
3. **Exit code 67 on success.** The real result is in `_PackageInt\_RPTErrors.xml` (`<RPTErrors/>` = clean), plus
   whether `BuilderLogError.txt` was rewritten (it only is when something gets logged). [verified-sim]
4. **The tool sometimes hangs.** Its output ends at "Attached to EXE - waiting for completion" after the builder has finished. Kill
   it once the builder process is gone and the report has been written. [verified-sim]
5. **Exit 43 within about 1 s, nothing built.** A stale `GameLaunchHelper.exe` from an earlier build is still alive, and the tool
   attaches to it. Kill `GameLaunchHelper.exe` after every package run. [verified-sim]
6. **Validation warnings are logged but don't fail the build.** Seen: `Unknown parameter` for `editable` ([GENERAL]),
   `radiator_temp_*` in [PISTON_ENGINE], and `yellow_*`/`red_*` in cockpit.cfg [MANIFOLD_PRESSURE]. All removed. [verified-sim]
7. **`<CompileBehaviors>` wipes runtime behaviours.** If a model XML has a `<CompileBehaviors>` block, the builder compiles
   **only that block** and replaces `<Behaviors>` with `<Behaviors Compiled="True"><IncludeBase RelativeFile="X.behavior.xml"/>`,
   silently dropping every template-based runtime component (it dropped our door handles). Keep everything in
   runtime `<Behaviors>` (as the NX Cub does); a model XML without `CompileBehaviors` is packaged unchanged. [verified-file]
8. **Run the layout generator afterwards.** `MSFSLayoutGenerator.exe .\layout.json` refreshes `layout.json`, and the user requires it. [verified-sim]

---

## 4. glTF, axes and animations

- **MSFS glTF frame:** nose **+Z**, left **+X**, up **+Y**, origin at the aircraft reference datum. [verified-file: SDK sample]
- **From Blender** (nose +X, left +Y, up +Z): the stock glTF exporter maps (x, y, z) → (x, z, −y). Turning the root
  object −90° about Z before export gives the MSFS frame (`tools/blender_export.py`). [verified-sim]
- **Config coordinates are feet from the datum:** longitudinal (+fwd), lateral (**+right**), vertical (+up). This holds for
  contact points, stations, `lightdef` `LocalPosition`, `Engine.N`, fuel tanks and `eyepoint`. [verified-file]
- **The stock Blender exporter is enough.** Strip `KHR_materials_*` extensions (not needed). The MSFS Blender exporter add-on wasn't needed. [verified-sim]
- **Animations are plain glTF rotation channels** named to match `<Animation name=...>` + `<PartInfo>` in the model
  XML. We write key times as frame/60 for 100 frames. The SDK sample's key times suggest the sim maps AnimLength onto
  the clip's duration, so 100/60 s works either way. [inferred]
- **Legacy `<Animation type="Sim" typeParam="AutoPlay">` + `<PartInfo>` with `<Code>` or `<Sim><Variable>`** still work
  in 2024. [verified-sim: control surfaces, prop, wheels, sticks, levers animate]
- **Visibility** uses runtime `<Behaviors><Component ID Node><Visibility><Parameter><Code>...`. [verified-sim: prop blur]
- **`model.cfg`:**
  ```
  [model.options]
  withExterior_showInterior=true
  withExterior_showInterior_hideFirstLod=false
  withInterior_forceFirstLod=true
  withInterior_showExterior=true
  [models]
  exterior=X.xml
  interior=X_Interior.xml
  ```
  With a single `normal=` model and no interior, the cockpit view shows **nothing**. [verified-sim]
- **Hull-intersecting geometry shows in the cockpit.** The source wings ran through the fuselage to the centreline and appeared inside the
  cabin, so wing faces inside the hull are trimmed at export. [verified-sim]

---

## 5. Avionics

### 5.1 SimAttachments are the 2024 way to get working instruments
Default aircraft don't model their avionics: they hang **SimAttachment** instruments on empty nodes.
Pattern from the NX Cub, verified-file and verified-sim on the Sling:
```
[SIM_ATTACHMENT.0]
attachment="SimAttachments/Instruments/asobo_mpa_g3x_touch/model/g3x_touch.xml"
attach_to_model="interior"
attach_to_model_minsize=1
attach_to_node="Attach_Point_G3X"
attach_offset=0,0,0
attach_pbh=0,0,0
attach_scale=1
always_execute_associate_js=1
always_execute_model_behavior=1
behavior_parameter.0="CIRCUIT_ID,13"
behavior_parameter.1="BOUNCE_POTENTIOMETER,(L:AS3X_Touch_ScreenLuminosity) 100 *"
behavior_parameter.2="BACKLIGHT_ID,1"
vcockpit_parameter.0="VCockpit01_htmlgauge00_file,NavSystems/G3XTouchv2/G3XTouch.html"
vcockpit_parameter.1="VCockpit01_htmlgauge00_params,?Index=1"
```
- **Available instruments** are listed under `VFSProjection\simattachments\instruments\`. The ones used here: `asobo_mpa_g3x_touch`,
  `asobo_autopilot_g307_noyawdamper` (GMC 307, param `POTENTIOMETER`), `asobo_radio_com_g225` (param `COM_ID`).
  Others seen: G1000 parts, GNS 430/530, GTN 650, G5 (see below), many analog gauges, ELT, compass, extinguisher.
  There's **no GTR 200**; the G225 is the same size and does the same job. [verified-file]
- **Attachment models face aft (−Z) with their origin on the panel surface.** Sizes: G3X 0.275 × 0.20 m, origin
  0.052 m above its bottom edge; G5 0.086 × 0.092 m, centred; GMC 307 0.142 × 0.052 m; G225 0.160 × 0.042 m. [verified-file]
- **An attach point built in Blender needs an extra +90° about Z.** The export root turns everything −90° about Z,
  while attachments are authored in the MSFS frame; without the correction they sat sideways. A panel tilt then goes about
  X. [verified-file: rendered with the real attachment meshes]
- **The G5 attachment can't be attached.** It ships **no model XML**, only glTF. Instead, model the G5 yourself, give its screen a
  `$`-named material and drive it from `panel.cfg` with the built-in gauge `NavSystems/AS5/AS5.html?Index=1`
  (AS5 = G5; Index 1 = attitude page, 2 = HSI). The Bagolu C172 does the same. [verified-file]

### 5.2 Gauges in panel.cfg (`$` materials)
- **`texture=$NAME` in `[VCockpitNN]` renders into the model material named `$NAME`.** The screen mesh needs 0..1 UVs, and
  the material should be emissive (the SDK WasmAircraft sample uses `emissiveFactor` 2000, scaled by a behaviour with
  `(A:AMBIENT LIGHT SENSOR, Number) 200 2000 0.005 1 (F:MapRange)`). [verified-sim: G5 displays]
- **Built-in gauge paths are on disk.** They're in the base packages under `html_ui\Pages\VCockpit\Instruments\`: `NavSystems/AS3X_Touch`
  (old Asobo G3X), `NavSystems/G3XTouchv2/G3XTouch.html` (Working Title), `NavSystems/AS5` (G5), AS1000/AS3000,
  GPS AS430/AS530, and generic radios and autopilots. GTR 200 and GFC 605 gauges come only from the Flysimware add-on. [verified-file]

### 5.3 Working Title G3X Touch: `panel\panel.xml`
- **The WT G3X reads the aircraft's `panel/panel.xml`** for its sensors, radios, engine page, annunciations and backlight. The NX
  Cub's file is a complete template (copied to `tools/templates/nxcub_panel.xml`, adapted by
  `tools/make_panel_xml.py`). [verified-sim: boots, engine page shows]
- **Backlight defaults to Manual at 100%.** The `<PhotoCell>` limits only apply once the pilot picks Photo Cell. Use
  `<Backlight default-mode="photocell"><PhotoCell min-brightness="0.05" max-brightness="0.85"/></Backlight>`.
  Also accepted: `min-input`, `max-input`, `time-constant`, and `default-mode` = manual / photocell / lightbus / none. Screen glow
  follows `L:1:WTG3X_Screen_Backlight_1` raised to the power 2.22. [verified-file; user saw the blinding screen at night]

---

## 6. Autopilot (WT GFC 500 driven by the G3X): the long debug

Final working configuration [verified-sim: HDG turns both ways settle within 1°, ALT capture]:

1. **`[AUTOPILOT]` in systems.cfg = the NX Cub's section.** This includes `use_no_default_bank = 1`,
   `use_no_default_pitch = 1`, `default_bank_mode = 3`, `default_pitch_mode = 1`, `pitch_use_elevator_only = 1`,
   `max_bank = 30,...`, and the full `roll_/pitch_/hdg_/vs_/flc_/nav_*` PID gains.
   - Without `use_no_default_*`, the sim's own modes fight the WT director and it turns the wrong way.
   - With `use_no_default_*` but **no PID gains**, the servos don't move: ailerons stay still and the aircraft spirals.
2. **A working `[VACUUM_SYSTEM]`**, even in an all-glass aircraft: `max_pressure = 5.15`, `vacuum_type = 1`,
   `engine_map = 1,0,0,0`, `suction_gain = 0.85`, `suction_min = 4.05` (NX Cub values). The G3X AHRS reads the sim's
   **gyro instruments** (`ATTITUDE INDICATOR BANK/PITCH DEGREES`), and without vacuum they topple.
   - Symptoms: a white diagonal line (tilted horizon) on the G3X, FD and AP steering the wrong way, and bank/pitch refs pinned at the limits (25° / −20°).
   - Live proof: suction 0, attitude indicator showing 29° bank / −20° pitch while the aircraft was at 12.8° / 0.2°.

**Lessons (avoid repeating our three wasted test flights):**
- **When the AP misbehaves, first compare the gyro instruments with true attitude** (and check suction) before touching
  gains or the flight model.
- **Negating the roll PID gains changed nothing**, which proved the servo wasn't the problem. Changing one thing per flight is what
  made that visible.
- **The G5 (AS5 gauge) draws the sim's flight director.** Its FD disagreed with the G3X only while the gyros were toppled.
  After the vacuum fix the user confirmed the G5 FD works alongside the WT autopilot. [verified-sim]

**Live debugging:** `python tools/ap_monitor.py SECONDS [HZ]` (needs `pip install SimConnect`). It logs attitude, the gyro
instruments, suction, AP modes, bank/pitch hold refs, FD values and control positions.
- **Sign conventions** [verified-sim]: `PLANE BANK DEGREES` is positive for **left** bank, `PLANE PITCH DEGREES` is positive
  **nose down**, both in **radians** by default. Positive `AILERON POSITION` = right roll input.
- **Hold refs need a custom request:** `AUTOPILOT BANK HOLD REF` / `PITCH HOLD REF` aren't in the Python library's list. Request them directly with
  `Request((b'AUTOPILOT BANK HOLD REF', b'Degrees'), sm, _time=0)`.

---

## 7. Flight model and systems facts

- **Modern flight model keys.** The SDK SimpleAircraft `flight_model.cfg` is an older layout. The NX Cub adds modern keys, which the Sling now
  copies: `modern_fm_only = 1`, CFD flags, `elevator_lift_coef`, `rudder_lift_coef`, `*_maxangle_scalar`,
  `*_chordangle_scalar`, gyro stability, wing flex, `enable_high_accuracy_integration`, etc. [verified-file]
- **Span fractions.** `aileron_span_outboard` is where the aileron **starts** (fraction of the semi-span), and flap
  `span-outboard` is where the flap **ends** (NX Cub: 0.65 / 0.35; Sling: 0.69 / 0.68). Adding it didn't change the AP
  problem (that was the vacuum). [inferred semantics]
- **Contact points:** `point.N = Name:X#Properties:class, lon, lat, vert, damage threshold, brake map, wheel radius,
  steer angle, static compression, max/static ratio, damping, ext time, retract time, sound type, airspeed limit,
  damage speed`, with the vertical position at the static ground contact. [verified-file]
- **Doors = interactive points in `flight_model.cfg`:**
  ```
  [INTERACTIVE POINTS]
  interactive_point.0 = Name:Door_Left#Properties:0.35,0,0,0,0,0,0,0,0,0,0,0,0,0,0
  ```
  The first property is the opening rate (fraction per second). Animate with `(A:INTERACTIVE POINT OPEN:N, Percent)`. The legacy
  `[EXITS]` / `EXIT OPEN` did nothing. [verified-sim]
- **Clickable door handle:** runtime `<Behaviors>` with `<Include ModelBehaviorFile="Asobo\\Common.xml"/>` and
  `ASOBO_AIRCRAFT_Door_Handle_Template` (`NODE_ID_HANDLE`, `ID` = 1-based point index, `ANIM_NAME`, and
  **`INTERACTION_TYPE` required**: Push/Switch/Knob/Lever; without it no click zone is created). Push = click
  toggles. [verified-sim: cockpit latch levers click and the doors animate]
- **Outside handles work the same way in the exterior model XML.** A handle node parented to the door hinge pivot, plus the
  same template with the same ID (both handles drive one interactive point). The exterior XML has no `<CompileBehaviors>`,
  so its runtime `<Behaviors>` are packaged unchanged. [verified-file; awaiting user test]
- **Clickable panel switches** use the Asobo templates with our own `NODE_ID` (the lever mesh) and `ANIM_NAME`. The
  animation convention is state x 100 (frame 0 = off, 100 = on). Templates used:
  `ASOBO_ELECTRICAL_Switch_Battery_Master_Template`, `..._Avionics_Master_Template`, `..._Alternator_Template`,
  `ASOBO_ENGINE_Switch_Magneto_Template` (`SWITCH_TYPE ON_OFF`, `MAGNETO_ID` 1/2: the Rotax lanes),
  `ASOBO_FUEL_Switch_Pump_Template`, `ASOBO_DEICE_Switch_Pitot_Template`, `ASOBO_LIGHTING_Switch_Light_{Landing,Taxi,
  Navigation,Strobe,Cabin}_Template`, `ASOBO_ELECTRICAL_Switch_Circuit_Template` (`CIRCUIT_ID`, for switches with no sim
  function, on `CIRCUIT_XML:n` circuits), and `ASOBO_ENGINE_Push_Starter_Template` for the key. Subtemplates (defaults,
  parameters) are in `ModelBehaviorDefs/Asobo/Common/Subtemplates/*_Subtemplates.xml`. [verified-file; awaiting user test]
- **Panel layout is data-driven.** `tools/panel_layout.py` holds the diagram positions, switch-to-template table, legends
  and placards. `make_panel_texture.py` paints the face texture from it, `interior.py` places the parts from it, and
  `make_interior_behaviors.py` writes the switch components between markers in `SlingTSi_Interior.xml`. So adding a
  switch there wires it everywhere.
- **Systems.cfg `lightdef` format:**
  `Type:3#Index:0#LocalPosition:lon,lat,vert#LocalRotation:p,b,h#EffectFile:LIGHT_ASOBO_NavigationGreen#PotentiometerIndex:1#EmMesh:NodeName`.
  EmMesh drives the emissive of a named light mesh. [verified-file]
- **Rotax 915 iS in `engines.cfg`:** engine RPM limits (5800), `gear_reduction_ratio` 2.54, turbocharged. The power and drag
  tuning hasn't been flight-checked. [inferred]

---

## 8. Repo tools (msfs/tools)

| Script | Purpose |
| --- | --- |
| `build.py [--package]` | Full pipeline: Blender export of four exterior LODs + interior, post-process, configs, `panel.xml`, thumbnails; with `--package`: fspackagetool (hang/43 handling), error checks, layout generator |
| `blender_export.py` | Runs in Blender: restructures nodes, trims wings inside the hull, root to the MSFS frame, writes hinge axes to `meta.json`; `interior` part calls `interior.py` |
| `interior.py` | Procedural cockpit from POH 7.9/7.10 (panel outline traced from the diagram, items placed by diagram pixel), attach points, hull-fitted seats, a clearance check that fails loudly when parts cross the fuselage lining |
| `postprocess_gltf.py` | Strips unsupported extensions, sets up `$` screen materials, appends all animations |
| `make_configs.py` | Writes flight_model/engines/cameras from the SDK sample plus Sling values (**systems.cfg, aircraft.cfg, cockpit.cfg are hand-edited, not generated**) |
| `make_panel_xml.py` | Writes the G3X `panel.xml` from the NX Cub template with checked substitutions |
| `render_cockpit.py` | Blender review renders of the exported glTFs, importing the real attachment meshes from the VFS projection when available |
| `ap_monitor.py` | Live SimConnect logger for the autopilot chain |

Reference material: POH at `C:\Users\arnau\Downloads\Sling-4-TSi-Pilot-Operating-Handbook-Rev-3.5.pdf` (panel
diagram p.124, cockpit plan p.122, stick p.108, prop controller p.115; extract images with PyMuPDF).

## 9. Open items at hand-off

- **User tests pending:** do the outside door handles show click spots (the cockpit ones and the G5 FD are confirmed)?
  Do the front headrests clear the fuselage?
- **Flight model performance unchecked:** stall 47/56 KIAS, 135 KTAS cruise, about 1,000 fpm climb.
- **AP modes not flown yet:** NAV, VS, FLC, approach.
- **Cockpit switches aren't clickable yet** (only the door latches have behaviours).

### Magneto template pitfall (independent lane/mag toggles)
`ASOBO_ENGINE_Switch_Magneto_Template` with `SWITCH_TYPE ON_OFF` (uncovered) does **not** give an
independent left/right toggle: it uses `MAGNETO_ID` as the *engine* index, clicks
`B:ENGINE_Magneto_<n>_Toggle` (cycles the whole OFF/L/R/BOTH selector) and animates the lever up
only when the selector is exactly LEFT. Result: engine runs on BOTH while the levers read OFF.
Fix used for the Sling's ECU lanes (`tools/panel_layout.py:_lane`): `ASOBO_GT_Component_Switch_Code`
with `ANIM_CODE (A:RECIP ENG LEFT|RIGHT MAGNETO:1, Bool) 100 *` and a click that computes
`left + 2*right` with the clicked side flipped and fires `K:MAGNETO1_OFF/LEFT/RIGHT/BOTH`.

### G225 com radio needs a NAVCOM circuit and volume
The `asobo_radio_com_g225` attachment (template `ASOBO_AS_225_TSO`, SDK `ModelBehaviorDefs\Asobo\NAVCOM\NavComSystem.xml`)
is powered only when `(A:COM VOLUME:1, Percent) 0 > (A:CIRCUIT NAVCOM1 ON, Bool) and`. A `CIRCUIT_COM:1` is **not**
enough: add `Type:CIRCUIT_NAVCOM:1` on the avionics bus (systems.cfg circuit.27 here), and the volume knob must be
above 0. [verified-file]

### Console levers: templates used
- Throttle: `ASOBO_ENGINE_Lever_Throttle_Template` (NODE_ID = knob mesh, ANIM_NAME = the lever animation, ID 1).
- Hand brake: `ASOBO_LANDING_GEAR_Lever_Brake_Template` (anim = `B:LANDING_GEAR_Brake` percent).
- When a template drives an animation, remove any legacy `<Animation>`/`<PartInfo>` for the same name.
- Park brake valve / fuel selector: `ASOBO_GT_Component_Switch_Code` with `K:PARKING_BRAKES`,
  `K:FUEL_SELECTOR_LEFT/RIGHT/OFF` and `(A:FUEL TANK SELECTOR:1, Enum)` (0 off, 2 left, 3 right).
- Parts that sit on a printed plate must not share its surface plane (z-fighting); mount them slightly above.

### Exterior fixes applied at export (tools/exterior.py)
The generated model (../model/index.html) is left untouched; blender_export.py patches it:
- **Livery**: the generator's fuselage UV v was the superellipse *angle*, which crowds the side stripe into
  ~7 mm texels (the lower section is boxy, H ~ sqrt(angle) near the sides) and was point-sampled. make_livery.py
  (runs in Blender for numpy) repaints the same design at 4096x4096 in arc-length space with 2x3 supersampling;
  exterior.livery() remaps the shell UVs (Fuselage, Door skins, glass) with sling_shape.arc_fraction(). Must run
  for the interior too: the cabin lining copies the fuselage UVs and livery alpha.
- **Intakes**: skin faces inside each inlet outline (+4 mm) are deleted; a rounded lip (+12..-5 mm, hides the
  jagged cut) and a dark duct with a radiator core replace the flat patches.
- **Exhaust**: bent pipe out through the cowling floor with a collar; **wheel pants**: scaled about their
  bottom until the tyre above axle-5 cm is enclosed (mains x1.14, nose x1.07).
- **Cowl details** (exterior.nose_ring / cooling_exit / gear_well, parametric cowl only): the rolled nose ring with
  a dark bulkhead behind it, the open cooling exit slot under the lower cowl's aft edge, the nose gear leg's well in
  the keel. See "Cowl details" below.
- Open meshes: MSFS draws one side, so every generated face is oriented explicitly (exterior.loft's `facing`).
- **Windows** (make_livery.window_at): laid out on the skin in (X, q = arc distance from the roof centreline);
  door windows = the gull-wing door inset by a frame (60 mm below the hinge line, sill at H 1330), windscreen corners
  rounded with a distance-field join. Side-view (X, H) rectangles kinked where they wrapped over the roof.

### Checking the shape against the POH 3-view
`tools/render_orthographic.py` (Blender) renders side/front/top orthographic views with scale sidecars;
`tools/compare_3view.py` overlays the POH rev 3.5 pages 1-3/1-4 (rendered at 200 dpi with pymupdf) in red,
registered on the spinner tip, centreline and ground. Findings (2026-09-30): fuselage, cowl, wing, tailplane,
gear positions and front view match; the door/rear windows and baggage door were moved to the drawing.
Not changed (model-level, in ../model/index.html): the fin is ~60 mm taller and the rudder trailing edge
~0.1 m further aft than the rev 3.5 drawing (the model follows rev 3.1: 7175 x 9544 x 2414 mm vs 7200 x 9500
x 2350), and the nose-gear leg is straight where the drawing shows a raked leg from further forward.

### Engine would not start from cold (fuel pressure)
`rpm_to_fuel_pressure_table` (engines.cfg) scales fuel pressure by engine rpm, as for an engine-driven pump.
With the SDK-style rising table (0:0 ... 2800:1) a cold start sat at 0 psi while cranking and never fired,
while starts right after Ctrl+E worked on leftover pressure. The 915 iS has electric pumps only, so the table
is flat (`0:1, 5800:1`). `tools/engine_monitor.py` logs the start chain (starter, rpm, combustion, magnetos,
selector, pump, fuel pressure/flow, throttle, bus) over SimConnect.
**Update — the real cause was the engine fuel valve.** The legacy fuel system has a per-engine shutoff
(`GENERAL ENG FUEL VALVE:1`, toggled by `K:TOGGLE_FUEL_VALVE_ENG1`). Cold-and-dark closes it; only autostart
(Ctrl+E) opens it, so a manual start with pump, selector and lanes on still got no fuel (0 psi, no combustion).
SlingTSi.xml has a no-node component with `<Update Frequency="2">` that keeps the valve open whenever the
fuel selector is not OFF. `<Update>` is how a behaviour runs code continuously (Asobo uses it in Lighting.xml).

### FADEC mixture and the Airmaster propeller controller
- No mixture lever on the TSi: SlingTSi.xml `FADEC_Mixture` holds `GENERAL ENG MIXTURE LEVER POSITION` at 100%
  (`K:MIXTURE1_SET 16383`), so a hardware mixture axis has no effect.
- The propeller is governed by the Airmaster AP430 controller (POH 7.3.2), not the FADEC. Cockpit controls only set
  `L:SLING_PROP_*` (mode knob, AUTO/MAN, feather toggle, FINE/COARSE rocker via scroll); `Airmaster_Logic` in
  SlingTSi.xml (`<Update Frequency="10">`, runs in every view) turns them into the sim propeller lever with
  `K:PROP_PITCH1_SET` (`K:PROPELLER1_SET` has no effect), overriding a hardware prop axis. The sim's lever-to-rpm
  mapping is not linear (measured in flight: 100% 5896, 75% 4675, 50% already at the 34 deg pitch stop), so the
  logic governs in closed loop on `GENERAL ENG RPM:1`, walking the lever toward the mode's target rpm.
  RPN: `sN` stores and keeps the value on the stack, `spN` stores and pops; use `spN` for plain assignments.
  Modes: T.O. 5800, CLIMB 5500, CRUISE 5000 (POH 5.4 / 2.14.3), HOLD pilot-set (starts 5000), FEATHER = coarsest
  governed pitch (the sim cannot feather this prop). MAN trims the lever directly (the sim still governs).
- Generic knob behaviour with custom code: `ASOBO_GT_Knob_Finite_Code` (ANIM_CODE / CLOCKWISE_CODE /
  ANTICLOCKWISE_CODE) inside `<Component ID=.. Node="mesh">`. Used for the flap selector and the Airmaster knob.

### Rescue parachute handle (POH 7.2.6 / 9.5.2) and translation animations
- `interior.chute_handle()`: mount, red T-handle on `Chute_handle_slide`, safety pin + REMOVE BEFORE FLIGHT streamer
  (`Chute_pin_group`, printed from the console atlas `flag` region). L:vars `SLING_BRS_PIN_OUT`, `SLING_BRS_PULLED`;
  the handle only pulls with the pin out, stays out in flight, resets on the ground. No deployment physics yet:
  MSFS has no ballistic parachute; options are a big-drag spoiler hack in the flight model or a WASM module that
  drives the velocity (POH: 9.4 m/s descent at 950 kg, deploy below 155 kt).
- `postprocess_gltf.translation_anim(name, node, [(frame, metres)])` slides a node along its meta axis (absolute
  keys = rest translation + offset; the axis is in the root's local glTF frame, like the rotation axes).
- `<Visibility>` on a node hides its children too (pin group, prop still/blur).
- **Built-in parachute (found in the default SF50, `microsoft_sf50`, readable in the VFS):** MSFS 2024 has an aircraft
  parachute declared in flight_model.cfg as `[OBJ_EA1_PARACHUTE]` with `position` (lateral, vertical, longitudinal
  ft; SF50 `0, 4, -13.43`) and `size` (canopy radius ft, default 47; SF50 100). It deploys when
  `A:PARACHUTE OPEN` is set to 1: the SF50 CAPS system (Working Title `sf50mfdplugins.js`, `Sf50CapsSystem`) does
  exactly that from JS once `L:1:SF50_CAPS_Handle_Position` = 1 and IAS < 135 / TAS < 145. The docs list the
  simvar as read-only and "Parachute SimObject used by Winches" only, but it is written in practice. The Sling sets
  it from SlingTSi.xml `BRS_Deploy` (`1 (>A:PARACHUTE OPEN, Number)`), size 55 [TUNE to 9.4 m/s].
  The `visionjet` folder is FlightFX's encrypted Vision Jet (no chute); Asobo's is `microsoft_sf50`.
- **Pitot / AOA probe** (POH 7.8: below the left wing, with an AOA hole): `exterior.pitot()` builds a GAP 26-style
  L probe at 2.9 m span [GUESS, not published], mast at 15% chord fitted to the lower skin by ray cast.

### Exterior lights: potentiometer trap and wingtip units
- Light intensity is scaled by `LIGHT POTENTIOMETER:<PotentiometerIndex>`. Ours used index 1 (as the SDK sample) and the
  sim had every potentiometer at 2% (read over SimConnect), so the nav/strobe/landing lights were effectively off with
  the switches ON and the circuits powered. Exterior lightdefs now use potentiometer 10, held at 100% by SlingTSi.xml
  `Exterior_Light_Pot` (`(>K:LIGHT_POTENTIOMETER_10_SET)`, as Asobo's Lighting.xml does). The Python SimConnect
  library cannot send that event (not in its list, and a raw send had no effect), so verify in the sim.
- `exterior.wing_lights()` replaces the generator's 24 mm spheres with Whelen-style wingtip units (bezel, clear lens,
  reflector, nav LED dome, strobe tube, white aft position light); emitters are renamed to `LIGHT_*` EmMesh nodes.
- **Magnetic compass** (`interior.compass`): card on `Compass_card_pivot`, legacy anim `compass_card_anim` from
  `WISKEY COMPASS INDICATION DEGREES` (spin keys every 90 deg). Reverse sensing: the strip is printed with
  360 - heading so the sequence runs backwards (E left of the lubber line heading north) but glyphs read normally.
- **Seats** (`interior.upholstered`): each cushion/back is one swept shell, a cross-section (dished quilted centre,
  seam groove, rolled bolster, rounded outer edge) swept along the piece with width/centre/bolster functions of t
  (neck + integrated headrest on the front backs), two material slots (leather, quilted atlas at true size),
  orange piping and stitch tubes along the edge/seam polylines, widths fitted to the hull at every station.
  Puffy quilting (`interior.quilt_panel`, currently NOT used to save polygons): a dense grid (~6.7 mm) over each centre panel, displaced by the same 40 mm
  diamond function the quilt texture is painted with, so printed stitches sit in the valleys; ~5 k tris per panel.
- **Taxi wig-wag** (POH 7.15.5): the taxi switch is a 3-position knob-template switch (L:SLING_TAXI_MODE); the two
  taxi lightdefs use potentiometers 11/12, which SlingTSi.xml `Taxi_WigWag` alternates on its own tick counter: `(E:ABSOLUTE TIME)` stayed constant inside an `<Update>` (read live), so time-based blinking needs a counter. Two-parameter key events in
  RPN take their parameters in order then the event: `value index (>K:2:LIGHT_POTENTIOMETER_SET)` (Asobo usage).

## Cowling shape (smooth lofted cowl, Rotax 915 iS description)
- The user supplied a written description of the cowl. Sections are smooth and crease-free, lofted through four stations in `sling_shape.py`:
  - X 290: the 285 mm nose ring;
  - X 475: an inverted trapezoid with wide cheeks;
  - X 700: the cheeks at their widest;
  - from X 1000: the cabin's own section, blended in up to the firewall at X 1165.
- Each section is a trapezoidal superellipse (`cowl_section`): the half-width narrows from the cheek line (Wc at Hc) to Wt·Wc at the top and Wb·Wc at the bottom. The narrowing is quadratic in t; a linear narrowing leaves a kink along the cheek line.
- Local features are radial offsets in `skin_point`:
  - concave pockets round the cheek inlets (`POCKET`);
  - the keel channel for the nose gear (`GEAR_CHANNEL`);
  - the lower cowl's aft edge stepping 18 mm proud of the belly as the cowl-flap exit (`EXIT_LIP`, not faded at the firewall).
- `exterior.spinner()` scales the spinner to a 280 mm backplate and moves it 6 mm forward, leaving the gap to the ring.
- Cheek inlets: teardrops 170 × 72 mm at H 1180, Z ±250. Chin scoop: 360 × 125 mm at H 950.
- Painted on the livery (make_livery.paint): the cowl split line at H 1125 and the port oil door (X 905–1065, |Z| 70–200) with four cam-locks.
- Not followed from the description:
  - Its lengths (cowl about 650 mm, firewall 955 mm from the spinner tip) conflict with the POH 3-view (about 1150 mm). The POH stations are kept.
  - The thrust-line cant (1.5–2° down, 1.5° right) is not modelled.
- Pitfall: make_livery.py must get an absolute output path. With a relative one, Blender writes the PNGs somewhere else and exports silently use a stale livery, which shows as wavy stripes on a reshaped skin.

## Grafted nose from a reference mesh (reference/meshy_cowling.glb)
- The user supplied an AI-generated (Meshy) whole aircraft whose nose they liked. It is one fused 176k-triangle mesh, nose toward −x, z up, +y starboard, arbitrary units, no UVs.
- `tools/meshy_cowl.py` measures its landmarks:
  - the spinner tip;
  - the nose ring, fixed at x −0.696. Automatic detection is fooled by the cheek-inlet lips at the thrust line.
  - the firewall, where the windscreen base makes the top line's slope jump;
  - the firewall section, measured from inside so the fused gear is ignored.
- It then maps the reference onto our X 290–1165, with separate scales above the thrust line, below it, and across, so the reference meets the cabin section at the firewall.
- It writes `tools/data/cowl_meshy.npz`: the radius about (0, hm) by polar angle at 5 mm stations, port and starboard averaged, outliers removed, median-filtered and blurred. The underside gets a much heavier blur along the length.
  - Outliers are rays escaping through the gear well that hit the wheel about 1 m away; they are filled from neighbouring angles.
  - The heavy underside blur matters because the section's whole perimeter sets the livery's arc-length v. Noise on the belly would shift the paint on the sides.
- `sling_shape.skin_point()` uses that table (bilinear) for X < 1165, pulled onto our 285 mm ring at the front and blended into the cabin over X 1000–1165. This smooth surface is what the livery is painted on, and what the UV arc fractions refer to.
- `exterior.graft_nose()` runs on the exterior LODs in place of `intakes()`. It grafts the reference's actual geometry:
  - bisect at X 290 and GRAFT_X 1170;
  - drop faces hanging more than 30 mm below the smoothed cowl (the gear) and keep the largest piece;
  - eight `bmesh.ops.smooth_vert` passes take out rivets and lumps. `smooth_laplacian_vert` had no visible effect on this mesh.
  - radial shifts pull the front onto our ring (using the reference's own ring edge by angle) and the rear onto the cabin section at GRAFT_X;
  - livery UVs: the point's polar direction gives the generator angle a, then `arc_fraction` gives v. Faces across the a = 0 seam keep v above 1, so the texture repeats.
  - recessed, forward-facing faces (more than 30 mm deeper than the surface 70 mm around them, seen from ahead) get Intake_duct;
  - finally the graft replaces the Fuselage faces ahead of X 1170.
- Known blemishes, all from the AI mesh: its chin-mouth interior carries livery paint, its chin corners are ragged, and a panel joint kinks the painted split line.

### Meshy API (tools/meshy_api.py) and reference/cowl.json
- `tools/meshy_api.py OUT.glb IMG [IMG...]`: with one image it uses image-to-3d (remeshed, MESHY_POLYCOUNT triangles); with 2–4 images it uses multi-image-to-3d. It is untextured, costing 20 credits per run. The key comes from MESHY_API_KEY or MESHY_API_KEY_FILE and is never stored in the project.
- Multi-image with four photos of different aircraft and settings returned a blob, not a cowl.
- Single image from the unpainted-cowl photo gave a recognisable cowl, but with the photo's open access doors and engine parts inside. It is lumpier and loses the small eye intakes. It is kept as an alternative in cowl.json, not used.
- `reference/cowl.json` names the reference GLB and its landmarks (x_ring, x_fw, z_axis, in its own units).
  - `meshy_cowl.py` samples from outside inward and rejects outliers both ways (gear below, holes into an engine).
  - `graft_nose()` welds vertices first: glTF import splits vertices per face, and without welding the "largest piece" is a single facet. It then drops faces hidden from both the front and the outside, and caps access openings whose rim lies on the smoothed cowl.
- Third generation: multi-image from two photos of one closed cowl (`reference/cowl_meshy_closed.glb`, now the reference). The upper cowl is good: eye intakes, vent grille, panel lines. The underside is junk, because the photos are dark and cluttered there.
  - `cowl.json keep_below_h: 1080` grafts only the reference above that height. Below it our own skin (sling_shape) stays, with its chin scoop cut by `intakes(only=('Cowl_inlet_lower',))`.
  - The reference is laid onto our skin over SEAM (40 mm) above the cut.
  - Our faces are kept SEAM_OVERLAP (15 mm) above the cut, under the reference, so no hairline gap opens.
  - The outside-the-cowl trim applies in every direction, to drop clutter beside the aircraft in the photo.
  - The recess shading only applies within 230 mm of the ring.
- Known: a few pinholes in the generated mesh just above the cut show dark specks.
- The user's markup showed the bump: the cowl rises from the spinner as a rounded dome, with no flat face, and the intakes sit on its flank. Now:
  - `cowl.json keep_ahead_x: 580` puts our own nose ahead of X 580.
  - `sling_shape.skin_point` for X < NOSE_X (620): the section grows from the 285 mm ring as 1 − (1 − t)^1.7 into the cowl section at NOSE_X, interpolating points rather than polar radii (hm moves).
  - The cheek inlets are cut by `intakes()` on the bump's flank: 190 × 92 teardrops at H 1190, Z ±215.
  - The reference keeps the crown, grille and panel lines aft of X 580, blended onto our skin over SEAM.
  - Below keep_below_h the cowl follows the generator's POH-matched section, not the table: the reference's underside is junk and sat 150 mm too low.
- The dome over the top of the nose (user markup): `sling_shape.dome_lift`.
  - The top line runs straight from the ring top (1312.5) to fTop at the firewall, plus DOME·sin(πt)^0.6 (30 mm, gone by X 1050). It never lowers the skin, and fades with sin(φ)^1.5 towards the sides.
  - It is added to `skin_point` through `_skin_point_base` + dome, and to the graft as the last warp before the UVs.
  - Pitfall: the seam blend must lay the graft onto the skin *before* the dome (`_skin_point_base`). Otherwise it is lifted twice, leaving a fin at the seam.
- Matched-side review (`ext_cowl_photo2` faces the same side as the user's second photo; `ext_cowl_photo` is the mirror view).
  - Intakes are now 140 × 68 at H 1205, Z ±330, cut on the flank about 190 mm behind the ring.
  - The top line is convex: 1 − (1 − t)^2.4 from the ring top to the windscreen base. The earlier sin-shaped dome peaked mid-cowl and read as a hump.
  - Cheeks: CHEEK 28 mm at −25° below the section centre, mid-cowl.
  - The table's top is smoothed over about 250 mm, and the graft is clipped to our skin + 4 mm above 10°.
  - Pitfall: in elevated left-side views the far wing's leading edge shows above the cowl. Hide the fuselage (`RENDER_HIDE=Fuselage`) before blaming the cowl.
- The user's clean Meshy cowl shell (`reference/cowl_meshy_shell.glb`) is now the reference. It is hollow, nose toward −y (`cowl.json forward: "-y"`), with real inlet holes. Ring −0.95, firewall 0.70, axis z 0.10.
  - Scales are 530 along, 341 above the thrust line, 613 below and 675 across. Its upper half is much taller than our POH section, so it is squashed there.
  - The width at the firewall is measured from each side separately: an open side access panel let one ray through, giving a negative width that mirrored everything.
  - `cowl.json inlets` makes it a whole shell: its inside is deleted, every hole is capped (FILL_ON_SHELL 80), and our `intakes()` cuts the inlets listed there. Those are measured from its own holes by front rays: eyes 120 × 55 at H 1187, Z ±327, and twin chin inlets 155 × 92 at H 925, Z ±101, 60 mm ducts.
  - The underside trim is loosened (GRAFT_OUT_SHELL 150): the shell's chin lip stands below the smoothed table.
  - `shape_lifts: false`: our dome and cheeks are off. The nose bump (NOSE_X) only applies with keep_ahead_x.
  - Things that did not work on this shell:
    - Keeping its inside and shading it dark: the visibility and normal tests misfire on its rolled lips.
    - Ducting its own holes: deletions leave about 20 tears that also look like inlets.
  - Livery stripes now start behind the inlets (X > 520–620).

## Back to the fully generated exterior (Oct 2026)
- The user tried the Meshy full-aircraft exterior (`tools/reference_exterior.py`, fitted by `tools/fit_reference_aircraft.py`) and rejected it, then asked for no Meshy at all.
- Disabled, not deleted:
  - `reference/disabled/sling_meshy_full.glb` (the full-aircraft swap runs only if `reference/sling_meshy_full.glb` exists);
  - `reference/disabled/cowl.json` (the cowl graft runs only if `reference/cowl.json` exists);
  - `tools/data/disabled/cowl_meshy.npz` (the sampled cowl table).
- The cowl is again the parametric lofted one in `sling_shape.py`, built from the user's written description: four stations, cheek pockets, keel channel, exit lip. The cheek inlets are 170 × 72 teardrops at H 1180, Z ±250, and the chin scoop is 360 × 125 at H 950.
- `exterior.graft_nose()` and its dome and cheek code still reference functions that no longer exist in `sling_shape` (`cowl_radius`, `dome_lift`, etc.). It is dormant; reviving it means restoring those functions.

## Cowl from photos + POH blueprint (Oct 2026, parametric)
- Sources:
  - `Documents/photos`. The front photo `images(4).jpg`, with the 280 mm spinner as the ruler, gives the inlet sizes; `maxresdefault.jpg` and `images(5).jpg` show the bare cowl.
  - `msfs/reference/blueprint` (the POH 3-view, see its README).
- Cheek inlets: rounded eggs (`exterior.eye`, EGG 0.15 narrower outer end, 12° tilt). Cut 132 × 90 mm at H 1188, Z ±232, giving about 112 × 76 visible inside the lip, as in the photo.
- Chin: two grilles, as the photos show. Upper 330 × 112 at H 978, tucked under the nose ring; lower 300 × 66 at H 864, below a 25 mm lip. Both have radiator cores (any inlet named `Cowl_inlet_lower*`).
- Scoops: a recess round each cheek inlet that runs aft as a tapering groove. `SCOOP_DEPTH` / `SCOOP_WIDTH` are by station, centred on the inlet's polar angle, and replace the old Gaussian `POCKET`.
- Crown: a raised band (20 mm, 34 mm rounded edge) between edges running from beside the spinner (95 mm half-width) to the windscreen corners (250 mm). It rises over X 330–760 and fades into the windscreen base.
- Check: an alpha-silhouette ortho render plus an edge-distance table against the POH side view. The top line is within ~10 mm over X 440–880. The rear cowl top (X 900–1150) is still 10–28 mm under the drawing.

## Cowl details (Oct 2026, parametric cowl)
Skin offsets in `sling_shape.skin_point` (so the mesh reshape, the arc-length UVs and the livery all agree) and
geometry in `exterior.py`, run from `blender_export.py` after the exhaust, only when there is no `reference/cowl.json`.
- Skin (`sling_shape.py`):
  - Split line: the two-piece cowl's joint at `COWL_SPLIT_H` (1125, now defined here; make_livery imports it). The
    upper half's edge stands `SPLIT_LEDGE` (2 mm) outside the lower half's, blended over ±3 mm, fading in behind the
    one-piece nose ring (X 300–340). Reads as a shaded line under the painted seam.
  - Firewall joint: the cowl's aft edge stands `JOINT_STEP` (3 mm) proud of the fuselage skin, ramped up over X
    1090–1150. The skin returns to the cabin section at the first station at or behind X 1165 (1170 in the high
    model, 1175 in the standard one), so the step is a short steep band there, under the painted seam at 1165.
  - Exit lip raised from 18 to 24 mm (`EXIT_LIP`); `EXIT_ARC` is the sin(phi) range it (and the slot) fades in
    over; `skin_point(..., exit_lip=False)` gives the floor without it (the exit duct's floor).
  - `belly_height(X, Z)`: the underside's H at (X, Z) with every feature, for placing things on the keel.
  - `RING_LIP`, `GEAR_WELL`, `EXIT_DEPTH`: the geometry's sizes, kept with the shape.
- Geometry (`exterior.py`):
  - `nose_ring()`: a bead round the 285 mm opening, rolled 8 mm in and curling 3 mm forward of X 290 (the spinner
    backplate is 6 mm ahead, so a 3 mm gap stays). It tapers out across the bottom, where the chin grille's lip is
    tucked under the ring. A dark bulkhead disc 2 mm behind the ring closes the opening; it is flat-bottomed at
    H 1050 so the grille's duct is not crossed. Before this the ring was open and the inside of the hull showed through
    the spinner gap.
  - `cooling_exit()`: the fuselage faces between the last cowl station and the first cabin station are deleted over
    the arc where the lip stands clear (sin(phi) < −0.5), leaving the proud floor as a free edge with a 23–27 mm slot
    under it. A dark duct floor 6 mm inside the lip-less skin runs forward `EXIT_DEPTH` (60 mm, but never ahead of
    the gear well) to a bulkhead facing aft, so nothing inside shows; a 4 mm strip gives the trailing edge thickness.
  - `gear_well()`: the leg's opening in the keel channel, a 220 × 84 mm rounded rectangle (`GEAR_WELL`) with a
    3 mm flange round it (hides the jagged cut, as the inlet lips do) and a dark well 60 mm up, closed at the top.
    The generator's leg stopped 13 mm short of the channel floor with an open top; its top vertices (above H 690)
    are raised 70 mm into the well.
  - `loft(..., closed=False)` lofts open arcs (the duct floor, the edge strip).
- Livery (`make_livery.paint`): quarter-turn fasteners (5.5 mm, `LOCK` grey) every 95 mm along the lower half's flange
  12 mm under the split line (`SPLIT_LOCKS`), and every 110 mm of arc along the cowl's aft edge at X 1148
  (`JOINT_LOCKS`), skipped over the exit slot.
- Checked without Blender: `sling_shape` (arc fractions monotone, sections smooth, profiles plotted) and the three
  geometry functions run against a stand-in `bpy`/`bmesh`/`mathutils` on a fuselage grid built as the generator
  builds it (faces deleted: 80 for the exit, 56 for the well, on the high grid). Not yet rendered in Blender or the
  sim: the first build should look at `ext_cowl_chin`, `ext_cowl_front` and a view from behind-below.
- Not changed: the rear cowl top against the POH side view (previous section). The top line is left as it was.

