"""Build a deterministic, DAW-independent manifest for one song."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median
from typing import Any, Literal

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT, discover_song_media, resolve_output_directory
from .midi_cleanup import analyze_midi_file


@dataclass(frozen=True, slots=True)
class SongPreparationConfig:
    bpm: float
    numerator: int = 4
    denominator: int = 4
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"] = "suno_stems"
    analysis_level: Literal["metadata", "signal"] = "metadata"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_metadata(path: Path) -> dict[str, Any]:
    import soundfile as sf

    info = sf.info(path)
    return {
        "file_name": path.name,
        "file_path": str(path.resolve()),
        "sha256": _sha256(path),
        "sample_rate_hz": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
        "duration_seconds": info.duration,
        "format": info.format,
        "subtype": info.subtype,
    }


def _track_label(path: Path) -> str:
    label = re.sub(r"^\s*\d+\s*[-_. ]*", "", path.stem)
    return label.replace("_", " ").strip() or path.stem


def _track_order(path: Path) -> tuple[int, str]:
    match = re.match(r"^\s*(\d+)", path.stem)
    return (int(match.group(1)) if match else 10_000, path.name.casefold())


def classify_stem(path: Path) -> str:
    name = _track_label(path).casefold()
    if "backing" in name and ("vocal" in name or "voice" in name):
        return "backing_vocals"
    if any(token in name for token in ("coral", "choir", "chorus")):
        return "choir"
    if any(token in name for token in ("vocal", "voice", "lead vox")):
        return "lead_vocal"
    if "bass" in name or "bajo" in name:
        return "bass"
    if any(token in name for token in ("drum", "bateria", "batería")):
        return "drums"
    if any(token in name for token in ("percussion", "percusion", "percusión")):
        return "percussion"
    if any(token in name for token in ("guitar", "guitarra")):
        return "guitar"
    if any(token in name for token in ("keyboard", "piano", "keys", "teclado")):
        return "keys"
    if any(token in name for token in ("synth", "sintetizador")):
        return "synth"
    return "other"


def _validate_config(config: SongPreparationConfig) -> None:
    if not 20.0 <= config.bpm <= 400.0:
        raise ValueError("bpm must be between 20 and 400")
    if not 1 <= config.numerator <= 32:
        raise ValueError("time signature numerator must be between 1 and 32")
    if config.denominator not in {1, 2, 4, 8, 16, 32}:
        raise ValueError("time signature denominator must be a power of two up to 32")


def _issue(
    severity: Literal["error", "warning", "info"],
    code: str,
    message: str,
    files: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if files:
        result["files"] = files
    return result


def _existing_midi_cleanup(
    midi_path: Path, session_midi_directory: Path
) -> dict[str, Any] | None:
    report_path = session_midi_directory / f"{midi_path.stem} - cleanup-report.json"
    if not report_path.is_file():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "report_path": str(report_path.resolve()),
            "status": "invalid_report",
        }
    current_hash = _sha256(midi_path)
    report_hash = report.get("inputs", {}).get("midi_sha256")
    return {
        "report_path": str(report_path.resolve()),
        "status": "current" if report_hash == current_hash else "stale",
        "source_hash_matches": report_hash == current_hash,
        "clean_safe_path": report.get("clean_safe", {}).get("path"),
        "reconstructed_path": report.get("reconstructed", {}).get("path"),
        "safe_change_counts": report.get("clean_safe", {}).get("change_counts", {}),
        "reconstruction_change_counts": report.get("reconstructed", {}).get(
            "change_counts", {}
        ),
    }


def build_song_manifest(
    song_name: str,
    config: SongPreparationConfig,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Analyze assets and return a manifest without writing anything."""
    _validate_config(config)
    workspace_root = workspace_root.resolve()
    discovery = discover_song_media(song_name, workspace_root=workspace_root)
    stem_paths = sorted((Path(value) for value in discovery["stems"]), key=_track_order)
    reference_paths = [Path(value) for value in discovery["references"]]
    midi_paths = [Path(value) for value in discovery["midi_files"]]
    session_root = resolve_output_directory(
        workspace_root / "sessions" / str(discovery["song_name"]),
        workspace_root=workspace_root,
    )
    session_midi_directory = session_root / "midi"
    issues: list[dict[str, Any]] = []

    if not stem_paths:
        issues.append(_issue("error", "no_stems", "No WAV stems were found."))
    if not reference_paths:
        issues.append(
            _issue("warning", "no_reference", "No full-song reference WAV was found.")
        )
    elif len(reference_paths) > 1:
        issues.append(
            _issue(
                "warning",
                "multiple_references",
                "More than one likely reference was found.",
                [str(path) for path in reference_paths],
            )
        )

    analyze = analyze_audio_file if config.analysis_level == "signal" else _audio_metadata
    stems: list[dict[str, Any]] = []
    base_labels = [_track_label(path) for path in stem_paths]
    label_totals = Counter(label.casefold() for label in base_labels)
    label_indexes: Counter[str] = Counter()
    for order, path in enumerate(stem_paths, start=1):
        metrics = analyze(path)
        base_label = _track_label(path)
        label_key = base_label.casefold()
        label_indexes[label_key] += 1
        suggested_name = (
            f"{base_label} {label_indexes[label_key]}"
            if label_totals[label_key] > 1
            else base_label
        )
        stems.append(
            {
                "order": order,
                "role": classify_stem(path),
                "suggested_track_name": suggested_name,
                "import": {
                    "file_path": str(path.resolve()),
                    "position_seconds": 0.0,
                    "timebase": "time",
                },
                "audio": metrics,
            }
        )

    references = [analyze(path) for path in reference_paths]
    durations = [stem["audio"]["duration_seconds"] for stem in stems]
    sample_rates = Counter(stem["audio"]["sample_rate_hz"] for stem in stems)
    channel_counts = Counter(stem["audio"]["channels"] for stem in stems)
    if durations:
        typical_duration = float(median(durations))
        for stem in stems:
            difference = abs(stem["audio"]["duration_seconds"] - typical_duration)
            if difference > max(0.25, typical_duration * 0.005):
                issues.append(
                    _issue(
                        "warning",
                        "stem_duration_mismatch",
                        f"Stem duration differs from the median by {difference:.3f} seconds.",
                        [stem["audio"]["file_path"]],
                    )
                )
    else:
        typical_duration = None
    if len(sample_rates) > 1:
        issues.append(
            _issue("warning", "mixed_sample_rates", "Stems use different sample rates.")
        )
    if typical_duration is not None:
        for reference in references:
            difference = abs(reference["duration_seconds"] - typical_duration)
            if difference > max(0.5, typical_duration * 0.01):
                issues.append(
                    _issue(
                        "warning",
                        "reference_duration_mismatch",
                        f"Reference duration differs from the stem median by {difference:.3f} seconds.",
                        [reference["file_path"]],
                    )
                )
            if sample_rates and reference["sample_rate_hz"] not in sample_rates:
                issues.append(
                    _issue(
                        "warning",
                        "reference_sample_rate_mismatch",
                        "Reference sample rate differs from every stem.",
                        [reference["file_path"]],
                    )
                )

    duplicate_hashes: dict[str, list[str]] = {}
    for stem in stems:
        duplicate_hashes.setdefault(stem["audio"]["sha256"], []).append(
            stem["audio"]["file_path"]
        )
    for paths in duplicate_hashes.values():
        if len(paths) > 1:
            issues.append(
                _issue(
                    "warning",
                    "identical_stem_files",
                    "Two or more stems are byte-for-byte identical.",
                    paths,
                )
            )

    midi_items: list[dict[str, Any]] = []
    pair_by_midi = {pair["midi"]: pair for pair in discovery["suggested_pairs"]}
    for path in midi_paths:
        analysis = analyze_midi_file(path)
        midi_bpm = analysis["structure"]["inferred_bpm"]
        if abs(midi_bpm - config.bpm) > 1.0:
            issues.append(
                _issue(
                    "warning",
                    "midi_tempo_mismatch",
                    f"MIDI median tempo {midi_bpm:.3f} differs from confirmed {config.bpm:.3f} BPM.",
                    [str(path.resolve())],
                )
            )
        pair = pair_by_midi.get(str(path.resolve()))
        if not pair or not pair.get("audio"):
            issues.append(
                _issue(
                    "warning",
                    "midi_without_audio_pair",
                    "No matching stem was found for a MIDI file.",
                    [str(path.resolve())],
                )
            )
        midi_items.append(
            {
                "file_path": str(path.resolve()),
                "paired_audio_path": None if pair is None else pair.get("audio"),
                "pair_match_score": 0.0 if pair is None else pair.get("match_score", 0.0),
                "analysis": analysis,
                "cleanup": _existing_midi_cleanup(path, session_midi_directory),
            }
        )

    if config.analysis_level == "signal":
        for stem in stems:
            if stem["audio"].get("samples_at_or_above_0_dbfs", 0) > 0:
                issues.append(
                    _issue(
                        "warning",
                        "samples_at_or_above_0_dbfs",
                        "Stem contains samples at or above 0 dBFS.",
                        [stem["audio"]["file_path"]],
                    )
                )

    severity_counts = Counter(issue["severity"] for issue in issues)
    status = (
        "blocked"
        if severity_counts["error"]
        else "ready_with_warnings" if severity_counts["warning"] else "ready"
    )
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_song_manifest",
        "metrics_are_observations_not_mix_decisions": True,
        "song": {
            "name": discovery["song_name"],
            "bpm": config.bpm,
            "time_signature": [config.numerator, config.denominator],
            "source_kind": config.source_kind,
        },
        "configuration": asdict(config),
        "validation": {
            "status": status,
            "issue_counts": dict(severity_counts),
            "issues": issues,
        },
        "summary": {
            "stem_count": len(stems),
            "midi_count": len(midi_items),
            "reference_count": len(references),
            "typical_duration_seconds": typical_duration,
            "sample_rates": {str(key): value for key, value in sample_rates.items()},
            "channel_counts": {str(key): value for key, value in channel_counts.items()},
            "role_counts": dict(Counter(stem["role"] for stem in stems)),
        },
        "stems": stems,
        "midi": midi_items,
        "references": references,
        "mix_policy": {
            "preserve_source_levels": config.source_kind == "suno_stems",
            "normalize_individual_stems": False,
            "reason": (
                "Suno stems inherit relative balance from an already mixed source."
                if config.source_kind == "suno_stems"
                else "No normalization is applied during intake."
            ),
        },
        "reaper_import_plan": {
            "execute": False,
            "project_name": discovery["song_name"],
            "bpm": config.bpm,
            "time_signature": [config.numerator, config.denominator],
            "audio_timebase": "time",
            "tracks": [
                {
                    "order": stem["order"],
                    "track_name": stem["suggested_track_name"],
                    "role": stem["role"],
                    "initial_volume_db": 0.0,
                    "initial_pan": 0.0,
                    "muted": False,
                    **stem["import"],
                }
                for stem in stems
            ],
            "reference_track": (
                None
                if not references
                else {
                    "track_name": "REFERENCE",
                    "file_path": references[0]["file_path"],
                    "position_seconds": 0.0,
                    "muted": True,
                }
            ),
        },
        "paths": {
            "session_root": str(session_root.resolve()),
            "manifest": str((session_root / "song-manifest.json").resolve()),
        },
        "outputs_written": False,
    }


def write_song_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    """Atomically replace a generated manifest inside sessions/."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, output_path)


def prepare_song(
    song_name: str,
    config: SongPreparationConfig,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    manifest = build_song_manifest(song_name, config, workspace_root=workspace_root)
    output_path = resolve_output_directory(
        Path(manifest["paths"]["session_root"]), workspace_root=workspace_root
    ) / "song-manifest.json"
    manifest["outputs_written"] = True
    write_song_manifest(manifest, output_path)
    return manifest
