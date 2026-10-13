"""
Learn2Earn Life - Classroom Scene Builder
=========================================

Procedurally builds the classroom described in the scene spec and exports it as
``classroom.glb``.

    blender -b -noaudio -P build_classroom.py

Outputs
-------
    classroom.glb              glTF binary of the scene (lights + camera included)
    renders/stage1_shell.png   isometric preview render

Coordinate conventions
----------------------
The spec is written in a "room" frame:

    x   ->  right              (+x right, -x left)
    z   ->  toward the FRONT   (-z toward the back wall, +z toward the entrance)
    y   ->  up                 (implicit height in the spec)

Blender's frame already matches that mapping (Blender X/Y/Z = spec x/z-depth/up
once you read Blender's Y as "height"), so the conversion is the identity.
``P()`` is used everywhere to make the mapping explicit at each call site.

    spec (x, height, depth)  ->  blender (x, y, z)

Origin = centre of the room floor. Units = metres.

Stage 1 (this file) covers: floor, walls, back recess alcove, windows, the glass
entrance + lobby, and the small enclosed toilet room, plus the ``logo_wall``.
Desks, chairs, laptops, beanbags, pantry, ceiling fixtures, people and the mentor
bot are deliberately left for later stages.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
GLB_PATH = os.path.join(HERE, "classroom.glb")
RENDER_DIR = os.path.join(HERE, "renders")
RENDER_PATH = os.path.join(RENDER_DIR, "classroom_iso.png")
FONT_PATH = os.path.join(HERE, "assets", "fonts", "Nunito-ExtraBold.ttf")

# ---------------------------------------------------------------------------
# Room dimensions (metres)
# ---------------------------------------------------------------------------

ROOM_W = 14.0           # x: -7 .. +7   (interior clear width)
ROOM_D = 9.0            # z: -4.5 .. +4.5 (interior clear depth)
ROOM_H = 3.0            # interior clear height
WALL_T = 0.20           # wall thickness

X_L, X_R = -7.0, 7.0    # inner faces of the side walls
Z_B, Z_F = -4.5, 4.5    # inner faces of the back / front walls
X_L_OUT, X_R_OUT = X_L - WALL_T, X_R + WALL_T
Z_B_OUT, Z_F_OUT = Z_B - WALL_T, Z_F + WALL_T

# Back-wall recess (alcove).
REC_X0, REC_X1 = -0.8, 1.8      # alcove mouth / clear width
REC_Z0, REC_Z1 = -5.5, -4.5     # alcove back face .. wall inner face
REC_T = 0.20                    # alcove wall thickness

# Front-wall cutaway height (deliberately low so the iso camera can see in).
CUTAWAY_H = 1.0

# Window band.
WIN_W = 2.0         # opening width, measured along the wall
WIN_SILL = 1.0      # sill height
WIN_HEAD = 2.5      # head height
WIN_Z_BACK = -2.7   # window centre, "near the back"
WIN_Z_MID = 0.4     # window centre, "the middle"

# Glass lobby (vestibule) behind the entrance.
LOB_X0, LOB_X1 = -2.9, -0.3
LOB_Z0, LOB_Z1 = -1.4, 4.5
LOB_H = 2.6
GLASS_T = 0.03

# Entrance opening in the front wall.
DOOR_X0, DOOR_X1 = -2.7, -0.6
DOOR_H = 2.4        # leaf height
DOOR_HEAD_H = 3.0   # top of the glazed screen

# Enclosed toilet room, front-right corner.
WC_CX, WC_CZ = 6.1, 3.5
WC_W, WC_D = 1.7, 2.0
WC_H = 2.7
WC_T = 0.12
WC_DOOR_W = 0.90
WC_DOOR_H = 2.05

# Logo.
LOGO_X, LOGO_Y, LOGO_Z = 5.0, 1.9, Z_B
LOGO_W = 1.8        # target rendered width
LOGO_D = 0.05       # target extrusion depth
BRAND_BLUE = (0.118, 0.369, 1.0, 1.0)   # #1E5EFF in linear-ish sRGB

COLLECTIONS = [
    "shell", "desks", "chairs", "laptops", "beanbags",
    "pantry", "lights", "murals", "logo", "people",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def P(x, h, z):
    """Spec coords (right, up, depth) -> Blender coords."""
    return Vector((x, h, z))


def srgb(hex_str, alpha=1.0):
    """#RRGGBB -> linear RGBA tuple (Blender wants linear, glTF wants sRGB)."""
    h = hex_str.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    out.append(alpha)
    return tuple(out)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    for name in COLLECTIONS:
        bpy.data.collections.new(name)
        scene.collection.children.link(bpy.data.collections[name])
    return scene


def coll(name):
    return bpy.data.collections[name]


def set_input(node, names, value):
    """Blender 4.x renamed several Principled sockets; try them in order."""
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def mat(name, hex_color, roughness=0.7, metallic=0.0, alpha=1.0,
        emission=None, emission_strength=0.0, transmission=0.0, ior=1.45):
    """Principled material. Kept as flat PBR so it survives the glTF export."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    col = srgb(hex_color, alpha)
    set_input(bsdf, ["Base Color"], col)
    set_input(bsdf, ["Roughness"], roughness)
    set_input(bsdf, ["Metallic"], metallic)
    set_input(bsdf, ["Alpha"], alpha)
    set_input(bsdf, ["IOR"], ior)
    if transmission > 0.0:
        set_input(bsdf, ["Transmission Weight", "Transmission"], transmission)
    if emission is not None:
        set_input(bsdf, ["Emission Color", "Emission"], srgb(emission))
        set_input(bsdf, ["Emission Strength"], emission_strength)
    if alpha < 1.0 or transmission > 0.0:
        # Eevee / viewport fallback; Cycles uses the real transmission above.
        m.blend_method = "BLEND"
    m.diffuse_color = col
    return m


_CUBE_FACES = [
    (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]


def _box_data(size, offset):
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    ox, oy, oz = offset
    v = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
         (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    return [(x + ox, y + oy, z + oz) for x, y, z in v]


class MeshBuilder:
    """Accumulates boxes and low-poly cylinders into one multi-material mesh.

    Every part of a prop (chair frame, seat mesh, castors) is appended here with
    a material slot index, so a whole prop collapses into a single datablock that
    can then be instanced many times.
    """

    def __init__(self):
        self.verts = []
        self.faces = []
        self.slots = []

    def add_box(self, size, center, slot=0, rot=None):
        base = len(self.verts)
        c = Vector(center)
        for v in _box_data(size, (0, 0, 0)):
            p = rot @ Vector(v) if rot is not None else Vector(v)
            self.verts.append((p.x + c.x, p.y + c.y, p.z + c.z))
        for f in _CUBE_FACES:
            self.faces.append(tuple(base + i for i in f))
            self.slots.append(slot)
        return self

    def add_cyl(self, radius, depth, center, axis="y", segments=8, slot=0, rot=None):
        """Prism whose length runs along ``axis`` ("y" = vertical in this scene)."""
        half = depth / 2.0
        base = len(self.verts)
        c = Vector(center)
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            u, v = radius * math.cos(a), radius * math.sin(a)
            for w in (-half, half):
                if axis == "y":
                    p = Vector((u, w, v))
                elif axis == "x":
                    p = Vector((w, u, v))
                else:
                    p = Vector((u, v, w))
                if rot is not None:
                    p = rot @ p
                self.verts.append((p.x + c.x, p.y + c.y, p.z + c.z))
        for i in range(segments):
            j = (i + 1) % segments
            self.faces.append((base + 2 * i, base + 2 * j, base + 2 * j + 1,
                               base + 2 * i + 1))
            self.slots.append(slot)
        self.faces.append(tuple(base + 2 * i for i in range(segments)))
        self.slots.append(slot)
        self.faces.append(tuple(base + 2 * i + 1 for i in range(segments - 1, -1, -1)))
        self.slots.append(slot)
        return self

    def to_mesh(self, name, materials, origin=(0.0, 0.0, 0.0)):
        """Build the mesh, shifted so ``origin`` becomes the object pivot."""
        o = Vector(origin)
        verts = [(v[0] - o.x, v[1] - o.y, v[2] - o.z) for v in self.verts]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], self.faces)
        mesh.update()
        for m in materials:
            mesh.materials.append(m)
        if materials:
            for poly, slot in zip(mesh.polygons, self.slots):
                poly.material_index = slot
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        return mesh


def boxes(name, specs, material=None, collection="shell", origin_at_center=True):
    """Build one object from a list of ``(size, world_center)`` boxes.

    ``specs`` are absolute spec-space centres; the object origin is moved to the
    geometry centroid so the exported glb has a sane pivot per object.
    """
    mb = MeshBuilder()
    for spec in specs:
        if len(spec) == 3:
            size, center, slot = spec[0], spec[1], spec[2]
        else:
            size, center, slot = spec[0], spec[1], 0
        mb.add_box(size, center, slot)

    pivot = Vector((0, 0, 0))
    if origin_at_center and mb.verts:
        pivot = sum((Vector(v) for v in mb.verts), Vector((0, 0, 0))) / len(mb.verts)

    mesh = mb.to_mesh(name, [material] if material else [], origin=pivot)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = pivot
    coll(collection).objects.link(obj)
    return obj


def instance(name, mesh, location, rot_y=0.0, collection="shell", material=None):
    """Create an object that shares ``mesh`` with every other instance of it."""
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = (0.0, rot_y, 0.0)
    if material is not None and len(mesh.materials):
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
    coll(collection).objects.link(obj)
    return obj


def box(name, size, center, material=None, collection="shell"):
    return boxes(name, [(size, center)], material, collection)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def build_materials():
    return {
        "floor": mat("mat_floor", "#C9CBCE", roughness=0.5),
        "floor_recess": mat("mat_floor_recess", "#BFC1C4", roughness=0.58),
        "concrete": mat("mat_concrete_wall", "#BAB7B1", roughness=0.85),
        "concrete_cut": mat("mat_concrete_cut", "#A8A59F", roughness=0.9),
        "concrete_dark": mat("mat_concrete_dark", "#9C9993", roughness=0.9),
        "glass": mat("mat_glass", "#DCE9EE", roughness=0.03, alpha=0.18,
                     transmission=1.0, ior=1.45),
        "frame_dark": mat("mat_frame_dark", "#2B2F33", roughness=0.42, metallic=0.65),
        "frame_light": mat("mat_frame_light", "#8E9296", roughness=0.4, metallic=0.5),
        "sill": mat("mat_sill", "#C6C3BD", roughness=0.7),
        "wood_door": mat("mat_wood_door", "#8A5A2B", roughness=0.48),
        "logo": mat("mat_logo_blue", "#1E5EFF", roughness=0.35,
                    emission="#1E5EFF", emission_strength=0.25),

        # --- stage 2: furniture -------------------------------------------
        "desk_top": mat("mat_desk_top_oak", "#C9A97C", roughness=0.55),
        "desk_leg": mat("mat_desk_leg_steel", "#7B8189", roughness=0.38, metallic=0.7),
        "divider": mat("mat_desk_divider_grey", "#9AA1A8", roughness=0.62),
        "chair_black": mat("mat_chair_black", "#22252A", roughness=0.48),
        "chair_mesh": mat("mat_chair_mesh", "#3A3F46", roughness=0.8),
        "chair_metal": mat("mat_chair_metal", "#565C63", roughness=0.35, metallic=0.75),
        "laptop_body": mat("mat_laptop_body", "#2C3036", roughness=0.42, metallic=0.25),
        "bottle": mat("mat_bottle_water", "#BEE2F2", roughness=0.12, alpha=0.42,
                      transmission=0.85, ior=1.33),
        "bottle_cap": mat("mat_bottle_cap", "#2C3036", roughness=0.45),

        # Runtime hook: every laptop display uses one of these three. The viewer
        # finds them by name and raises emissiveIntensity for the night look.
        "screen_blue": mat("screen_laptop_blue", "#8FD4FF", roughness=0.18,
                           emission="#7FC8FF", emission_strength=2.2),
        "screen_warm": mat("screen_laptop_warm", "#FFE7C4", roughness=0.18,
                           emission="#FFD9A0", emission_strength=1.8),
        "screen_dim": mat("screen_laptop_dim", "#2A3138", roughness=0.2,
                          emission="#33404C", emission_strength=0.25),
    }


# ---------------------------------------------------------------------------
# 1. Floor
# ---------------------------------------------------------------------------

def build_floor(M):
    box("floor_main", (ROOM_W, 0.2, ROOM_D), P(0, -0.1, 0), M["floor"])
    # The alcove has its own floor slab, flush with floor_main.
    box("floor_recess", (REC_X1 - REC_X0, 0.2, REC_Z1 - REC_Z0),
        P((REC_X0 + REC_X1) / 2, -0.1, (REC_Z0 + REC_Z1) / 2), M["floor_recess"])


# ---------------------------------------------------------------------------
# 2. Walls + back recess
# ---------------------------------------------------------------------------

def build_back_wall(M):
    """Back wall at z = -4.5, split around the alcove mouth."""
    # Left of the alcove and right of the alcove, full height.
    box("wall_back_left", (REC_X0 - X_L_OUT, ROOM_H, WALL_T),
        P((X_L_OUT + REC_X0) / 2, ROOM_H / 2, Z_B - WALL_T / 2), M["concrete"])
    box("wall_back_right", (X_R_OUT - REC_X1, ROOM_H, WALL_T),
        P((REC_X1 + X_R_OUT) / 2, ROOM_H / 2, Z_B - WALL_T / 2), M["concrete"])

    # Alcove reveal walls + alcove back wall. The reveals start at the BACK of the
    # main wall (z = Z_B - WALL_T) rather than its front face, so they butt against
    # the wall segments above instead of overlapping them (which z-fought).
    reveal_z1 = Z_B - WALL_T          # -4.7
    box("wall_recess_side_left", (REC_T, ROOM_H, reveal_z1 - REC_Z0),
        P(REC_X0 - REC_T / 2, ROOM_H / 2, (REC_Z0 + reveal_z1) / 2), M["concrete"])
    box("wall_recess_side_right", (REC_T, ROOM_H, reveal_z1 - REC_Z0),
        P(REC_X1 + REC_T / 2, ROOM_H / 2, (REC_Z0 + reveal_z1) / 2), M["concrete"])
    box("wall_recess_back", (REC_X1 - REC_X0 + 2 * REC_T, ROOM_H, REC_T),
        P((REC_X0 + REC_X1) / 2, ROOM_H / 2, REC_Z0 - REC_T / 2), M["concrete"])


def _side_wall_with_windows(side, M):
    """One side wall as a single mesh: sill band + head band + solid piers."""
    is_left = side == "left"
    x_in = X_L if is_left else X_R
    x_out = X_L_OUT if is_left else X_R_OUT
    xa, xb = min(x_out, x_in), max(x_out, x_in)
    xc = (xa + xb) / 2.0

    z0, z1 = Z_B_OUT, Z_F_OUT
    zc = (z0 + z1) / 2.0
    depth = z1 - z0
    wt = xb - xa

    # Two openings; the pier between them and the two end piers stay solid.
    wins = [(WIN_Z_BACK, WIN_Z_MID)]
    edges = [z0]
    piers = []
    for wz in wins[0]:
        piers.append((wz - WIN_W / 2, wz + WIN_W / 2))
        edges.append(wz - WIN_W / 2)
        edges.append(wz + WIN_W / 2)
    edges.append(z1)

    specs = [
        # sill band, full length
        ((wt, WIN_SILL, depth), P(xc, WIN_SILL / 2, zc)),
        # head band, full length
        ((wt, ROOM_H - WIN_HEAD, depth), P(xc, (ROOM_H + WIN_HEAD) / 2, zc)),
    ]
    # solid piers between sill and head bands
    for i in range(0, len(edges), 2):
        a, b = edges[i], edges[i + 1]
        if b - a > 1e-6:
            specs.append(((wt, WIN_HEAD - WIN_SILL, b - a),
                          P(xc, (WIN_SILL + WIN_HEAD) / 2, (a + b) / 2)))

    boxes("wall_%s" % side, specs, M["concrete"])


def build_side_walls(M):
    _side_wall_with_windows("left", M)
    _side_wall_with_windows("right", M)


def build_front_wall(M):
    """Low concrete cutaway wall at z = +4.5, split around the entrance."""
    h = CUTAWAY_H
    specs = []
    for a, b in ((X_L_OUT, DOOR_X0), (DOOR_X1, X_R_OUT)):
        if b - a > 1e-6:
            specs.append(((b - a, h, WALL_T), P((a + b) / 2, h / 2, Z_F + WALL_T / 2)))
    boxes("wall_front", specs, M["concrete"])

    # A slightly darker cap on the cut edge sells the "section cut" read.
    cap = []
    for a, b in ((X_L_OUT, DOOR_X0), (DOOR_X1, X_R_OUT)):
        if b - a > 1e-6:
            cap.append(((b - a, 0.04, WALL_T + 0.02),
                        P((a + b) / 2, h + 0.02, Z_F + WALL_T / 2)))
    if cap:
        boxes("wall_front_cut_edge", cap, M["concrete_cut"])


# ---------------------------------------------------------------------------
# 3. Windows
# ---------------------------------------------------------------------------

def _build_window(name, xa, xb, z_center, M):
    """Window assembly in a side wall whose x extent is [xa, xb]."""
    is_left = xa < 0
    # Inward direction: left wall faces +x, right wall faces -x.
    inward = 1.0 if is_left else -1.0
    xc = (xa + xb) / 2.0
    wt = xb - xa

    z0, z1 = z_center - WIN_W / 2, z_center + WIN_W / 2
    y0, y1 = WIN_SILL, WIN_HEAD
    height = y1 - y0
    zc, yc = (z0 + z1) / 2, (y0 + y1) / 2

    bar = 0.07          # frame face width
    fdepth = 0.09      # frame depth

    # Frame sits toward the outer half of the wall.
    fx0 = xa + (wt - fdepth) if is_left else xa + 0.02
    fx1 = fx0 + fdepth
    fxc = (fx0 + fx1) / 2

    frame = [
        ((fdepth, bar, WIN_W), P(fxc, y0 + bar / 2, zc)),
        ((fdepth, bar, WIN_W), P(fxc, y1 - bar / 2, zc)),
        ((fdepth, height, bar), P(fxc, yc, z0 + bar / 2)),
        ((fdepth, height, bar), P(fxc, yc, z1 - bar / 2)),
        ((fdepth, height, 0.05), P(fxc, yc, zc)),          # centre mullion
    ]
    boxes("%s_frame" % name, frame, M["frame_dark"])

    box("%s_glass" % name, (GLASS_T, height - 2 * bar, WIN_W - 2 * bar),
        P(xc, yc, zc), M["glass"])

    # Interior sill ledge.
    sill_t = 0.04
    boxes("%s_sill" % name,
          [((wt, sill_t, WIN_W + 0.16), P(xc, y0 - sill_t / 2, zc))],
          M["sill"])


def build_windows(M):
    _build_window("window_left_01", X_L_OUT, X_L, WIN_Z_BACK, M)
    _build_window("window_left_02", X_L_OUT, X_L, WIN_Z_MID, M)
    _build_window("window_right_01", X_R_OUT, X_R, WIN_Z_BACK, M)
    _build_window("window_right_02", X_R_OUT, X_R, WIN_Z_MID, M)


# ---------------------------------------------------------------------------
# 4. Glass lobby + entrance
# ---------------------------------------------------------------------------

def _glazed_screen(name, axis, fixed, a0, a1, height, M, mullions):
    """Framed glass screen.

    ``axis`` is 'x' when the screen lies in a plane of constant x (so it runs
    along z) and 'z' when it lies in a plane of constant z (runs along x).
    ``fixed`` is the plane coordinate; ``a0..a1`` the span along the run axis.
    """
    t = 0.08          # frame section
    g = GLASS_T

    def rect(u_c, h_c, du, dh, depth=None):
        """depth=None -> glass sheet; otherwise a frame member of that depth."""
        d = depth if depth is not None else g
        if axis == "x":
            return ((d, dh, du), P(fixed, h_c, u_c))
        return ((du, dh, d), P(u_c, h_c, fixed))

    ac = (a0 + a1) / 2.0
    span = a1 - a0
    frame = [
        rect(ac, t / 2, span, t, depth=t),                 # bottom rail
        rect(ac, height - t / 2, span, t, depth=t),         # top rail
        rect(a0 + t / 2, height / 2, t, height, depth=t),   # start post
        rect(a1 - t / 2, height / 2, t, height, depth=t),   # end post
    ]
    for k in range(1, mullions + 1):
        u = a0 + span * k / (mullions + 1)
        frame.append(rect(u, height / 2, t, height, depth=t))
    boxes("%s_frame" % name, frame, M["frame_dark"])

    # Glass sits in the middle of the frame, inset by the frame section.
    boxes("%s_glass" % name,
          [rect(ac, height / 2, span - 2 * t, height - 2 * t)],
          M["glass"])


def build_lobby(M):
    _glazed_screen("lobby_glass_left", "x", LOB_X0, LOB_Z0, LOB_Z1, LOB_H, M, 2)
    _glazed_screen("lobby_glass_right", "x", LOB_X1, LOB_Z0, LOB_Z1, LOB_H, M, 2)
    _glazed_screen("lobby_glass_back", "z", LOB_Z0, LOB_X0, LOB_X1, LOB_H, M, 1)


def build_entrance(M):
    """Glass double door in the front wall opening, plus a glazed transom."""
    t = 0.08
    zc = Z_F + WALL_T / 2
    span = DOOR_X1 - DOOR_X0
    xc = (DOOR_X0 + DOOR_X1) / 2

    # Screen frame: jambs, meeting stile, mid rail, head, transom head.
    frame = [
        ((t, DOOR_HEAD_H, WALL_T), P(DOOR_X0 + t / 2, DOOR_HEAD_H / 2, zc)),
        ((t, DOOR_HEAD_H, WALL_T), P(DOOR_X1 - t / 2, DOOR_HEAD_H / 2, zc)),
        ((t, DOOR_HEAD_H, WALL_T), P(xc, DOOR_HEAD_H / 2, zc)),
        ((span, t, WALL_T), P(xc, DOOR_H + t / 2, zc)),          # door head rail
        ((span, t, WALL_T), P(xc, DOOR_HEAD_H - t / 2, zc)),     # screen head
        # glass-to-floor rails on each leaf
        ((span / 2 - t, 0.12, WALL_T), P(DOOR_X0 + span / 4, 0.06, zc)),
        ((span / 2 - t, 0.12, WALL_T), P(DOOR_X1 - span / 4, 0.06, zc)),
    ]
    boxes("door_frame", frame, M["frame_dark"])

    g = GLASS_T
    leaf_w = span / 2 - t
    boxes("door_leaf_left",
          [((leaf_w, DOOR_H - 0.2, g), P(DOOR_X0 + t + leaf_w / 2, DOOR_H / 2, zc))],
          M["glass"])
    boxes("door_leaf_right",
          [((leaf_w, DOOR_H - 0.2, g), P(DOOR_X1 - t - leaf_w / 2, DOOR_H / 2, zc))],
          M["glass"])
    # Transom above the doors, up to the 3 m line.
    boxes("door_transom",
          [((span - 2 * t, DOOR_HEAD_H - DOOR_H - t, g),
            P(xc, (DOOR_HEAD_H + DOOR_H) / 2, zc))],
          M["glass"])

    # Pull handles either side of the meeting stile.
    hx = 0.10
    boxes("door_handle_left",
          [((0.05, 1.05, 0.05), P(xc - hx - 0.06, 1.05, zc + WALL_T / 2 + 0.05)),
           ((0.05, 0.05, 0.12), P(xc - hx - 0.06, 1.58, zc + WALL_T / 2))],
          M["frame_light"])
    boxes("door_handle_right",
          [((0.05, 1.05, 0.05), P(xc + hx + 0.06, 1.05, zc + WALL_T / 2 + 0.05)),
           ((0.05, 0.05, 0.12), P(xc + hx + 0.06, 1.58, zc + WALL_T / 2))],
          M["frame_light"])


# ---------------------------------------------------------------------------
# 5. Enclosed toilet room
# ---------------------------------------------------------------------------

def build_wc_room(M):
    x0, x1 = WC_CX - WC_W / 2, WC_CX + WC_W / 2      # 5.25 .. 6.95
    z0, z1 = WC_CZ - WC_D / 2, WC_CZ + WC_D / 2      # 2.50 .. 4.50

    # The room re-uses the main right wall (x >= 7.0) and front wall (z >= 4.5),
    # so only two faces need building: the -x face and the -z face.
    dw0, dw1 = WC_CZ - WC_DOOR_W / 2, WC_CZ + WC_DOOR_W / 2

    specs = [
        ((WC_T, WC_H, dw0 - z0), P(x0 + WC_T / 2, WC_H / 2, (z0 + dw0) / 2)),
        ((WC_T, WC_H, z1 - dw1), P(x0 + WC_T / 2, WC_H / 2, (dw1 + z1) / 2)),
        ((WC_T, WC_H - WC_DOOR_H, WC_DOOR_W), P(x0 + WC_T / 2, WC_DOOR_H + (WC_H - WC_DOOR_H) / 2, WC_CZ)),
        ((x1 - x0, WC_H, WC_T), P((x0 + x1) / 2, WC_H / 2, z0 + WC_T / 2)),
    ]
    boxes("room_wc_walls", specs, M["concrete_dark"])

    # Flat roof cap so it reads as a closed volume from the iso camera.
    boxes("room_wc_ceiling",
          [((x1 - x0 + 0.08, 0.10, z1 - z0 + 0.08), P((x0 + x1) / 2, WC_H + 0.05, (z0 + z1) / 2))],
          M["concrete_dark"])

    # Wooden door leaf, recessed slightly into its opening.
    boxes("room_wc_door",
          [((0.06, WC_DOOR_H - 0.04, WC_DOOR_W - 0.04),
            P(x0 + WC_T / 2, (WC_DOOR_H - 0.04) / 2, WC_CZ))],
          M["wood_door"])

    # Casing around the opening.
    c = 0.06
    boxes("room_wc_door_frame",
          [((WC_T + 0.04, c, c), P(x0 + WC_T / 2, WC_DOOR_H + c / 2, dw0 - c / 2)),
           ((WC_T + 0.04, c, c), P(x0 + WC_T / 2, WC_DOOR_H + c / 2, dw1 + c / 2)),
           ((WC_T + 0.04, c, WC_DOOR_W + 2 * c), P(x0 + WC_T / 2, WC_DOOR_H + c, WC_CZ))],
          M["frame_light"])


# ---------------------------------------------------------------------------
# 6. Wall logo - extruded 3D text
# ---------------------------------------------------------------------------

def build_logo(M):
    """'Learn2earn' as extruded, bevelled, slightly emissive 3D text.

    The font curve lives in its local XY plane with local +Z as the extrusion
    direction, which maps straight onto the back wall (world XY) without any
    rotation. Converted to mesh so the glTF export carries real geometry.
    """
    curve = bpy.data.curves.new("logo_wall_crv", type="FONT")
    curve.body = "Learn2earn"
    if os.path.exists(FONT_PATH):
        curve.font = bpy.data.fonts.load(FONT_PATH)
    curve.size = 1.0
    curve.extrude = 0.025          # curve extrude is symmetric -> 0.05 total
    # No bevel: a 6 mm bevel on this word costs 23k triangles (34k vs 11k) for a
    # highlight the render cannot resolve at this scale. The extrusion still reads.
    curve.bevel_depth = 0.0
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"

    tmp = bpy.data.objects.new("logo_wall_crv", curve)
    bpy.context.scene.collection.objects.link(tmp)
    bpy.context.view_layer.update()

    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.curves.remove(curve)
    mesh.name = "logo_wall"

    # Normalise: centre XY on the origin, sit the back face on z = 0.
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    sx = LOGO_W / max(1e-6, max(xs) - min(xs))
    sz = LOGO_D / max(1e-6, max(zs) - min(zs))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    z0 = min(zs)
    for v in mesh.vertices:
        v.co.x = (v.co.x - cx) * sx
        v.co.y = (v.co.y - cy)
        v.co.z = (v.co.z - z0) * sz
    mesh.update()

    obj = bpy.data.objects.new("logo_wall", mesh)
    obj.location = P(LOGO_X, LOGO_Y, LOGO_Z)
    mesh.materials.append(M["logo"])
    coll("logo").objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# 6. Stage 2: desks, chairs, laptops, water bottles
# ---------------------------------------------------------------------------

DESK_TOP_Y = 0.74        # working surface height
DESK_TOP_T = 0.04
CHAIR_OFF = 0.64         # chair centre from the desk centre
CHAIR_FOOT = 0.27        # chair base radius (star base + castors)
STOOL_H = 0.66

# name, centre x, centre z, axis, along, across, seats(+side,-side), laptops, flags
# ``axis`` is the desk's long direction; the mesh is always authored with its
# length along local X and rotated into place, so one builder serves both.
DESKS = [
    ("desk_L1",   -4.40, -3.45, "x", 3.30, 0.80, (3, 3), 5, ""),
    ("desk_L2",   -4.60, -1.55, "x", 3.50, 0.80, (3, 3), 3, "glow"),
    ("desk_L3",   -4.85,  2.90, "x", 3.80, 0.80, (0, 4), 2, ""),
    ("table_mid", -1.40, -3.10, "z", 2.00, 0.90, (3, 3), 4, ""),
    ("desk_R1",    0.45, -2.60, "z", 2.70, 0.90, (2, 2), 4, ""),
    ("desk_R2",    1.90, -2.60, "z", 2.70, 0.90, (2, 2), 4, "divider"),
    ("desk_R3",    3.50, -2.60, "z", 2.70, 0.90, (2, 2), 4, "divider"),
    ("desk_R4",    5.20, -2.60, "z", 2.70, 0.90, (2, 2), 4, "divider"),
    ("desk_R5",    3.20,  1.00, "x", 3.00, 0.80, (3, 3), 6, "divider"),
    ("desk_R6",    3.60,  3.00, "x", 3.00, 0.80, (0, 3), 3, "divider"),
    ("desk_R7",    5.75,  0.60, "z", 2.20, 0.90, (2, 2), 4, "divider"),
    ("desk_R8",    0.60,  2.20, "z", 3.00, 0.90, (3, 3), 6, "divider"),
]

BAR_TABLE = (0.60, -4.95, 2.20, 0.60)   # x, z, along, across - inside the alcove


_TILT = Euler((math.radians(-15), 0.0, 0.0)).to_matrix()   # laptop lid, leaning back
_UP = _TILT @ Vector((0, 1, 0))
_NORMAL = _TILT @ Vector((0, 0, 1))                      # lid face, toward the user
_HINGE = Vector((0.0, 0.018, -0.105))                    # top-back edge of the base


def _lid_centre():
    return _HINGE + _UP * 0.1025 + _NORMAL * 0.007


def _chair_mesh(M):
    """Black mesh office chair: 5-star base with castors, gas column, seat, mesh back."""
    mb = MeshBuilder()
    black, mesh_f, metal = 0, 1, 2

    for i in range(5):
        a = 2.0 * math.pi * i / 5.0 + math.radians(18)
        rot = Euler((0.0, -a, 0.0)).to_matrix()
        spoke = Vector((math.cos(a), 0.0, math.sin(a)))
        mb.add_box((0.30, 0.045, 0.075), spoke * 0.16 + Vector((0, 0.055, 0)),
                   slot=black, rot=rot)
        mb.add_cyl(0.042, 0.034, spoke * 0.295 + Vector((0, 0.042, 0)),
                   axis="x", segments=6, slot=metal, rot=rot)

    mb.add_cyl(0.048, 0.10, (0, 0.10, 0), axis="y", segments=8, slot=black)
    mb.add_cyl(0.032, 0.30, (0, 0.27, 0), axis="y", segments=6, slot=metal)

    mb.add_box((0.44, 0.075, 0.42), (0, 0.455, 0.01), slot=mesh_f)
    mb.add_box((0.42, 0.03, 0.40), (0, 0.415, 0.01), slot=black)   # seat pan
    mb.add_box((0.07, 0.20, 0.06), (0, 0.56, -0.18), slot=black)   # back stem
    mb.add_box((0.40, 0.42, 0.035), (0, 0.78, -0.20), slot=mesh_f)  # mesh back
    for sx in (-1, 1):                                            # back frame rails
        mb.add_box((0.030, 0.44, 0.05), (sx * 0.195, 0.78, -0.20), slot=black)

    return mb.to_mesh("mesh_chair", [M["chair_black"], M["chair_mesh"], M["chair_metal"]])


def _laptop_mesh(M):
    """Laptop base + tilted lid. Local frame: screen faces +Z, base sits on y = 0."""
    mb = MeshBuilder()
    mb.add_box((0.32, 0.018, 0.22), (0, 0.009, 0), slot=0)
    mb.add_box((0.30, 0.010, 0.13), (0, 0.020, 0.03), slot=0)     # trackpad hint
    mb.add_box((0.32, 0.205, 0.014), _lid_centre(), slot=0, rot=_TILT)
    return mb.to_mesh("mesh_laptop", [M["laptop_body"]])


def _screen_mesh(M):
    """Emissive display panel only, so it can carry its own screen_laptop_* material.

    Sits just proud of the lid: the lid box is 0.014 thick centred on
    ``_lid_centre()``, so its front face is at ``_NORMAL * 0.007`` from there and
    the 0.004-thick panel has to start beyond that, not inside it.
    """
    mb = MeshBuilder()
    mb.add_box((0.285, 0.175, 0.004), _lid_centre() + _NORMAL * 0.009, slot=0, rot=_TILT)
    return mb.to_mesh("mesh_laptop_screen", [M["screen_blue"]])


def _bottle_mesh(M):
    mb = MeshBuilder()
    mb.add_cyl(0.036, 0.215, (0, 0.1075, 0), axis="y", segments=8, slot=0)
    mb.add_cyl(0.020, 0.030, (0, 0.230, 0), axis="y", segments=6, slot=1)
    return mb.to_mesh("mesh_bottle", [M["bottle"], M["bottle_cap"]])


def _stool_mesh(M):
    mb = MeshBuilder()
    mb.add_cyl(0.17, 0.045, (0, STOOL_H, 0), axis="y", segments=10, slot=0)
    mb.add_cyl(0.145, 0.02, (0, STOOL_H + 0.032, 0), axis="y", segments=10, slot=1)
    mb.add_cyl(0.030, STOOL_H - 0.02, (0, (STOOL_H - 0.02) / 2, 0), axis="y",
               segments=6, slot=1)
    mb.add_cyl(0.19, 0.03, (0, 0.015, 0), axis="y", segments=10, slot=1)
    return mb.to_mesh("mesh_stool", [M["desk_top"], M["desk_leg"]])


def _desk_mesh(name, along, across, divider, M):
    """Desk authored in local space: length along X, depth along Z, front at +Z."""
    mb = MeshBuilder()
    oak, steel, grey, black = 0, 1, 2, 3
    leg_h = DESK_TOP_Y - DESK_TOP_T

    mb.add_box((along, DESK_TOP_T, across), (0, DESK_TOP_Y - DESK_TOP_T / 2, 0), slot=oak)
    mb.add_box((along - 0.04, 0.05, across - 0.04),
               (0, leg_h - 0.09, 0), slot=black)          # apron under the top

    xs = [-(along / 2 - 0.12), along / 2 - 0.12]
    if along > 2.5:
        xs.append(0.0)
    for x in xs:
        for z in (-(across / 2 - 0.10), across / 2 - 0.10):
            mb.add_box((0.05, leg_h, 0.05), (x, leg_h / 2, z), slot=steel)
        mb.add_box((0.06, 0.035, across - 0.20), (x, 0.018, 0), slot=steel)

    if divider:
        mb.add_box((along - 0.08, 0.40, 0.028), (0, DESK_TOP_Y + 0.20, 0), slot=grey)
        mb.add_box((along - 0.06, 0.028, 0.045), (0, DESK_TOP_Y + 0.414, 0), slot=black)
    return mb.to_mesh("mesh_%s" % name,
                      [M["desk_top"], M["desk_leg"], M["divider"], M["chair_black"]])


def _seat_offsets(n, length):
    """Evenly spaced positions along a desk's length for ``n`` seats."""
    if n <= 0:
        return []
    if n == 1:
        return [0.0]
    step = length / n
    return [-(length / 2) + step * (i + 0.5) for i in range(n)]


def build_furniture(M):
    """Desks, chairs, laptops and water bottles.

    Chair / laptop / screen / bottle meshes are built once and then instanced:
    every placement is a new object sharing one mesh datablock, which the glTF
    exporter emits as a single mesh with many nodes.
    """
    meshes = {
        "chair": _chair_mesh(M),
        "laptop": _laptop_mesh(M),
        "screen": _screen_mesh(M),
        "bottle": _bottle_mesh(M),
        "stool": _stool_mesh(M),
    }

    chair_n = laptop_n = bottle_n = 0

    for (name, cx, cz, axis, along, across, seats, n_laptops, flags) in DESKS:
        divider = "divider" in flags
        rot = 0.0 if axis == "x" else math.radians(90.0)
        # Local +X / +Z mapped into world by the desk's own rotation.
        xdir = Vector((math.cos(rot), 0.0, -math.sin(rot)))
        zdir = Vector((math.sin(rot), 0.0, math.cos(rot)))
        centre = Vector((cx, 0.0, cz))

        desk_mesh = _desk_mesh(name, along, across, divider, M)
        obj = bpy.data.objects.new(name, desk_mesh)
        obj.location = centre
        obj.rotation_euler = (0.0, rot, 0.0)
        coll("desks").objects.link(obj)

        # Walk the seats in a stable order so laptop counts are deterministic.
        slots = [(side, u) for side in (1, -1)
                 for u in _seat_offsets(seats[0 if side > 0 else 1], along)]
        lap_slots = slots[:n_laptops]

        for side, u in slots:
            pos = centre + xdir * u + zdir * (side * CHAIR_OFF)
            # Chair faces the desk, so local +Z must point back along the desk's -Z.
            chair_n += 1
            instance("chair_%02d" % chair_n, meshes["chair"],
                     (pos.x, 0.0, pos.z), rot + (0.0 if side < 0 else math.pi),
                     collection="chairs")

            # Bottle sits beside the laptop, clamped inside the desk in LOCAL space
            # (world x is the desk's depth for the 90-degree desks, so clamping in
            # world space would be wrong).
            ub = max(-along / 2 + 0.13, min(along / 2 - 0.13, u + 0.30))
            vb = side * (across / 2 - 0.17)
            bpos = centre + xdir * ub + zdir * vb
            bottle_n += 1
            instance("bottle_water_%02d" % bottle_n, meshes["bottle"],
                     (bpos.x, DESK_TOP_Y, bpos.z), 0.0, collection="desks")

        for side, u in lap_slots:
            lpos = centre + xdir * u + zdir * (side * (across / 2 - 0.13))
            r = rot if side > 0 else rot + math.pi
            laptop_n += 1
            instance("laptop_%02d" % laptop_n, meshes["laptop"],
                     (lpos.x, DESK_TOP_Y, lpos.z), r, collection="laptops")
            if laptop_n % 7 == 0:
                screen_mat = M["screen_dim"]
            elif flags == "glow" or laptop_n % 3:
                screen_mat = M["screen_blue"]
            else:
                screen_mat = M["screen_warm"]
            instance("screen_laptop_%02d" % laptop_n, meshes["screen"],
                     (lpos.x, DESK_TOP_Y, lpos.z), r, collection="laptops",
                     material=screen_mat)

    # Standing bar table inside the back recess, with three stools.
    bx, bz, along, across = BAR_TABLE
    mb = MeshBuilder()
    h = 1.05
    mb.add_box((along, 0.05, across), (0, h - 0.025, 0), slot=0)
    for x in (-(along / 2 - 0.14), along / 2 - 0.14):
        mb.add_box((0.07, h, 0.07), (x, h / 2, 0), slot=1)
        mb.add_box((0.09, 0.04, across - 0.06), (x, 0.02, 0), slot=1)
    bar = bpy.data.objects.new("bar_table",
                               mb.to_mesh("mesh_bar_table", [M["desk_top"], M["desk_leg"]]))
    bar.location = P(bx, 0.0, bz)
    coll("desks").objects.link(bar)

    for i in range(3):
        instance("stool_%02d" % (i + 1), meshes["stool"],
                 (bx - along / 2 + along * (i + 1) / 4.0, 0.0, bz + across / 2 + 0.40),
                 collection="chairs")

    print("[furniture] chairs=%d laptops=%d bottles=%d stools=3"
          % (chair_n, laptop_n, bottle_n))
    return meshes


# ---------------------------------------------------------------------------
# 7. Lighting
# ---------------------------------------------------------------------------

def _add_light(name, kind, collection, location, energy, **kw):
    ld = bpy.data.lights.new(name, type=kind)
    ld.energy = energy
    ld.color = srgb(kw.pop("color", "#FFF6EC"))[:3]
    for k, v in kw.items():
        setattr(ld, k, v)
    lo = bpy.data.objects.new(name, ld)
    lo.location = location
    lo.rotation_euler = (math.radians(180), 0, 0)   # emit along -Y (straight down)
    coll(collection).objects.link(lo)
    return lo


def build_lights():
    """Stage 1 lighting.

    ``light_ceiling_*`` are SPOT lights on purpose: glTF has no area-light type,
    and Blender silently exports area lights as empty nodes, which would leave the
    ``light_ceiling_*`` night-dimming hook carrying no light at all. Spots survive
    the export as KHR_lights_punctual, so the viewer can find and dim them.

    The soft ``light_fill_*`` area lights exist only to keep the Cycles render
    gentle; they are expected to be dropped by the exporter.
    """
    lights = []

    # Daylight coming in through the side windows.
    sun_data = bpy.data.lights.new("light_sun_01", type="SUN")
    sun_data.energy = 1.6
    sun_data.angle = math.radians(3.0)
    sun_data.color = srgb("#FFF4E2")[:3]
    sun = bpy.data.objects.new("light_sun_01", sun_data)
    sun.location = P(-9, 9, 6)
    sun.rotation_euler = (math.radians(52), 0.0, math.radians(-118))
    coll("lights").objects.link(sun)
    lights.append(sun)

    # The ceiling luminaires - these carry the runtime hook.
    for i, (x, z) in enumerate([(-4.6, -2.2), (-4.6, 2.0), (3.2, -2.2), (3.2, 2.0)],
                               start=1):
        lights.append(_add_light(
            "light_ceiling_%02d" % i, "SPOT", "lights", P(x, ROOM_H - 0.12, z),
            energy=260,
            spot_size=math.radians(115), spot_blend=0.75,
            shadow_soft_size=0.35,
        ))

    # Vestibule fill, also a spot so it exports.
    lights.append(_add_light(
        "light_ceiling_lobby", "SPOT", "lights", P(-1.6, LOB_H - 0.12, 1.5),
        energy=90, spot_size=math.radians(120), spot_blend=0.8,
        shadow_soft_size=0.3,
    ))

    # The 1 m-deep alcove is sealed off from the ceiling grid, so without its own
    # light the reveal walls read as black bars from the iso camera. Stage 2 hangs
    # pendants here; this keeps the recess legible for now.
    lights.append(_add_light(
        "light_ceiling_alcove", "SPOT", "lights",
        P((REC_X0 + REC_X1) / 2, ROOM_H - 0.15, (REC_Z0 + REC_Z1) / 2 - 0.1),
        energy=110, spot_size=math.radians(125), spot_blend=0.8,
        shadow_soft_size=0.25,
    ))

    # Render-only soft fill (area lights are dropped by the glTF exporter).
    for i, (x, z, w, d) in enumerate([(-3.5, 0.0, 7.0, 8.5), (3.5, 0.0, 7.0, 8.5)],
                                     start=1):
        lights.append(_add_light(
            "light_fill_%02d" % i, "AREA", "lights", P(x, ROOM_H - 0.10, z),
            energy=95, shape="RECTANGLE", size=w, size_y=d,
        ))
    return lights


def setup_world():
    world = bpy.data.worlds.new("world_classroom")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = srgb("#C9D4DE")
    bg.inputs["Strength"].default_value = 0.38
    bpy.context.scene.world = world


# ---------------------------------------------------------------------------
# 8. Camera + render settings
# ---------------------------------------------------------------------------

def setup_render(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 220
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.012
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    scene.cycles.transmission_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0


def aim_rotation(loc, target, up=Vector((0.0, 1.0, 0.0))):
    """Euler that points a Blender camera's local -Z from ``loc`` at ``target``.

    Written out by hand rather than using ``Vector.to_track_quat`` because that
    helper aligns its ``up`` axis to *world +Z* - Blender's own up axis - whereas
    this scene is built Y-up (room height = world Y). Using it here rolls the
    camera 180 degrees and renders the room upside down.
    """
    z_axis = (Vector(loc) - Vector(target)).normalized()   # local +Z, points back
    x_axis = up.cross(z_axis).normalized()                 # screen right
    y_axis = z_axis.cross(x_axis)                          # screen up
    return Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))


def build_camera(scene):
    """Orthographic isometric camera: high, from the front, aimed at the back wall."""
    azimuth = math.radians(28.0)    # swing off the front axis toward +x
    elev = math.radians(42.0)
    target = Vector(P(0.0, 1.0, -0.3))
    dist = 42.0
    direction = Vector((
        math.sin(azimuth) * math.cos(elev),
        math.sin(elev),
        math.cos(azimuth) * math.cos(elev),
    ))

    cam_data = bpy.data.cameras.new("camera_iso")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("camera_iso", cam_data)
    loc = target + direction * dist
    rot = aim_rotation(loc, target)
    cam.location = loc
    cam.rotation_euler = rot.to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    # Frame every mesh object, including the alcove.
    bpy.context.view_layer.update()
    inv = rot.transposed()
    min_x = min_y = float("inf")
    max_x = max_y = -float("inf")
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        for corner in ev.bound_box:
            p = inv @ (ev.matrix_world @ Vector(corner))
            min_x, max_x = min(min_x, p.x), max(max_x, p.x)
            min_y, max_y = min(min_y, p.y), max(max_y, p.y)

    # Pan in the camera's own plane so the projected bounds land dead centre.
    cam.location = loc + rot @ Vector(((min_x + max_x) / 2, (min_y + max_y) / 2, 0.0))

    aspect = scene.render.resolution_x / scene.render.resolution_y
    cam_data.ortho_scale = max(max_x - min_x, (max_y - min_y) * aspect) * 1.06
    return cam


# ---------------------------------------------------------------------------
# Stats + output
# ---------------------------------------------------------------------------

def report_stats():
    tris = 0
    meshes = 0
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            meshes += 1
            tris += sum(max(0, len(p.vertices) - 2) for p in obj.data.polygons)
    print("[stats] mesh objects: %d" % meshes)
    print("[stats] triangles:    %d  (budget 100000)" % tris)
    return tris


def export_glb():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH,
        export_format="GLB",
        use_selection=False,
        export_apply=True,
        export_cameras=True,
        export_lights=True,
        export_extras=True,
        export_yup=True,
    )
    size = os.path.getsize(GLB_PATH) / 1024.0
    print("[export] %s (%.1f kB)" % (GLB_PATH, size))


def render_preview():
    os.makedirs(RENDER_DIR, exist_ok=True)
    bpy.context.scene.render.filepath = RENDER_PATH
    bpy.ops.render.render(write_still=True)
    print("[render] %s" % RENDER_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    do_render = "--no-render" not in args

    scene = reset_scene()
    M = build_materials()

    build_floor(M)
    build_back_wall(M)
    build_side_walls(M)
    build_front_wall(M)
    build_windows(M)
    build_lobby(M)
    build_entrance(M)
    build_wc_room(M)
    build_logo(M)
    build_furniture(M)

    build_lights()
    setup_world()
    setup_render(scene)
    build_camera(scene)

    report_stats()
    export_glb()
    if do_render:
        render_preview()
    print("[done] stage 1 complete")


if __name__ == "__main__":
    main()
