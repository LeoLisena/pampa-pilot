"""Local web interface and provider-neutral agent gateway for PampaPilot."""

from __future__ import annotations

import asyncio
from dataclasses import replace
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
)
from .bridge_client import BridgeClient
from .lmstudio_client import (
    LMStudioClient,
    LMStudioConfig,
    LMStudioError,
    normalize_base_url,
)
from .media_discovery import WORKSPACE_ROOT


WEB_ROOT = Path(__file__).with_name("web")
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
SONG_INVALID_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


class BrainSettingsInput(BaseModel):
    base_url: Annotated[str, Field(min_length=8, max_length=2048)]
    model: Annotated[str, Field(max_length=512)] = ""
    token: Annotated[str | None, Field(max_length=4096)] = None
    authentication_required: bool = True
    timeout_seconds: Annotated[float, Field(ge=15, le=300)] = 180.0


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


class RuntimeState:
    """Process-local settings; secrets never touch disk or API responses."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._brain = LMStudioConfig(
            base_url=os.environ.get(
                "PAMPAPILOT_LMSTUDIO_URL", "http://127.0.0.1:1234"
            ),
            model=os.environ.get("PAMPAPILOT_LMSTUDIO_MODEL", ""),
            token=os.environ.get("PAMPAPILOT_LMSTUDIO_TOKEN", ""),
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

    def brain(self) -> LMStudioConfig:
        with self._lock:
            return self._brain

    def configure_brain(self, value: BrainSettingsInput) -> LMStudioConfig:
        normalize_base_url(value.base_url)
        with self._lock:
            token = self._brain.token if value.token is None else value.token.strip()
            if not value.authentication_required and value.token is None:
                token = ""
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
    ) -> None:
        with self._lock:
            self._conversations[(conversation_id, project_name)] = {
                "response_id": response_id,
                "context_level": context_level,
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


def _project_view(name: str) -> dict[str, Any]:
    context = build_project_context(name)
    song = context["song"]
    source = str(song.get("source_kind") or "unknown")
    source_label = {
        "suno_stems": "Suno",
        "organic_multitrack": "Orgánico",
        "unknown": "Sin clasificar",
        "mixed": "Suno + orgánico",
    }.get(source, source)
    return {
        "name": song["title"],
        "tempo_bpm": song.get("tempo_bpm"),
        "source_kind": source,
        "source_label": source_label,
        "status": song.get("status"),
        "sections": context["lyrics"]["sections"],
        "lyrics_available": context["lyrics"]["available"],
        "stems": [
            {
                **stem,
                "source": source_label,
                "status": "Disponible",
                "problems": "Sin analizar",
            }
            for stem in context["stems"]
        ],
        "midi_files": context["midi_files"],
        "references": context["references"],
        "verification": context["verification"],
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
        if conversation is None:
            context = build_project_context(project_name)
            if not deep_context:
                context = compact_project_context(context)
            messages = build_agent_messages(
                context,
                value.message,
                [item.model_dump() for item in value.history],
            )
        elif deep_context and conversation.get("context_level") != "deep":
            context = build_project_context(project_name)
            messages = [
                {
                    "role": "user",
                    "content": build_context_update_message(context, value.message),
                }
            ]
        else:
            messages = [{"role": "user", "content": value.message}]
        result = await asyncio.to_thread(
            LMStudioClient(runtime.brain()).chat_result,
            messages,
            max_tokens=900 if deep_context else 220,
            reasoning="on" if deep_context else "off",
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
