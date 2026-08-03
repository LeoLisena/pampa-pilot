"""Lyrics-guided, audio-timed song structure proposals."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import unicodedata

from .timeline_analysis import analyze_music_timeline


ALGORITHM_VERSION = "0.2"
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


def _contains_repeated_token_fragment(token: str) -> bool:
    if len(token) < 6:
        return False
    for size in range(2, len(token) // 2 + 1):
        if token[:size] == token[size:2 * size] or token[-size:] == token[-2 * size:-size]:
            return True
    return False


def _assess_lyrics_quality(sections: list[Mapping[str, Any]]) -> dict[str, Any]:
    section_scores = []
    for section in sections:
        text = str(section["lyrics_text"])
        tokens = re.findall(r"[^\W_]+", _normalized_label(text), flags=re.UNICODE)
        adjacent_duplicates = sum(
            left == right for left, right in zip(tokens, tokens[1:])
        )
        repeated_fragments = sum(_contains_repeated_token_fragment(token) for token in tokens)
        inline_brackets = text.count("[") + text.count("]")
        denominator = max(1, len(tokens))
        penalty = (
            2.5 * adjacent_duplicates / denominator
            + 2.0 * repeated_fragments / denominator
            + 0.18 * inline_brackets
        )
        score = max(0.0, min(1.0, 1.0 - penalty))
        section_scores.append(score)
        section["lyric_quality_score"] = round(score, 4)

    recurring: dict[str, list[str]] = {}
    for section in sections:
        family = "chorus" if section["kind"] in {"chorus", "final_chorus"} else str(section["kind"])
        if family in {"chorus", "pre_chorus"}:
            recurring.setdefault(family, []).append(_normalized_label(str(section["lyrics_text"])))
    similarities = [
        SequenceMatcher(None, left, right).ratio()
        for values in recurring.values() if len(values) > 1
        for left, right in itertools.combinations(values, 2)
    ]
    lexical_integrity = sum(section_scores) / max(1, len(section_scores))
    repeat_consistency = sum(similarities) / len(similarities) if similarities else None
    overall = (
        0.55 * lexical_integrity + 0.45 * repeat_consistency
        if repeat_consistency is not None else lexical_integrity
    )
    profile = "clean" if overall >= 0.85 else "uncertain" if overall >= 0.6 else "damaged"
    return {
        "profile": profile,
        "overall_score": round(overall, 4),
        "lexical_integrity": round(lexical_integrity, 4),
        "repeated_section_text_consistency": (
            round(repeat_consistency, 4) if repeat_consistency is not None else None
        ),
        "timing_policy": (
            "clean_lyrics_phrase_and_repeat_constraints"
            if profile == "clean" else "structural_tags_only_audio_dominant"
        ),
    }


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
    quality = _assess_lyrics_quality(sections)
    return {
        "file_path": str(lyric_path),
        "sha256": _sha256(lyric_path),
        "encoding": "utf-8",
        "sections": sections,
        "quality": quality,
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


def _load_specialist_analysis(path: Path) -> dict[str, Any]:
    specialist_path = Path(path).resolve()
    payload = json.loads(specialist_path.read_text(encoding="utf-8"))
    downbeats, segments = payload.get("downbeats"), payload.get("segments")
    if not isinstance(downbeats, list) or len(downbeats) < 2:
        raise ValueError("specialist analysis contains no usable downbeats")
    if not isinstance(segments, list) or len(segments) < 2:
        raise ValueError("specialist analysis contains no usable segments")
    normalized_downbeats = [float(value) for value in downbeats]
    if any(right <= left for left, right in zip(normalized_downbeats, normalized_downbeats[1:])):
        raise ValueError("specialist downbeats must be strictly increasing")

    def snap_to_downbeat(value: float) -> float:
        nearest = min(normalized_downbeats, key=lambda candidate: abs(candidate - value))
        return nearest if abs(nearest - value) <= 0.08 else value

    normalized_segments = []
    for segment in segments:
        start = snap_to_downbeat(float(segment["start"]))
        end = snap_to_downbeat(float(segment["end"]))
        if end <= start:
            raise ValueError("specialist segment end must be greater than start")
        normalized_segments.append(
            {"start": start, "end": end, "label": _normalized_label(str(segment["label"]))}
        )
    if any(
        right["start"] < left["start"]
        for left, right in zip(normalized_segments, normalized_segments[1:])
    ):
        raise ValueError("specialist segments must be chronological")
    return {
        "file_path": str(specialist_path),
        "sha256": _sha256(specialist_path),
        "provider": payload.get("provider", "all_in_one_compatible"),
        "bpm": payload.get("bpm"),
        "downbeats": normalized_downbeats,
        "segments": normalized_segments,
    }


def _specialist_anchor_map(
    sections: list[Mapping[str, Any]], specialist: Mapping[str, Any]
) -> dict[int, dict[str, Any]]:
    segments = list(specialist["segments"])
    chorus_segments = [segment for segment in segments if segment["label"] == "chorus"]
    verse_segments = [segment for segment in segments if segment["label"] == "verse"]
    verse_indexes = [index for index, section in enumerate(sections) if section["kind"] == "verse"]
    chorus_indexes = [
        index for index, section in enumerate(sections)
        if section["kind"] in {"chorus", "final_chorus"}
    ]
    anchors: dict[int, dict[str, Any]] = {
        0: {"time_seconds": 0.0, "source": "song_start"}
    }
    # Only as many early verse segments as the lyric declares are used. A
    # specialist can label the intimate half of a bridge as another verse.
    for section_index, segment in zip(verse_indexes, verse_segments):
        anchors[section_index] = {
            "time_seconds": segment["start"],
            "source": "specialist_verse_start",
            "specialist_label": segment["label"],
        }
    for occurrence, (section_index, segment) in enumerate(
        zip(chorus_indexes, chorus_segments), start=1
    ):
        anchors[section_index] = {
            "time_seconds": segment["start"],
            "source": "specialist_chorus_start",
            "specialist_label": segment["label"],
            "occurrence": occurrence,
        }
    for section_index, section in enumerate(sections):
        if section["kind"] not in {"bridge", "outro"} or section_index == 0:
            continue
        previous_chorus_count = sum(
            prior["kind"] in {"chorus", "final_chorus"}
            for prior in sections[:section_index]
        )
        if 0 < previous_chorus_count <= len(chorus_segments):
            segment = chorus_segments[previous_chorus_count - 1]
            anchors[section_index] = {
                "time_seconds": segment["end"],
                "source": f"specialist_{section['kind']}_after_chorus",
                "specialist_label": segment["label"],
            }
    return anchors


def _timeline_boundary_lookup(timeline: Mapping[str, Any]) -> dict[float, Mapping[str, Any]]:
    return {
        round(float(entry["time_seconds"]), 5): entry
        for entry in timeline["boundary_evidence"]
    }


def _role_segment_matrix(
    timeline: Mapping[str, Any], role: str, start: float, end: float, samples: int = 8
) -> Any | None:
    import numpy as np

    boundaries = np.asarray(timeline["interval_boundaries_seconds"], dtype=np.float64)
    first = max(0, int(np.searchsorted(boundaries, start, side="left")))
    last = min(len(boundaries) - 1, int(np.searchsorted(boundaries, end, side="left")))
    matrices = [
        np.asarray(stem["standardized_embedding"], dtype=np.float64)
        for stem in timeline["stems"] if stem["role"] == role
    ]
    if not matrices or last - first < 1:
        return None
    matrix = np.mean([item[first:last] for item in matrices], axis=0)
    source_x = np.linspace(0.0, 1.0, len(matrix))
    target_x = np.linspace(0.0, 1.0, samples)
    return np.column_stack(
        [np.interp(target_x, source_x, matrix[:, column]) for column in range(matrix.shape[1])]
    )


def _segment_similarity(
    timeline: Mapping[str, Any], first: tuple[float, float], second: tuple[float, float]
) -> float:
    import numpy as np

    weighted = []
    role_weights = {
        "drums": 1.2,
        "bass": 1.1,
        "keys": 1.0,
        "guitar": 1.0,
        "lead_vocal": 0.8,
        "backing_vocals": 0.6,
    }
    for role, weight in role_weights.items():
        left = _role_segment_matrix(timeline, role, *first)
        right = _role_segment_matrix(timeline, role, *second)
        if left is None or right is None:
            continue
        left_vector, right_vector = left.ravel(), right.ravel()
        denominator = float(np.linalg.norm(left_vector) * np.linalg.norm(right_vector))
        if denominator <= 1e-9:
            continue
        cosine = float(np.dot(left_vector, right_vector) / denominator)
        weighted.append((weight, max(0.0, min(1.0, (cosine + 1.0) / 2.0))))
    if not weighted:
        return 0.5
    return sum(weight * value for weight, value in weighted) / sum(weight for weight, _ in weighted)


def _candidate_local_scores(
    timeline: Mapping[str, Any], candidates: list[float]
) -> dict[float, dict[str, float]]:
    import numpy as np

    lookup = _timeline_boundary_lookup(timeline)
    changes = np.asarray(
        [float(lookup[round(candidate, 5)]["multistem_change"]) for candidate in candidates]
    )
    minimum, maximum = float(np.min(changes)), float(np.max(changes))
    result = {}
    for candidate, change in zip(candidates, changes):
        evidence = lookup[round(candidate, 5)]
        role_delta = evidence["role_energy_delta_db"]
        rhythm_rise = (
            max(0.0, float(role_delta.get("drums", 0.0)))
            + max(0.0, float(role_delta.get("bass", 0.0)))
        )
        vocal_shift = abs(float(role_delta.get("lead_vocal", 0.0)))
        normalized_change = (float(change) - minimum) / max(maximum - minimum, 1e-9)
        local = (
            0.35 * normalized_change
            + 0.30 * float(evidence["change_consensus"])
            + 0.20 * math.tanh(rhythm_rise / 12.0)
            + 0.15 * math.tanh(vocal_shift / 10.0)
        )
        result[candidate] = {
            "score": local,
            "normalized_multistem_change": normalized_change,
            "change_consensus": float(evidence["change_consensus"]),
            "rhythm_rise_score": math.tanh(rhythm_rise / 12.0),
            "vocal_shift_score": math.tanh(vocal_shift / 10.0),
        }
    return result


def _select_pre_choruses(
    sections: list[Mapping[str, Any]],
    anchors: Mapping[int, Mapping[str, Any]],
    timeline: Mapping[str, Any],
    lyrics_quality: Mapping[str, Any],
) -> tuple[dict[int, float], dict[int, dict[str, Any]]]:
    import numpy as np

    grid = list(timeline["interval_boundaries_seconds"])
    pre_indexes = [index for index, section in enumerate(sections) if section["kind"] == "pre_chorus"]
    candidate_sets: list[list[float]] = []
    local_sets: list[dict[float, dict[str, float]]] = []
    usable_indexes = []
    for section_index in pre_indexes:
        if section_index - 1 not in anchors or section_index + 1 not in anchors:
            continue
        start = float(anchors[section_index - 1]["time_seconds"])
        end = float(anchors[section_index + 1]["time_seconds"])
        inside = [value for value in grid if start < value < end]
        # A clean lyric line normally needs about one bar at this granularity.
        # This is a feasibility constraint, not a timing prior: audio still
        # chooses the exact downbeat, but a four-line pre-chorus cannot collapse
        # into two bars merely because the bass has a strong fill there.
        verse_lines = int(sections[section_index - 1].get("lyric_line_count", 0))
        pre_lines = int(sections[section_index].get("lyric_line_count", 0))
        minimum_verse_bars = max(3, min(6, verse_lines))
        minimum_pre_bars = max(3, min(6, pre_lines))
        candidates = [
            value for position, value in enumerate(inside, start=1)
            if position >= minimum_verse_bars
            and len(inside) - position + 1 >= minimum_pre_bars
        ]
        if not candidates:
            continue
        usable_indexes.append(section_index)
        candidate_sets.append(candidates)
        local_sets.append(_candidate_local_scores(timeline, candidates))
    if not candidate_sets:
        return {}, {}

    best_score = -math.inf
    best_combination: tuple[float, ...] | None = None
    best_details: dict[str, float] = {}
    for combination in itertools.product(*candidate_sets):
        local = float(np.mean([
            local_scores[candidate]["score"]
            for local_scores, candidate in zip(local_sets, combination)
        ]))
        pre_segments, verse_segments, pre_lengths = [], [], []
        for section_index, candidate in zip(usable_indexes, combination):
            verse_start = float(anchors[section_index - 1]["time_seconds"])
            chorus_start = float(anchors[section_index + 1]["time_seconds"])
            verse_segments.append((verse_start, candidate))
            pre_segments.append((candidate, chorus_start))
            pre_lengths.append(chorus_start - candidate)
        pre_similarity = float(np.mean([
            _segment_similarity(timeline, left, right)
            for left, right in itertools.combinations(pre_segments, 2)
        ])) if len(pre_segments) > 1 else 0.5
        verse_similarity = float(np.mean([
            _segment_similarity(timeline, left, right)
            for left, right in itertools.combinations(verse_segments, 2)
        ])) if len(verse_segments) > 1 else 0.5
        length_consistency = (
            math.exp(-float(np.std(pre_lengths)) / max(float(np.mean(pre_lengths)), 1e-9))
            if len(pre_lengths) > 1 else 0.5
        )
        if lyrics_quality["profile"] == "clean":
            weights = {"local": 0.35, "pre": 0.30, "verse": 0.15, "length": 0.20}
        else:
            weights = {"local": 0.50, "pre": 0.30, "verse": 0.15, "length": 0.05}
        score = (
            weights["local"] * local + weights["pre"] * pre_similarity
            + weights["verse"] * verse_similarity + weights["length"] * length_consistency
        )
        if score > best_score:
            best_score, best_combination = score, combination
            best_details = {
                "ensemble_score": score,
                "local_evidence_score": local,
                "repeated_pre_chorus_similarity": pre_similarity,
                "repeated_verse_similarity": verse_similarity,
                "pre_chorus_length_consistency": length_consistency,
                "lyrics_profile": str(lyrics_quality["profile"]),
                "score_weights": weights,
            }
    assert best_combination is not None
    selected = dict(zip(usable_indexes, best_combination))
    details = {
        section_index: {
            **best_details,
            **local_sets[position][candidate],
            "candidate_count": len(candidate_sets[position]),
        }
        for position, (section_index, candidate) in enumerate(zip(usable_indexes, best_combination))
    }
    return selected, details


def _ensemble_boundaries(
    sections: list[Mapping[str, Any]],
    timeline: Mapping[str, Any],
    specialist: Mapping[str, Any],
    lyrics_quality: Mapping[str, Any],
) -> dict[str, Any]:
    anchors = _specialist_anchor_map(sections, specialist)
    pre_selected, pre_details = _select_pre_choruses(
        sections, anchors, timeline, lyrics_quality
    )
    for section_index, time_seconds in pre_selected.items():
        anchors[section_index] = {
            "time_seconds": time_seconds,
            "source": "multistem_repetition_and_local_transition",
            **pre_details[section_index],
        }
    duration = float(timeline["duration_seconds"])
    grid = list(timeline["interval_boundaries_seconds"])
    lookup = _timeline_boundary_lookup(timeline)
    for section_index in range(1, len(sections)):
        if section_index in anchors:
            continue
        previous = max(index for index in anchors if index < section_index)
        following = min((index for index in anchors if index > section_index), default=len(sections))
        start = float(anchors[previous]["time_seconds"])
        end = float(anchors[following]["time_seconds"]) if following < len(sections) else duration
        fraction = (section_index - previous) / (following - previous)
        expected = start + (end - start) * fraction
        candidates = [value for value in grid if start < value < end]
        if not candidates:
            chosen = expected
        else:
            local = _candidate_local_scores(timeline, candidates)
            chosen = max(
                candidates,
                key=lambda value: local[value]["score"]
                - 0.2 * abs(value - expected) / max(end - start, 1e-9),
            )
        anchors[section_index] = {
            "time_seconds": chosen,
            "source": "multistem_fallback",
            "shape_expected_seconds": expected,
        }
    times = [float(anchors[index]["time_seconds"]) for index in range(len(sections))] + [duration]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("ensemble produced non-monotonic section boundaries")
    boundary_evidence = []
    for section_index, time_seconds in enumerate(times[1:-1], start=1):
        entry = lookup.get(round(time_seconds, 5), {})
        source = anchors[section_index]["source"]
        confidence = 0.9 if source.startswith("specialist_") else 0.72
        confidence = min(0.98, confidence + 0.08 * float(entry.get("change_consensus", 0.0)))
        boundary_evidence.append(
            {
                "section_index": section_index,
                "section_label": sections[section_index]["label"],
                "time_seconds": time_seconds,
                "source": source,
                "confidence": round(confidence, 4),
                "multistem_change": entry.get("multistem_change"),
                "change_consensus": entry.get("change_consensus"),
                "role_changes": entry.get("role_changes"),
                "role_energy_delta_db": entry.get("role_energy_delta_db"),
                "selection_details": {
                    key: value for key, value in anchors[section_index].items()
                    if key not in {"time_seconds", "source"}
                },
            }
        )
    return {
        "duration_seconds": duration,
        "boundary_times_seconds": times,
        "boundary_evidence": boundary_evidence,
        "tempo_grid_bpm": timeline["bpm"],
        "grid_source": timeline["grid_source"],
        "method": "lyrics_constrained_multistem_repetition_plus_specialist",
        "specialist": {
            "provider": specialist["provider"],
            "file_path": specialist["file_path"],
            "sha256": specialist["sha256"],
        },
        "timeline_summary": {
            "analysis_version": timeline["analysis_version"],
            "stem_count": len(timeline["stems"]),
            "roles": sorted({stem["role"] for stem in timeline["stems"]}),
            "interval_count": len(timeline["interval_boundaries_seconds"]) - 1,
            "reuse_contract": timeline["reuse_contract"],
        },
        "lyrics_quality": dict(lyrics_quality),
    }


def build_song_structure_proposal(
    audio_path: Path,
    lyrics_path: Path,
    *,
    bpm: float | None = None,
    vocal_path: Path | None = None,
    stem_paths: Iterable[Path] | None = None,
    specialist_analysis_path: Path | None = None,
) -> dict[str, Any]:
    """Use lyric order as semantic evidence and audio features for timing."""

    if bpm is not None and not 20.0 <= bpm <= 400.0:
        raise ValueError("bpm must be between 20 and 400")
    audio = Path(audio_path).resolve()
    lyrics = parse_structured_lyrics(Path(lyrics_path))
    vocal = Path(vocal_path).resolve() if vocal_path is not None else None
    vocal_start = _first_sustained_vocal_start(vocal) if vocal is not None else None
    stems = (
        sorted((Path(path).resolve() for path in stem_paths), key=lambda path: str(path).casefold())
        if stem_paths is not None else []
    )
    specialist = (
        _load_specialist_analysis(Path(specialist_analysis_path))
        if specialist_analysis_path is not None else None
    )
    if stems and specialist is not None:
        if bpm is None:
            raise ValueError("bpm is required for multistem ensemble analysis")
        if specialist["bpm"] is not None and abs(float(specialist["bpm"]) - bpm) > 0.5:
            raise ValueError("specialist BPM does not match requested BPM")
        timeline = analyze_music_timeline(stems, bpm=bpm, downbeats=specialist["downbeats"])
        timing = _ensemble_boundaries(
            lyrics["sections"], timeline, specialist, lyrics["quality"]
        )
    else:
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
                "boundary_source": timing["method"],
            }
        )
    audio_sha256 = _sha256(audio)
    vocal_sha256 = _sha256(vocal) if vocal is not None else None
    identity = {
        "algorithm_version": ALGORITHM_VERSION,
        "audio_sha256": audio_sha256,
        "lyrics_sha256": lyrics["sha256"],
        "vocal_sha256": vocal_sha256,
        "stem_sha256": [_sha256(path) for path in stems],
        "specialist_sha256": specialist["sha256"] if specialist is not None else None,
        "bpm": bpm,
        "regions": [(region["label"], round(region["start_seconds"], 6)) for region in regions],
    }
    structure_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    evidence_values = [
        float(entry.get("confidence", min(float(entry.get("relative_to_p90", 0.0)), 1.0)))
        for entry in timing["boundary_evidence"]
    ]
    confidence = min(1.0, max(0.0, sum(evidence_values) / max(1, len(evidence_values))))
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
            "stem_paths": [str(path) for path in stems],
            "specialist_analysis_path": specialist["file_path"] if specialist is not None else None,
            "specialist_analysis_sha256": specialist["sha256"] if specialist is not None else None,
        },
        "regions": regions,
        "timing_evidence": timing,
        "confidence": {
            "section_order": 1.0,
            "boundary_timing": confidence,
            "note": "Labels/order come from lyrics; boundaries are audio estimates requiring review.",
        },
        "warnings": lyrics["warnings"],
        "lyrics_quality": lyrics["quality"],
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
