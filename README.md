# Learn2Earn Life — Classroom Scene

Procedural Blender scene for the Learn2Earn Life classroom, exported as glTF
binary and viewable in Three.js.

```
build_classroom.py      procedural scene builder (bpy)
classroom.glb           exported scene (geometry + materials + lights + camera)
viewer/index.html       Three.js orbit-controls viewer (loads classroom.glb)
renders/                isometric preview renders, one per stage
assets/fonts/           Nunito ExtraBold, used for the wall logo
```

## Build

```bash
blender -b -noaudio -P build_classroom.py            # build + export + render
blender -b -noaudio -P build_classroom.py -- --no-render
```

Serve the viewer over HTTP (ES modules + `fetch` will not work from `file://`):

```bash
python3 -m http.server 8000     # then open http://localhost:8000/viewer/
```

## Conventions

Units are metres. Origin is the centre of the room floor. The spec's frame is

```
x  -> right          y -> up (height)          z -> toward the front/entrance
```

which maps onto Blender's X/Z/Y one-for-one, so `P(x, h, z)` in the script is the
identity — it exists only to make that mapping explicit at each call site.
Walls sit *outside* the 14 × 9 m clear interior, so the inner faces are at
x = ±7, z = ±4.5 and the room is exactly 14 × 9 × 3 m.

Every object is named per the spec and linked into a category collection:
`shell`, `desks`, `chairs`, `laptops`, `beanbags`, `pantry`, `lights`, `murals`,
`logo`, `people`. Stage 1 fills `shell`, `lights` and `logo`; the rest exist
empty and are populated in later stages.

Current budget: **268 mesh objects, 34,920 triangles** (limit 100,000). The glTF
carries 278 nodes but only 60 meshes — chairs, laptops, bottles and stools are
instanced, not duplicated.

## Runtime hooks

| Pattern | Status |
|---|---|
| `light_ceiling_*` | 4 ceiling spots + `light_ceiling_lobby` + `light_ceiling_alcove` |
| `light_track_*` | stage 3 (track fixtures) |
| `light_pendant_*` | stage 3 (rattan pendants) |
| `screen_laptop_*` | 49 displays, 3 shared emissive materials |
| `mural_*` | stage 3 |
| `logo_wall` | built |
| `bot_mentor` | stage 3 |

`light_ceiling_*` are **spot** lights deliberately: glTF has no area-light type,
and Blender's exporter silently drops area lights, writing empty nodes that would
leave the night-dimming hook carrying no light. The soft `light_fill_*` area
lights exist only for the Cycles render and are expected to vanish on export.

`screen_laptop_*` exists twice over: the display *objects* are named
`screen_laptop_01..49` and the *materials* are `screen_laptop_blue`,
`screen_laptop_warm` and `screen_laptop_dim`. The viewer keys off the material
names and raises `emissiveIntensity` for the night look.

## Stage 1 decisions and deviations from the spec

Positions are as given unless listed here.

1. **No ceiling plane.** The stage-1 list is shell only, and a solid ceiling
   would hide the interior from a high isometric camera. Track lights and
   pendants (spec §6) are stage 2, which will add the ceiling with them.

2. **Alcove reveal walls start at `z = -4.7`, not `z = -4.5`.** The spec gives the
   alcove as `x -0.8..1.8` extending back to `z = -5.5`. Built naively the reveal
   walls overlap the main back wall by 0.2 m, which z-fights. Pulling them back
   to the rear face of the main wall keeps the clear recess exactly 2.6 × 1.0 m
   with no coincident faces.

3. **`light_ceiling_alcove` added.** A 1 m-deep, 3 m-tall recess receives almost
   no light from a ceiling grid, so its reveals rendered as hard black vertical
   bars in the iso view. A dedicated spot keeps the recess legible. Stage 2's
   pendant cluster at `(0.0/0.5/0.9, -5.0)` can absorb this.

4. **Window count and placement.** The spec gives "windows near the back and the
   middle" for the left wall and simply "windows" for the right. Both walls get
   the same two: 2.0 m wide, z centres at `-2.7` (back) and `0.4` (middle),
   sill 1.0 m, head 2.5 m. The right wall's front third is left solid because the
   enclosed room occupies `z 2.5..4.5` there.

5. **Enclosed room height 2.7 m, with a roof cap.** The spec gives 1.7 × 2.0 m at
   `(6.1, 3.5)` and concrete walls but no height. 2.7 m keeps it a believable
   room without towering over the 3 m shell; the cap makes it read as enclosed
   from outside. Its `+x` and `+z` faces reuse the main right and front walls, so
   only two faces are built.

6. **Door is full height behind a 1 m cutaway.** The front wall is a 1 m
   cutaway so the camera can see in, but a 2.1 m entrance opening needs a real
   door. The door is glass (2.4 m leaves + transom to the 3 m line), so it reads
   as a portal without blocking the view. The low wall is split around the
   opening at `x -2.7..-0.6` and capped with a slightly darker section-cut band.

7. **Camera: orthographic, azimuth 28° toward +x, elevation 42°**, auto-fitted to
   the scene bounds. Orthographic rather than a long-lens perspective because the
   brief asks for isometric.

8. **Materials are flat PBR colours.** No procedural concrete/speckle textures,
   so the glTF round-trips exactly and the file stays small. Add image textures
   in stage 2 via the `mural_*` slots.

9. **Logo.** "Learn2earn" as a Blender text object converted to mesh, Nunito
   ExtraBold (rounded sans), normalised in the script to exactly 1.8 m wide ×
   0.05 m deep, centred at `(5.0, 1.9, -4.5)`, `#1E5EFF`, emission strength
   0.25. Named `logo_wall` and kept as a single swappable object. **No bevel:**
   a 6 mm bevel on that word costs 23k triangles (34k vs 11k) for a highlight the
   render cannot resolve, which alone was 97% of the stage-1 triangle budget.

## Stage 2: desks, chairs, laptops, bottles

57 chairs, 49 laptops, 57 bottles, 3 stools. Each of those four props is built
once as a mesh and then placed as instances — every `chair_NN` shares
`mesh_chair`, so the glb holds one chair mesh and 57 nodes.

Desks are not instanced: each has a different length and divider flag, so each
gets its own mesh. They are all authored in a canonical local frame (length
along local X, depth along local Z, user on the +Z side) and rotated 90° for the
`z`-axis desks, so one builder serves both orientations.

Positions moved off the spec values, and why:

| Item | Spec | Used | Reason |
|---|---|---|---|
| `desk_L1` | `(-4.4, -3.8)` | `z = -3.45` | At the spec value the rear chairs and the desk itself pass through the back wall at `z = -4.5`. |
| `desk_L2` | `(-4.6, -1.7)` | `z = -1.55` | Needs ~1.9 m to `desk_L1` so the two facing chair rows clear each other. |
| `desk_L3` | `(-4.6, 3.0)` | `x = -4.85` | 3.8 m long from the spec `x` overlapped the lobby's left glass wall at `x = -2.9` by 0.2 m. |
| `table_mid` | `(-1.4, -3.9)` | `z = -3.10` | 2.0 m deep from the spec `z` put 0.4 m of table inside the back wall. Also 3 chairs per side instead of 2-per-side-plus-ends: end chairs had no clearance to the wall. |
| `desk_R1..R4` | `z = -2.9` | `z = -2.60` | At the spec value the three bar-table stools landed inside `desk_R1`. The alcove is only 1 m deep and the bar table takes 0.6 m of it, so the stools have to sit in the room, and the row needed to move forward to make room. |
| `desk_R5` | `(3.5, 1.0)` | `x = 3.20` | Its right-hand chairs collided with `desk_R7`'s left-hand chairs. |
| `desk_R8` | `(0.8, 2.2)` | `x = 0.60` | Same conflict with `desk_R5` on the other side. |
| `bar_table` | `(0.6, -4.6)` | `z = -4.95` | Straddled the alcove mouth; moved fully inside the recess. |
| `desk_L3` | front-side chairs | front-side chairs | Kept as specified. |

Chair count is **57 + 3 stools = 60**, against the spec's "about 70". Seat counts
per desk were derived from desk length (roughly one seat per 1.1 m) rather than
guessed, which lands below the spec's ballpark. Say the word and I'll tighten
the spacing to add seats.

Screens use three shared emissive materials: blue and warm are lit, dim is off.
`desk_L2`'s three laptops are forced to the bright blue material, per spec.

**Known conflict for stage 3:** the spec's lounge A at `(-1.1, -2.3)` overlaps
`table_mid`'s seat area. Lounge A will need nudging when the beanbags go in.

## Notable implementation details

- `MeshBuilder` accumulates boxes and low-poly prisms with per-face material
  slots into one mesh datablock. Everything multi-part is built through it: a
  wall with window openings, a glazed screen, a chair with five castors. That
  single datablock is then instanced.
- `instance()` links a new object to an existing mesh. For laptop screens it also
  flips `material_slots[0].link` to `OBJECT`, which is how 49 displays share one
  mesh while each still gets its own `screen_laptop_*` material.
- Side walls are built as a sill band + head band + solid piers rather than by
  boolean-cutting holes: fewer triangles, no boolean artefacts, real openings.
- `aim_rotation()` writes the camera basis out by hand instead of using
  `Vector.to_track_quat`. That helper aligns its up axis to *world +Z* (Blender's
  up), but this scene is Y-up, so it rolls the camera 180° and renders the room
  upside down.
