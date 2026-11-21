"""Parametric 3D-printable case for Pebbo around an Espressif ESP32-S3-BOX-3.

The shape is traced from the concept image (lieferung-fm/, see docs/vision.md): a wide,
egg-shaped cream head with a large black visor and a row of dots on the forehead, a
lavender pebble cap with three glowing sparks, a soft round torso with an oval dot grille,
two angel-wing fins with two glowing slots each, a glowing ring and a puffy lavender base.
All concept proportions are kept. Because the BOX-3 (66 x 61 mm) is taller than the
concept's display module, everything is scaled by ``K``.

Run with build123d (Apache-2.0) to regenerate the STL and STEP files in ``print/``:

    uv run --with build123d python pebbo_case.py

Coordinates: millimetres, Z up, the face looks towards -Y. The BOX-3 main unit stays closed
(its glass, speaker box and microphone covers are glued in by Espressif and tuned for its
echo cancellation). It stands on the BOX-3 BRACKET inside the torso. Its speaker sounds into
the head and leaves through the torso grille. Pressing the cap presses the BOX-3's mute
button through a plunger. BOX-3 measurements come from Espressif's drawings and STEP
files, see README.md.
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Compound,
    Cylinder,
    Part,
    Plane,
    Polyline,
    Pos,
    RectangleRounded,
    Rot,
    Sphere,
    Spline,
    Vector,
    export_step,
    export_stl,
    extrude,
    fillet,
    loft,
    make_face,
    mirror,
    offset,
    revolve,
    scale,
)

OUT = Path(__file__).parent / "print"
BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

# Concept scale: 1.0 is the 128 mm Pebbo of the concept image.
K = 1.3

# Printing ------------------------------------------------------------------
FIT = 0.3  # clearance between parts that slide into each other
WALL = 2.4

# ESP32-S3-BOX-3 main unit (Espressif drawings and STEP files) -------------------
BOX_W, BOX_H, BOX_D = 66.0, 61.0, 16.6
MIC_X, MIC_FROM_TOP = 17.0, 5.5  # the two microphone ports on the front
# BOX-3 BRACKET: the main unit plugs into its PCIe socket from above.
BRACKET_W, BRACKET_D, BRACKET_H = 70.5, 22.5, 18.8
BRACKET_SCREW_X = 30.0  # two vertical M3 holes, 60 mm apart, in the floor of its pocket
# The holes sit 6.5 mm off the middle towards one face. The STEP file does not say which
# face is the front, so the shelf has inserts for both.
BRACKET_SCREW_OFFSET = 6.5
BOX_SINK = 1.8  # the BOX-3 sits this deep in the bracket's pocket
BRACKET_DROP = 6.0  # the bracket sits this far below the torso top, so the torso can round in

# Bought parts --------------------------------------------------------------
LED_RING_OD, LED_RING_ID, LED_RING_T = 65.5, 52.3, 3.2  # 24 x WS2812B ring
LED_PCB = 10.4  # single WS2812B on a round 10 mm PCB, for the wings and the cap
INSERT_M3, INSERT_M25 = 4.2, 3.6  # holes for heat-set inserts
CLEAR_M3, CLEAR_M25 = 3.4, 2.8

# Shape, measured on the concept's front, side and back views (concept mm) -------------
BASE_H = 27.0 * K
BASE_OUTLINE = [
    (r * K, z * K) for r, z in [(42.0, 0.0), (46.0, 4.0), (47.2, 12.0), (46.2, 20.0), (43.5, 25.2), (40.5, 27.0)]
]
RING_R, RING_T = 40.5 * K, 3.5 * K  # glowing band between base and torso
TORSO_H = 35.0 * K
TORSO_OUTLINE = [
    (r * K, z * K) for r, z in [(40.0, 0.0), (42.4, 5.0), (42.8, 13.0), (42.0, 21.0), (39.0, 29.0), (34.0, 35.0)]
]
HEAD_A, HEAD_C = 44.0 * K, 36.5 * K  # half width and half depth at the widest level
HEAD_LOW, HEAD_HIGH = 22.0 * K, 35.0 * K  # widest level above the bottom; top above it
HEAD_BOTTOM_SCALE = 0.87  # the bottom is narrower than the widest level
HEAD_P_FRONT, HEAD_P_BACK = 6.0, 2.4  # a flat face, a rounder back
HEAD_Q_TOP, HEAD_Q_BOTTOM = 2.3, 2.4
HEAD_EDGE = 2.0 * K  # rounding of the bottom edge
VISOR_W, VISOR_R = 67.0 * K, 14.0 * K
FOREHEAD_DOTS, FOREHEAD_PITCH = 4, 7.0  # decorative, like the concept
CAP_RADII = (28.0 * K, 22.0 * K, 14.0 * K)
CAP_TILT = 0.0  # degrees, leaning back like in the side view
CAP_BACK = 22.0  # mm behind the mute button, like the concept's side view
WING_T = 9.0 * K

# Stack ---------------------------------------------------------------------
Z_RING = BASE_H
Z_TORSO = Z_RING + RING_T
Z_HEAD = Z_TORSO + TORSO_H  # the BOX-3 rests on the bracket, flush with the torso top
Z_WIDEST = Z_HEAD + HEAD_LOW
Z_HEAD_TOP = Z_WIDEST + HEAD_HIGH
BOX_Z = Z_HEAD - BRACKET_DROP - BOX_SINK + BOX_H / 2
BOX_TOP = BOX_Z + BOX_H / 2
SCREW_ANGLES = (90.0, 210.0, 330.0)  # base to torso
SCREW_R = 0.5 * (LED_RING_OD / 2 + TORSO_OUTLINE[0][0] - WALL) + 1.0


def polar(radius: float, degrees: float) -> tuple[float, float]:
    return radius * math.cos(math.radians(degrees)), radius * math.sin(math.radians(degrees))


def smooth_revolved(outline: list[tuple[float, float]]) -> Part:
    """A solid of revolution whose outer surface is a spline through (radius, z) points."""
    bottom, top = outline[0], outline[-1]
    curve = Spline(*[Vector(r, 0, z) for r, z in outline])
    closing = Polyline(
        Vector(top[0], 0, top[1]), Vector(0, 0, top[1]), Vector(0, 0, bottom[1]), Vector(bottom[0], 0, bottom[1])
    )
    return revolve(make_face([curve, closing]), Axis.Z)


def ellipsoid(center: tuple[float, float, float], radii: tuple[float, float, float]) -> Part:
    return Pos(*center) * scale(Sphere(1.0), radii)


def above(z: float) -> Part:
    return Pos(0, 0, z) * Box(400, 400, 400, align=BOTTOM)


def in_front_of(y: float) -> Part:
    return Pos(0, y - 200, 0) * Box(400, 400, 800)


# Head ----------------------------------------------------------------------
def head_section(a: float, c: float, z: float, points: int = 80) -> Spline:
    """A superellipse that is flatter at the face (front, -Y) than at the back."""
    vertices = []
    for index in range(points):
        t = 2 * math.pi * index / points
        cos, sin = math.cos(t), math.sin(t)
        p = HEAD_P_FRONT if sin < 0 else HEAD_P_BACK
        x = a * math.copysign(abs(cos) ** (2 / p), cos)
        y = c * math.copysign(abs(sin) ** (2 / p), sin)
        vertices.append(Vector(x, y, z))
    return Spline(*vertices, periodic=True)


def head_scale(z: float) -> float:
    """Size of the head's section at height z, relative to the widest level."""
    dz = z - Z_WIDEST
    if dz >= 0:
        return max(0.0, 1 - (dz / HEAD_HIGH) ** HEAD_Q_TOP) ** (1 / HEAD_Q_TOP)
    q = HEAD_Q_BOTTOM
    reach = HEAD_LOW / (1 - HEAD_BOTTOM_SCALE**q) ** (1 / q)
    return (1 - (-dz / reach) ** q) ** (1 / q)


@cache
def head_solid(inset: float = 0.0) -> Part:
    """The egg-shaped head, shrunk by ``inset`` all around (for the cavity and the visor)."""
    bottom = Z_HEAD + inset
    top = Z_HEAD_TOP - inset - 0.5
    levels = [bottom + (top - bottom) * (1 - math.cos(math.pi * i / 20)) / 2 for i in range(21)]
    edge = max(HEAD_EDGE - inset, 0.6)
    sections = []
    for z in levels:
        s = head_scale(z)
        h = z - bottom
        rounding = edge - math.sqrt(max(edge**2 - (edge - h) ** 2, 0.0)) if h < edge else 0.0
        rounding = min(rounding, edge * 0.85)
        sections.append(make_face(head_section(HEAD_A * s - inset - rounding, HEAD_C * s - inset - rounding, z)))
    return loft(sections)


def head_outer() -> Part:
    return head_solid(0.0)


def head_cavity() -> Part:
    return head_solid(WALL)


@cache
def box_front_y() -> float:
    """The most forward BOX-3 position where it fits the head and its bracket fits the torso."""
    cavity = head_cavity()
    torso_inside = Pos(0, 0, Z_TORSO) * torso_solid(WALL)
    bracket_bottom = Z_HEAD - BRACKET_DROP - BRACKET_H
    y = -HEAD_C
    while y < 0:
        center = y + FIT + BOX_D / 2
        box = Pos(0, center, BOX_Z) * Box(BOX_W + 2 * FIT, BOX_D + 2 * FIT, BOX_H + 2 * FIT)
        bracket = Pos(0, center, bracket_bottom) * Box(
            BRACKET_W + 2 * FIT, BRACKET_D + 2 * FIT, BRACKET_H, align=BOTTOM
        )
        in_head = ((box & above(Z_HEAD + WALL)) - cavity).volume < 0.5
        if in_head and ((box - above(Z_HEAD)) + bracket - torso_inside).volume < 0.5:
            return y + FIT
        y += 0.5
    raise ValueError("The BOX-3 does not fit into the head")


def box_y() -> float:
    return box_front_y() + BOX_D / 2


def box3_space() -> Part:
    """The BOX-3 with clearance. No printed part may reach into it."""
    return Pos(0, box_y(), BOX_Z) * Box(BOX_W + 2 * FIT, BOX_D + 2 * FIT, BOX_H + 2 * FIT)


# The visor's opening on the face of the head, and the window it narrows to at the BOX-3
# glass. The window reaches above the screen to the two microphone ports, so the sound
# reaches them straight through the visor. The screen sits low in the visor, so the top
# edge hides little of it when Pebbo is seen from above at a desk.
def visor_front() -> tuple[float, float]:
    """Bottom and top of the visor opening on the face."""
    return Z_HEAD + 8.0, BOX_TOP - 2.0


def glass_window() -> tuple[float, float, float]:
    """Width, bottom and top of the opening at the BOX-3 glass."""
    return 54.0, BOX_Z - 19.5, BOX_TOP - MIC_FROM_TOP + 2.5


def rounded_rect(width: float, bottom: float, top: float, radius: float, y: float) -> Part:
    face = Plane.XZ * Pos(0, (bottom + top) / 2) * RectangleRounded(width, top - bottom, radius)
    return Pos(0, y, 0) * face


def visor_prism(width: float, bottom: float, top: float, radius: float) -> Part:
    face = Plane.XZ * Pos(0, (bottom + top) / 2) * RectangleRounded(width, top - bottom, radius)
    return extrude(face, amount=200, both=True)


def head_split_y() -> float:
    return box_y() + BOX_D / 2 + 1.5


def mic_z() -> float:
    return BOX_TOP - MIC_FROM_TOP


def head_shell() -> Part:
    shell = head_outer() - head_cavity()
    bottom, top = visor_front()
    shell -= visor_prism(VISOR_W, bottom, top, VISOR_R) & in_front_of(box_front_y())
    # Decorative dots on the forehead, shallow so they do not open into the head.
    for index in range(FOREHEAD_DOTS):
        x = (index - (FOREHEAD_DOTS - 1) / 2) * FOREHEAD_PITCH
        dot = Pos(x, -HEAD_C - 5.0, top + 5.0) * Rot(90, 0, 0) * Cylinder(1.4, 12.0)
        shell -= dot - head_solid(1.4)
    # The BOX-3 passes through the floor into the bracket. The opening behind it lets the
    # speaker's sound down into the torso and out of the grille.
    shell -= Pos(0, box_y(), Z_HEAD) * Box(BOX_W + 2 * FIT, BOX_D + 2 * FIT, 2 * WALL + 2)
    shell -= Pos(0, box_y() + BOX_D / 2 + 9, Z_HEAD) * Box(50.0, 10.0, 2 * WALL + 2)
    # Guide for the mute plunger under the cap, above the BOX-3 mute button.
    x0, y0 = mute_xy()
    _, cap_y, _ = cap_center()
    guide_bottom = BOX_TOP + FIT + 2.0  # above the plunger's flange
    guide = Pos(x0, y0, guide_bottom) * Cylinder(5.6, Z_HEAD_TOP - guide_bottom, align=BOTTOM)
    shell += guide & head_outer()
    shell -= Pos(x0, y0, Z_HEAD_TOP - 30.0) * Cylinder(3.5, 50.0, align=BOTTOM)
    for x in (-12.0, 12.0):  # guide holes for the cap's pins
        shell -= Pos(x, cap_y, Z_HEAD_TOP - 12.0) * Cylinder(1.8, 20.0, align=BOTTOM)
    return shell - box3_space()


def torso_head_screws() -> list[tuple[float, float]]:
    """Screws from inside the torso up into the head: two into each half, all hidden."""
    split = head_split_y()
    return [(-37.8, box_y() + 6.0), (37.8, box_y() + 6.0), (-28.0, split + 8.0), (28.0, split + 8.0)]


def dowels() -> list[tuple[float, float]]:
    """Two 3 mm dowels hold the halves together at the top (a piece of filament works)."""
    return [(-26.0, Z_WIDEST + 22.0), (26.0, Z_WIDEST + 22.0)]


def floor_bosses(part: Part) -> Part:
    for x, y in torso_head_screws():
        boss = Pos(x, y, Z_HEAD) * Cylinder(4.0, 8.0, align=BOTTOM)
        part += boss & head_outer()
        part -= Pos(x, y, Z_HEAD) * Cylinder(INSERT_M3 / 2, 6.5, align=BOTTOM)
    return part


def dowel_bosses(part: Part, split: float, sign: int) -> Part:
    for x, z in dowels():
        part += Pos(x, split + sign * 5.0, z) * Rot(90, 0, 0) * Cylinder(3.5, 10.0) & head_outer()
        part -= Pos(x, split + sign * 4.0, z) * Rot(90, 0, 0) * Cylinder(1.6, 8.0)
    return part


def head_front() -> Part:
    split = head_split_y()
    front = floor_bosses(head_shell()) & in_front_of(split)
    front = dowel_bosses(front, split, -1)
    for side in (-1, 1):  # side ribs keep the BOX-3 centred
        rib = Pos(side * (BOX_W / 2 + FIT + 1.5), box_y(), BOX_Z) * Box(3.0, BOX_D - 2, 26.0)
        front += rib & head_cavity()
    return front - box3_space()


def head_back() -> Part:
    split = head_split_y()
    back = floor_bosses(head_shell()) - in_front_of(split)
    back = dowel_bosses(back, split, 1)
    depth = split - (box_y() + BOX_D / 2 + FIT)
    for x in (-18.0, 18.0):  # two ribs press the BOX-3 against the visor
        back += Pos(x, split - depth / 2 + 0.01, BOX_Z) * Box(4.0, depth, 18.0)
    return back - box3_space()


def visor() -> Part:
    """The black visor: a glossy-black funnel from the face of the head to the screen."""
    rim = 2.0
    bottom, top = visor_front()
    body = visor_prism(VISOR_W - 2 * FIT, bottom + FIT, top - FIT, VISOR_R - FIT) & head_solid(1.0)
    body &= in_front_of(box_front_y() - FIT)
    width, glass_bottom, glass_top = glass_window()
    funnel = loft(
        [
            rounded_rect(VISOR_W - 2 * rim, bottom + rim, top - rim, VISOR_R - rim, -HEAD_C - 2.0),
            rounded_rect(width, glass_bottom, glass_top, 6.0, box_front_y() + 1.0),
        ]
    )
    return body - funnel - box3_space()


# Cap: lavender pebble with three glowing sparks; pressing it mutes the microphones -----
def mute_xy() -> tuple[float, float]:
    """The BOX-3 mute button, in the middle of its top."""
    return 0.0, box_y()


def cap_center() -> tuple[float, float, float]:
    return 0.0, box_y() + CAP_BACK, Z_HEAD_TOP + 0.35 * CAP_RADII[2] - 5.0


def cap_frame(part: Part) -> Part:
    """Move a part from cap coordinates (centre at the origin) onto the head, leaning back."""
    return Pos(*cap_center()) * Rot(-CAP_TILT, 0, 0) * part


def cap_shape(shrink: float = 0.0) -> Part:
    radii = (CAP_RADII[0] - shrink, CAP_RADII[1] - shrink, CAP_RADII[2] - shrink)
    pebble = ellipsoid((0, 0, 0), radii) & Pos(0, 0, -CAP_RADII[2] * 0.35) * Box(200, 200, 200, align=BOTTOM)
    return cap_frame(pebble)


def sparks(shrink: float = 0.0) -> Part:
    result = None
    for degrees in (-32.0, 0.0, 32.0):
        angle = math.radians(degrees)
        width = 3.4 - 2 * shrink
        length = (8.5 if degrees == 0 else 7.0) * K - 2 * shrink
        cx, cy = 7.5 * K * math.sin(angle), -8.0 * K * math.cos(angle) - 8.0 * K
        slot = Pos(cx, cy, 0) * Rot(0, 0, degrees) * Box(width, length, 60.0)
        slot = fillet(slot.edges().filter_by(Axis.Z), width / 2 - 0.05)
        result = slot if result is None else result + slot
    assert result is not None
    return cap_frame(result)


def cap() -> Part:
    """The lavender pebble: a shell with a solid floor that follows the head."""
    _, y0, z0 = cap_center()
    mx, my = mute_xy()
    dome = (cap_shape() - cap_shape(2.2)) + (cap_shape() - above(z0 + 1.0))
    dome -= sparks()
    pins = Pos(-12.0, y0, z0 - 7.0) * Cylinder(1.8 - FIT / 2, 8.0, align=BOTTOM)
    pins += Pos(12.0, y0, z0 - 7.0) * Cylinder(1.8 - FIT / 2, 8.0, align=BOTTOM)
    dome += pins
    dome -= Pos(0, 0, 1.0) * head_outer() - pins
    dome -= Pos(mx, my, z0 - 20.0) * Cylinder(3.3, 20.0 + 0.5, align=BOTTOM)  # the plunger is glued in here
    dome -= Pos(mx, my, z0 - 20.0) * Cylinder(1.8, 30.0, align=BOTTOM)  # LED wires
    return dome


def cap_light() -> Part:
    """Translucent insert on the cap's floor that fills the three sparks and holds a WS2812B."""
    _, y0, z0 = cap_center()
    floor = above(z0 + 1.0 + FIT)
    insert = (cap_shape(2.2 + FIT) & floor) + (sparks(FIT) & cap_shape(0.3) & floor)
    insert -= Pos(0, y0 - 6.0, z0 + 1.0) * Box(LED_PCB + 0.6, LED_PCB + 0.6, 3.5, align=BOTTOM)
    channel = abs(y0 - 6.0 - mute_xy()[1]) + 3  # wires from the plunger to the LED
    insert -= Pos(0, (y0 - 6.0 + mute_xy()[1]) / 2, z0 + 1.0) * Box(3.0, channel, 2.0, align=BOTTOM)
    return insert - Pos(0, 0, 1.0 + FIT) * head_outer()


def mute_plunger() -> Part:
    """Rests on the BOX-3 mute button and carries the cap. Hollow for the cap LED's wires."""
    mx, my = mute_xy()
    _, _, z0 = cap_center()
    bottom = BOX_TOP + FIT
    top = z0 - 0.5
    pin = Pos(mx, my, bottom) * Cylinder(3.15, top - bottom, align=BOTTOM)
    pin += Pos(mx, my, bottom + 0.2) * Cylinder(5.0, 1.4, align=BOTTOM)  # stays under the guide
    pin -= Pos(mx, my, bottom + 3.0) * Cylinder(1.6, 80.0, align=BOTTOM)  # wire bore
    pin -= Pos(mx, my + 3.0, bottom + 5.5) * Box(3.2, 6.0, 4.0)  # the wires leave at the side
    return pin


# Torso ---------------------------------------------------------------------
GRILLE = (35.0 * K / 2, 20.0 * K / 2, 3.3)  # half width, half height, pitch


def torso_radius(z: float) -> float:
    """Radius of the round part of the torso at height z (a smooth curve through the outline)."""
    points = TORSO_OUTLINE
    for i in range(len(points) - 1):
        (r1, z1), (r2, z2) = points[i], points[i + 1]
        if z1 <= z <= z2:
            r0 = points[i - 1][0] if i > 0 else 2 * r1 - r2
            r3 = points[i + 2][0] if i + 2 < len(points) else 2 * r2 - r1
            f = (z - z1) / (z2 - z1)
            return 0.5 * (
                2 * r1 + (r2 - r0) * f + (2 * r0 - 5 * r1 + 4 * r2 - r3) * f**2 + (3 * r1 - r0 - 3 * r2 + r3) * f**3
            )
    return points[-1][0]


TORSO_BLEND_FROM = 19.0 * K  # above this height the torso turns into the head's outline
TORSO_SHOULDER = 6.0  # the top rounds in this much under the head, like the concept's crease
TORSO_P_FRONT = 4.8  # the torso's front stays round, flatter than a circle only to hold the bracket


def torso_section(z: float, inset: float) -> Spline:
    w = min(max((z - TORSO_BLEND_FROM) / (TORSO_H - TORSO_BLEND_FROM), 0.0), 1.0)
    w = w * w * (3 - 2 * w)
    r = torso_radius(z)
    a_top, c_top = HEAD_A * HEAD_BOTTOM_SCALE - 0.5, HEAD_C * HEAD_BOTTOM_SCALE - 0.5
    shoulder = TORSO_H - TORSO_SHOULDER
    rounding = 0.0
    if z > shoulder:
        h = (z - shoulder) / TORSO_SHOULDER
        rounding = TORSO_SHOULDER * (1 - math.sqrt(max(1 - h * h, 0.0))) * 0.9
    a = (1 - w) * r + w * a_top - inset - rounding
    c = (1 - w) * r + w * c_top - inset - rounding
    front = (1 - w) * 2.0 + w * TORSO_P_FRONT
    back = (1 - w) * 2.0 + w * HEAD_P_BACK
    vertices = []
    for index in range(80):
        angle = 2 * math.pi * index / 80
        cos, sin = math.cos(angle), math.sin(angle)
        p = front if sin < 0 else back
        x = a * math.copysign(abs(cos) ** (2 / p), cos)
        y = c * math.copysign(abs(sin) ** (2 / p), sin)
        vertices.append(Vector(x, y, z))
    return Spline(*vertices, periodic=True)


@cache
def torso_solid(inset: float = 0.0) -> Part:
    """The torso in its own coordinates (bottom at z = 0), shrunk by ``inset`` all around."""
    levels = [TORSO_H * i / 20 for i in range(20)]
    levels += [TORSO_H - TORSO_SHOULDER * (1 - i / 4) for i in range(5)]
    levels = sorted(set(round(z, 3) for z in levels))
    return loft([make_face(torso_section(z, inset)) for z in levels])


def torso_half_width(z: float) -> float:
    w = min(max((z - TORSO_BLEND_FROM) / (TORSO_H - TORSO_BLEND_FROM), 0.0), 1.0)
    w = w * w * (3 - 2 * w)
    return (1 - w) * torso_radius(z) + w * (HEAD_A * HEAD_BOTTOM_SCALE - 0.5)


def torso() -> Part:
    outer = torso_solid(0.0)
    body = outer - torso_solid(WALL)
    bottom_r = TORSO_OUTLINE[0][0]
    body += (Cylinder(bottom_r - 0.5, 4.0, align=BOTTOM) - Cylinder(SCREW_R - 6, 4.0, align=BOTTOM)) & outer
    for angle in SCREW_ANGLES:
        x, y = polar(SCREW_R, angle)
        body -= Pos(x, y, 0) * Cylinder(INSERT_M3 / 2, 5.5, align=BOTTOM)
    # Top plate with the bracket opening, a sound opening and the screws into the head.
    by = box_y()
    overlap = torso_solid(WALL / 2)  # reaches into the wall, so the parts fuse cleanly
    body += Pos(0, 0, TORSO_H - 3.0) * Cylinder(80.0, 3.0, align=BOTTOM) & overlap
    bracket_bottom = TORSO_H - BRACKET_DROP - BRACKET_H
    shelf = Pos(0, by, bracket_bottom - 3.0) * Box(BRACKET_W + 6, BRACKET_D + 6, 3.0, align=BOTTOM)
    body += shelf & overlap
    body -= Pos(0, by, bracket_bottom) * Box(BRACKET_W + 2 * FIT, BRACKET_D + 2 * FIT, BRACKET_H, align=BOTTOM)
    body -= Pos(0, by, bracket_bottom + BRACKET_H - 1.0) * Box(
        BOX_W + 2 * FIT, BOX_D + 2 * FIT, BRACKET_DROP + 2.0, align=BOTTOM
    )
    for side in (-1, 1):
        for offset in (-BRACKET_SCREW_OFFSET, BRACKET_SCREW_OFFSET):
            body -= Pos(side * BRACKET_SCREW_X, by + offset, bracket_bottom - 3.0) * Cylinder(
                INSERT_M3 / 2, 3.0, align=BOTTOM
            )
    body -= Pos(0, by, bracket_bottom - 3.0) * Box(30.0, 12.0, 3.0, align=BOTTOM)
    body -= Pos(0, by + BOX_D / 2 + 9, TORSO_H - 3.0) * Box(50.0, 10.0, 3.0, align=BOTTOM)  # sound
    for x, y in torso_head_screws():
        body -= Pos(x, y, TORSO_H - 3.0) * Cylinder(CLEAR_M3 / 2, 3.0, align=BOTTOM)
    # Oval dot grille on the front, staggered rows like the concept.
    half_w, half_h, pitch = GRILLE
    z_mid = TORSO_H * 0.47
    rows = int(half_h * 2 / (pitch * 0.87)) + 1
    for row in range(rows):
        z = z_mid + (row - (rows - 1) / 2) * pitch * 0.87
        offset = pitch / 2 if row % 2 else 0.0
        columns = int(half_w * 2 / pitch) + 2
        for column in range(-columns, columns + 1):
            x = column * pitch + offset
            if (x / half_w) ** 2 + ((z - z_mid) / half_h) ** 2 <= 1:
                body -= Pos(x, -60.0, z) * Rot(90, 0, 0) * Cylinder(1.15, 60.0)
    for side in (-1, 1):  # wing sockets near the top, with holes for the LED wires
        body -= wing_socket(side)
    body -= above(TORSO_H)  # the loft can bulge a hair above its top section
    return Pos(0, 0, Z_TORSO) * body


def wing_root() -> tuple[float, float]:
    """Where the wings meet the torso: distance from the middle and height above its bottom."""
    z = 27.5 * K
    return torso_half_width(z) + 0.5, z


def wing_peg(grow: float = 0.0) -> Part:
    """The peg at the wing's root, in wing coordinates. ``grow`` makes the matching socket."""
    peg = Pos(-4.0, 0, 0) * Box(16.0 + 2 * grow, 6.0 - FIT + 2 * grow, 9.0 - FIT + 2 * grow)
    if grow:
        peg += Pos(-12.0, 0, 0) * Rot(0, 90, 0) * Cylinder(2.4, 14.0)  # wires into the torso
    return peg


def wing_socket(side: int) -> Part:
    """The socket in the torso, in torso coordinates."""
    return Pos(0, 0, -Z_TORSO) * place_wing(wing_peg(FIT), side)


# Ring and base ---------------------------------------------------------------
def ring() -> Part:
    """Translucent band that glows from the LED ring underneath."""
    body = Cylinder(RING_R, RING_T, align=BOTTOM) - Cylinder(LED_RING_ID / 2 - 4.0, RING_T, align=BOTTOM)
    for angle in SCREW_ANGLES:
        x, y = polar(SCREW_R, angle)
        body -= Pos(x, y, 0) * Cylinder(CLEAR_M3 / 2, RING_T, align=BOTTOM)
    return Pos(0, 0, Z_RING) * body


def base() -> Part:
    outer = smooth_revolved(BASE_OUTLINE)
    body = outer - (Pos(0, 0, 2.5) * smooth_revolved([(r - 4.0, z) for r, z in BASE_OUTLINE]))
    body -= above(BASE_H - 1.5) & Cylinder(BASE_OUTLINE[-1][0] - 3.0, 400)  # open top
    for angle in SCREW_ANGLES:
        x, y = polar(SCREW_R, angle)
        body += (Pos(x, y, 0) * Cylinder(3.5, BASE_H, align=BOTTOM)) & outer
        body -= Pos(x, y, 0) * Cylinder(CLEAR_M3 / 2, BASE_H, align=BOTTOM)
        body -= Pos(x, y, 0) * Cylinder(2.9, 3.0, align=BOTTOM)  # M3 low-head screws
    ring_mid = (LED_RING_OD + LED_RING_ID) / 4
    for angle in (30.0, 150.0, 270.0):  # pillars under the LED ring, LEDs flush with the top
        x, y = polar(ring_mid, angle)
        body += Pos(x, y, 0) * Cylinder(2.5, BASE_H - LED_RING_T, align=BOTTOM)
    # USB-C breakout with screw terminals at the back: 5 V for the BOX-3 and the LEDs.
    body -= Pos(0, BASE_OUTLINE[2][0] - 2.0, 12.0) * Box(13.0, 14.0, 7.0)
    for angle in (45.0, 135.0, 225.0, 315.0):  # rubber feet
        x, y = polar(BASE_OUTLINE[0][0] - 9.0, angle)
        body -= Pos(x, y, 0) * Cylinder(5.25, 1.2, align=BOTTOM)
    return body


# Wings ---------------------------------------------------------------------
# Angel wing seen from the back: a round top edge and three feather lobes underneath.
WING_OUTLINE = [
    (0.0, 3.5), (6.0, 9.0), (15.0, 12.5), (24.0, 12.5), (30.5, 9.5), (32.0, 5.0), (29.0, 1.5),
    (24.0, 0.5), (26.0, -2.5), (24.0, -6.0), (18.0, -7.5), (10.0, -6.5), (3.5, -5.0), (0.0, -2.5),
]  # fmt: skip
WING_TILT = 22.0  # degrees up
WING_SIZE = 1.25 * K  # the concept's wings, slightly larger than drawn so they read at desk distance
WING_SWEEP = 18.0  # degrees back


@cache
def wing_blank(inset: float = 0.0) -> Part:
    """The wing's pillow shape, or the same shape shrunk by ``inset`` all around."""
    if inset:
        return offset(wing_blank(0.0), amount=-inset)
    points = [Vector(x * WING_SIZE, 0, z * WING_SIZE) for x, z in WING_OUTLINE]
    face = make_face(Spline(*points, periodic=True))
    thickness = WING_T / 2
    body = extrude(face, amount=thickness, both=True)
    for radius in (thickness - 0.6, thickness * 0.6, thickness * 0.3):
        try:
            return fillet(body.edges().filter_by(Axis.Y, reverse=True), radius)
        except Exception:  # noqa: S112 - some outlines only round with a smaller radius
            continue
    return body


def wing_slots(shrink: float = 0.0) -> Part:
    slots = None
    for x, z, length, width, angle in ((18.0, 7.0, 15.0, 3.6, -8.0), (16.0, -2.8, 10.0, 3.2, 10.0)):
        w = width * WING_SIZE / 1.3 - 2 * shrink
        slot = Pos(x * WING_SIZE, -WING_T / 2, z * WING_SIZE) * Rot(0, angle, 0) * Box(
            length * WING_SIZE / 1.3 - 2 * shrink, 10.0, w
        )
        slot = fillet(slot.edges().filter_by(Axis.Y), w / 2 - 0.05)
        slots = slot if slots is None else slots + slot
    assert slots is not None
    return slots


def place_wing(part: Part, side: int) -> Part:
    r, z = wing_root()
    placed = Pos(r, 4.0, Z_TORSO + z) * Rot(0, 0, WING_SWEEP) * Rot(0, -WING_TILT, 0) * part
    return placed if side > 0 else mirror(placed, Plane.YZ)


def wing_back() -> Part:
    return Pos(0, 2.0, 0) * Box(400, WING_T, 400)


def largest_solid(part: Part) -> Part:
    """Keep the main solid. Boolean cuts on curved surfaces can leave tiny slivers."""
    solids = sorted(part.solids(), key=lambda solid: solid.volume, reverse=True)
    return solids[0] if solids else part  # type: ignore[return-value]


def clear_of_body(part: Part, side: int, pieces: int = 1) -> Part:
    """Cut away the torso and the head with a gap, so the wings follow their curves."""
    grown_head = scale(head_outer(), (1 + FIT / HEAD_A, 1 + FIT / HEAD_C, 1.0))
    part -= Pos(0, 0, Z_TORSO) * torso_solid(-FIT)
    for head in (grown_head, head_outer()):
        try:
            cut = part - head
            if cut.is_valid:
                part = cut
                break
        except ValueError:  # OpenCascade occasionally fails on near-tangent surfaces
            continue
    if pieces > 1:
        solids = sorted(part.solids(), key=lambda solid: solid.volume, reverse=True)[:pieces]
        return Part(Compound(solids).wrapped)
    return largest_solid(part)


SKIN = 2.4  # front skin of the wing, where the glowing slots are


def wing_hollow(inset: float = 0.0) -> Part:
    front = -WING_T / 2 + SKIN
    return wing_blank(1.6 + inset) & Pos(0, front + 200 + inset, 0) * Box(400, 400, 400)


def wing(side: int) -> Part:
    """Cream wing shell, open at the back."""
    body = wing_blank() - wing_hollow() - wing_slots()
    body = clear_of_body(place_wing(body, side), side)
    body += place_wing(wing_peg(), side)  # the peg reaches into the torso's socket
    body -= place_wing(Rot(0, 90, 0) * Cylinder(1.8, 40.0), side)  # wires
    return largest_solid(body)


def wing_cover(side: int) -> Part:
    """Cream back of the wing, holding a WS2812B behind the glowing slots."""
    back = WING_T / 2 - 1.6 - 2.0
    cover = wing_hollow(FIT) & Pos(0, back + 200, 0) * Box(400, 400, 400)
    cover -= Pos(15.0 * WING_SIZE, back, 3.0 * WING_SIZE) * Box(LED_PCB + 0.6, 4.0, LED_PCB + 0.6)
    cover -= Pos(0, back + 0.5, 0) * Rot(0, 90, 0) * Cylinder(1.8, 60.0)
    cover -= wing_peg(FIT)
    return clear_of_body(place_wing(cover, side), side)


def wing_glow(side: int) -> Part:
    """Translucent inlays that fill the two slots, with a lip behind the skin."""
    inlay = wing_slots(FIT) & wing_blank(0.4) & Pos(0, -WING_T / 2 + SKIN - 200, 0) * Box(400, 400, 400)
    lip = Pos(0, -WING_T / 2 + SKIN + 0.6, 0) * Box(400, 1.2, 400) & (wing_slots(-1.5) & wing_hollow(FIT))
    return clear_of_body(place_wing(inlay + lip, side), side, pieces=2)


PARTS = {
    "base": base,
    "ring": ring,
    "torso": torso,
    "wing_right": lambda: wing(1),
    "wing_left": lambda: wing(-1),
    "wing_cover_right": lambda: wing_cover(1),
    "wing_cover_left": lambda: wing_cover(-1),
    "wing_glow_right": lambda: wing_glow(1),
    "wing_glow_left": lambda: wing_glow(-1),
    "head_front": head_front,
    "head_back": head_back,
    "visor": visor,
    "cap": cap,
    "cap_light": cap_light,
    "mute_plunger": mute_plunger,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    print(f"height {Z_HEAD_TOP + CAP_RADII[2]:.0f} mm, head {2 * HEAD_A:.0f} x {2 * HEAD_C:.0f} mm")
    print(f"BOX-3 front at y = {box_front_y():.1f}, head front at y = {-HEAD_C:.1f}")
    for name, make in PARTS.items():
        part = make()
        print(f"{name:17} volume {part.volume / 1000:6.1f} cm3  valid {part.is_valid}")
        export_stl(part, str(OUT / f"{name}.stl"), tolerance=0.02, angular_tolerance=0.15)
        export_step(part, str(OUT / f"{name}.step"))


if __name__ == "__main__":
    main()
