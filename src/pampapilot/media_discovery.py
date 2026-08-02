"""Safe discovery and path policy for offline song assets."""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Iterable
import unicodedata


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class MediaPathError(ValueError):
    """A requested path escapes the offline media workspace."""


def _resolve_candidate(raw_path: str | Path, workspace_root: Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.resolve()


def _require_within(candidate: Path, roots: Iterable[Path]) -> Path:
    resolved_roots = tuple(root.resolve() for root in roots)
    if not any(candidate == root or candidate.is_relative_to(root) for root in resolved_roots):
        allowed = ", ".join(str(root) for root in resolved_roots)
        raise MediaPathError(f"path is outside allowed roots: {allowed}")
    return candidate


def resolve_input_file(
    raw_path: str | Path,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
    suffixes: Iterable[str] | None = None,
) -> Path:
    workspace_root = workspace_root.resolve()
    candidate = _require_within(
        _resolve_candidate(raw_path, workspace_root),
        (workspace_root / "media", workspace_root / "sessions"),
    )
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    if suffixes is not None and candidate.suffix.casefold() not in {
        suffix.casefold() for suffix in suffixes
    }:
        raise MediaPathError(f"unsupported file type: {candidate.suffix}")
    return candidate


def resolve_output_directory(
    raw_path: str | Path,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> Path:
    workspace_root = workspace_root.resolve()
    return _require_within(
        _resolve_candidate(raw_path, workspace_root),
        (workspace_root / "sessions",),
    )


def _normalized_name(value: str) -> str:
    value = re.sub(r"^\s*\d+\s*[-_. ]*", "", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    tokens = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    return " ".join(dict.fromkeys(tokens))


def _find_named_directory(parent: Path, name: str) -> Path | None:
    if not parent.is_dir():
        return None
    expected = name.casefold()
    return next(
        (child for child in parent.iterdir() if child.is_dir() and child.name.casefold() == expected),
        None,
    )


def _files(directory: Path | None, suffixes: set[str]) -> list[Path]:
    if directory is None:
        return []
    return sorted(
        (
            path.resolve()
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.casefold() in suffixes
        ),
        key=lambda path: path.name.casefold(),
    )


def discover_song_media(
    song_name: str,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, object]:
    """Find stems, MIDI files and likely MIDI/WAV pairs for one song."""
    if not song_name.strip() or len(song_name) > 128:
        raise ValueError("song_name must contain 1 to 128 characters")
    if any(separator in song_name for separator in ("/", "\\")) or song_name in {".", ".."}:
        raise ValueError("song_name must be a name, not a path")
    if re.search(r"[<>:\"|?*\x00-\x1f]", song_name):
        raise ValueError("song_name contains characters that are invalid on Windows")

    workspace_root = workspace_root.resolve()
    inbox = workspace_root / "media" / "inbox"
    stems_directory = _find_named_directory(inbox / "stems", song_name)
    midi_directory = _find_named_directory(inbox / "midi", song_name)
    stems = _files(stems_directory, {".wav"})
    midi_files = _files(midi_directory, {".mid", ".midi"})
    references = _files(workspace_root / "media" / "references", {".wav"})
    normalized_song = _normalized_name(song_name)
    matching_references = [
        path
        for path in references
        if SequenceMatcher(None, normalized_song, _normalized_name(path.stem)).ratio() >= 0.8
    ]

    pairs: list[dict[str, object]] = []
    for midi_path in midi_files:
        midi_key = _normalized_name(midi_path.stem)
        ranked = sorted(
            (
                (
                    SequenceMatcher(None, midi_key, _normalized_name(stem.stem)).ratio(),
                    stem,
                )
                for stem in stems
            ),
            key=lambda item: (-item[0], item[1].name.casefold()),
        )
        if ranked and ranked[0][0] >= 0.35:
            score, audio_path = ranked[0]
            pairs.append(
                {
                    "midi": str(midi_path),
                    "audio": str(audio_path),
                    "match_score": round(score, 4),
                    "match_basis": "normalized_filename",
                }
            )
        else:
            pairs.append(
                {
                    "midi": str(midi_path),
                    "audio": None,
                    "match_score": 0.0,
                    "match_basis": "no_candidate",
                }
            )

    canonical_name = (
        stems_directory.name
        if stems_directory is not None
        else midi_directory.name if midi_directory is not None else song_name.strip()
    )
    return {
        "song_name": canonical_name,
        "stems_directory": None if stems_directory is None else str(stems_directory.resolve()),
        "midi_directory": None if midi_directory is None else str(midi_directory.resolve()),
        "stems": [str(path) for path in stems],
        "midi_files": [str(path) for path in midi_files],
        "references": [str(path) for path in matching_references],
        "suggested_pairs": pairs,
        "suggested_output_directory": str(
            (workspace_root / "sessions" / canonical_name / "midi").resolve()
        ),
        "complete_pair_count": sum(pair["audio"] is not None for pair in pairs),
    }
