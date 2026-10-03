# Sling 4 TSi

A procedurally generated 3D model of the Sling 4 TSi, built from the factory 3-view in the Pilot Operating
Handbook, and the tools that turn it into a Microsoft Flight Simulator 2024 aircraft.

- [`model/`](model/README.md): the generator (`index.html`, Three.js) and `export-glb.mjs`, which exports the
  model as glTF.
- [`msfs/`](msfs/README.md): the MSFS 2024 build pipeline (`msfs/tools`, Blender 5.x + the MSFS 2024 SDK) and the
  development notes (`msfs/docs`).

Not included: the generated `.blend` / `.glb` files, build outputs and compiled packages, the POH and its
drawings, reference photos, and `msfs/tools/templates/nxcub_panel.xml` (copied from the sim's default NX Cub;
`make_panel_xml.py` reads it from there).
