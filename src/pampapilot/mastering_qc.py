"""Read-only technical QC for candidate distribution masters."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT


def _load_profile(knowledge_root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = knowledge_root / "mastering" / "spotify-delivery-qc.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profile"), dict):
        raise ValueError("Spotify delivery knowledge is invalid")
    return document, path


def _estimated_true_peak(path: Path, oversample: int = 4) -> float | None:
    """Estimate inter-sample peak in bounded blocks using polyphase resampling."""

    import numpy as np
    from scipy.signal import resample_poly
    import soundfile as sf

    maximum = 0.0
    with sf.SoundFile(path) as stream:
        sample_rate = int(stream.samplerate)
        block_frames = max(sample_rate, 4096)
        overlap = 128
        while True:
            start = stream.tell()
            block = stream.read(block_frames, dtype="float64", always_2d=True)
            if len(block) == 0:
                break
            left_count = min(overlap, start)
            right_count = overlap if stream.tell() < len(stream) else 0
            if left_count or right_count:
                center_end = stream.tell()
                stream.seek(start - left_count)
                padded = stream.read(
                    left_count + len(block) + right_count,
                    dtype="float64",
                    always_2d=True,
                )
                stream.seek(center_end)
            else:
                padded = block
            upsampled = resample_poly(padded, oversample, 1, axis=0)
            first = left_count * oversample
            last = first + len(block) * oversample
            maximum = max(maximum, float(np.max(np.abs(upsampled[first:last]))))
    return 20.0 * math.log10(maximum) if maximum > 0.0 else None


def _check(identifier: str, status: str, observation: str, recommendation: str) -> dict[str, str]:
    return {
        "id": identifier,
        "status": status,
        "observation": observation,
        "recommendation": recommendation,
    }


def _normalization_scenario(
    integrated_lufs: float, true_peak_dbpt: float, target_lufs: float
) -> dict[str, float | bool]:
    requested_gain = target_lufs - integrated_lufs
    if requested_gain > 0.0:
        headroom_limited_gain = -1.0 - true_peak_dbpt
        applied_gain = max(0.0, min(requested_gain, headroom_limited_gain))
    else:
        applied_gain = requested_gain
    return {
        "target_lufs": target_lufs,
        "requested_gain_db": round(requested_gain, 3),
        "estimated_applied_gain_db": round(applied_gain, 3),
        "estimated_playback_lufs": round(integrated_lufs + applied_gain, 3),
        "headroom_limited": applied_gain + 1e-9 < requested_gain,
    }


def build_master_delivery_qc(
    audio_path: Path,
    *,
    profile_name: str = "spotify_streaming",
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Measure one candidate master and return an informational delivery report."""

    if profile_name != "spotify_streaming":
        raise ValueError(f"unsupported delivery profile: {profile_name}")
    path = Path(audio_path).resolve()
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_profile(root)
    profile: Mapping[str, Any] = knowledge["profile"]
    metrics = analyze_audio_file(path)
    integrated_lufs = metrics.get("integrated_lufs")
    if not isinstance(integrated_lufs, (int, float)):
        raise ValueError("integrated loudness could not be measured")
    true_peak = _estimated_true_peak(path)
    if true_peak is None:
        raise ValueError("true peak could not be estimated")

    checks = []
    channels = int(metrics["channels"])
    checks.append(
        _check(
            "format.stereo",
            "pass" if channels == int(profile["preferred_channels"]) else "warning",
            f"The master contains {channels} channel(s).",
            "Deliver one high-quality stereo master per track.",
        )
    )
    sample_rate = int(metrics["sample_rate_hz"])
    checks.append(
        _check(
            "format.sample_rate",
            "pass" if sample_rate >= int(profile["minimum_sample_rate_hz"]) else "warning",
            f"Sample rate is {sample_rate} Hz.",
            "Use at least 44.1 kHz for this delivery profile.",
        )
    )
    clipped = int(metrics["samples_at_or_above_0_dbfs"])
    checks.append(
        _check(
            "signal.sample_clipping",
            "pass" if clipped == 0 else "fail",
            f"Samples at or above 0 dBFS: {clipped}.",
            "Remove sample clipping before delivery.",
        )
    )
    normal_lufs = float(profile["normalization_lufs"])
    peak_limit = float(
        profile[
            "true_peak_max_dbtp_above_normalization"
            if integrated_lufs > normal_lufs
            else "true_peak_max_dbtp_at_or_below_normalization"
        ]
    )
    checks.append(
        _check(
            "signal.estimated_true_peak",
            "pass" if true_peak <= peak_limit else "warning",
            f"Estimated true peak is {true_peak:.3f} dBTP; profile limit is {peak_limit:.1f} dBTP.",
            "Create more true-peak headroom if lossy encoding tests reveal distortion.",
        )
    )
    checks.append(
        _check(
            "measurement.true_peak_method",
            "measurement_limit",
            "True peak is estimated with 4x polyphase oversampling.",
            "Confirm the final master with a standards-compliant meter and codec audition.",
        )
    )

    scenarios = {
        name: _normalization_scenario(integrated_lufs, true_peak, float(target))
        for name, target in (
            ("normal", profile["normalization_lufs"]),
            ("loud", profile["loud_normalization_lufs"]),
            ("quiet", profile["quiet_normalization_lufs"]),
        )
    }
    identity = {
        "profile": profile_name,
        "knowledge_id": knowledge["id"],
        "reviewed_at": str(knowledge["reviewed_at"]),
        "sha256": metrics["sha256"],
        "checks": checks,
        "scenarios": scenarios,
    }
    report_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    status_counts: dict[str, int] = {}
    for check in checks:
        status_counts[check["status"]] = status_counts.get(check["status"], 0) + 1
    overall = "fail" if status_counts.get("fail") else (
        "review" if status_counts.get("warning") else "technical_checks_passed"
    )
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_master_delivery_qc",
        "report_id": report_id,
        "execute": False,
        "profile": profile_name,
        "overall_status": overall,
        "source": {
            "file_path": str(path),
            "sha256": metrics["sha256"],
            "format": metrics["format"],
            "subtype": metrics["subtype"],
        },
        "measurements": {
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "integrated_lufs": float(integrated_lufs),
            "sample_peak_dbfs": metrics["sample_peak_dbfs"],
            "estimated_true_peak_dbtp": true_peak,
            "crest_factor_db": metrics["crest_factor_db"],
            "stereo_correlation": metrics["stereo_correlation"],
            "samples_at_or_above_0_dbfs": clipped,
        },
        "normalization_scenarios": scenarios,
        "checks": checks,
        "knowledge": {
            "id": knowledge["id"],
            "path": str(knowledge_path),
            "reviewed_at": str(knowledge["reviewed_at"]),
            "sources": list(knowledge["sources"]),
        },
        "verification": {
            "state_verified": False,
            "signal_verified": True,
            "perceptually_evaluated": False,
        },
    }


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


def build_project_master_delivery_qc(
    render_state: Mapping[str, Any], file_report: Mapping[str, Any]
) -> dict[str, Any]:
    """Link verified REAPER render configuration to a measured delivery file."""

    if file_report.get("kind") != "pampapilot_master_delivery_qc":
        raise ValueError("file_report is not a master delivery QC report")
    project_ref = render_state.get("project_ref")
    if not isinstance(project_ref, str) or not project_ref:
        raise ValueError("render_state has no project_ref")
    checks: list[dict[str, str]] = []
    measurements = file_report["measurements"]
    render_channels = int(render_state.get("render_channels") or 0)
    file_channels = int(measurements["channels"])
    checks.append(
        _check(
            "render.channels_match_file",
            "pass" if render_channels == file_channels else "warning",
            f"REAPER is set to {render_channels} channel(s); the file has {file_channels}.",
            "Confirm the analyzed file was produced with the current render settings.",
        )
    )

    render_sample_rate = float(render_state.get("render_sample_rate_hz") or 0.0)
    if render_sample_rate <= 0.0 and render_state.get("project_sample_rate_enabled"):
        render_sample_rate = float(render_state.get("project_sample_rate_hz") or 0.0)
    file_sample_rate = int(measurements["sample_rate_hz"])
    if render_sample_rate > 0.0:
        rate_status = "pass" if round(render_sample_rate) == file_sample_rate else "warning"
        rate_observation = (
            f"REAPER resolves to {round(render_sample_rate)} Hz; the file is "
            f"{file_sample_rate} Hz."
        )
    else:
        rate_status = "measurement_limit"
        rate_observation = (
            "REAPER delegates render sample rate without an enabled project rate; "
            f"the file is {file_sample_rate} Hz."
        )
    checks.append(
        _check(
            "render.sample_rate_matches_file",
            rate_status,
            rate_observation,
            "Set an explicit render or project sample rate when reproducibility is required.",
        )
    )

    actual_path = _normalized_path(str(file_report["source"]["file_path"]))
    raw_targets = str(render_state.get("render_targets") or "")
    targets = [target for target in raw_targets.split(";") if target.strip()]
    target_matches = actual_path in {_normalized_path(target) for target in targets}
    checks.append(
        _check(
            "render.target_matches_file",
            (
                "pass"
                if target_matches
                else "warning" if targets else "measurement_limit"
            ),
            (
                "The analyzed file is one of REAPER's current render targets."
                if target_matches
                else "The analyzed file is not among REAPER's current render targets."
                if targets
                else "REAPER did not expose a concrete current render target."
            ),
            "A matching target supports configuration consistency but does not prove provenance.",
        )
    )

    dirty = bool(render_state.get("project_dirty"))
    checks.append(
        _check(
            "project.saved_state",
            "warning" if dirty else "pass",
            "The REAPER project has unsaved changes." if dirty else "The project is saved.",
            "Save or version the project before producing the distribution master.",
        )
    )
    normalize_flags = int(render_state.get("render_normalize_flags") or 0)
    checks.append(
        _check(
            "render.normalization",
            "warning" if normalize_flags & 1 else "pass",
            (
                "REAPER render normalization is enabled."
                if normalize_flags & 1
                else "REAPER render normalization is disabled."
            ),
            "Keep automatic normalization intentional and record its target before rendering.",
        )
    )
    offline_master_fx = [
        fx for fx in render_state.get("master_fx", []) if bool(fx.get("offline"))
    ]
    checks.append(
        _check(
            "master.fx_online",
            "warning" if offline_master_fx else "pass",
            f"Offline master FX count: {len(offline_master_fx)}.",
            "Bring intended master processors online before the final render.",
        )
    )

    render_settings_flags = int(render_state.get("render_settings_flags") or 0)
    render_mode = {
        0: "master_mix",
        1: "stems_and_master_mix",
        2: "stems_only",
        3: "stems_flag_combination",
    }[render_settings_flags & 3]
    status_counts: dict[str, int] = {}
    for check in [*file_report["checks"], *checks]:
        status_counts[check["status"]] = status_counts.get(check["status"], 0) + 1
    overall = "fail" if status_counts.get("fail") else (
        "review" if status_counts.get("warning") else "technical_checks_passed"
    )
    identity = {
        "project_ref": project_ref,
        "project_state_change_count": render_state.get("project_state_change_count"),
        "file_report_id": file_report["report_id"],
        "checks": checks,
    }
    report_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_project_master_delivery_qc",
        "report_id": report_id,
        "execute": False,
        "overall_status": overall,
        "project": {
            "project_ref": project_ref,
            "project_state_change_count": render_state.get(
                "project_state_change_count"
            ),
            "dirty": dirty,
        },
        "render": {
            "mode": render_mode,
            "channels": render_channels,
            "sample_rate_hz": render_sample_rate or None,
            "directory": render_state.get("render_directory"),
            "pattern": render_state.get("render_pattern"),
            "targets": targets,
            "dither_flags": int(render_state.get("render_dither_flags") or 0),
            "normalize_flags": normalize_flags,
            "master_fx": list(render_state.get("master_fx", [])),
        },
        "file_report": dict(file_report),
        "linkage_checks": checks,
        "provenance": {
            "configuration_consistent": target_matches
            and render_channels == file_channels
            and (render_sample_rate <= 0.0 or round(render_sample_rate) == file_sample_rate),
            "render_provenance_verified": False,
            "note": (
                "Matching configuration cannot prove that this exact file was rendered "
                "from the current project state."
            ),
        },
        "verification": {
            "state_verified": True,
            "signal_verified": True,
            "perceptually_evaluated": False,
        },
    }
