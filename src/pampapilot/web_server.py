"""Local web interface and provider-neutral agent gateway for PampaPilot."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent_context import (
    action_project_context,
    build_agent_messages,
    build_context_update_message,
    build_turn_context_message,
    build_project_context,
    compact_project_context,
    load_system_prompt,
    parse_agent_response,
    request_needs_deep_context,
    request_needs_reasoning,
    request_is_direct_action,
)
from .agent_protocol import (
    ACTION_FIELDS,
    AGENT_PROTOCOL_NAME,
    AGENT_PROTOCOL_VERSION,
    EVIDENCE_TYPES,
    result_envelope,
)
from .ambience_proposal import (
    build_ambience_application_payload,
    propose_ambience,
)
from .bridge_client import BridgeClient
from .lmstudio_client import (
    LMStudioClient,
    LMStudioConfig,
    LMStudioError,
    normalize_base_url,
)
from .knowledge_retrieval import retrieve_knowledge
from .media_discovery import WORKSPACE_ROOT, discover_song_media
from .midi_cleanup import preview_cleanup, run_cleanup
from .mastering_proposal import (
    build_mastering_application_payload,
    build_mastering_proposal,
)
from .mastering_qc import build_master_delivery_qc
from .project_analysis import (
    analyze_project_media,
    source_overrides_from_metadata,
)
from .render_workflow import build_rendered_master_candidate_report
from .secret_store import SecretStoreError, WindowsSecretStore
from .section_volume import (
    build_section_volume_application_payload,
    build_section_volume_proposal,
)
from .song_structure import build_structure_region_payload
from .vocal_rider import build_vocal_rider_proposal
from .web_actions import (
    apply_filter_proposal,
    apply_producer_chain,
    bridge_project,
    build_filter_proposal,
    capability_catalog,
    filter_bindings,
    match_reaper_track,
    normalize_track_name,
    track_producer_chain,
)


WEB_ROOT = Path(__file__).with_name("web")
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
SONG_INVALID_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


class BrainSettingsInput(BaseModel):
    base_url: Annotated[str, Field(min_length=8, max_length=2048)]
    model: Annotated[str, Field(max_length=512)] = ""
    token: Annotated[str | None, Field(max_length=4096)] = None
    authentication_required: bool = True
    timeout_seconds: Annotated[float, Field(ge=15, le=300)] = 180.0
    remember_token: bool = False
    approval_mode: Literal["manual", "low_risk", "all"] = "manual"


class StemOrderInput(BaseModel):
    names: Annotated[list[str], Field(min_length=1, max_length=64)]


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=8_000)]


class ChatInput(BaseModel):
    project_name: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    history: Annotated[list[HistoryMessage], Field(max_length=20)] = []
    conversation_id: Annotated[str, Field(min_length=1, max_length=64)] = "default"
    reasoning_mode: Literal["auto", "fast", "deep"] = "auto"


class ReasoningModeInput(BaseModel):
    reasoning_mode: Literal["auto", "fast", "deep"]


class ProposalDecision(BaseModel):
    decision: Literal["preview", "apply", "reject"]


class CompactWindowInput(BaseModel):
    project_name: Annotated[str, Field(max_length=128)] = ""


class StemSourceInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"]


class StemActionInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"] | None = None
    include_artistic_saturation: bool = False


class ApplyChainInput(StemActionInput):
    approved_chain_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]


class FilterInput(StemActionInput):
    filter_type: Literal[
        "eq",
        "compressor",
        "gate",
        "deesser",
        "dynamic_resonance",
        "saturation",
        "tuning",
    ]
    preset_name: Annotated[str, Field(max_length=128)] = "pampapilota#"


class ApplyFilterInput(FilterInput):
    approved_proposal_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]
    fx_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None


class StaticMixInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    volume_db: Annotated[float | None, Field(ge=-60.0, le=12.0)] = None
    pan: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    muted: bool | None = None
    solo: bool | None = None


class UndoInput(BaseModel):
    project_ref: Annotated[str, Field(min_length=1, max_length=4096)]
    transaction_request_id: Annotated[str, Field(min_length=1, max_length=64)]


class UndoPlanInput(BaseModel):
    project_ref: Annotated[str, Field(min_length=1, max_length=4096)]
    transaction_request_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=64)]],
        Field(min_length=1, max_length=64),
    ]


class RuntimeState:
    """Process-local state; secrets never appear in API responses or plain text."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._secret_store = WindowsSecretStore()
        self._settings_path = WORKSPACE_ROOT / ".runtime" / "web-settings.json"
        persisted_settings = self._load_settings()
        try:
            persisted_token = self._secret_store.load()
        except SecretStoreError:
            persisted_token = ""
        self._brain = LMStudioConfig(
            base_url=os.environ.get(
                "PAMPAPILOT_LMSTUDIO_URL",
                str(persisted_settings.get("base_url", "http://127.0.0.1:1234")),
            ),
            model=os.environ.get(
                "PAMPAPILOT_LMSTUDIO_MODEL", str(persisted_settings.get("model", ""))
            ),
            token=os.environ.get("PAMPAPILOT_LMSTUDIO_TOKEN", persisted_token),
            authentication_required=(
                os.environ.get("PAMPAPILOT_LMSTUDIO_REQUIRE_AUTH", "").casefold()
                not in {"0", "false", "no"}
                if os.environ.get("PAMPAPILOT_LMSTUDIO_REQUIRE_AUTH") is not None
                else bool(persisted_settings.get("authentication_required", True))
            ),
            timeout_seconds=float(
                os.environ.get(
                    "PAMPAPILOT_LMSTUDIO_TIMEOUT_SECONDS",
                    str(persisted_settings.get("timeout_seconds", 180)),
                )
            ),
        )
        configured_approval = os.environ.get("PAMPAPILOT_APPROVAL_MODE", "").casefold()
        stored_approval = persisted_settings.get("approval_mode", "manual")
        self._approval_mode = (
            configured_approval
            if configured_approval in {"manual", "low_risk", "all"}
            else str(stored_approval)
            if stored_approval in {"manual", "low_risk", "all"}
            else "manual"
        )
        self._proposals: dict[str, dict[str, Any]] = {}
        self._conversations: dict[tuple[str, str], dict[str, str]] = {}
        self._activity: list[dict[str, Any]] = []

    def _load_settings(self) -> dict[str, Any]:
        try:
            decoded = json.loads(self._settings_path.read_text(encoding="utf-8"))
            return dict(decoded) if isinstance(decoded, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "base_url": self._brain.base_url,
                    "model": self._brain.model,
                    "authentication_required": self._brain.authentication_required,
                    "timeout_seconds": self._brain.timeout_seconds,
                    "approval_mode": self._approval_mode,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._settings_path)

    def brain(self) -> LMStudioConfig:
        with self._lock:
            return self._brain

    def configure_brain(self, value: BrainSettingsInput) -> LMStudioConfig:
        normalize_base_url(value.base_url)
        with self._lock:
            token = self._brain.token if value.token is None else value.token.strip()
            if not value.authentication_required and value.token is None:
                token = ""
            if value.remember_token:
                if not token:
                    raise ValueError("Ingrese un token antes de recordarlo")
                try:
                    self._secret_store.save(token)
                except SecretStoreError as exc:
                    raise ValueError(str(exc)) from exc
            else:
                self._secret_store.clear()
            self._brain = replace(
                self._brain,
                base_url=value.base_url.strip().rstrip("/"),
                model=value.model.strip(),
                token=token,
                authentication_required=value.authentication_required,
                timeout_seconds=value.timeout_seconds,
            ).validated()
            self._approval_mode = value.approval_mode
            self._save_settings()
            return self._brain

    def public_brain(self) -> dict[str, Any]:
        config = self.brain()
        return {
            "provider": "lm_studio",
            "base_url": config.base_url,
            "model": config.model,
            "authentication_configured": bool(config.token),
            "authentication_required": config.authentication_required,
            "timeout_seconds": config.timeout_seconds,
            "token_persisted": self._secret_store.exists(),
            "approval_mode": self._approval_mode,
        }

    def approval_mode(self) -> str:
        with self._lock:
            return self._approval_mode

    def add_proposal(self, proposal: dict[str, Any], *, executable: bool = False) -> str:
        proposal_id = str(uuid4())
        with self._lock:
            self._proposals[proposal_id] = {
                **proposal,
                "proposal_id": proposal_id,
                "status": "pending",
                "executable": executable,
            }
        return proposal_id

    def conversation(
        self, conversation_id: str, project_name: str
    ) -> dict[str, str] | None:
        with self._lock:
            value = self._conversations.get((conversation_id, project_name))
            return None if value is None else dict(value)

    def save_conversation(
        self,
        conversation_id: str,
        project_name: str,
        response_id: str,
        context_level: str,
        context_revision: str,
    ) -> None:
        with self._lock:
            self._conversations[(conversation_id, project_name)] = {
                "response_id": response_id,
                "context_level": context_level,
                "context_revision": context_revision,
            }

    def drop_conversation(self, conversation_id: str, project_name: str) -> None:
        with self._lock:
            self._conversations.pop((conversation_id, project_name), None)

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            return dict(proposal)

    def reject(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            proposal["status"] = "rejected"
            return dict(proposal)

    def mark_proposal(self, proposal_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            proposal.update(updates)
            return dict(proposal)

    def record_activity(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._activity.append(entry)
            self._activity = self._activity[-100:]

    def activity(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in reversed(self._activity)]


runtime = RuntimeState()
app = FastAPI(title="PampaPilot", version="0.1.0")
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")
CHAT_STATE_PATH = WORKSPACE_ROOT / ".runtime" / "web-chat-state.json"
CHAT_STATE_LOCK = RLock()


def _read_chat_state() -> dict[str, Any]:
    with CHAT_STATE_LOCK:
        try:
            decoded = json.loads(CHAT_STATE_PATH.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"reasoning_mode": "auto", "projects": {}}
        return dict(decoded) if isinstance(decoded, dict) else {"reasoning_mode": "auto", "projects": {}}


def _write_chat_state(value: dict[str, Any]) -> None:
    with CHAT_STATE_LOCK:
        CHAT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CHAT_STATE_PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(CHAT_STATE_PATH)


def _new_chat_record() -> dict[str, Any]:
    return {"conversation_id": str(uuid4()), "history": [], "archives": []}


def _normalized_chat_record(raw: object) -> dict[str, Any]:
    if isinstance(raw, list):
        return {
            "conversation_id": str(uuid4()),
            "history": [item for item in raw if isinstance(item, dict)][-100:],
            "archives": [],
        }
    if not isinstance(raw, dict):
        return _new_chat_record()
    conversation_id = raw.get("conversation_id")
    history = raw.get("history", [])
    archives = raw.get("archives", [])
    return {
        "conversation_id": conversation_id
        if isinstance(conversation_id, str) and conversation_id
        else str(uuid4()),
        "history": [item for item in history if isinstance(item, dict)][-100:]
        if isinstance(history, list)
        else [],
        "archives": [item for item in archives if isinstance(item, dict)][-20:]
        if isinstance(archives, list)
        else [],
    }


def _archive_summary(archive: dict[str, Any]) -> dict[str, Any]:
    history = archive.get("history", [])
    first_user = next(
        (
            str(item.get("content", ""))
            for item in history
            if isinstance(item, dict) and item.get("role") == "user"
        ),
        "Conversación sin título",
    )
    return {
        "archive_id": archive.get("archive_id"),
        "conversation_id": archive.get("conversation_id"),
        "archived_at": archive.get("archived_at"),
        "title": first_user[:80],
        "message_count": len(history),
    }


def _chat_state_for_project(project_name: str) -> dict[str, Any]:
    state = _read_chat_state()
    projects = state.get("projects")
    projects = dict(projects) if isinstance(projects, dict) else {}
    record = _normalized_chat_record(projects.get(project_name))
    if projects.get(project_name) != record:
        projects[project_name] = record
        state["projects"] = projects
        _write_chat_state(state)
    return {
        "reasoning_mode": state.get("reasoning_mode", "auto"),
        "conversation_id": record["conversation_id"],
        "history": record["history"],
        "archives": [_archive_summary(item) for item in reversed(record["archives"])],
    }


def _start_new_project_chat(project_name: str, *, archive_current: bool) -> dict[str, Any]:
    state = _read_chat_state()
    projects = state.get("projects")
    projects = dict(projects) if isinstance(projects, dict) else {}
    record = _normalized_chat_record(projects.get(project_name))
    if archive_current and record["history"]:
        record["archives"].append(
            {
                "archive_id": str(uuid4()),
                "conversation_id": record["conversation_id"],
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "history": record["history"],
            }
        )
        record["archives"] = record["archives"][-20:]
    runtime.drop_conversation(record["conversation_id"], project_name)
    record["conversation_id"] = str(uuid4())
    record["history"] = []
    projects[project_name] = record
    state["projects"] = projects
    _write_chat_state(state)
    return _chat_state_for_project(project_name)


def _record_chat_exchange(
    project_name: str,
    conversation_id: str,
    user_message: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    state = _read_chat_state()
    projects = state.get("projects")
    projects = dict(projects) if isinstance(projects, dict) else {}
    record = _normalized_chat_record(projects.get(project_name))
    if record["conversation_id"] != conversation_id:
        record["conversation_id"] = conversation_id
        record["history"] = []
    history = record["history"]
    history.extend(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": str(response.get("message", ""))},
        ]
    )
    record["history"] = history[-100:]
    projects[project_name] = record
    state["projects"] = projects
    _write_chat_state(state)
    return response


def _archived_project_chat(project_name: str, archive_id: str) -> dict[str, Any]:
    state = _read_chat_state()
    projects = state.get("projects")
    record = _normalized_chat_record(
        projects.get(project_name) if isinstance(projects, dict) else None
    )
    matches = [
        item for item in record["archives"]
        if item.get("archive_id") == archive_id
    ]
    if len(matches) != 1:
        raise KeyError(archive_id)
    archive = matches[0]
    return {**_archive_summary(archive), "history": archive.get("history", [])}


def _restore_project_chat(project_name: str, archive_id: str) -> dict[str, Any]:
    state = _read_chat_state()
    projects = state.get("projects")
    projects = dict(projects) if isinstance(projects, dict) else {}
    record = _normalized_chat_record(projects.get(project_name))
    selected = next(
        (item for item in record["archives"] if item.get("archive_id") == archive_id),
        None,
    )
    if selected is None:
        raise KeyError(archive_id)
    remaining = [item for item in record["archives"] if item is not selected]
    if record["history"]:
        remaining.append(
            {
                "archive_id": str(uuid4()),
                "conversation_id": record["conversation_id"],
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "history": record["history"],
            }
        )
    runtime.drop_conversation(record["conversation_id"], project_name)
    record = {
        "conversation_id": str(selected.get("conversation_id") or uuid4()),
        "history": list(selected.get("history", []))[-100:],
        "archives": remaining[-20:],
    }
    projects[project_name] = record
    state["projects"] = projects
    _write_chat_state(state)
    return _chat_state_for_project(project_name)


def _validate_song_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 128 or value in {".", ".."}:
        raise ValueError("El título debe tener entre 1 y 128 caracteres")
    if SONG_INVALID_RE.search(value):
        raise ValueError("El título contiene caracteres no permitidos")
    return value


def _project_names(workspace_root: Path = WORKSPACE_ROOT) -> list[str]:
    roots = (
        workspace_root / "media" / "inbox" / "stems",
        workspace_root / "media" / "inbox" / "midi",
    )
    return sorted(
        {
            child.name
            for root in roots
            if root.is_dir()
            for child in root.iterdir()
            if child.is_dir()
        },
        key=str.casefold,
    )


def _context_revision(context: dict[str, Any]) -> str:
    serialized = json.dumps(
        {"context": context, "system_prompt": load_system_prompt()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _project_metadata(name: str) -> dict[str, Any]:
    discovery = discover_song_media(name)
    directory = discovery.get("stems_directory")
    if not directory:
        return {}
    path = Path(str(directory)) / "session.json"
    if not path.is_file():
        return {}
    decoded = json.loads(path.read_text(encoding="utf-8-sig"))
    return dict(decoded) if isinstance(decoded, dict) else {}


def _write_project_metadata(name: str, metadata: dict[str, Any]) -> None:
    discovery = discover_song_media(name)
    directory = discovery.get("stems_directory")
    if not directory:
        raise FileNotFoundError("El proyecto no tiene una carpeta de stems")
    path = Path(str(directory)) / "session.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_song_regions(name: str) -> list[dict[str, Any]]:
    analysis_dir = WORKSPACE_ROOT / "sessions" / name / "analysis"
    candidates = sorted(
        analysis_dir.glob("song-structure-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    candidates.extend(
        path
        for path in (analysis_dir / "all-in-one-structure.json",)
        if path.is_file() and path not in candidates
    )
    for path in candidates:
        try:
            decoded = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        regions = decoded.get("regions") if isinstance(decoded, dict) else None
        if isinstance(regions, list) and len(regions) >= 2:
            return [dict(region) for region in regions if isinstance(region, dict)]
    raise FileNotFoundError(
        "No hay una estructura temporal aprobada para calcular volumen por secciones"
    )


def _load_song_structure(name: str) -> dict[str, Any]:
    analysis_dir = WORKSPACE_ROOT / "sessions" / name / "analysis"
    candidates = sorted(
        analysis_dir.glob("song-structure-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            decoded = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(decoded, dict)
            and decoded.get("kind") == "pampapilot_song_structure_proposal"
            and isinstance(decoded.get("regions"), list)
        ):
            return dict(decoded)
    raise FileNotFoundError("No existe una propuesta temporal de estructura para aplicar")


def _load_latest_master_report(name: str) -> dict[str, Any]:
    render_dir = WORKSPACE_ROOT / "sessions" / name / "renders"
    candidates = sorted(
        render_dir.glob("*.report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            decoded = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(decoded, dict):
            continue
        report = decoded.get("file_report", decoded)
        if isinstance(report, dict) and report.get("kind") == "pampapilot_master_delivery_qc":
            return dict(report)
    raise FileNotFoundError(
        "No existe un render candidato con informe de entrega para calcular mastering"
    )


def _next_master_candidate_path(name: str) -> Path:
    render_dir = WORKSPACE_ROOT / "sessions" / name / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10_000):
        candidate = render_dir / f"{name} - master-candidate-{index:03d}.wav"
        if not candidate.exists() and not candidate.with_suffix(".report.json").exists():
            return candidate.resolve()
    raise FileExistsError("No queda un nombre libre para el próximo candidato de master")


def _stem_descriptor(name: str, stem_name: str) -> dict[str, Any]:
    project = _project_view(name)
    stem = next(
        (item for item in project["stems"] if item["name"] == stem_name),
        None,
    )
    if stem is None:
        raise ValueError(f"No existe el stem {stem_name}")
    discovery = discover_song_media(name)
    path = next(
        (
            Path(str(raw_path))
            for raw_path in discovery.get("stems", [])
            if Path(str(raw_path)).stem == stem_name
        ),
        None,
    )
    if path is None:
        raise FileNotFoundError(f"No se encontró el WAV de {stem_name}")
    return {**stem, "path": path}


def _source_kind_for_stem(name: str, stem: dict[str, Any]) -> str:
    raw = stem.get("source_kind")
    if raw in {"suno_stems", "organic_multitrack", "unknown"}:
        return str(raw)
    metadata = _project_metadata(name)
    source = metadata.get("source_kind", "unknown")
    return str(source) if source in {"suno_stems", "organic_multitrack"} else "unknown"


def _connected_stem(
    name: str, stem_name: str, timeout_seconds: float = 8.0
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    stem = _stem_descriptor(name, stem_name)
    state = bridge_project(BridgeClient(timeout_seconds=timeout_seconds))
    result = state["result"]
    track = match_reaper_track(
        list(result.get("tracks", [])),
        str(stem.get("track_name", "")),
        stem_name,
    )
    if track is None:
        raise ValueError(
            f"No pude vincular {stem_name} con una única pista del proyecto abierto en REAPER"
        )
    return stem, state, track


_CHAT_ROLE_ALIASES = {
    "percu": {"percussion"},
    "percusion": {"percussion"},
    "bateria": {"drums"},
    "drums": {"drums"},
    "lead": {"lead_vocal"},
    "lead vocal": {"lead_vocal"},
    "voz": {"lead_vocal"},
    "voz principal": {"lead_vocal"},
    "coros": {"backing_vocals", "choir"},
    "bajo": {"bass"},
    "guitarra": {"guitar"},
}


def _resolve_chat_stem(project: dict[str, Any], target: str) -> dict[str, Any]:
    normalized = normalize_track_name(target)
    exact = [
        stem
        for stem in project["stems"]
        if normalized
        in {
            normalize_track_name(str(stem.get("name", ""))),
            normalize_track_name(str(stem.get("track_name", ""))),
        }
    ]
    if len(exact) == 1:
        return dict(exact[0])
    alias_roles = _CHAT_ROLE_ALIASES.get(target.strip().casefold(), set())
    by_role = [stem for stem in project["stems"] if stem.get("role") in alias_roles]
    if len(by_role) == 1:
        return dict(by_role[0])
    if len(exact) > 1 or len(by_role) > 1:
        raise ValueError(f"'{target}' identifica más de una pista; usá el nombre exacto")
    raise ValueError(f"No existe una pista única que corresponda a '{target}'")


def _chat_track(
    stem: dict[str, Any], tracks: list[dict[str, Any]]
) -> dict[str, Any]:
    track = match_reaper_track(
        tracks,
        str(stem.get("track_name", "")),
        str(stem.get("name", "")),
    )
    if track is None:
        raise ValueError(
            f"No pude vincular {stem['name']} con una única pista del proyecto abierto"
        )
    return track


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 2)


def _resolve_agent_evidence(
    project_name: str, requests: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve one bounded, read-only evidence round for the planning LLM."""

    if not 1 <= len(requests) <= 4:
        raise ValueError("El LLM puede pedir entre una y cuatro evidencias por ronda")
    context = build_project_context(project_name)
    project = _project_view(project_name)
    bridge_snapshot: dict[str, Any] | None = None
    items: list[dict[str, Any]] = []
    for request in requests:
        evidence_type = str(request.get("evidence_type", ""))
        target = str(request.get("target", "")).strip()
        query = str(request.get("query", "")).strip()
        try:
            if evidence_type == "project_analysis":
                data = context.get("analysis")
                if data is None:
                    raise ValueError("Todavía no existe un análisis técnico del proyecto")
            elif evidence_type == "track_analysis":
                stem = _resolve_chat_stem(project, target)
                analysis = context.get("analysis")
                analyzed = analysis.get("stems", []) if isinstance(analysis, dict) else []
                wanted = {
                    normalize_track_name(str(stem.get("name", ""))),
                    normalize_track_name(str(stem.get("track_name", ""))),
                }
                matches = [
                    item for item in analyzed
                    if isinstance(item, dict)
                    and normalize_track_name(str(item.get("track_name", ""))) in wanted
                ]
                if len(matches) != 1:
                    raise ValueError("No hay un informe técnico único para esa pista")
                data = matches[0]
            elif evidence_type == "knowledge":
                data = retrieve_knowledge(query or target, context)
            elif evidence_type in {"reaper_track_state", "fx_parameters"}:
                if bridge_snapshot is None:
                    bridge_snapshot = dict(
                        bridge_project(BridgeClient(timeout_seconds=8.0))["result"]
                    )
                stem = _resolve_chat_stem(project, target)
                track = _chat_track(stem, list(bridge_snapshot.get("tracks", [])))
                reply = BridgeClient(timeout_seconds=8.0).call(
                    "get_track_state",
                    {
                        "project_ref": str(bridge_snapshot["project_ref"]),
                        "track_guid": str(track["guid"]),
                    },
                )
                data = (
                    {"track": reply.result.get("track"), "fx": reply.result.get("fx", [])}
                    if evidence_type == "reaper_track_state"
                    else {"track": stem.get("track_name"), "fx": reply.result.get("fx", [])}
                )
            else:
                raise ValueError("Tipo de evidencia no permitido")
            items.append({
                "evidence_type": evidence_type,
                "target": target or None,
                "status": "ok",
                "data": data,
            })
        except Exception as exc:
            items.append({
                "evidence_type": evidence_type,
                "target": target or None,
                "status": "unavailable",
                "error": str(exc),
            })
    return result_envelope(status="ok", data={"evidence": items})


def _build_chat_action_plan(
    project_name: str, raw_actions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve model output into a closed, deterministic action plan."""

    mutating = [action for action in raw_actions if action.get("kind") != "analyze_project"]
    if not mutating:
        raise ValueError("El pedido no contiene una acción de REAPER para previsualizar")
    if any(action.get("kind") == "render" for action in mutating) and len(mutating) != 1:
        raise ValueError("El render debe ser una acción terminal separada para conservar trazabilidad")
    project = _project_view(project_name)
    needs_bridge = any(action.get("kind") != "midi_cleanup" for action in mutating)
    if needs_bridge:
        bridge_state = bridge_project(BridgeClient(timeout_seconds=8.0))
        result = dict(bridge_state["result"])
        project_ref = str(result["project_ref"])
        tracks = [dict(track) for track in result.get("tracks", [])]
    else:
        project_ref = ""
        tracks = []
    operations: list[dict[str, Any]] = []
    changes: list[dict[str, str]] = []
    risks: list[str] = []
    mix_by_guid: dict[str, dict[str, Any]] = {}

    for action in mutating:
        kind = str(action.get("kind"))
        if kind == "song_structure":
            proposal = _load_song_structure(project_name)
            payload = build_structure_region_payload(
                proposal, str(proposal["structure_id"])
            )
            operations.append(
                {"kind": "song_structure", "proposal": proposal, "payload": payload}
            )
            changes.append(
                {
                    "target": "Línea de tiempo",
                    "action": f"Reemplazar regiones de PampaPilot por {len(proposal['regions'])} secciones analizadas",
                    "reason": "Usar la última propuesta temporal auditable guardada para la canción.",
                }
            )
            risks.append("medium")
            continue
        if kind == "midi_cleanup":
            discovery = discover_song_media(project_name)
            pairs = [dict(pair) for pair in discovery.get("suggested_pairs", [])]
            requested = normalize_track_name(str(action.get("target", "")))
            if requested:
                pairs = [
                    pair
                    for pair in pairs
                    if requested
                    in {
                        normalize_track_name(Path(str(pair["midi"])).name),
                        normalize_track_name(Path(str(pair["midi"])).stem),
                        normalize_track_name(Path(str(pair["audio"])).stem),
                    }
                ]
            if len(pairs) != 1:
                raise ValueError("La limpieza MIDI necesita un único par MIDI/WAV identificable")
            midi_path = Path(str(pairs[0]["midi"])).resolve()
            audio_path = Path(str(pairs[0]["audio"])).resolve()
            audio_role = str(_stem_descriptor(project_name, audio_path.stem)["role"])
            profile = {
                "guitar": "guitar",
                "bass": "bass",
                "keys": "piano",
                "drums": "drums",
                "percussion": "drums",
            }.get(audio_role, "generic")
            bpm = float(project.get("tempo_bpm") or 0.0)
            preview = preview_cleanup(midi_path, audio_path, bpm=bpm, profile=profile)
            output_directory = Path(str(discovery["suggested_output_directory"])).resolve()
            operations.append(
                {
                    "kind": "midi_cleanup",
                    "midi_path": str(midi_path),
                    "audio_path": str(audio_path),
                    "output_directory": str(output_directory),
                    "bpm": bpm,
                    "profile": profile,
                }
            )
            safe = preview.get("clean_safe", {}).get("summary", {})
            reconstructed = preview.get("reconstructed", {}).get("summary", {})
            changes.append(
                {
                    "target": midi_path.name,
                    "action": (
                        f"Generar variante segura ({safe.get('note_count', '?')} notas) y "
                        f"reconstruida ({reconstructed.get('note_count', '?')} notas)"
                    ),
                    "reason": "Análisis MIDI/WAV conservador; los originales no se modifican.",
                }
            )
            risks.append("medium")
            continue
        if kind == "render":
            output_path = _next_master_candidate_path(project_name)
            operations.append(
                {
                    "kind": "render",
                    "output_file": str(output_path),
                    "sample_rate_hz": 48_000,
                }
            )
            changes.append(
                {
                    "target": "Master",
                    "action": f"Renderizar WAV 24-bit/48 kHz: {output_path.name}",
                    "reason": "Crear un candidato nuevo, medible y sin sobrescribir archivos existentes.",
                }
            )
            risks.append("high")
            continue
        if kind == "mastering":
            file_report = _load_latest_master_report(project_name)
            proposal = build_mastering_proposal(file_report)
            if proposal.get("review_status") != "user_approval_required":
                raise ValueError("El último render medido no necesita una acción automática de mastering")
            master_state = BridgeClient(timeout_seconds=8.0).call(
                "get_master_track_state", {"project_ref": project_ref}
            )
            matches = [
                fx
                for fx in master_state.result.get("fx", [])
                if "realimit" in str(fx.get("name", "")).casefold()
            ]
            if len(matches) > 1:
                raise ValueError("Hay más de un ReaLimit en el master; elegí la instancia manualmente")
            fx_guid = str(matches[0]["guid"]) if len(matches) == 1 else None
            payload = build_mastering_application_payload(
                proposal, str(proposal["proposal_id"]), fx_guid
            )
            step = proposal["chain"][0]
            operations.append(
                {"kind": "mastering", "proposal": proposal, "payload": payload}
            )
            changes.append(
                {
                    "target": "Master",
                    "action": (
                        f"ReaLimit: techo {step['parameters']['ceiling_db']:+.2f} dB, "
                        f"release {step['parameters']['release_ms']:.0f} ms"
                    ),
                    "reason": "Propuesta ligada al último render candidato y su QC de entrega.",
                }
            )
            risks.append("medium")
            continue
        target = str(action.get("target", "")).strip()
        stem = _resolve_chat_stem(project, target)
        track = _chat_track(stem, tracks)
        stem_descriptor = _stem_descriptor(project_name, str(stem["name"]))
        source_kind = str(action.get("source_kind") or _source_kind_for_stem(project_name, stem_descriptor))

        if kind == "static_mix":
            item = mix_by_guid.setdefault(
                str(track["guid"]),
                {"track_guid": str(track["guid"]), "stem_name": str(stem["name"])},
            )
            descriptions: list[str] = []
            if "volume_delta_db" in action:
                delta = float(action["volume_delta_db"])
                if not -24.0 <= delta <= 24.0:
                    raise ValueError("El cambio relativo de volumen excede ±24 dB")
                starting_db = float(item.get("volume_db", track["volume_db"]))
                target_db = max(-60.0, min(12.0, starting_db + delta))
                item["volume_db"] = round(target_db, 4)
                descriptions.append(f"volumen {delta:+.2f} dB → {target_db:.2f} dB")
            if "volume_db" in action:
                target_db = float(action["volume_db"])
                if not -60.0 <= target_db <= 12.0:
                    raise ValueError("El volumen absoluto debe estar entre -60 y +12 dB")
                item["volume_db"] = target_db
                descriptions.append(f"volumen → {target_db:.2f} dB")
            if "pan" in action:
                pan = float(action["pan"])
                if not -1.0 <= pan <= 1.0:
                    raise ValueError("El paneo debe estar entre -1 y 1")
                item["pan"] = pan
                descriptions.append(f"paneo → {pan:+.2f}")
            if "muted" in action:
                if not isinstance(action["muted"], bool):
                    raise ValueError("muted debe ser booleano")
                item["muted"] = action["muted"]
                descriptions.append("mute activado" if action["muted"] else "mute desactivado")
            if "soloed" in action:
                if not isinstance(action["soloed"], bool):
                    raise ValueError("soloed debe ser booleano")
                item["soloed"] = action["soloed"]
                descriptions.append("solo activado" if action["soloed"] else "solo desactivado")
            if not descriptions:
                raise ValueError(f"La acción de mezcla para {target} no contiene cambios")
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": ", ".join(descriptions),
                    "reason": "Pedido explícito del usuario; se verificará por lectura posterior.",
                }
            )
            risks.append("low")
            continue

        track_state = BridgeClient(timeout_seconds=8.0).call(
            "get_track_state",
            {"project_ref": project_ref, "track_guid": track["guid"]},
        )
        existing_fx = [dict(item) for item in track_state.result.get("fx", [])]
        if kind == "adjust_compressor":
            matches = [
                fx for fx in existing_fx
                if "reacomp" in str(fx.get("name", "")).casefold()
                and "reaxcomp" not in str(fx.get("name", "")).casefold()
            ]
            if len(matches) != 1:
                raise ValueError(
                    "El ajuste fino necesita exactamente un ReaComp activo en la pista"
                )
            delta = float(action.get("attack_percent_delta", 0.0))
            if not -75.0 <= delta <= 300.0 or delta == 0.0:
                raise ValueError("El ajuste relativo de ataque debe estar entre -75% y +300% y no ser cero")
            operations.append(
                {
                    "kind": "adjust_compressor",
                    "track_guid": str(track["guid"]),
                    "fx_guid": str(matches[0]["guid"]),
                    "attack_percent_delta": delta,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": f"Cambiar el tiempo de ataque actual de ReaComp en {delta:+.1f}%",
                    "reason": "Ajuste relativo sobre la instancia existente, con lectura posterior en REAPER.",
                }
            )
            risks.append("low")
            continue
        if kind == "filter":
            filter_type = str(action.get("filter_type", ""))
            proposal = build_filter_proposal(
                Path(stem_descriptor["path"]),
                str(stem_descriptor["role"]),
                source_kind,
                filter_type,
                preset_name=str(action.get("preset_name", "pampapilota#")),
            )
            binding = filter_bindings(proposal, existing_fx)
            if not proposal["can_approve"]:
                raise ValueError(f"{proposal['title']}: {proposal['reason']}")
            selected_guid = None
            if binding["status"] == "selection_required":
                selected_guid = "__create_new__"
            operations.append(
                {
                    "kind": "filter",
                    "stem_name": stem["name"],
                    "track_guid": track["guid"],
                    "source_kind": source_kind,
                    "proposal": proposal,
                    "existing_fx": existing_fx,
                    "selected_fx_guid": selected_guid,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": f"Aplicar {proposal['title']} con parámetros calculados",
                    "reason": (
                        f"{proposal['reason']} Se creará una instancia nueva para no alterar un FX ambiguo."
                        if selected_guid == "__create_new__"
                        else str(proposal["reason"])
                    ),
                }
            )
            risks.append("medium" if filter_type == "tuning" else "low")
        elif kind == "ambience":
            role = str(stem_descriptor["role"])
            if role == "choir":
                role = "backing_vocals"
            if role not in {"lead_vocal", "backing_vocals", "guitar", "strings"}:
                raise ValueError("Los buses automáticos de ambiente no están validados para ese rol")
            effect_type = str(action.get("effect_type", ""))
            if effect_type not in {"reverb", "delay"}:
                raise ValueError("El ambiente debe ser reverb o delay")
            bpm = float(project.get("tempo_bpm") or 0.0)
            proposal = propose_ambience(
                Path(stem_descriptor["path"]),
                role,  # type: ignore[arg-type]
                effect_type,  # type: ignore[arg-type]
                bpm,
                source_kind,  # type: ignore[arg-type]
            )
            payload = build_ambience_application_payload(
                proposal, str(proposal["proposal_id"])
            )
            operations.append(
                {
                    "kind": "ambience",
                    "stem_name": stem["name"],
                    "track_guid": track["guid"],
                    "proposal": proposal,
                    "payload": payload,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": f"Crear bus de {effect_type} y envío a {payload['send_db']:+.1f} dB",
                    "reason": str(proposal["reason"]),
                }
            )
            risks.append("medium")
        elif kind == "vocal_rider":
            if str(stem_descriptor["role"]) != "lead_vocal":
                raise ValueError("El vocal rider automático requiere una voz principal")
            if source_kind != "organic_multitrack":
                raise ValueError("El vocal rider sólo se aplica automáticamente a una voz orgánica confirmada")
            proposal = build_vocal_rider_proposal(
                Path(stem_descriptor["path"]), "organic_multitrack"
            )
            if proposal.get("status") != "audition_only" or not proposal.get("envelope_points"):
                raise ValueError(str(proposal.get("reason", "El vocal rider no es necesario")))
            items_reply = BridgeClient(timeout_seconds=8.0).call(
                "get_track_items",
                {"project_ref": project_ref, "track_guid": track["guid"]},
            )
            source_path = Path(stem_descriptor["path"]).resolve()
            matches = []
            for item in items_reply.result.get("items", []):
                take = item.get("take") if isinstance(item, dict) else None
                observed = take.get("source_path") if isinstance(take, dict) else None
                if observed and Path(str(observed)).resolve() == source_path:
                    matches.append(item)
            if len(matches) != 1:
                raise ValueError(
                    "El vocal rider necesita exactamente un ítem de REAPER ligado al WAV vocal analizado"
                )
            operations.append(
                {
                    "kind": "vocal_rider",
                    "stem_name": stem["name"],
                    "track_guid": track["guid"],
                    "item_guid": matches[0]["guid"],
                    "proposal": proposal,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": (
                        f"Automatizar {proposal['corrected_phrase_count']} de "
                        f"{proposal['phrase_count']} frases (máximo ±{proposal['maximum_correction_db']:.1f} dB)"
                    ),
                    "reason": str(proposal["reason"]),
                }
            )
            risks.append("medium")
        elif kind == "section_volume":
            role = str(stem_descriptor["role"])
            if role == "choir":
                role = "backing_vocals"
            if role == "synth":
                role = "synth"
            regions = _load_song_regions(project_name)
            proposal = build_section_volume_proposal(
                regions,
                role,  # type: ignore[arg-type]
                source_kind,  # type: ignore[arg-type]
            )
            payload = build_section_volume_application_payload(
                proposal, str(proposal["proposal_id"])
            )
            operations.append(
                {
                    "kind": "section_volume",
                    "stem_name": stem["name"],
                    "track_guid": track["guid"],
                    "proposal": proposal,
                    "payload": payload,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": (
                        f"Escribir volumen relativo para {len(proposal['sections'])} secciones "
                        f"(máximo ±{proposal['maximum_absolute_move_db']:.2f} dB)"
                    ),
                    "reason": "Movimientos pequeños ligados a la estructura temporal analizada.",
                }
            )
            risks.append("medium")
        elif kind == "producer_chain":
            chain = track_producer_chain(
                Path(stem_descriptor["path"]),
                str(stem_descriptor["role"]),
                source_kind,
                existing_fx=existing_fx,
                include_artistic_saturation=bool(action.get("include_artistic_saturation", False)),
            )
            if chain.get("review_status") != "user_approval_required":
                raise ValueError("La cadena calculada no está lista para aplicar")
            operations.append(
                {
                    "kind": "producer_chain",
                    "stem_name": stem["name"],
                    "track_guid": track["guid"],
                    "chain": chain,
                }
            )
            changes.append(
                {
                    "target": str(stem["track_name"]),
                    "action": f"Aplicar cadena de {len(chain['steps'])} procesadores",
                    "reason": "Cadena conservadora calculada según rol, señal y origen.",
                }
            )
            risks.append("medium")
        else:
            raise ValueError(f"Acción de chat no soportada: {kind}")

    if mix_by_guid:
        operations.insert(
            0,
            {
                "kind": "static_mix",
                "items": [
                    {key: value for key, value in item.items() if key != "stem_name"}
                    for item in mix_by_guid.values()
                ],
                "targets": [str(item["stem_name"]) for item in mix_by_guid.values()],
            },
        )
    risk = max(risks, key=_risk_rank) if risks else "low"
    return {
        "title": "Plan de acciones del chat",
        "summary": f"{len(changes)} cambio(s) determinista(s) listo(s) para REAPER.",
        "risk": risk,
        "requires_approval": True,
        "changes": changes,
        "project_name": project_name,
        "project_ref": project_ref,
        "operations": operations,
        "executable": True,
    }


def _execute_chat_action_plan(plan: dict[str, Any]) -> dict[str, Any]:
    client = BridgeClient(timeout_seconds=60.0)
    project_ref = str(plan["project_ref"])
    transactions: list[str] = []
    try:
        for operation in plan["operations"]:
            kind = operation["kind"]
            if kind == "static_mix":
                reply = client.call(
                    "apply_track_mix_batch",
                    {"project_ref": project_ref, "items": operation["items"]},
                )
            elif kind == "adjust_compressor":
                reply = client.call(
                    "adjust_reacomp",
                    {
                        "project_ref": project_ref,
                        "track_guid": operation["track_guid"],
                        "fx_guid": operation["fx_guid"],
                        "attack_percent_delta": operation["attack_percent_delta"],
                    },
                )
            elif kind == "filter":
                proposal = operation["proposal"]
                reply = apply_filter_proposal(
                    client,
                    project_ref=project_ref,
                    track_guid=str(operation["track_guid"]),
                    proposal=proposal,
                    approved_proposal_id=str(proposal["proposal_id"]),
                    existing_fx=operation["existing_fx"],
                    selected_fx_guid=operation["selected_fx_guid"],
                )
            elif kind == "producer_chain":
                chain = operation["chain"]
                reply = apply_producer_chain(
                    client,
                    project_ref=project_ref,
                    track_guid=str(operation["track_guid"]),
                    chain=chain,
                    approved_chain_id=str(chain["chain_id"]),
                )
            elif kind == "ambience":
                payload = operation["payload"]
                bus_reply = client.call(
                    "create_effect_bus",
                    {
                        "project_ref": project_ref,
                        "bus_name": payload["bus_name"],
                        "effect_type": payload["effect_type"],
                        "parameters": payload["parameters"],
                    },
                    timeout_seconds=30.0,
                )
                bus_transaction = str(
                    bus_reply.result.get("transaction_request_id", bus_reply.request_id)
                )
                transactions.append(bus_transaction)
                bus = bus_reply.result["bus"]
                reply = client.call(
                    "create_bus_send",
                    {
                        "project_ref": project_ref,
                        "source_track_guid": operation["track_guid"],
                        "destination_track_guid": bus["guid"],
                        "volume_db": payload["send_db"],
                        "pan": 0.0,
                    },
                )
            elif kind == "vocal_rider":
                proposal = operation["proposal"]
                reply = client.call(
                    "apply_vocal_rider_envelope",
                    {
                        "project_ref": project_ref,
                        "track_guid": operation["track_guid"],
                        "item_guid": operation["item_guid"],
                        "proposal_id": proposal["proposal_id"],
                        "source_file_path": proposal["source_file_path"],
                        "source_sha256": proposal["source_sha256"],
                        "source_kind": "organic_multitrack",
                        "points": proposal["envelope_points"],
                    },
                )
            elif kind == "section_volume":
                reply = client.call(
                    "apply_section_volume_envelope",
                    {
                        "project_ref": project_ref,
                        "track_guid": operation["track_guid"],
                        **operation["payload"],
                    },
                )
            elif kind == "mastering":
                reply = client.call(
                    "apply_mastering_limiter",
                    {"project_ref": project_ref, **operation["payload"]},
                    timeout_seconds=30.0,
                )
            elif kind == "render":
                output_file = str(operation["output_file"])
                reply = client.call(
                    "render_master_candidate",
                    {
                        "project_ref": project_ref,
                        "output_file": output_file,
                        "sample_rate_hz": operation["sample_rate_hz"],
                    },
                    timeout_seconds=900.0,
                )
                render_transaction = str(
                    reply.result.get("transaction_request_id", reply.request_id)
                )
                transactions.append(render_transaction)
                file_report = build_master_delivery_qc(Path(output_file))
                report = build_rendered_master_candidate_report(reply.to_dict(), file_report)
                report_path = Path(output_file).with_suffix(".report.json")
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                snapshot = reply.result.get("previous_render_settings")
                reply = client.call(
                    "restore_render_settings",
                    {
                        "project_ref": project_ref,
                        "output_file": output_file,
                        "snapshot": snapshot,
                    },
                    timeout_seconds=30.0,
                )
            elif kind == "midi_cleanup":
                report = run_cleanup(
                    Path(operation["midi_path"]),
                    Path(operation["audio_path"]),
                    Path(operation["output_directory"]),
                    bpm=float(operation["bpm"]),
                    profile=str(operation["profile"]),
                )
                runtime.record_activity(
                    {
                        "kind": "midi_cleanup",
                        "project": plan["project_name"],
                        "target": Path(operation["midi_path"]).name,
                        "summary": "Variantes MIDI generadas; original preservado",
                        "reaper_modified": False,
                        "report_path": report.get("report_path"),
                    }
                )
                continue
            elif kind == "song_structure":
                reply = client.call(
                    "apply_song_structure_regions",
                    {"project_ref": project_ref, **operation["payload"]},
                    timeout_seconds=60.0,
                )
            else:
                raise ValueError(f"Operación no ejecutable: {kind}")
            transactions.append(str(reply.result.get("transaction_request_id", reply.request_id)))
    except Exception:
        for transaction_id in reversed(transactions):
            try:
                client.call(
                    "undo_transaction",
                    {"project_ref": project_ref, "transaction_request_id": transaction_id},
                    timeout_seconds=15.0,
                )
            except Exception:
                pass
        raise
    return {
        "status": "applied",
        "message": "Plan aplicado y verificado en REAPER.",
        "project_ref": project_ref,
        "transaction_request_ids": transactions,
        "transaction_request_id": transactions[-1] if transactions else None,
    }


def _source_label(source_kind: str) -> str:
    return {
        "suno_stems": "Suno",
        "organic_multitrack": "Orgánico",
        "unknown": "Sin clasificar",
        "mixed": "Suno + orgánico",
    }.get(source_kind, source_kind)


def _suggested_track_names(stems: list[dict[str, Any]]) -> dict[str, str]:
    labels = {
        str(stem["name"]): re.sub(r"^\s*\d+\s*[-_. ]*", "", str(stem["name"]))
        .replace("_", " ")
        .strip()
        or str(stem["name"])
        for stem in stems
    }
    totals = Counter(label.casefold() for label in labels.values())
    indexes: Counter[str] = Counter()
    result = {}
    for stem in stems:
        name = str(stem["name"])
        label = labels[name]
        key = label.casefold()
        indexes[key] += 1
        result[name] = f"{label} {indexes[key]}" if totals[key] > 1 else label
    return result


def _project_view(name: str) -> dict[str, Any]:
    context = build_project_context(name)
    metadata = _project_metadata(name)
    file_source_overrides = metadata.get("stem_source_files", {})
    if not isinstance(file_source_overrides, dict):
        file_source_overrides = {}
    song = context["song"]
    source = str(song.get("source_kind") or "unknown")
    source_label = _source_label(source)
    analysis = context.get("analysis")
    analyzed_by_name = {
        str(stem.get("name")): stem
        for stem in (analysis or {}).get("stems", [])
        if isinstance(stem, dict)
    }
    raw_stems = list(context["stems"])
    configured_order = metadata.get("stem_order", [])
    if isinstance(configured_order, list):
        positions = {str(value): index for index, value in enumerate(configured_order)}
        raw_stems.sort(
            key=lambda stem: (
                positions.get(str(stem["name"]), len(positions)),
                str(stem["name"]).casefold(),
            )
        )
    fallback_track_names = _suggested_track_names(raw_stems)
    stems = []
    for stem in raw_stems:
        diagnosed = analyzed_by_name.get(str(stem["name"]))
        stem_source_kind = (
            str(diagnosed.get("source_kind"))
            if diagnosed
            else str(file_source_overrides.get(str(stem["name"]), source))
        )
        findings = diagnosed.get("findings", []) if diagnosed else []
        finding_count = len(findings) if isinstance(findings, list) else 0
        stems.append(
            {
                **stem,
                "track_name": str(diagnosed.get("track_name", fallback_track_names[str(stem["name"])]))
                if diagnosed
                else fallback_track_names[str(stem["name"])],
                "source_kind": stem_source_kind,
                "source": _source_label(stem_source_kind),
                "status": "Analizado" if diagnosed else "Disponible",
                "problems": (
                    "Sin problemas detectados"
                    if diagnosed and finding_count == 0
                    else f"{finding_count} hallazgo" + ("" if finding_count == 1 else "s")
                    if diagnosed
                    else "Sin analizar"
                ),
            }
        )
    return {
        "name": song["title"],
        "tempo_bpm": song.get("tempo_bpm"),
        "source_kind": source,
        "source_label": source_label,
        "status": song.get("status"),
        "sections": context["lyrics"]["sections"],
        "lyrics_available": context["lyrics"]["available"],
        "stems": stems,
        "midi_files": context["midi_files"],
        "references": context["references"],
        "verification": context["verification"],
        "analysis": analysis,
        "reaper_project_path": metadata.get("reaper_project_path"),
    }


async def _lm_status() -> dict[str, Any]:
    config = runtime.brain()
    try:
        models = await asyncio.to_thread(
            LMStudioClient(config).list_models, timeout_seconds=2.0
        )
    except (LMStudioError, ValueError) as exc:
        return {"connected": False, "models": [], "error": str(exc)}
    selected = config.model or (models[0] if models else "")
    return {"connected": True, "models": models, "selected_model": selected}


async def _bridge_status() -> dict[str, Any]:
    try:
        reply = await asyncio.to_thread(
            BridgeClient(timeout_seconds=0.75).call,
            "health_check",
        )
    except Exception as exc:  # bridge errors are intentionally presented as status
        return {"connected": False, "error": str(exc)}
    result = dict(reply.result)
    return {
        "connected": True,
        "bridge_version": result.get("bridge_version"),
        "reaper_version": result.get("reaper_version"),
        "project_ref": result.get("project_ref"),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/settings/brain")
def get_brain_settings() -> dict[str, Any]:
    return runtime.public_brain()


@app.get("/api/agent-protocol")
def get_agent_protocol() -> dict[str, Any]:
    return {
        "name": AGENT_PROTOCOL_NAME,
        "version": AGENT_PROTOCOL_VERSION,
        "schema_base": "schemas/agent/v1",
        "action_kinds": sorted(ACTION_FIELDS),
        "evidence_types": sorted(EVIDENCE_TYPES),
        "execution_boundary": (
            "El LLM propone acciones; PampaPilot valida, aprueba, ejecuta y verifica."
        ),
    }


@app.put("/api/settings/brain")
async def configure_brain(value: BrainSettingsInput) -> dict[str, Any]:
    try:
        runtime.configure_brain(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**runtime.public_brain(), "status": await _lm_status()}


@app.get("/api/projects/{project_name}/chat-state")
def get_project_chat_state(project_name: str) -> dict[str, Any]:
    try:
        return _chat_state_for_project(_validate_song_name(project_name))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/chat/new")
def start_project_chat(project_name: str) -> dict[str, Any]:
    try:
        return _start_new_project_chat(
            _validate_song_name(project_name), archive_current=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/chat/archive")
def archive_project_chat(project_name: str) -> dict[str, Any]:
    try:
        return _start_new_project_chat(
            _validate_song_name(project_name), archive_current=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/projects/{project_name}/chat/history")
def clear_project_chat(project_name: str) -> dict[str, Any]:
    try:
        return _start_new_project_chat(
            _validate_song_name(project_name), archive_current=False
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/projects/{project_name}/chat/archives/{archive_id}")
def get_archived_project_chat(project_name: str, archive_id: str) -> dict[str, Any]:
    try:
        return _archived_project_chat(_validate_song_name(project_name), archive_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversación archivada no encontrada") from exc


@app.post("/api/projects/{project_name}/chat/archives/{archive_id}/restore")
def restore_archived_project_chat(project_name: str, archive_id: str) -> dict[str, Any]:
    try:
        return _restore_project_chat(_validate_song_name(project_name), archive_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversación archivada no encontrada") from exc


@app.put("/api/chat/reasoning")
def set_chat_reasoning(value: ReasoningModeInput) -> dict[str, Any]:
    state = _read_chat_state()
    state["reasoning_mode"] = value.reasoning_mode
    _write_chat_state(state)
    return {"reasoning_mode": value.reasoning_mode}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    lm, bridge = await asyncio.gather(_lm_status(), _bridge_status())
    return {"application": "ready", "brain": lm, "reaper": bridge}


@app.post("/api/window/compact")
def open_compact_window(value: CompactWindowInput) -> dict[str, Any]:
    if os.name != "nt":
        raise HTTPException(
            status_code=501,
            detail="El modo always-on-top automático está implementado para Windows",
        )
    launcher = WORKSPACE_ROOT / "scripts" / "open-compact.ps1"
    if not launcher.is_file():
        raise HTTPException(status_code=500, detail="No se encontró el lanzador compacto")
    project_name = ""
    if value.project_name.strip():
        try:
            project_name = _validate_song_name(value.project_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher),
                "-ProjectName",
                project_name,
            ],
            cwd=str(WORKSPACE_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"No se pudo iniciar la ventana compacta: {exc}"
        ) from exc
    return {"status": "opening", "mode": "compact", "always_on_top": True}


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    projects = []
    for name in _project_names():
        try:
            projects.append(_project_view(name))
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            projects.append({"name": name, "status": "invalid", "error": str(exc)})
    return {"projects": projects}


@app.get("/api/projects/{project_name}")
def get_project(project_name: str) -> dict[str, Any]:
    try:
        return _project_view(_validate_song_name(project_name))
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/analysis")
async def analyze_project(project_name: str) -> dict[str, Any]:
    """Run the deterministic WAV engine before asking any LLM to interpret it."""

    try:
        name = _validate_song_name(project_name)
        metadata = _project_metadata(name)
        bpm = metadata.get("tempo_bpm")
        if not isinstance(bpm, (int, float)):
            raise ValueError("El proyecto necesita un BPM antes de analizarlo")
        source_kind = str(metadata.get("source_kind", "unknown"))
        artifact = await asyncio.to_thread(
            analyze_project_media,
            name,
            float(bpm),
            source_kind,
            source_overrides_from_metadata(metadata),
        )
        project = _project_view(name)
    except (ValueError, FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    diagnosis = artifact["diagnosis"]
    return {
        "project": project,
        "summary": diagnosis["summary"],
        "verification": diagnosis["verification"],
    }


@app.get("/api/capabilities")
def capabilities() -> dict[str, Any]:
    return {"groups": capability_catalog()}


@app.get("/api/activity")
def activity() -> dict[str, Any]:
    return {"items": runtime.activity()}


@app.get("/api/reaper/project")
async def reaper_project() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            bridge_project, BridgeClient(timeout_seconds=1.25)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"REAPER/Bridge no disponible: {exc}") from exc


@app.put("/api/projects/{project_name}/stem-source")
def classify_project_stem(project_name: str, value: StemSourceInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        stem = _stem_descriptor(name, value.stem_name)
        metadata = _project_metadata(name)
        sources = metadata.get("stem_sources")
        sources = dict(sources) if isinstance(sources, dict) else {}
        sources[str(stem["track_name"])] = value.source_kind
        metadata["stem_sources"] = sources
        file_sources = metadata.get("stem_source_files")
        file_sources = dict(file_sources) if isinstance(file_sources, dict) else {}
        file_sources[value.stem_name] = value.source_kind
        metadata["stem_source_files"] = file_sources
        _write_project_metadata(name, metadata)
        runtime.record_activity(
            {
                "kind": "classification",
                "project": name,
                "target": value.stem_name,
                "summary": f"Origen definido como {_source_label(value.source_kind)}",
                "reaper_modified": False,
            }
        )
        return {"project": _project_view(name), "analysis_invalidated": True}
    except (ValueError, FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/producer-chain/preview")
async def preview_project_chain(project_name: str, value: StemActionInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        stem = _stem_descriptor(name, value.stem_name)
        source_kind = value.source_kind or _source_kind_for_stem(name, stem)
        existing_fx: list[dict[str, Any]] = []
        reaper_binding: dict[str, Any] | None = None
        try:
            _, state, track = await asyncio.to_thread(
                _connected_stem, name, value.stem_name, 1.25
            )
            track_state = await asyncio.to_thread(
                BridgeClient(timeout_seconds=8.0).call,
                "get_track_state",
                {"project_ref": state["result"]["project_ref"], "track_guid": track["guid"]},
            )
            existing_fx = [dict(item) for item in track_state.result.get("fx", [])]
            reaper_binding = {
                "project_ref": state["result"]["project_ref"],
                "track_guid": track["guid"],
                "track_name": track["name"],
            }
        except Exception:
            reaper_binding = None
        chain = await asyncio.to_thread(
            track_producer_chain,
            Path(stem["path"]),
            str(stem["role"]),
            source_kind,
            existing_fx=existing_fx,
            include_artistic_saturation=value.include_artistic_saturation,
        )
        return {
            "chain": chain,
            "reaper_binding": reaper_binding,
            "can_apply": bool(reaper_binding) and chain["review_status"] == "user_approval_required",
        }
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/producer-chain/apply")
async def apply_project_chain(project_name: str, value: ApplyChainInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        stem, state, track = await asyncio.to_thread(_connected_stem, name, value.stem_name)
        project_ref = str(state["result"]["project_ref"])
        track_state = await asyncio.to_thread(
            BridgeClient(timeout_seconds=8.0).call,
            "get_track_state",
            {"project_ref": project_ref, "track_guid": track["guid"]},
        )
        source_kind = value.source_kind or _source_kind_for_stem(name, stem)
        chain = await asyncio.to_thread(
            track_producer_chain,
            Path(stem["path"]),
            str(stem["role"]),
            source_kind,
            existing_fx=[dict(item) for item in track_state.result.get("fx", [])],
            include_artistic_saturation=value.include_artistic_saturation,
        )
        reply = await asyncio.to_thread(
            apply_producer_chain,
            BridgeClient(timeout_seconds=60.0),
            project_ref=project_ref,
            track_guid=str(track["guid"]),
            chain=chain,
            approved_chain_id=value.approved_chain_id,
        )
        transaction_id = str(reply.result.get("transaction_request_id", reply.request_id))
        runtime.record_activity(
            {
                "kind": "producer_chain",
                "project": name,
                "target": value.stem_name,
                "summary": f"Cadena aplicada: {len(chain['steps'])} procesadores",
                "reaper_modified": True,
                "project_ref": project_ref,
                "transaction_request_id": transaction_id,
            }
        )
        return {"chain": chain, "application": reply.to_dict(), "transaction_request_id": transaction_id}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/filters/preview")
async def preview_project_filter(project_name: str, value: FilterInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        stem = _stem_descriptor(name, value.stem_name)
        source_kind = value.source_kind or _source_kind_for_stem(name, stem)
        proposal = await asyncio.to_thread(
            build_filter_proposal,
            Path(stem["path"]),
            str(stem["role"]),
            source_kind,
            value.filter_type,
            preset_name=value.preset_name,
        )
        existing_fx: list[dict[str, Any]] = []
        reaper_binding: dict[str, Any] | None = None
        try:
            _, state, track = await asyncio.to_thread(
                _connected_stem, name, value.stem_name, 1.25
            )
            track_state = await asyncio.to_thread(
                BridgeClient(timeout_seconds=8.0).call,
                "get_track_state",
                {"project_ref": state["result"]["project_ref"], "track_guid": track["guid"]},
            )
            existing_fx = [dict(item) for item in track_state.result.get("fx", [])]
            reaper_binding = {
                "project_ref": state["result"]["project_ref"],
                "track_guid": track["guid"],
                "track_name": track["name"],
            }
        except Exception:
            reaper_binding = None
        binding = filter_bindings(proposal, existing_fx)
        return {
            "proposal": proposal,
            "binding": binding,
            "reaper_binding": reaper_binding,
            "can_apply": bool(reaper_binding) and bool(proposal["can_approve"]),
        }
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/filters/apply")
async def apply_project_filter(project_name: str, value: ApplyFilterInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        stem, state, track = await asyncio.to_thread(_connected_stem, name, value.stem_name)
        project_ref = str(state["result"]["project_ref"])
        track_state = await asyncio.to_thread(
            BridgeClient(timeout_seconds=8.0).call,
            "get_track_state",
            {"project_ref": project_ref, "track_guid": track["guid"]},
        )
        existing_fx = [dict(item) for item in track_state.result.get("fx", [])]
        source_kind = value.source_kind or _source_kind_for_stem(name, stem)
        proposal = await asyncio.to_thread(
            build_filter_proposal,
            Path(stem["path"]),
            str(stem["role"]),
            source_kind,
            value.filter_type,
            preset_name=value.preset_name,
        )
        reply = await asyncio.to_thread(
            apply_filter_proposal,
            BridgeClient(timeout_seconds=60.0),
            project_ref=project_ref,
            track_guid=str(track["guid"]),
            proposal=proposal,
            approved_proposal_id=value.approved_proposal_id,
            existing_fx=existing_fx,
            selected_fx_guid=value.fx_guid,
        )
        transaction_id = str(reply.result.get("transaction_request_id", reply.request_id))
        runtime.record_activity(
            {
                "kind": "filter",
                "project": name,
                "target": value.stem_name,
                "summary": f"{proposal['title']} aplicado y verificado",
                "reaper_modified": True,
                "project_ref": project_ref,
                "transaction_request_id": transaction_id,
            }
        )
        return {
            "proposal": proposal,
            "application": reply.to_dict(),
            "transaction_request_id": transaction_id,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/static-mix/apply")
async def apply_static_mix(project_name: str, value: StaticMixInput) -> dict[str, Any]:
    if all(item is None for item in (value.volume_db, value.pan, value.muted, value.solo)):
        raise HTTPException(status_code=422, detail="No hay ningún ajuste para aplicar")
    try:
        name = _validate_song_name(project_name)
        _, state, track = await asyncio.to_thread(_connected_stem, name, value.stem_name)
        project_ref = str(state["result"]["project_ref"])
        client = BridgeClient(timeout_seconds=15.0)
        action = "apply_track_mix_batch"
        item = {"track_guid": track["guid"]}
        if value.volume_db is not None:
            item["volume_db"] = value.volume_db
        if value.pan is not None:
            item["pan"] = value.pan
        if value.muted is not None:
            item["muted"] = value.muted
        if value.solo is not None:
            item["soloed"] = value.solo
        params = {"project_ref": project_ref, "items": [item]}
        reply = await asyncio.to_thread(client.call, action, params)
        transaction_id = str(reply.result.get("transaction_request_id", reply.request_id))
        runtime.record_activity(
            {
                "kind": "static_mix",
                "project": name,
                "target": value.stem_name,
                "summary": "Ajuste estático aplicado y verificado",
                "reaper_modified": True,
                "project_ref": project_ref,
                "transaction_request_id": transaction_id,
            }
        )
        return {"application": reply.to_dict(), "transaction_request_id": transaction_id}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/reaper/undo")
async def undo_reaper(value: UndoInput) -> dict[str, Any]:
    try:
        reply = await asyncio.to_thread(
            BridgeClient(timeout_seconds=15.0).call,
            "undo_transaction",
            value.model_dump(),
        )
        runtime.record_activity(
            {
                "kind": "undo",
                "project": "",
                "target": "REAPER",
                "summary": "Última acción de PampaPilot deshecha",
                "reaper_modified": True,
            }
        )
        return reply.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/reaper/undo-plan")
async def undo_reaper_plan(value: UndoPlanInput) -> dict[str, Any]:
    undone: list[str] = []
    try:
        client = BridgeClient(timeout_seconds=15.0)
        for transaction_id in reversed(value.transaction_request_ids):
            await asyncio.to_thread(
                client.call,
                "undo_transaction",
                {
                    "project_ref": value.project_ref,
                    "transaction_request_id": transaction_id,
                },
            )
            undone.append(transaction_id)
        runtime.record_activity(
            {
                "kind": "undo_plan",
                "project": "",
                "target": "REAPER",
                "summary": f"Plan de {len(undone)} transacciones deshecho",
                "reaper_modified": True,
            }
        )
        return {"status": "undone", "transaction_request_ids": undone}
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Se deshicieron {len(undone)} transacciones antes del error: {exc}",
        ) from exc


def _copy_upload(upload: UploadFile, destination: Path, suffixes: set[str]) -> None:
    filename = Path(upload.filename or "").name
    if not filename or Path(filename).suffix.casefold() not in suffixes:
        raise ValueError(f"Archivo no soportado: {filename or 'sin nombre'}")
    if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
        raise ValueError(f"Archivo demasiado grande: {filename}")
    target = destination / filename
    if target.exists():
        raise FileExistsError(target)
    with target.open("xb") as output:
        shutil.copyfileobj(upload.file, output, length=1024 * 1024)


def _named_uploads(uploads: list[UploadFile | str]) -> list[UploadFile]:
    """Ignore the empty multipart placeholders emitted by optional file inputs."""

    return [
        upload
        for upload in uploads
        if not isinstance(upload, str) and Path(upload.filename or "").name
    ]


def _stem_files(name: str) -> list[Path]:
    directory = WORKSPACE_ROOT / "media" / "inbox" / "stems" / name
    if not directory.is_dir():
        raise FileNotFoundError("La canción no tiene carpeta de stems")
    return sorted(
        (
            path.resolve()
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".wav"
        ),
        key=lambda path: path.name.casefold(),
    )


def _invalidate_project_analysis(name: str) -> None:
    analysis = WORKSPACE_ROOT / "sessions" / name / "analysis"
    if analysis.is_dir():
        shutil.rmtree(analysis)


def _ordered_stem_paths(name: str) -> list[Path]:
    files = _stem_files(name)
    by_stem = {path.stem: path for path in files}
    metadata = _project_metadata(name)
    configured = metadata.get("stem_order", [])
    ordered = [by_stem.pop(str(value)) for value in configured if str(value) in by_stem] if isinstance(configured, list) else []
    ordered.extend(sorted(by_stem.values(), key=lambda path: path.name.casefold()))
    return ordered


@app.post("/api/projects", status_code=201)
def create_project(
    title: Annotated[str, Form(min_length=1, max_length=128)],
    bpm: Annotated[float, Form(ge=20, le=400)],
    source_kind: Annotated[
        Literal["suno_stems", "organic_multitrack", "mixed", "unknown"], Form()
    ],
    lyrics: Annotated[str, Form(max_length=100_000)] = "",
    stems: Annotated[list[UploadFile | str], File()] = [],
    midi: Annotated[list[UploadFile | str], File()] = [],
    reference: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    try:
        name = _validate_song_name(title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stem_dir = WORKSPACE_ROOT / "media" / "inbox" / "stems" / name
    midi_dir = WORKSPACE_ROOT / "media" / "inbox" / "midi" / name
    if stem_dir.exists() or midi_dir.exists():
        raise HTTPException(status_code=409, detail="La canción ya existe")
    stem_dir.mkdir(parents=True)
    midi_dir.mkdir(parents=True)
    try:
        for upload in _named_uploads(stems):
            _copy_upload(upload, stem_dir, {".wav"})
        for upload in _named_uploads(midi):
            _copy_upload(upload, midi_dir, {".mid", ".midi"})
        if reference is not None and reference.filename:
            references = WORKSPACE_ROOT / "media" / "references"
            references.mkdir(parents=True, exist_ok=True)
            suffix = Path(reference.filename).suffix.casefold()
            reference.filename = f"{name} - reference{suffix}"
            _copy_upload(reference, references, {".wav", ".flac"})
        if lyrics.strip():
            (stem_dir / "lyric-clean.txt").write_text(
                lyrics.strip() + "\n", encoding="utf-8"
            )
        (stem_dir / "session.json").write_text(
            json.dumps(
                {
                    "title": name,
                    "tempo_bpm": bpm,
                    "source_kind": source_kind,
                    "status": "uploaded_from_web",
                    "stem_order": [
                        Path(upload.filename or "").stem
                        for upload in _named_uploads(stems)
                    ],
                    "reaper_sync_required": bool(_named_uploads(stems)),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except (ValueError, FileExistsError, OSError) as exc:
        shutil.rmtree(stem_dir, ignore_errors=True)
        shutil.rmtree(midi_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _project_view(name)


@app.post("/api/projects/{project_name}/stems")
def add_project_stems(
    project_name: str,
    stems: Annotated[list[UploadFile | str], File()] = [],
) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        directory = WORKSPACE_ROOT / "media" / "inbox" / "stems" / name
        if not directory.is_dir():
            raise FileNotFoundError("La canción no existe")
        uploads = _named_uploads(stems)
        if not uploads:
            raise ValueError("Elegí al menos un WAV o FLAC")
        existing = {path.name.casefold() for path in _stem_files(name)}
        incoming = [Path(upload.filename or "").name for upload in uploads]
        if len({value.casefold() for value in incoming}) != len(incoming):
            raise ValueError("La selección contiene nombres duplicados")
        duplicates = [value for value in incoming if value.casefold() in existing]
        if duplicates:
            raise FileExistsError(f"Ya existe el stem {duplicates[0]}")
        for upload in uploads:
            _copy_upload(upload, directory, {".wav"})
        metadata = _project_metadata(name)
        order = metadata.get("stem_order", [])
        order = [str(value) for value in order] if isinstance(order, list) else []
        order.extend(Path(value).stem for value in incoming)
        metadata["stem_order"] = list(dict.fromkeys(order))
        metadata["reaper_sync_required"] = True
        _write_project_metadata(name, metadata)
        _invalidate_project_analysis(name)
        return _project_view(name)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/projects/{project_name}/stems/{stem_name}")
def delete_project_stem(project_name: str, stem_name: str) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        requested = stem_name.strip()
        matches = [path for path in _stem_files(name) if path.stem == requested]
        if len(matches) != 1:
            raise FileNotFoundError(f"No existe el stem {requested}")
        metadata = _project_metadata(name)
        imported = metadata.get("reaper_imported_stems", [])
        if isinstance(imported, list) and requested in {str(value) for value in imported}:
            raise FileExistsError(
                "El stem ya está usado por REAPER. La retirada sincronizada se implementará sin borrar su WAV de origen."
            )
        matches[0].unlink()
        order = metadata.get("stem_order", [])
        if isinstance(order, list):
            metadata["stem_order"] = [value for value in order if str(value) != requested]
        metadata["reaper_sync_required"] = True
        metadata.setdefault("removed_stems", []).append(requested)
        _write_project_metadata(name, metadata)
        _invalidate_project_analysis(name)
        return _project_view(name)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/projects/{project_name}/stem-order")
def order_project_stems(project_name: str, value: StemOrderInput) -> dict[str, Any]:
    try:
        name = _validate_song_name(project_name)
        current = {path.stem for path in _stem_files(name)}
        requested = [item.strip() for item in value.names]
        if len(set(requested)) != len(requested) or set(requested) != current:
            raise ValueError("El orden debe contener cada stem exactamente una vez")
        metadata = _project_metadata(name)
        metadata["stem_order"] = requested
        metadata["reaper_sync_required"] = True
        _write_project_metadata(name, metadata)
        return _project_view(name)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_name}/reaper-sync")
async def sync_project_to_reaper(project_name: str) -> dict[str, Any]:
    """Create/open the song RPP and import only audio sources not already present."""

    try:
        name = _validate_song_name(project_name)
        metadata = _project_metadata(name)
        bpm = metadata.get("tempo_bpm")
        if not isinstance(bpm, (int, float)):
            raise ValueError("La canción necesita un BPM válido")
        stems = _ordered_stem_paths(name)
        session_dir = (WORKSPACE_ROOT / "sessions" / name).resolve()
        project_path = (session_dir / f"{name}.rpp").resolve()
        client = BridgeClient(timeout_seconds=30.0)
        state = bridge_project(client)["result"]
        active_path = str(state.get("project_path") or "")
        same_project = active_path and os.path.normcase(os.path.abspath(active_path)) == os.path.normcase(str(project_path))
        created = False
        opened = False
        if not same_project:
            if project_path.is_file():
                reply = await asyncio.to_thread(
                    client.call,
                    "open_song_project",
                    {"project_path": str(project_path)},
                )
                opened = True
            else:
                reply = await asyncio.to_thread(
                    client.call,
                    "create_song_project",
                    {"project_path": str(project_path), "bpm": float(bpm)},
                )
                created = True
            project_ref = str(reply.result["project_ref"])
        else:
            project_ref = str(state["project_ref"])

        current = bridge_project(client)["result"]
        project_ref = str(current["project_ref"])
        imported_sources: set[str] = set()
        for track in current.get("tracks", []):
            items_reply = await asyncio.to_thread(
                client.call,
                "get_track_items",
                {"project_ref": project_ref, "track_guid": track["guid"]},
            )
            for item in items_reply.result.get("items", []):
                take = item.get("take") if isinstance(item, dict) else None
                source_path = take.get("source_path") if isinstance(take, dict) else None
                if source_path:
                    imported_sources.add(os.path.normcase(os.path.abspath(str(source_path))))

        project = _project_view(name)
        track_names = {stem["name"]: stem["track_name"] for stem in project["stems"]}
        missing = [
            path for path in stems
            if os.path.normcase(os.path.abspath(str(path))) not in imported_sources
        ]
        if missing:
            await asyncio.to_thread(
                client.call,
                "import_audio_batch",
                {
                    "project_ref": project_ref,
                    "items": [
                        {
                            "file_path": str(path),
                            "track_name": track_names[path.stem],
                            "position_seconds": 0.0,
                        }
                        for path in missing
                    ],
                },
                timeout_seconds=60.0,
            )
        if stems:
            await asyncio.to_thread(
                client.call,
                "reorder_audio_tracks_by_source",
                {
                    "project_ref": project_ref,
                    "source_paths": [str(path) for path in stems],
                },
                timeout_seconds=30.0,
            )
        await asyncio.to_thread(
            client.call,
            "set_project_tempo",
            {"project_ref": project_ref, "bpm": float(bpm)},
        )
        saved = await asyncio.to_thread(
            client.call,
            "save_project_as",
            {"project_ref": project_ref, "project_path": str(project_path)},
        )
        metadata["reaper_project_path"] = str(project_path)
        metadata["reaper_sync_required"] = False
        metadata["reaper_imported_stems"] = [path.stem for path in stems]
        _write_project_metadata(name, metadata)
        runtime.record_activity(
            {
                "kind": "reaper_sync",
                "project": name,
                "target": "REAPER",
                "summary": f"{len(missing)} stem(s) importados; proyecto guardado.",
                "reaper_modified": bool(created or missing),
            }
        )
        return {
            "project": _project_view(name),
            "project_path": str(project_path),
            "created": created,
            "opened": opened,
            "imported_count": len(missing),
            "already_present_count": len(stems) - len(missing),
            "track_count": saved.result.get("track_count"),
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/chat")
async def chat(value: ChatInput) -> dict[str, Any]:
    try:
        project_name = _validate_song_name(value.project_name)
        conversation_id = str(
            _chat_state_for_project(project_name)["conversation_id"]
        )
        deep_context = request_needs_deep_context(value.message)
        direct_action = request_is_direct_action(value.message)
        conversation = runtime.conversation(conversation_id, project_name)
        context_level = (
            "action"
            if direct_action
            else "deep"
            if deep_context
            or (conversation is not None and conversation.get("context_level") == "deep")
            else "compact"
        )
        context: dict[str, Any] | None = None
        context_revision = (
            conversation.get("context_revision", "") if conversation else ""
        )
        if conversation is None:
            context = build_project_context(project_name)
            if direct_action:
                context = action_project_context(context)
            elif not deep_context:
                context = compact_project_context(context)
            context_revision = _context_revision(context)
            messages = build_agent_messages(
                context,
                value.message,
                [item.model_dump() for item in value.history],
            )
        elif direct_action:
            context = action_project_context(build_project_context(project_name))
            current_revision = _context_revision(context)
            if (
                conversation.get("context_level") != "action"
                or conversation.get("context_revision") != current_revision
            ):
                context_revision = current_revision
                messages = [
                    {
                        "role": "user",
                        "content": build_context_update_message(context, value.message),
                    }
                ]
            else:
                messages = [{
                    "role": "user",
                    "content": build_turn_context_message(context, value.message),
                }]
        elif deep_context:
            context = build_project_context(project_name)
            current_revision = _context_revision(context)
            if (
                conversation.get("context_level") != "deep"
                or conversation.get("context_revision") != current_revision
            ):
                context_revision = current_revision
                messages = [
                    {
                        "role": "user",
                        "content": build_context_update_message(context, value.message),
                    }
                ]
            else:
                messages = [{
                    "role": "user",
                    "content": build_turn_context_message(context, value.message),
                }]
        else:
            messages = [{"role": "user", "content": value.message}]
        use_reasoning = value.reasoning_mode == "deep" or (
            value.reasoning_mode == "auto"
            and (
                direct_action
                or (deep_context and request_needs_reasoning(value.message))
            )
        )
        result = await asyncio.to_thread(
            LMStudioClient(runtime.brain()).chat_result,
            messages,
            max_tokens=1600 if direct_action else 900 if use_reasoning else 600,
            reasoning="on" if use_reasoning else "off",
            previous_response_id=None
            if conversation is None
            else conversation["response_id"],
            store=True,
        )
        response = parse_agent_response(result.content)
        if not response.get("structured"):
            repair = await asyncio.to_thread(
                LMStudioClient(runtime.brain()).chat_result,
                [
                    {
                        "role": "user",
                        "content": (
                            "Tu respuesta anterior quedó incompleta o no fue JSON válido. "
                            "Repetí la misma decisión como un único objeto JSON válido, sin Markdown, "
                            "respetando exactamente el contrato de actions y los nombres de stems del contexto."
                        ),
                    }
                ],
                max_tokens=1600,
                reasoning="on" if use_reasoning else "off",
                previous_response_id=result.response_id,
                store=True,
            )
            repaired_response = parse_agent_response(repair.content)
            if repaired_response.get("structured"):
                result = repair
                response = repaired_response
            else:
                response = {
                    "message": (
                        "El modelo no pudo devolver una orden estructurada válida. "
                        "No se aplicó ningún cambio en REAPER."
                    ),
                    "proposal": None,
                    "actions": [],
                    "structured": False,
                }
        evidence_actions = [
            item for item in response.get("actions", [])
            if item.get("kind") == "request_evidence"
        ]
        other_actions = [
            item for item in response.get("actions", [])
            if item.get("kind") != "request_evidence"
        ]
        if evidence_actions:
            if other_actions:
                response = {
                    "message": (
                        "El modelo mezcló consultas de evidencia con cambios. "
                        "No se aplicó nada; debe evaluar primero los datos solicitados."
                    ),
                    "proposal": None,
                    "actions": [],
                    "structured": True,
                    "protocol_version": "1.0",
                }
            else:
                evidence = await asyncio.to_thread(
                    _resolve_agent_evidence, project_name, evidence_actions
                )
                evidence_result = await asyncio.to_thread(
                    LMStudioClient(runtime.brain()).chat_result,
                    [{
                        "role": "user",
                        "content": (
                            "PampaPilot resolvió tu solicitud de evidencia. "
                            "Tomá ahora una decisión final usando el contrato agent/1.0; "
                            "no vuelvas a pedir evidencia en esta ronda:\n"
                            + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
                        ),
                    }],
                    max_tokens=1600,
                    reasoning="on" if use_reasoning else "off",
                    previous_response_id=result.response_id,
                    store=True,
                )
                evidence_response = parse_agent_response(evidence_result.content)
                if evidence_response.get("structured"):
                    result = evidence_result
                    response = evidence_response
                    repeated = [
                        item for item in response.get("actions", [])
                        if item.get("kind") == "request_evidence"
                    ]
                    if repeated:
                        response["actions"] = []
                        response["proposal"] = None
                        response["message"] = (
                            "La evidencia solicitada fue entregada, pero el modelo no llegó "
                            "a una decisión final. No se aplicó ningún cambio."
                        )
                else:
                    response = {
                        "message": (
                            "El modelo recibió la evidencia, pero no devolvió una decisión "
                            "estructurada válida. No se aplicó ningún cambio."
                        ),
                        "proposal": None,
                        "actions": [],
                        "structured": False,
                        "protocol_version": "1.0",
                    }
        response["context_level"] = context_level
        response["reasoning_mode"] = value.reasoning_mode
        response["reasoning_used"] = use_reasoning
        response["timing"] = {
            key: result.stats.get(key)
            for key in (
                "input_tokens",
                "total_output_tokens",
                "reasoning_output_tokens",
                "tokens_per_second",
                "time_to_first_token_seconds",
            )
            if key in result.stats
        }
        if result.response_id:
            runtime.save_conversation(
                conversation_id,
                project_name,
                result.response_id,
                context_level,
                context_revision,
            )
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LMStudioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    actions = response.get("actions")
    if isinstance(actions, list) and actions:
        analysis_actions = [item for item in actions if item.get("kind") == "analyze_project"]
        mutating_actions = [item for item in actions if item.get("kind") != "analyze_project"]
        if analysis_actions and mutating_actions:
            response["message"] = (
                f"{response['message']}\n\nPrimero ejecutaré el análisis; pedí los cambios en el siguiente mensaje "
                "para que se calculen con evidencia actualizada."
            )
            actions = analysis_actions
            mutating_actions = []
        if analysis_actions and not mutating_actions:
            try:
                metadata = _project_metadata(project_name)
                bpm = metadata.get("tempo_bpm")
                if not isinstance(bpm, (int, float)):
                    raise ValueError("El proyecto necesita un BPM antes de analizarlo")
                artifact = await asyncio.to_thread(
                    analyze_project_media,
                    project_name,
                    float(bpm),
                    str(metadata.get("source_kind", "unknown")),
                    source_overrides_from_metadata(metadata),
                )
                summary = artifact["diagnosis"]["summary"]
                finding_count = sum(
                    int(value)
                    for value in summary.get("finding_counts_by_severity", {}).values()
                )
                response["message"] = (
                    f"{response['message']}\n\nAnálisis técnico completado: "
                    f"{summary.get('stem_count', 0)} stems medidos y "
                    f"{finding_count} hallazgos."
                )
                response["proposal"] = None
                runtime.record_activity(
                    {
                        "kind": "analysis",
                        "project": project_name,
                        "target": "Stems",
                        "summary": "Análisis técnico solicitado desde el chat",
                        "reaper_modified": False,
                    }
                )
                return _record_chat_exchange(
                    project_name, conversation_id, value.message, response
                )
            except Exception as exc:
                response["message"] = f"{response['message']}\n\nNo pude completar el análisis: {exc}"
                response["proposal"] = None
                return _record_chat_exchange(
                    project_name, conversation_id, value.message, response
                )
        try:
            plan = await asyncio.to_thread(_build_chat_action_plan, project_name, actions)
        except Exception as exc:
            response["message"] = (
                f"{response['message']}\n\nNo pude preparar una orden segura: {exc}"
            )
            response["proposal"] = None
            response["action_error"] = str(exc)
            return _record_chat_exchange(
                project_name, conversation_id, value.message, response
            )
        proposal_id = runtime.add_proposal(plan, executable=True)
        stored = {**plan, "proposal_id": proposal_id, "status": "pending"}
        approval_mode = runtime.approval_mode()
        should_apply = approval_mode == "all" or (
            approval_mode == "low_risk" and plan["risk"] == "low"
        )
        if should_apply:
            try:
                application = await asyncio.to_thread(_execute_chat_action_plan, plan)
                stored = runtime.mark_proposal(
                    proposal_id,
                    status="applied",
                    application=application,
                )
                runtime.record_activity(
                    {
                        "kind": "chat_action_plan",
                        "project": project_name,
                        "target": "REAPER",
                        "summary": application["message"],
                        "reaper_modified": True,
                        "project_ref": application["project_ref"],
                        "transaction_request_id": application.get("transaction_request_id"),
                        "transaction_request_ids": application.get("transaction_request_ids", []),
                    }
                )
                response["message"] = f"{response['message']}\n\n{application['message']}"
            except Exception as exc:
                stored = runtime.mark_proposal(
                    proposal_id,
                    status="failed",
                    application_error=str(exc),
                )
                response["message"] = (
                    f"{response['message']}\n\nEl plan automático no se aplicó: {exc}"
                )
        response["proposal"] = stored
    else:
        proposal = response.get("proposal")
        if isinstance(proposal, dict):
            proposal_id = runtime.add_proposal(proposal)
            response["proposal"] = {
                **proposal,
                "proposal_id": proposal_id,
                "status": "pending",
                "executable": False,
            }
    return _record_chat_exchange(
        project_name, conversation_id, value.message, response
    )


@app.post("/api/proposals/{proposal_id}/decision")
async def decide_proposal(proposal_id: str, value: ProposalDecision) -> dict[str, Any]:
    try:
        proposal = runtime.proposal(proposal_id)
        if value.decision == "preview":
            return proposal
        if value.decision == "reject":
            return runtime.reject(proposal_id)
        if not proposal.get("executable") or not isinstance(proposal.get("operations"), list):
            return {
                **proposal,
                "status": "awaiting_deterministic_mapping",
                "message": (
                    "La propuesta es una recomendación, no una orden tipada. "
                    "PampaPilot no modificó REAPER."
                ),
            }
        if proposal.get("status") == "applied":
            return proposal
        application = await asyncio.to_thread(_execute_chat_action_plan, proposal)
        updated = runtime.mark_proposal(
            proposal_id,
            status="applied",
            application=application,
        )
        runtime.record_activity(
            {
                "kind": "chat_action_plan",
                "project": proposal.get("project_name", ""),
                "target": "REAPER",
                "summary": application["message"],
                "reaper_modified": True,
                "project_ref": application["project_ref"],
                "transaction_request_id": application.get("transaction_request_id"),
                "transaction_request_ids": application.get("transaction_request_ids", []),
            }
        )
        return updated
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Propuesta inexistente") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    uvicorn.run(
        "pampapilot.web_server:app",
        host=os.environ.get("PAMPAPILOT_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("PAMPAPILOT_WEB_PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    main()
