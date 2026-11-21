"""Render the case from the STL files in print/, next to the concept image for comparison.

    uv run --with vtk --with pillow python render.py
"""

from __future__ import annotations

import math
from pathlib import Path

import vtk
from PIL import Image

import pebbo_case as case

HERE = Path(__file__).parent
CONCEPT = HERE.parents[1] / "lieferung-fm" / "70b13974-37a8-4e82-83be-da007dccf95b.png"
CREAM, LAVENDER, GLOW, VISOR = "#eee3d4", "#8f7ca8", "#ffc285", "#17121c"
COLOURS = {
    "base": LAVENDER,
    "ring": GLOW,
    "torso": CREAM,
    "head_front": CREAM,
    "head_back": CREAM,
    "visor": VISOR,
    "cap": LAVENDER,
    "cap_light": GLOW,
    "mute_plunger": LAVENDER,
    "wing_right": CREAM,
    "wing_left": CREAM,
    "wing_cover_right": CREAM,
    "wing_glow_right": GLOW,
    "wing_cover_left": CREAM,
    "wing_glow_left": GLOW,
}
# VTK pipeline objects must outlive the render; Python would free them too early.
KEEP: list[object] = []
GLOWING = {"ring", "cap_light", "wing_glow_right", "wing_glow_left"}
EXPLODE = {
    "base": (0, 0, 0),
    "ring": (0, 0, 28),
    "torso": (0, 0, 56),
    "wing_right": (34, 0, 56),
    "wing_left": (-34, 0, 56),
    "wing_cover_right": (34, 30, 56),
    "wing_glow_right": (34, -20, 56),
    "wing_cover_left": (-34, 30, 56),
    "wing_glow_left": (-34, -20, 56),
    "head_front": (0, 0, 92),
    "head_back": (0, 60, 92),
    "visor": (0, -45, 92),
    "cap": (0, 0, 150),
    "cap_light": (0, 0, 132),
    "mute_plunger": (0, 0, 114),
}
# Views of the concept sheet: (name, camera azimuth, crop box in the concept image).
VIEWS = (("front", 0.0, (95, 700, 295, 945)), ("side", 90.0, (320, 700, 490, 945)), ("back", 180.0, (495, 700, 720, 945)))


def rgb(colour: str) -> tuple[float, float, float]:
    return (int(colour[1:3], 16) / 255, int(colour[3:5], 16) / 255, int(colour[5:7], 16) / 255)


def actor(source: vtk.vtkAlgorithmOutput, colour: str, offset: tuple[float, float, float], glow: bool = False) -> vtk.vtkActor:
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(source)
    normals.SetFeatureAngle(40)
    KEEP.append(normals)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    result = vtk.vtkActor()
    result.SetMapper(mapper)
    result.SetPosition(*offset)
    prop = result.GetProperty()
    prop.SetColor(*rgb(colour))
    prop.SetAmbient(0.9 if glow else 0.42)
    prop.SetDiffuse(0.3 if glow else 0.72)
    prop.SetSpecular(0.05 if glow else 0.12)
    prop.SetSpecularPower(15)
    return result


def stl(name: str) -> vtk.vtkAlgorithmOutput:
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(HERE / "print" / f"{name}.stl"))
    KEEP.append(reader)
    return reader.GetOutputPort()


def face(offset: tuple[float, float, float]) -> list[vtk.vtkActor]:
    """Pebbo's happy face on the screen: closed eyes, blush lines and an open smile."""
    y = case.box_front_y() - 0.3
    z0 = case.BOX_Z
    actors = []

    def stroke(points: list[tuple[float, float]], colour: str, radius: float) -> None:
        line = vtk.vtkPoints()
        for x, z in points:
            line.InsertNextPoint(x + offset[0], y + offset[1], z0 + z + offset[2])
        polyline = vtk.vtkPolyLineSource()
        polyline.SetPoints(line)
        tube = vtk.vtkTubeFilter()
        tube.SetInputConnection(polyline.GetOutputPort())
        tube.SetRadius(radius)
        tube.SetNumberOfSides(12)
        KEEP.extend([line, polyline, tube])
        actors.append(actor(tube.GetOutputPort(), colour, (0, 0, 0), glow=True))

    for side in (-1, 1):
        arc = [(side * 12 + 6 * math.cos(t), 2 + 5 * math.sin(t)) for t in [math.pi * i / 16 for i in range(17)]]
        stroke(arc, "#ffe9c9", 1.3)
        for k in range(3):
            x = side * (17 + k * 2.2)
            stroke([(x, -5.5), (x - side * 1.0, -8.5)], "#ff9e9e", 0.5)
    smile = [(4.5 * math.cos(t), -6 + 4.5 * math.sin(t)) for t in [math.pi + math.pi * i / 16 for i in range(17)]]
    stroke(smile + [smile[0]], "#ff9fb0", 1.2)
    return actors


def render(file: Path, azimuth: float, elevation: float, exploded: bool = False, size: tuple[int, int] = (800, 980)) -> None:
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(*rgb("#f3ebe3"))
    for part, colour in COLOURS.items():
        offset = EXPLODE[part] if exploded else (0.0, 0.0, 0.0)
        renderer.AddActor(actor(stl(part), colour, offset, glow=part in GLOWING))
    head_offset = EXPLODE["head_front"] if exploded else (0.0, 0.0, 0.0)
    for item in face(head_offset):
        renderer.AddActor(item)
    box3 = vtk.vtkCubeSource()  # the BOX-3: black glass behind the visor
    y = case.box_front_y()
    box3.SetBounds(-case.BOX_W / 2, case.BOX_W / 2, y, y + case.BOX_D, case.BOX_Z - case.BOX_H / 2, case.BOX_Z + case.BOX_H / 2)
    KEEP.append(box3)
    renderer.AddActor(actor(box3.GetOutputPort(), "#0d0a10", head_offset))
    camera = renderer.GetActiveCamera()
    middle = 150 if exploded else 85
    camera.SetFocalPoint(0, 0, middle)
    camera.SetPosition(0, -900, middle)
    camera.SetViewUp(0, 0, 1)
    camera.SetViewAngle(18)
    camera.Azimuth(azimuth)
    camera.Elevation(elevation)
    renderer.ResetCamera()
    renderer.ResetCameraClippingRange()
    light = vtk.vtkLight()
    light.SetLightTypeToCameraLight()
    light.SetPosition(-0.6, 0.8, 1.0)
    light.SetIntensity(0.95)
    renderer.AddLight(light)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.AddRenderer(renderer)
    window.SetSize(*size)
    window.SetMultiSamples(8)
    window.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(window)
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(file))
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    print("wrote", file.name)


def comparison() -> None:
    """Concept views on top, the printed case from the same side underneath."""
    concept = Image.open(CONCEPT).convert("RGB")
    tiles = []
    for name, azimuth, box in VIEWS:
        render(HERE / f"render_{name}.png", azimuth, 6.0)
        ours = Image.open(HERE / f"render_{name}.png").convert("RGB")
        theirs = concept.crop(box)
        height = 520
        theirs = theirs.resize((int(theirs.width * height / theirs.height), height))
        ours = ours.resize((int(ours.width * height / ours.height), height))
        tile = Image.new("RGB", (max(theirs.width, ours.width), 2 * height), "#f3ebe3")
        tile.paste(theirs, ((tile.width - theirs.width) // 2, 0))
        tile.paste(ours, ((tile.width - ours.width) // 2, height))
        tiles.append(tile)
    sheet = Image.new("RGB", (sum(t.width for t in tiles), tiles[0].height), "#f3ebe3")
    x = 0
    for tile in tiles:
        sheet.paste(tile, (x, 0))
        x += tile.width
    sheet.save(HERE / "comparison.png")
    print("wrote comparison.png")


if __name__ == "__main__":
    render(HERE / "preview_front.png", azimuth=-28.0, elevation=8.0)
    render(HERE / "preview_exploded.png", azimuth=-30.0, elevation=8.0, exploded=True, size=(900, 1400))
    comparison()
