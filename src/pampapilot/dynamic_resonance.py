"""Source-aware broad dynamic-resonance proposals for stock ReaXcomp."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal, Mapping


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]
Role = Literal["lead_vocal", "guitar", "strings", "keys"]

_ROLE_RANGES: dict[str, tuple[float, float]] = {
    "lead_vocal": (180.0, 9_000.0),
    "guitar": (100.0, 8_000.0),
    "strings": (150.0, 10_000.0),
    "keys": (100.0, 9_000.0),
}

_PROFILES: dict[str, dict[str, float]] = {
    "organic_multitrack": {
        "minimum_prominence_db": 5.5,
        "minimum_variation_db": 3.0,
        "threshold_percentile": 82.0,
        "ratio": 1.6,
        "knee_db": 3.0,
        "attack_ms": 12.0,
        "release_ms": 140.0,
        "rms_ms": 10.0,
    },
    "suno_stems": {
        "minimum_prominence_db": 8.0,
        "minimum_variation_db": 5.0,
        "threshold_percentile": 92.0,
        "ratio": 1.25,
        "knee_db": 4.0,
        "attack_ms": 20.0,
        "release_ms": 180.0,
        "rms_ms": 20.0,
    },
    "unknown": {
        "minimum_prominence_db": 7.0,
        "minimum_variation_db": 4.0,
        "threshold_percentile": 88.0,
        "ratio": 1.4,
        "knee_db": 4.0,
        "attack_ms": 16.0,
        "release_ms": 160.0,
        "rms_ms": 15.0,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _db(values: Any) -> Any:
    import numpy as np

    return 20.0 * np.log10(np.maximum(values, 1e-12))


def _frame_band_rms(
    mono: Any, sample_rate: int, low_hz: float, high_hz: float
) -> Any:
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    nyquist = sample_rate / 2.0
    sos = butter(
        4,
        [low_hz / nyquist, min(high_hz / nyquist, 0.98)],
        btype="bandpass",
        output="sos",
    )
    filtered = sosfiltfilt(sos, mono)
    block_size = max(1, round(sample_rate * 0.05))
    count = len(filtered) // block_size
    blocks = filtered[: count * block_size].reshape(count, block_size)
    return np.sqrt(np.mean(blocks * blocks, axis=1, dtype=np.float64))


def analyze_dynamic_resonance(
    path: Path,
    role: Role,
    source_kind: SourceKind,
) -> dict[str, Any]:
    """Return one broad, dynamic ReaXcomp audition hypothesis at most."""

    import numpy as np
    import soundfile as sf
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import stft

    if role not in _ROLE_RANGES:
        raise ValueError(f"unsupported role: {role}")
    if source_kind not in _PROFILES:
        raise ValueError(f"unsupported source kind: {source_kind}")
    path = Path(path).resolve()
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if data.size == 0:
        raise ValueError("empty audio file")
    if sample_rate < 22_050:
        raise ValueError("sample rate is too low for resonance analysis")
    mono = np.mean(data, axis=1, dtype=np.float64)

    frequencies, _, spectrum = stft(
        mono,
        fs=sample_rate,
        window="hann",
        nperseg=4096,
        noverlap=2048,
        boundary=None,
        padded=False,
    )
    if spectrum.shape[1] < 4:
        raise ValueError("audio file is too short for resonance analysis")
    magnitude = np.abs(spectrum)
    p90_db = _db(np.percentile(magnitude, 90, axis=1))
    broad_db = gaussian_filter1d(p90_db, sigma=18.0, mode="nearest")
    prominence = p90_db - broad_db
    minimum_hz, maximum_hz = _ROLE_RANGES[role]
    eligible = (frequencies >= minimum_hz) & (frequencies <= maximum_hz)
    if not np.any(eligible):
        raise ValueError("no FFT bins fall inside the role range")
    eligible_indexes = np.flatnonzero(eligible)
    peak_index = int(eligible_indexes[np.argmax(prominence[eligible])])
    center_hz = float(frequencies[peak_index])
    prominence_db = float(prominence[peak_index])

    half_octave = math.sqrt(2.0)
    low_hz = max(minimum_hz, center_hz / half_octave)
    high_hz = min(maximum_hz, center_hz * half_octave)
    if high_hz / low_hz < 1.25:
        raise ValueError("detected band is too narrow at the role boundary")
    band_rms = _frame_band_rms(mono, sample_rate, low_hz, high_hz)
    band_db = _db(band_rms)
    active = band_db[band_db > -80.0]
    if active.size < 4:
        raise ValueError("insufficient active blocks in the candidate band")
    p50_dbfs = float(np.percentile(active, 50))
    p90_dbfs = float(np.percentile(active, 90))
    variation_db = p90_dbfs - p50_dbfs

    profile = _PROFILES[source_kind]
    evidence_sufficient = (
        prominence_db >= profile["minimum_prominence_db"]
        and variation_db >= profile["minimum_variation_db"]
    )
    threshold_db = float(
        np.percentile(active, profile["threshold_percentile"])
    )
    threshold_db = round(max(-45.0, min(-8.0, threshold_db)), 1)
    band3_top = min(20_000.0, max(high_hz * 1.8, high_hz + 2_000.0))
    parameters = {
        "lower_crossover_hz": round(low_hz, 1),
        "upper_crossover_hz": round(high_hz, 1),
        "band3_top_frequency_hz": round(band3_top, 1),
        "threshold_db": threshold_db,
        "ratio": profile["ratio"],
        "knee_db": profile["knee_db"],
        "attack_ms": profile["attack_ms"],
        "release_ms": profile["release_ms"],
        "rms_ms": profile["rms_ms"],
    }
    if source_kind == "unknown":
        decision = "classify_source_first"
        reason = "Source classification is required before dynamic processing."
    elif not evidence_sufficient:
        decision = "insufficient_evidence"
        reason = "No sufficiently prominent and time-varying broad resonance was measured."
    else:
        decision = "audition_only"
        reason = (
            "A time-varying spectral prominence supports a broad-band ReaXcomp audition."
        )

    source_sha256 = _sha256(path)
    identity = {
        "source_sha256": source_sha256,
        "role": role,
        "source_kind": source_kind,
        "decision": decision,
        "parameters": parameters if decision == "audition_only" else None,
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_dynamic_resonance_proposal",
        "proposal_id": proposal_id,
        "execute": False,
        "review_status": "user_approval_required",
        "decision": decision,
        "reason": reason,
        "source": {
            "file_name": path.name,
            "file_path": str(path),
            "sha256": source_sha256,
            "role": role,
            "source_kind": source_kind,
        },
        "observations": {
            "candidate_center_hz": center_hz,
            "spectral_prominence_db": prominence_db,
            "candidate_band_rms_dbfs_p50": p50_dbfs,
            "candidate_band_rms_dbfs_p90": p90_dbfs,
            "candidate_band_variation_db": variation_db,
            "minimum_prominence_db": profile["minimum_prominence_db"],
            "minimum_variation_db": profile["minimum_variation_db"],
        },
        "processor": (
            {
                "type": "reaxcomp_dynamic_resonance",
                "target_band": 2,
                "parameters": parameters,
                "transparent_bands": [1, 3, 4],
            }
            if decision == "audition_only"
            else None
        ),
        "warnings": [
            "A musical note or harmonic can resemble a fixed resonance.",
            "ReaXcomp controls a broad band and is not a surgical dynamic EQ.",
            "Compare bypass at matched loudness and listen for tonal dulling or pumping.",
        ],
        "verification_plan": {
            "state": "re-read all 51 parameters and the exact ReaXcomp GUID",
            "signal": "measure gain reduction only while the candidate band is excessive",
            "perceptual": "approve timbre, articulation and bypass by listening",
        },
    }


def build_dynamic_resonance_application_payload(
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    fx_guid: str | None,
) -> dict[str, Any]:
    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False or proposal.get("decision") != "audition_only":
        raise ValueError("only an audition-only dynamic resonance proposal can be approved")
    source = proposal.get("source")
    processor = proposal.get("processor")
    if not isinstance(source, Mapping) or not isinstance(processor, Mapping):
        raise ValueError("proposal is missing source or processor data")
    parameters = processor.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("proposal has no ReaXcomp parameters")
    source_sha256 = source.get("sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("proposal source does not contain a SHA-256 identity")
    return {
        "proposal_id": approved_proposal_id,
        "source_sha256": source_sha256,
        "mode": "reuse_existing" if fx_guid else "create_new",
        "fx_guid": fx_guid,
        "parameters": dict(parameters),
    }
