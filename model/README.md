# Sling 4 TSi model

A 3D model of the Sling 4 TSi built from the factory 3-view in the Pilot Operating Handbook
(DC-POH-001-X-F-3.1, rev 3.1, pages 1-3 and 1-4). It measures 9.544 × 7.175 × 2.414 m, the
same as the POH's span, length and height.

| File | What it is |
| --- | --- |
| `index.html` | Interactive viewer (Three.js). Open in a browser. |
| `sling-tsi-high.blend` | **High detail**, about 954k triangles, mostly quads (469k quads, 17k triangles), 4096 px paint. Blender 5.0 or later. |
| `sling-tsi-high.glb` | The same high-detail model as glTF 2.0 (triangulated). |
| `sling-tsi.blend` | Standard detail, about 123k triangles, 2048 px paint. Blender 5.0 or later, textures packed in. |
| `sling-tsi.glb` | Standard detail as glTF 2.0. In Blender: File → Import → glTF 2.0. Also opens in most other 3D tools. |
| `export-glb.mjs` | Regenerates the `.glb` files from `index.html`: `node export-glb.mjs`, or `node export-glb.mjs --high` (needs Playwright). |

Triangles in the high-detail model, by part: fuselage 429k, wings 114k, wheel fairings 74k, doors 51k,
windscreen and windows 39k, tailplane 37k, tyres 37k, flaps 27k, spinner 26k, elevators 20k,
blades 18k, main gear legs 16k, fin 14k, ailerons 13k, rudder 11k, everything else about 28k.

In both model files, units are metres, the aircraft sits on the ground plane, and the nose points
along +X (Blender axes). It's exported with gear down, flaps up, doors shut and the propeller stopped.
Each moving part is its own object, with its origin on its hinge line:
`Aileron_L/R`, `Flap_L/R`, `Elevator_L/R`, `Rudder`, `Door_L/R` and `Propeller`. Rotate one about
the axis of its hinge to deflect it; the rudder and doors are hinged on slanted lines.

Window openings are cut with the alpha channel of the fuselage and door paint (`Paint_livery`,
alpha clip). The glass is a separate shell (`Glass`, alpha blend).

The POH doesn't publish airfoil sections, so the wing and tail use NACA profiles as stand-ins.
The inlets, exhaust and antenna are placed by eye from the drawing.
