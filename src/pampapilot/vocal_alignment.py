"""Optional phrase alignment for clean lyrics against an isolated vocal stem."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import itertools
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
import unicodedata

from .accelerator import select_inference_backend


ALIGNMENT_VERSION = "0.1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def _best_word_alignment(
    target_text: str, words: list[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Find a lyric phrase in imperfect ASR output without trusting timestamps blindly."""

    target = _tokens(target_text)
    recognized = [token for word in words for token in _tokens(str(word["word"]))]
    if not target or not recognized:
        return None
    # faster-whisper normally emits one lexical token per word. If punctuation
    # or contractions split one item, retain a conservative index map.
    token_to_word = []
    for word_index, word in enumerate(words):
        token_to_word.extend([word_index] * max(1, len(_tokens(str(word["word"])))))
    best: tuple[float, int, int] | None = None
    minimum = max(2, round(len(target) * 0.7))
    maximum = min(len(recognized), round(len(target) * 1.3))
    for length in range(minimum, maximum + 1):
        for first in range(0, len(recognized) - length + 1):
            candidate = recognized[first:first + length]
            ratio = _sequence_ratio(target, candidate)
            if best is None or ratio > best[0]:
                best = (ratio, first, first + length)
    if best is None:
        return None
    ratio, first_token, last_token = best
    first_word = token_to_word[min(first_token, len(token_to_word) - 1)]
    last_word = token_to_word[min(last_token - 1, len(token_to_word) - 1)]
    selected = words[first_word:last_word + 1]
    probabilities = [float(word.get("probability", 0.0)) for word in selected]
    word_confidence = sum(probabilities) / max(1, len(probabilities))
    confidence = 0.65 * ratio + 0.35 * word_confidence
    return {
        "detected_start_seconds": float(selected[0]["start"]),
        "detected_end_seconds": float(selected[-1]["end"]),
        "text_match_score": round(ratio, 5),
        "mean_word_probability": round(word_confidence, 5),
        "confidence": round(confidence, 5),
        "recognized_text": " ".join(str(word["word"]).strip() for word in selected),
        "matched_word_count": len(selected),
    }


def _sequence_ratio(left: list[str], right: list[str]) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, left, right).ratio()


def _default_transcriber(
    vocal_path: Path,
    windows: list[Mapping[str, Any]],
    *,
    model_name: str,
    model_cache: Path,
    device: str,
    compute_type: str | None,
    cuda_runtime_root: Path,
    language: str,
) -> list[list[dict[str, Any]]]:
    try:
        import truststore

        truststore.inject_into_ssl()
        import librosa
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "vocal alignment requires the optional lyrics-alignment dependencies"
        ) from error

    signal, sample_rate = librosa.load(vocal_path, sr=16_000, mono=True)
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type or ("float16" if device == "cuda" else "int8"),
        download_root=str(model_cache),
        cpu_threads=12,
    )
    results = []
    for window in windows:
        start, end = float(window["window_start_seconds"]), float(window["window_end_seconds"])
        clip = signal[round(start * sample_rate):round(end * sample_rate)]
        segments, _ = model.transcribe(
            clip,
            language=language,
            beam_size=5,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=str(window["prompt"]),
            hotwords=str(window["target_text"]),
        )
        words = []
        for segment in segments:
            for word in segment.words or []:
                words.append(
                    {
                        "word": word.word,
                        "start": float(word.start + start),
                        "end": float(word.end + start),
                        "probability": float(word.probability),
                    }
                )
        results.append(words)
    return results


def build_vocal_lyric_alignment(
    vocal_path: Path,
    lyrics_path: Path,
    sections: list[Mapping[str, Any]],
    regions: list[Mapping[str, Any]],
    *,
    target_kinds: Iterable[str] = ("pre_chorus",),
    model_name: str = "large-v3",
    model_cache: Path = Path(".runtime/models/faster-whisper"),
    device: str = "auto",
    compute_type: str | None = None,
    cuda_runtime_root: Path = Path(".runtime/cuda"),
    language: str = "es",
    transcriber: Callable[..., list[list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    """Align selected clean lyric sections inside conservative proposal windows."""

    vocal, lyrics = Path(vocal_path).resolve(), Path(lyrics_path).resolve()
    targets = set(target_kinds)
    windows = []
    occurrence: dict[str, int] = {}
    for index, (section, region) in enumerate(zip(sections, regions)):
        kind = str(section["kind"])
        if kind not in targets or not str(section.get("lyrics_text", "")).strip():
            continue
        occurrence[kind] = occurrence.get(kind, 0) + 1
        following = regions[min(len(regions) - 1, index + 1)]
        window_start = max(0.0, float(region["start_seconds"]) - 4.0)
        window_end = min(
            float(regions[-1]["end_seconds"]), float(following["start_seconds"]) + 1.5
        )
        prompt_parts = [str(section["lyrics_text"])]
        if index + 1 < len(sections):
            next_lines = str(sections[index + 1].get("lyrics_text", "")).splitlines()
            prompt_parts.extend(next_lines[:1])
        windows.append(
            {
                "section_index": index,
                "section_label": section["label"],
                "section_kind": kind,
                "occurrence": occurrence[kind],
                "target_text": section["lyrics_text"],
                "prompt": "\n".join(prompt_parts),
                "window_start_seconds": window_start,
                "window_end_seconds": window_end,
                "baseline_start_seconds": float(region["start_seconds"]),
            }
        )
    if transcriber is None:
        backend = select_inference_backend(
            device, cuda_runtime_root=Path(cuda_runtime_root)
        )
        selected_device = str(backend["selected_device"])
        selected_compute_type = compute_type or str(backend["compute_type"])
        run = _default_transcriber
    else:
        backend = {
            "requested_device": device,
            "selected_device": "provider_supplied",
            "compute_type": compute_type,
            "cuda_available": None,
            "fallback_used": False,
        }
        selected_device, selected_compute_type = device, compute_type
        run = transcriber
    word_sets = run(
        vocal,
        windows,
        model_name=model_name,
        model_cache=Path(model_cache),
        device=selected_device,
        compute_type=selected_compute_type,
        cuda_runtime_root=Path(cuda_runtime_root),
        language=language,
    )
    alignments = []
    for window, words in zip(windows, word_sets):
        match = _best_word_alignment(str(window["target_text"]), words)
        alignments.append(
            {
                **{key: value for key, value in window.items() if key not in {"prompt", "target_text"}},
                "status": "matched" if match is not None and match["confidence"] >= 0.7 else "low_confidence",
                "match": match,
                "transcript_words": words,
            }
        )
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_vocal_lyric_alignment",
        "alignment_version": ALIGNMENT_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "vocal_path": str(vocal),
        "vocal_sha256": _sha256(vocal),
        "lyrics_path": str(lyrics),
        "lyrics_sha256": _sha256(lyrics),
        "model": {
            "name": model_name,
            "requested_device": device,
            "requested_compute_type": compute_type,
            "selected_device": backend["selected_device"],
            "selected_compute_type": backend["compute_type"],
            "cuda_available": backend["cuda_available"],
            "fallback_used": backend["fallback_used"],
            "cuda_runtime_root": str(Path(cuda_runtime_root).resolve()),
            "language": language,
        },
        "target_kinds": sorted(targets),
        "alignments": alignments,
        "observations_not_ground_truth": True,
    }


def write_vocal_lyric_alignment(report: Mapping[str, Any], output_path: Path) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
