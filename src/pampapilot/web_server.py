"""Local web interface and provider-neutral agent gateway for PampaPilot."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent_context import (
    build_agent_messages,
    build_context_update_message,
    build_project_context,
    compact_project_context,
    parse_agent_response,
    request_needs_deep_context,
    request_needs_reasoning,
)
from .bridge_client import BridgeClient
from .lmstudio_client import (
    LMStudioClient,
    LMStudioConfig,
    LMStudioError,
    normalize_base_url,
)
from .media_discovery import WORKSPACE_ROOT, discover_song_media
from .project_analysis import (
    analyze_project_media,
    source_overrides_from_metadata,
)
from .secret_store import SecretStoreError, WindowsSecretStore
from .web_actions import (
    apply_producer_chain,
    bridge_project,
    capability_catalog,
    match_reaper_track,
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


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=8_000)]


class ChatInput(BaseModel):
    project_name: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    history: Annotated[list[HistoryMessage], Field(max_length=20)] = []
    conversation_id: Annotated[str, Field(min_length=1, max_length=64)] = "default"


class ProposalDecision(BaseModel):
    decision: Literal["preview", "apply", "reject"]


class StemSourceInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"]


class StemActionInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"] | None = None
    include_artistic_saturation: bool = False


class ApplyChainInput(StemActionInput):
    approved_chain_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]


class StaticMixInput(BaseModel):
    stem_name: Annotated[str, Field(min_length=1, max_length=256)]
    volume_db: Annotated[float | None, Field(ge=-60.0, le=12.0)] = None
    pan: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    muted: bool | None = None
    solo: bool | None = None


class UndoInput(BaseModel):
    project_ref: Annotated[str, Field(min_length=1, max_length=4096)]
    transaction_request_id: Annotated[str, Field(min_length=1, max_length=64)]


class RuntimeState:
    """Process-local state; secrets never appear in API responses or plain text."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._secret_store = WindowsSecretStore()
        try:
            persisted_token = self._secret_store.load()
        except SecretStoreError:
            persisted_token = ""
        self._brain = LMStudioConfig(
            base_url=os.environ.get(
                "PAMPAPILOT_LMSTUDIO_URL", "http://127.0.0.1:1234"
            ),
            model=os.environ.get("PAMPAPILOT_LMSTUDIO_MODEL", ""),
            token=os.environ.get("PAMPAPILOT_LMSTUDIO_TOKEN", persisted_token),
            authentication_required=os.environ.get(
                "PAMPAPILOT_LMSTUDIO_REQUIRE_AUTH", "true"
            ).casefold()
            not in {"0", "false", "no"},
            timeout_seconds=float(
                os.environ.get("PAMPAPILOT_LMSTUDIO_TIMEOUT_SECONDS", "180")
            ),
        )
        self._proposals: dict[str, dict[str, Any]] = {}
        self._conversations: dict[tuple[str, str], dict[str, str]] = {}
        self._activity: list[dict[str, Any]] = []

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
        }

    def add_proposal(self, proposal: dict[str, Any]) -> str:
        proposal_id = str(uuid4())
        with self._lock:
            self._proposals[proposal_id] = {
                **proposal,
                "proposal_id": proposal_id,
                "status": "pending",
                "executable": False,
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

    def decide(self, proposal_id: str, decision: str) -> dict[str, Any]:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            if decision == "preview":
                return dict(proposal)
            if decision == "apply":
                return {
                    **proposal,
                    "status": "awaiting_deterministic_mapping",
                    "message": (
                        "La propuesta todavía no es una orden ejecutable. "
                        "PampaPilot no modificó REAPER."
                    ),
                }
            proposal["status"] = "rejected"
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
        context,
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
    fallback_track_names = _suggested_track_names(list(context["stems"]))
    stems = []
    for stem in context["stems"]:
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


@app.put("/api/settings/brain")
async def configure_brain(value: BrainSettingsInput) -> dict[str, Any]:
    try:
        runtime.configure_brain(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**runtime.public_brain(), "status": await _lm_status()}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    lm, bridge = await asyncio.gather(_lm_status(), _bridge_status())
    return {"application": "ready", "brain": lm, "reaper": bridge}


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


@app.post("/api/projects/{project_name}/static-mix/apply")
async def apply_static_mix(project_name: str, value: StaticMixInput) -> dict[str, Any]:
    if all(item is None for item in (value.volume_db, value.pan, value.muted, value.solo)):
        raise HTTPException(status_code=422, detail="No hay ningún ajuste para aplicar")
    if value.solo is not None and any(item is not None for item in (value.volume_db, value.pan, value.muted)):
        raise HTTPException(status_code=422, detail="Aplicá Solo por separado para conservar un único Undo")
    try:
        name = _validate_song_name(project_name)
        _, state, track = await asyncio.to_thread(_connected_stem, name, value.stem_name)
        project_ref = str(state["result"]["project_ref"])
        client = BridgeClient(timeout_seconds=15.0)
        if value.solo is not None:
            action = "set_track_solo"
            params = {"project_ref": project_ref, "track_guid": track["guid"], "soloed": value.solo}
        else:
            action = "apply_track_mix_batch"
            item = {"track_guid": track["guid"]}
            if value.volume_db is not None:
                item["volume_db"] = value.volume_db
            if value.pan is not None:
                item["pan"] = value.pan
            if value.muted is not None:
                item["muted"] = value.muted
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


@app.post("/api/projects", status_code=201)
def create_project(
    title: Annotated[str, Form(min_length=1, max_length=128)],
    bpm: Annotated[float, Form(ge=20, le=400)],
    source_kind: Annotated[
        Literal["suno_stems", "organic_multitrack", "mixed", "unknown"], Form()
    ],
    lyrics: Annotated[str, Form(max_length=100_000)] = "",
    stems: Annotated[list[UploadFile], File()] = [],
    midi: Annotated[list[UploadFile], File()] = [],
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
        for upload in stems:
            _copy_upload(upload, stem_dir, {".wav", ".flac"})
        for upload in midi:
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


@app.post("/api/chat")
async def chat(value: ChatInput) -> dict[str, Any]:
    try:
        project_name = _validate_song_name(value.project_name)
        deep_context = request_needs_deep_context(value.message)
        conversation = runtime.conversation(value.conversation_id, project_name)
        context_level = (
            "deep"
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
            if not deep_context:
                context = compact_project_context(context)
            context_revision = _context_revision(context)
            messages = build_agent_messages(
                context,
                value.message,
                [item.model_dump() for item in value.history],
            )
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
                messages = [{"role": "user", "content": value.message}]
        else:
            messages = [{"role": "user", "content": value.message}]
        use_reasoning = deep_context and request_needs_reasoning(value.message)
        result = await asyncio.to_thread(
            LMStudioClient(runtime.brain()).chat_result,
            messages,
            max_tokens=900 if use_reasoning else 450 if deep_context else 220,
            reasoning="on" if use_reasoning else "off",
            previous_response_id=None
            if conversation is None
            else conversation["response_id"],
            store=True,
        )
        response = parse_agent_response(result.content)
        response["context_level"] = context_level
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
                value.conversation_id,
                project_name,
                result.response_id,
                context_level,
                context_revision,
            )
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LMStudioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    proposal = response.get("proposal")
    if isinstance(proposal, dict):
        proposal_id = runtime.add_proposal(proposal)
        response["proposal"] = {**proposal, "proposal_id": proposal_id, "status": "pending"}
    return response


@app.post("/api/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, value: ProposalDecision) -> dict[str, Any]:
    try:
        return runtime.decide(proposal_id, value.decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Propuesta inexistente") from exc


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
