"""Provider-neutral context and response contracts for the producer agent."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .media_discovery import WORKSPACE_ROOT, discover_song_media


SYSTEM_PROMPT_PATH = WORKSPACE_ROOT / "knowledge" / "agent" / "system-prompt.md"
SECTION_RE = re.compile(r"^\s*\[([^\]]+)]\s*$")


def load_system_prompt(path: Path = SYSTEM_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8").strip()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    decoded = json.loads(path.read_text(encoding="utf-8-sig"))
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _read_lyrics(directory: Path) -> tuple[str, str | None]:
    for name in ("lyric-clean.txt", "lyrics-clean.txt", "lyric.txt", "lyrics.txt"):
        path = directory / name
        if path.is_file():
            return path.read_text(encoding="utf-8-sig").strip(), name
    return "", None


def lyric_sections(lyrics: str) -> list[str]:
    sections: list[str] = []
    for line in lyrics.splitlines():
        match = SECTION_RE.match(line)
        if match:
            label = match.group(1).strip()
            if label and label.casefold() not in {"instrumental"}:
                sections.append(label)
    return sections


def build_project_context(
    song_name: str,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    discovery = discover_song_media(song_name, workspace_root=workspace_root)
    stems_directory_raw = discovery.get("stems_directory")
    stems_directory = Path(str(stems_directory_raw)) if stems_directory_raw else None
    metadata = (
        _read_json(stems_directory / "session.json")
        if stems_directory is not None
        else {}
    )
    lyrics, lyrics_file = (
        _read_lyrics(stems_directory) if stems_directory is not None else ("", None)
    )
    stems = [
        {"name": Path(str(path)).stem, "format": Path(str(path)).suffix.lower()}
        for path in discovery.get("stems", [])
    ]
    midi = [Path(str(path)).name for path in discovery.get("midi_files", [])]
    references = [Path(str(path)).name for path in discovery.get("references", [])]
    return {
        "song": {
            "title": metadata.get("title", discovery["song_name"]),
            "tempo_bpm": metadata.get("tempo_bpm"),
            "time_signature": metadata.get("time_signature"),
            "source_kind": metadata.get("source_kind", "unknown"),
            "status": metadata.get("status", "media_discovered"),
        },
        "stems": stems,
        "midi_files": midi,
        "references": references,
        "lyrics": {
            "available": bool(lyrics),
            "source": lyrics_file,
            "sections": lyric_sections(lyrics),
            "text": lyrics[:16_000],
        },
        "verification": {
            "signal_analyzed": False,
            "reaper_state_verified": False,
            "perceptually_evaluated": False,
        },
    }


def build_agent_messages(
    project_context: Mapping[str, Any],
    user_message: str,
    history: Sequence[Mapping[str, str]] = (),
) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": load_system_prompt()},
        {
            "role": "system",
            "content": "Contexto estructurado del proyecto:\n"
            + json.dumps(project_context, ensure_ascii=False, separators=(",", ":")),
        },
    ]
    for item in history[-8:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content[:8_000]})
    messages.append({"role": "user", "content": user_message.strip()[:8_000]})
    return messages


def parse_agent_response(raw: str) -> dict[str, Any]:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError:
        return {"message": raw.strip(), "proposal": None, "structured": False}
    if not isinstance(decoded, Mapping) or not isinstance(decoded.get("message"), str):
        return {"message": raw.strip(), "proposal": None, "structured": False}
    proposal = decoded.get("proposal")
    if proposal is not None and not isinstance(proposal, Mapping):
        proposal = None
    if isinstance(proposal, Mapping):
        changes = proposal.get("changes")
        if not isinstance(changes, list):
            proposal = None
        else:
            proposal = {
                "title": str(proposal.get("title", "Propuesta del productor"))[:120],
                "summary": str(proposal.get("summary", ""))[:1000],
                "risk": proposal.get("risk")
                if proposal.get("risk") in {"low", "medium", "high"}
                else "medium",
                "requires_approval": True,
                "changes": [
                    {
                        "target": str(change.get("target", "Proyecto"))[:128],
                        "action": str(change.get("action", ""))[:500],
                        "reason": str(change.get("reason", ""))[:500],
                    }
                    for change in changes[:20]
                    if isinstance(change, Mapping)
                ],
            }
    return {
        "message": str(decoded["message"])[:8_000],
        "proposal": proposal,
        "structured": True,
    }
