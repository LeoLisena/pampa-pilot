"""Persistent, provider-neutral project analysis for the web and agent layers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .media_discovery import (
    WORKSPACE_ROOT,
    discover_song_media,
    resolve_output_directory,
)
from .song_diagnosis import SourceKind, diagnose_song


ANALYSIS_SCHEMA_VERSION = "0.1"
ANALYSIS_FILE_NAME = "song-diagnosis.json"
SUPPORTED_SOURCE_KINDS = {"suno_stems", "organic_multitrack", "unknown"}


def default_diagnosis_source(source_kind: str) -> SourceKind:
    """Use an explicit neutral policy when a mixed project lacks per-stem origins."""

    return source_kind if source_kind in SUPPORTED_SOURCE_KINDS else "unknown"  # type: ignore[return-value]


def source_overrides_from_metadata(
    metadata: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Read optional per-stem origins without guessing from instrument names."""

    raw = metadata.get("stem_sources", {})
    if not isinstance(raw, Mapping):
        return []
    return [
        {"track_name": str(name), "source_kind": str(source_kind)}
        for name, source_kind in sorted(raw.items(), key=lambda item: str(item[0]).casefold())
        if isinstance(name, str) and source_kind in SUPPORTED_SOURCE_KINDS
    ]


def _analysis_path(song_name: str, workspace_root: Path) -> Path:
    directory = resolve_output_directory(
        workspace_root / "sessions" / song_name / "analysis",
        workspace_root=workspace_root,
    )
    return directory / ANALYSIS_FILE_NAME


def _input_signature(song_name: str, workspace_root: Path) -> list[dict[str, Any]]:
    discovery = discover_song_media(song_name, workspace_root=workspace_root)
    signature = []
    for raw_path in discovery.get("stems", []):
        path = Path(str(raw_path))
        stat = path.stat()
        signature.append(
            {
                "file_name": path.name,
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )
    return sorted(signature, key=lambda item: item["file_name"].casefold())


def _normalized_overrides(
    values: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "track_name": str(value.get("track_name", "")),
                "source_kind": str(value.get("source_kind", "")),
            }
            for value in values
        ],
        key=lambda item: item["track_name"].casefold(),
    )


def _write_artifact(artifact: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def analyze_project_media(
    song_name: str,
    bpm: float,
    source_kind: str,
    source_overrides: Sequence[Mapping[str, str]] = (),
    *,
    knowledge_root: Path | None = None,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Analyze every stem, persist the evidence and never modify a DAW project."""

    workspace_root = workspace_root.resolve()
    diagnosis_source = default_diagnosis_source(source_kind)
    normalized_overrides = _normalized_overrides(source_overrides)
    diagnosis = diagnose_song(
        song_name,
        bpm,
        diagnosis_source,
        normalized_overrides,
        knowledge_root=knowledge_root,
        workspace_root=workspace_root,
    )
    artifact = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "kind": "pampapilot_project_analysis",
        "analyzed_at_utc": datetime.now(UTC).isoformat(),
        "configuration": {
            "bpm": float(bpm),
            "declared_source_kind": source_kind,
            "diagnosis_default_source_kind": diagnosis_source,
            "source_overrides": normalized_overrides,
        },
        "input_signature": _input_signature(song_name, workspace_root),
        "diagnosis": diagnosis,
    }
    _write_artifact(artifact, _analysis_path(song_name, workspace_root))
    return artifact


def load_project_analysis(
    song_name: str,
    bpm: float | int | None,
    source_kind: str,
    source_overrides: Sequence[Mapping[str, str]] = (),
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any] | None:
    """Load only a current artifact; changed files or settings make it stale."""

    if not isinstance(bpm, (int, float)):
        return None
    path = _analysis_path(song_name, workspace_root.resolve())
    if not path.is_file():
        return None
    try:
        artifact = json.loads(path.read_text(encoding="utf-8-sig"))
        configuration = artifact["configuration"]
        if artifact.get("kind") != "pampapilot_project_analysis":
            return None
        if float(configuration.get("bpm")) != float(bpm):
            return None
        if configuration.get("declared_source_kind") != source_kind:
            return None
        if configuration.get("source_overrides") != _normalized_overrides(source_overrides):
            return None
        if artifact.get("input_signature") != _input_signature(song_name, workspace_root):
            return None
        if not isinstance(artifact.get("diagnosis"), Mapping):
            return None
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None
    return dict(artifact)


def public_project_analysis(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Remove local paths and hashes before returning evidence to UI or LLM."""

    diagnosis = artifact.get("diagnosis", {})
    if not isinstance(diagnosis, Mapping):
        return {}
    public_stems = []
    for stem in diagnosis.get("stems", []):
        if not isinstance(stem, Mapping):
            continue
        identity = stem.get("audio_identity", {})
        file_path = identity.get("file_path") if isinstance(identity, Mapping) else ""
        public_stems.append(
            {
                "name": Path(str(file_path)).stem,
                "track_name": stem.get("track_name"),
                "role": stem.get("role"),
                "source_kind": stem.get("source_kind"),
                "policy": stem.get("policy"),
                "observations": stem.get("observations"),
                "findings": stem.get("findings", []),
            }
        )
    return {
        "analyzed_at_utc": artifact.get("analyzed_at_utc"),
        "configuration": dict(artifact.get("configuration", {})),
        "summary": dict(diagnosis.get("summary", {})),
        "stems": public_stems,
        "relationships": dict(diagnosis.get("relationships", {})),
        "limitations": list(diagnosis.get("limitations", [])),
        "verification": dict(diagnosis.get("verification", {})),
    }

