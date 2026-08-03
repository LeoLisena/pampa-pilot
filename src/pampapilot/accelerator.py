"""Project-local accelerator discovery with a safe CPU fallback."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Callable


_DLL_HANDLES: list[object] = []


def configure_project_cuda_runtime(runtime_root: Path) -> dict[str, object]:
    """Expose project-local NVIDIA DLLs without modifying global Windows state."""

    root = Path(runtime_root).resolve()
    bin_directories = sorted(
        {
            path.parent
            for name in ("cublas64_12.dll", "cudnn64_9.dll")
            for path in root.rglob(name)
        }
    ) if root.is_dir() else []
    for directory in bin_directories:
        if os.name == "nt":
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    available = {}
    for library in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(library) if os.name == "nt" else ctypes.CDLL(library)
            available[library] = True
        except OSError:
            available[library] = False
    return {
        "runtime_root": str(root),
        "bin_directories": [str(path) for path in bin_directories],
        "libraries": available,
        "cuda_runtime_ready": all(available.values()),
    }


def select_inference_backend(
    requested_device: str,
    *,
    cuda_runtime_root: Path,
    cuda_device_count: Callable[[], int] | None = None,
) -> dict[str, object]:
    """Choose CUDA for capable machines and retain an explicit CPU fallback."""

    if requested_device not in {"auto", "cuda", "cpu"}:
        raise ValueError("device must be auto, cuda or cpu")
    runtime = configure_project_cuda_runtime(cuda_runtime_root)
    if cuda_device_count is None:
        try:
            import ctranslate2

            count = int(ctranslate2.get_cuda_device_count())
        except (ImportError, RuntimeError):
            count = 0
    else:
        count = int(cuda_device_count())
    cuda_available = bool(runtime["cuda_runtime_ready"] and count > 0)
    if requested_device == "cuda" and not cuda_available:
        raise RuntimeError(
            "CUDA was requested but project-local cuBLAS/cuDNN or a compatible GPU is unavailable"
        )
    device = "cuda" if requested_device == "cuda" or (
        requested_device == "auto" and cuda_available
    ) else "cpu"
    return {
        "requested_device": requested_device,
        "selected_device": device,
        "compute_type": "float16" if device == "cuda" else "int8",
        "cuda_device_count": count,
        "cuda_available": cuda_available,
        "runtime": runtime,
        "fallback_used": requested_device == "auto" and device == "cpu",
    }

