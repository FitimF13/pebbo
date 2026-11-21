"""Process setup that must run before any third-party library is imported."""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

# Hosts that serve model weights. They are allowed only while models are downloaded.
MODEL_HOSTS = ("huggingface.co", ".huggingface.co", ".hf.co")

_PRIVACY_ENVIRONMENT = {
    # ONNX Runtime's official builds send telemetry to Microsoft unless this is set.
    "ORT_DISABLE_TELEMETRY": "1",
    # Hugging Face libraries report usage unless told not to.
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
    # Ollama clients and others honour this convention.
    "DISABLE_TELEMETRY": "1",
}


def prepare_environment(*, offline: bool = True) -> None:
    """Disable telemetry, select offline model loading and expose GPU libraries.

    Args:
        offline: Load models only from the local cache. ``pebbo download-models`` runs with
            ``offline=False`` to fetch them once.
    """
    for key, value in _PRIVACY_ENVIRONMENT.items():
        os.environ[key] = value
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
    _expose_cuda_libraries()


def disable_onnxruntime_telemetry() -> None:
    """Switch off ONNX Runtime telemetry events in addition to the environment variable."""
    try:
        import onnxruntime
    except ImportError:
        return
    onnxruntime.disable_telemetry_events()


def _expose_cuda_libraries() -> None:
    """Make the CUDA libraries installed as Python wheels loadable on Windows."""
    if sys.platform != "win32":
        return
    site_packages = Path(next(p for p in sys.path if p.endswith("site-packages")))
    for directory in glob.glob(str(site_packages / "nvidia" / "*" / "bin")):
        os.add_dll_directory(directory)
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")


def download(url: str, target: Path) -> None:
    """Download a file over HTTPS to ``target``, atomically."""
    import shutil
    import urllib.request

    if not url.startswith("https://"):
        raise ValueError("Models are only downloaded over HTTPS.")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as file:  # noqa: S310
        shutil.copyfileobj(response, file)
    partial.replace(target)
