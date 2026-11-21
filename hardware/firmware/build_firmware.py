"""Build Pebbo's body firmware: xiaozhi-esp32 for the ESP32-S3-BOX-3 with Pebbo's board code.

Run inside an ESP-IDF 6.1 environment (for example the "ESP-IDF 6.1" PowerShell that the
ESP-IDF installation manager creates, or `. $IDF_PATH/export.sh`):

    python build_firmware.py --core http://192.168.1.50:8100

What it does:
1. Checks out xiaozhi-esp32 at the pinned commit next to this repository (build/xiaozhi).
2. Puts Pebbo's board code (pebbo-box-3/) over the BOX-3 board.
3. Sets the core's address as the default OTA address, so the body only ever talks to the
   local Pebbo core (also when its settings are erased), German as the language and no
   on-device wake word (the core recognises "Hey Pebbo" itself).
4. Builds it, then replaces the firmware's emoji with Pebbo's face (faces/png, drawn by
   faces/make_faces.py): black background, no subtitles, a font with German umlauts.
5. Writes the flashable image to out/pebbo-box-3.bin.

The network is only needed here, at build time: GitHub for the firmware sources and the
ESP component registry for its components, PyPI for two packages of the assets packer.
The firmware itself contacts only the core.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPOSITORY = "https://github.com/78/xiaozhi-esp32.git"
COMMIT = "831ffd1"  # v2.6.0, 2026-11-19; checked for outbound hosts, see README.md
BOARD = "espressif/esp32-s3-box-3"


def run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def checkout(work: Path) -> Path:
    source = work / "xiaozhi"
    if not (source / ".git").exists():
        work.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", REPOSITORY, str(source)], work)
    run(["git", "fetch", "--quiet", "origin"], source)
    run(["git", "checkout", "--quiet", "--force", COMMIT], source)
    run(["git", "clean", "-fdq", "main/boards"], source)
    return source


def install_board(source: Path, ota_url: str) -> None:
    board = source / "main" / "boards" / BOARD
    (board / "esp_box3_board.cc").unlink(missing_ok=True)
    for file in (HERE / "pebbo-box-3").iterdir():
        if file.name != "config.json":
            shutil.copy(file, board / file.name)
    config = json.loads((board / "config.json").read_text(encoding="utf-8"))
    config["builds"] = [
        {
            "name": "pebbo-box-3",
            "sdkconfig_append": [
                "CONFIG_USE_DEVICE_AEC=y",
                f'CONFIG_OTA_URL="{ota_url}"',
            ],
        }
    ]
    (board / "config.json").write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


ASSETS_OFFSET = 0x800000  # the "assets" partition in partitions/v2/16m.csv
FONT = "managed_components/78__xiaozhi-fonts/cbin/font_noto_sans_common_20_4.bin"
SKIN = {"text_color": "#FFE9CC", "background_color": "#000000"}


def build_faces(source: Path) -> bytes:
    """Pack Pebbo's faces and the font into the firmware's assets format."""
    tool = source / "scripts" / "spiffs_assets"
    run([sys.executable, "-m", "pip", "install", "--quiet", "numpy", "pillow"], tool)  # the packer needs them
    faces = str(HERE / "faces" / "png")
    run([sys.executable, "build.py", "--text_font", str(source / FONT), "--emoji_collection", faces], tool)
    index_path = tool / "build" / "assets" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["hide_subtitle"] = True
    index["skin"] = {"light": SKIN, "dark": SKIN}
    index_path.write_text(json.dumps(index, indent=4) + "\n", encoding="utf-8")
    run([sys.executable, "spiffs_assets_gen.py", "--config", str(tool / "build" / "config.json")], tool)
    return (tool / "build" / "output" / "assets.bin").read_bytes()


def with_faces(image: bytes, assets: bytes) -> bytes:
    """Put Pebbo's assets into the merged flash image, in place of the default ones.

    The assets partition is the last one, so everything after its start is replaced.
    """
    return image[:ASSETS_OFFSET].ljust(ASSETS_OFFSET, bytes([0xFF])) + assets


def ota_address(core: str) -> str:
    parsed = urlparse(core if "://" in core else f"http://{core}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(f"Not a core address: {core}")
    port = f":{parsed.port}" if parsed.port else ":8100"
    return f"{parsed.scheme}://{parsed.hostname}{port}/xiaozhi/ota/"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", required=True, help="address of the Pebbo core on the home network")
    parser.add_argument("--work", type=Path, default=HERE / "build", help="where the firmware sources go")
    arguments = parser.parse_args()

    ota_url = ota_address(arguments.core)
    source = checkout(arguments.work)
    install_board(source, ota_url)
    run(
        [sys.executable, "scripts/build.py", BOARD, "--language", "de-DE", "--wake-word", "disabled"],
        source,
    )
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    image = (source / "build" / "merged-binary.bin").read_bytes()
    (out / "pebbo-box-3.bin").write_bytes(with_faces(image, build_faces(source)))
    print(f"Firmware for {ota_url}: {out / 'pebbo-box-3.bin'}")


if __name__ == "__main__":
    main()
