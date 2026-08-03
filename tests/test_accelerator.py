from pathlib import Path

import pytest

from pampapilot.accelerator import select_inference_backend


def test_auto_falls_back_to_cpu_without_local_cuda_runtime(tmp_path: Path) -> None:
    selected = select_inference_backend(
        "auto", cuda_runtime_root=tmp_path, cuda_device_count=lambda: 1
    )
    assert selected["selected_device"] == "cpu"
    assert selected["compute_type"] == "int8"
    assert selected["fallback_used"] is True


def test_explicit_cuda_fails_instead_of_silently_using_cpu(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="CUDA was requested"):
        select_inference_backend(
            "cuda", cuda_runtime_root=tmp_path, cuda_device_count=lambda: 1
        )
