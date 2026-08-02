"""Servidor MCP v2 para controlar REAPER mediante el puente local."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .bridge_client import BridgeClient


mcp = MCPServer(
    "PampaPilot",
    instructions=(
        "Controla únicamente el proyecto REAPER activo mediante acciones permitidas. "
        "Antes de mutar, llama health_check y conserva project_ref. Usa GUID, nunca "
        "índices observados previamente. Después de cada mutación inspecciona "
        "observations.state_verified. No afirmes verificación de señal o perceptual "
        "si sus indicadores son false. Las ediciones producen transacciones undo; "
        "save_project_as cambia la identidad del proyecto y devuelve un project_ref nuevo."
    ),
)
_bridge = BridgeClient()


class AudioImportItem(BaseModel):
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    track_name: Annotated[str, Field(min_length=1, max_length=128)]
    position_seconds: Annotated[float, Field(ge=0.0)] = 0.0


class TrackMixItem(BaseModel):
    track_guid: Annotated[str, Field(min_length=1, max_length=64)]
    volume_db: Annotated[float | None, Field(ge=-60.0, le=12.0)] = None
    pan: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    muted: bool | None = None


def _call(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _bridge.call(action, params).to_dict()


@mcp.tool(
    title="Comprobar conexión con REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def health_check() -> dict[str, Any]:
    """Comprueba el puente y devuelve REAPER, proyecto activo y versiones."""

    return _call("health_check")


@mcp.tool(
    title="Leer proyecto de REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_project_state() -> dict[str, Any]:
    """Lee pistas y estado básico del proyecto activo, sin modificarlo."""

    return _call("get_project_state")


@mcp.tool(
    title="Leer pista por GUID",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_track_state(project_ref: str, track_guid: str) -> dict[str, Any]:
    """Lee una pista por GUID y exige que el proyecto activo no haya cambiado."""

    return _call(
        "get_track_state",
        {"project_ref": project_ref, "track_guid": track_guid},
    )


@mcp.tool(
    title="Crear pista en REAPER",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def create_track(
    project_ref: str,
    name: Annotated[str, Field(min_length=1, max_length=128)],
    index: Annotated[int | None, Field(ge=0)] = None,
) -> dict[str, Any]:
    """Crea una pista, verifica el nombre y devuelve GUID y transacción reversible."""

    params: dict[str, Any] = {"project_ref": project_ref, "name": name}
    if index is not None:
        params["index"] = index
    return _call("create_track", params)


@mcp.tool(
    title="Ajustar paneo de pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_pan(
    project_ref: str,
    track_guid: str,
    pan: Annotated[float, Field(ge=-1.0, le=1.0)],
) -> dict[str, Any]:
    """Ajusta paneo -1..1 y lo verifica; no sobrescribe automatización activa."""

    return _call(
        "set_track_pan",
        {"project_ref": project_ref, "track_guid": track_guid, "pan": pan},
    )


@mcp.tool(
    title="Ajustar volumen de pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_volume(
    project_ref: str,
    track_guid: str,
    volume_db: Annotated[float, Field(ge=-60.0, le=12.0)],
) -> dict[str, Any]:
    """Ajusta volumen -60..+12 dB y verifica la lectura posterior."""

    return _call(
        "set_track_volume",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "volume_db": volume_db,
        },
    )


@mcp.tool(
    title="Silenciar o activar pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_mute(
    project_ref: str,
    track_guid: str,
    muted: bool,
) -> dict[str, Any]:
    """Cambia el mute de una pista y verifica la lectura posterior."""

    return _call(
        "set_track_mute",
        {"project_ref": project_ref, "track_guid": track_guid, "muted": muted},
    )


@mcp.tool(
    title="Aplicar mezcla estática en lote",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def apply_track_mix_batch(
    project_ref: str,
    items: Annotated[list[TrackMixItem], Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Aplica volumen, paneo y mute como una sola transacción verificable."""

    return _call(
        "apply_track_mix_batch",
        {
            "project_ref": project_ref,
            "items": [item.model_dump(exclude_none=True) for item in items],
        },
    )


@mcp.tool(
    title="Importar audio en una pista nueva",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_audio(
    project_ref: str,
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    track_name: Annotated[str, Field(min_length=1, max_length=128)],
    position_seconds: Annotated[float, Field(ge=0.0)] = 0.0,
) -> dict[str, Any]:
    """Importa un WAV permitido, verifica pista/ítem/toma y devuelve sus GUID."""

    return _call(
        "import_audio",
        {
            "project_ref": project_ref,
            "file_path": file_path,
            "track_name": track_name,
            "position_seconds": position_seconds,
        },
    )


@mcp.tool(
    title="Importar lote de audio",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_audio_batch(
    project_ref: str,
    items: Annotated[list[AudioImportItem], Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Importa un lote de WAV como una sola transacción con verificación."""

    return _call(
        "import_audio_batch",
        {
            "project_ref": project_ref,
            "items": [item.model_dump() for item in items],
        },
    )


@mcp.tool(
    title="Ajustar tempo del proyecto",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_project_tempo(
    project_ref: str,
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
) -> dict[str, Any]:
    """Ajusta BPM y verifica que posiciones, duraciones y playrate no cambien."""

    return _call(
        "set_project_tempo",
        {"project_ref": project_ref, "bpm": bpm},
    )


@mcp.tool(
    title="Guardar proyecto con nombre nuevo",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def save_project_as(
    project_ref: str,
    project_path: Annotated[str, Field(min_length=1, max_length=4096)],
) -> dict[str, Any]:
    """Guarda como RPP nuevo dentro de las raíces de sesiones permitidas."""

    return _call(
        "save_project_as",
        {"project_ref": project_ref, "project_path": project_path},
    )


@mcp.tool(
    title="Deshacer transacción propia",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def undo_transaction(project_ref: str, transaction_request_id: str) -> dict[str, Any]:
    """Deshace sólo la última transacción propia si el historial sigue intacto."""

    return _call(
        "undo_transaction",
        {
            "project_ref": project_ref,
            "transaction_request_id": transaction_request_id,
        },
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
