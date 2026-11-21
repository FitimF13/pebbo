"""Check that the bought parts fit the printed parts without collisions.

Places simple stand-ins for the BOX-3 main unit, the BRACKET and the LED ring and reports
how much of each overlaps a printed part. Everything should be (close to) zero.

    uv run --with build123d python check_fit.py
"""

from __future__ import annotations

from itertools import combinations

from build123d import Align, Box, Cylinder, Pos

import pebbo_case as case

STAND_INS = {
    "BOX-3 main unit": Pos(0, case.box_y(), case.BOX_Z) * Box(case.BOX_W, case.BOX_D, case.BOX_H),
    "BOX-3 bracket": Pos(0, case.box_y(), case.Z_HEAD - case.BRACKET_DROP - case.BRACKET_H / 2)
    * Box(case.BRACKET_W, case.BRACKET_D, case.BRACKET_H),
    "LED ring": Pos(0, 0, case.BASE_H - case.LED_RING_T)
    * (
        Cylinder(case.LED_RING_OD / 2, case.LED_RING_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
        - Cylinder(case.LED_RING_ID / 2, case.LED_RING_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ),
}


def overlap_volume(a: object, b: object) -> float:
    """The volume two solids share. Empty or touching results count as zero."""
    try:
        shared = a & b  # type: ignore[operator]
    except ValueError:  # OpenCascade returns a null shape when nothing is shared
        return 0.0
    return float(shared.volume) if shared is not None else 0.0


def main() -> None:
    parts = {name: make() for name, make in case.PARTS.items()}
    worst = 0.0
    for stand_in, solid in STAND_INS.items():
        for name, part in parts.items():
            overlap = overlap_volume(solid, part)
            if overlap > 1.0:
                print(f"COLLISION {stand_in} with {name}: {overlap:.1f} mm3")
            worst = max(worst, overlap)
    for (first, a), (second, b) in combinations(parts.items(), 2):
        overlap = overlap_volume(a, b)
        if overlap > 1.0:
            print(f"OVERLAP {first} with {second}: {overlap:.1f} mm3")
            worst = max(worst, overlap)
    box = STAND_INS["BOX-3 main unit"]
    shell = case.head_outer().fuse(Pos(0, 0, case.Z_TORSO) * case.torso_solid())
    outside = (box - shell).volume
    print(f"BOX-3 outside the case: {outside:.1f} mm3")
    print(f"largest overlap {worst:.2f} mm3")


if __name__ == "__main__":
    main()
