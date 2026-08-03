"""Lyrics-guided, audio-timed song structure proposals."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
import unicodedata


ALGORITHM_VERSION = "0.1"
_STRUCTURE_ALIASES = (
    ("final_chorus", re.compile(r"^(final\s+chorus|chorus\s+final|estribillo\s+final)$")),
    ("pre_chorus", re.compile(r"^(pre[ -]?chorus|pre[ -]?estribillo)$")),
    ("intro", re.compile(r"^(intro|introduction)$")),
    ("verse", re.compile(r"^(verse|verse\s+\d+|estrofa|estrofa\s+\d+)$")),
    ("chorus", re.compile(r"^(chorus|chorus\s+\d+|estribillo|estribillo\s+\d+)$")),
    ("bridge", re.compile(r"^(bridge|puente)$")),
    ("outro", re.compile(r"^(outro|coda|final)$")),
    ("instrumental", re.compile(r"^(instrumental|solo|interlude|interludio)$")),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized.replace("_", " ")).strip()


def _section_kind(label: str) -> str | None:
    normalized = _normalized_label(label)
    for kind, pattern in _STRUCTURE_ALIASES:
        if pattern.fullmatch(normalized):
            return kind
    return None


def parse_structured_lyrics(path: Path) -> dict[str, Any]:
    """Separate structural tags, arrangement notes, and damaged lyric text."""

    lyric_path = Path(path).resolve()
    text = lyric_path.read_text(encoding="utf-8-sig")
    sections: list[dict[str, Any]] = []
    warnings: list[str] = []
    current: dict[str, Any] | None = None
    occurrence: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        bracket = re.fullmatch(r"\[([^\[\]]+)\]", line)
        if bracket:
            content = bracket.group(1).strip()
            kind = _section_kind(content)
            if kind is not None:
                occurrence[kind] = occurrence.get(kind, 0) + 1
                current = {
                    "index": len(sections),
                    "label": content,
                    "kind": kind,
                    "occurrence": occurrence[kind],
                    "line_number": line_number,
                    "arrangement_notes": [],
                    "lyrics": [],
                }
                sections.append(current)
            elif current is not None:
                current["arrangement_notes"].append(content)
            else:
                warnings.append(f"Ignored bracket note before first section at line {line_number}.")
            continue
        if current is None:
            warnings.append(f"Ignored text before first section at line {line_number}.")
        else:
            current["lyrics"].append(line)

    if len(sections) < 2:
        raise ValueError("lyrics must contain at least two recognized structural sections")
    for section in sections:
        joined = "\n".join(section["lyrics"])
        section["lyric_line_count"] = len(section["lyrics"])
        section["lyric_token_count"] = len(re.findall(r"[^\W_]+", joined, re.UNICODE))
        section["lyrics_text"] = joined
        del section["lyrics"]
    return {
        "file_path": str(lyric_path),
        "sha256": _sha256(lyric_path),
        "encoding": "utf-8",
        "sections": sections,
        "warnings": warnings,
    }


def _first_sustained_vocal_start(vocal_path: Path) -> float | None:
    import numpy as np
    import soundfile as sf

    data, sample_rate = sf.read(vocal_path, dtype="float64", always_2d=True)
    if len(data) == 0:
        return None
    block_frames = max(1, round(sample_rate * 0.1))
    usable = len(data) // block_frames
    if usable == 0:
        return None
    blocks = data[: usable * block_frames].reshape(usable, block_frames, data.shape[1])
    rms = np.sqrt(np.mean(np.square(blocks), axis=(1, 2)))
    levels = 20.0 * np.log10(np.maximum(rms, 1e-12))
    threshold = max(-50.0, float(np.percentile(levels, 20)) + 12.0)
    active = levels >= threshold
    required = 4
    run = 0
    for index, enabled in enumerate(active):
        run = run + 1 if enabled else 0
        if run >= required:
            return (index - required + 1) * 0.1
    return None


def _audio_boundaries(
    audio_path: Path,
    sections: list[Mapping[str, Any]],
    bpm: float | None,
    vocal_start_seconds: float | None,
) -> dict[str, Any]:
    import librosa
    import numpy as np
    from scipy.ndimage import gaussian_filter1d

    data, sample_rate = librosa.load(audio_path, sr=None, mono=True)
    if len(data) == 0:
        raise ValueError("audio has no samples")
    duration = len(data) / sample_rate
    section_count = len(sections)
    if duration < section_count * 2.0:
        raise ValueError("audio is too short for the declared section count")
    hop_length = max(512, round(sample_rate * 0.1))
    n_fft = 4096 if sample_rate >= 22_050 else 2048
    rms = librosa.feature.rms(y=data, frame_length=n_fft, hop_length=hop_length)
    onset = librosa.onset.onset_strength(y=data, sr=sample_rate, hop_length=hop_length)[None, :]
    centroid = librosa.feature.spectral_centroid(
        y=data, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )
    bandwidth = librosa.feature.spectral_bandwidth(
        y=data, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )
    chroma = librosa.feature.chroma_stft(
        y=data, sr=sample_rate, n_fft=n_fft, hop_length=hop_length
    )
    frame_count = min(feature.shape[1] for feature in (rms, onset, centroid, bandwidth, chroma))
    features = np.vstack(
        (rms[:, :frame_count], onset[:, :frame_count], centroid[:, :frame_count],
         bandwidth[:, :frame_count], chroma[:, :frame_count])
    ).astype(np.float64)
    medians = np.median(features, axis=1, keepdims=True)
    scales = np.median(np.abs(features - medians), axis=1, keepdims=True)
    features = (features - medians) / np.maximum(scales, 1e-9)
    features = gaussian_filter1d(features, sigma=2.0, axis=1, mode="nearest")
    novelty = np.linalg.norm(np.diff(features, axis=1), axis=0)
    novelty_p90 = float(np.percentile(novelty, 90)) if len(novelty) else 0.0
    shape_weights = {
        "intro": 0.65,
        "verse": 1.0,
        "pre_chorus": 0.7,
        "chorus": 1.15,
        "final_chorus": 1.2,
        "bridge": 0.9,
        "outro": 0.65,
        "instrumental": 0.9,
    }
    weights = [shape_weights[str(section["kind"])] for section in sections]
    total_weight = sum(weights)
    expected = []
    cumulative = 0.0
    for weight in weights[:-1]:
        cumulative += weight
        expected.append(duration * cumulative / total_weight)
    grid_seconds = 240.0 / bpm if bpm is not None else 1.0
    candidates = np.arange(grid_seconds, duration - grid_seconds / 2, grid_seconds)
    minimum_duration = max(2.0, grid_seconds * 1.5)
    average_duration = duration / section_count
    times = [0.0]
    selected_evidence = []
    for boundary_index, expected_time in enumerate(expected):
        remaining_sections = section_count - boundary_index - 1
        minimum = times[-1] + minimum_duration
        maximum = duration - remaining_sections * minimum_duration
        window = max(grid_seconds * 2.0, average_duration * 0.5)
        eligible = candidates[
            (candidates >= max(minimum, expected_time - window))
            & (candidates <= min(maximum, expected_time + window))
        ]
        if len(eligible) == 0:
            chosen = min(max(expected_time, minimum), maximum)
        else:
            best_score, chosen = -math.inf, float(eligible[0])
            for candidate in eligible:
                frame = min(
                    len(novelty) - 1,
                    max(0, round(float(candidate) * sample_rate / hop_length) - 1),
                )
                radius = max(1, round(0.4 * sample_rate / hop_length))
                local_strength = float(
                    np.max(novelty[max(0, frame - radius): min(len(novelty), frame + radius + 1)])
                )
                relative = local_strength / novelty_p90 if novelty_p90 > 0 else 0.0
                prior_penalty = abs(float(candidate) - expected_time) / window
                score = min(relative, 2.0) - 0.65 * prior_penalty
                if score > best_score:
                    best_score, chosen = score, float(candidate)
        times.append(chosen)
        selected_evidence.append({"expected_time_seconds": expected_time})
    times.append(duration)

    vocal_anchor = None
    if (
        vocal_start_seconds is not None
        and sections[0]["kind"] == "intro"
        and len(times) > 2
    ):
        vocal_anchor = round(vocal_start_seconds / grid_seconds) * grid_seconds
        vocal_anchor = max(minimum_duration, vocal_anchor)
        if vocal_anchor < times[2] - minimum_duration:
            times[1] = vocal_anchor
            selected_evidence[0]["vocal_onset_anchor_seconds"] = vocal_start_seconds

    boundary_evidence = []
    for evidence, time_seconds in zip(selected_evidence, times[1:-1]):
        frame = min(len(novelty) - 1, max(0, round(time_seconds * sample_rate / hop_length) - 1))
        strength = float(novelty[frame]) if len(novelty) else 0.0
        boundary_evidence.append(
            {
                "time_seconds": time_seconds,
                **evidence,
                "adjustment_from_shape_prior_seconds": time_seconds - evidence["expected_time_seconds"],
                "novelty_strength": strength,
                "relative_to_p90": strength / novelty_p90 if novelty_p90 > 0 else 0.0,
            }
        )
    return {
        "sample_rate_hz": sample_rate,
        "duration_seconds": duration,
        "hop_length": hop_length,
        "boundary_times_seconds": times,
        "boundary_evidence": boundary_evidence,
        "tempo_grid_bpm": bpm,
        "method": "lyrics_shape_prior_plus_audio_novelty_on_bar_grid",
        "first_sustained_vocal_start_seconds": vocal_start_seconds,
        "intro_boundary_vocal_anchor_seconds": vocal_anchor,
    }


def build_song_structure_proposal(
    audio_path: Path,
    lyrics_path: Path,
    *,
    bpm: float | None = None,
    vocal_path: Path | None = None,
) -> dict[str, Any]:
    """Use lyric order as semantic evidence and audio features for timing."""

    if bpm is not None and not 20.0 <= bpm <= 400.0:
        raise ValueError("bpm must be between 20 and 400")
    audio = Path(audio_path).resolve()
    lyrics = parse_structured_lyrics(Path(lyrics_path))
    vocal = Path(vocal_path).resolve() if vocal_path is not None else None
    vocal_start = _first_sustained_vocal_start(vocal) if vocal is not None else None
    timing = _audio_boundaries(audio, lyrics["sections"], bpm, vocal_start)
    times = timing["boundary_times_seconds"]
    regions = []
    for index, section in enumerate(lyrics["sections"]):
        regions.append(
            {
                **section,
                "start_seconds": times[index],
                "end_seconds": times[index + 1],
                "duration_seconds": times[index + 1] - times[index],
                "boundary_source": "lyrics_shape_prior_plus_audio_novelty_on_bar_grid",
            }
        )
    audio_sha256 = _sha256(audio)
    vocal_sha256 = _sha256(vocal) if vocal is not None else None
    identity = {
        "algorithm_version": ALGORITHM_VERSION,
        "audio_sha256": audio_sha256,
        "lyrics_sha256": lyrics["sha256"],
        "vocal_sha256": vocal_sha256,
        "bpm": bpm,
        "regions": [(region["label"], round(region["start_seconds"], 6)) for region in regions],
    }
    structure_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    evidence_values = [entry["relative_to_p90"] for entry in timing["boundary_evidence"]]
    confidence = min(1.0, max(0.0, sum(min(value, 1.0) for value in evidence_values) / max(1, len(evidence_values))))
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_song_structure_proposal",
        "structure_id": structure_id,
        "execute": False,
        "review_status": "user_approval_required",
        "algorithm_version": ALGORITHM_VERSION,
        "source": {
            "audio_path": str(audio),
            "audio_sha256": audio_sha256,
            "lyrics_path": lyrics["file_path"],
            "lyrics_sha256": lyrics["sha256"],
            "vocal_path": str(vocal) if vocal is not None else None,
            "vocal_sha256": vocal_sha256,
        },
        "regions": regions,
        "timing_evidence": timing,
        "confidence": {
            "section_order": 1.0,
            "boundary_timing": confidence,
            "note": "Labels/order come from lyrics; boundaries are audio estimates requiring review.",
        },
        "warnings": lyrics["warnings"],
        "verification": {
            "lyrics_parsed": True,
            "signal_analyzed": True,
            "state_verified": False,
            "perceptually_evaluated": False,
        },
    }


def build_structure_region_payload(
    proposal: Mapping[str, Any], approved_structure_id: str
) -> dict[str, Any]:
    if proposal.get("structure_id") != approved_structure_id:
        raise ValueError("approved structure id does not match the current proposal")
    regions = proposal.get("regions")
    if not isinstance(regions, list) or len(regions) < 2:
        raise ValueError("proposal contains no usable regions")
    return {
        "structure_id": approved_structure_id,
        "audio_sha256": proposal["source"]["audio_sha256"],
        "lyrics_sha256": proposal["source"]["lyrics_sha256"],
        "regions": [
            {
                "name": f"\u200b{region['label']}",
                "display_name": region["label"],
                "kind": region["kind"],
                "start_seconds": region["start_seconds"],
                "end_seconds": region["end_seconds"],
            }
            for region in regions
        ],
        "replace_existing_pampapilot_regions": True,
    }
