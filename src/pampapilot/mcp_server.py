"""Servidor MCP v2 para controlar REAPER mediante el puente local."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .bridge_client import BridgeClient


mcp = MCPServer(
    "PampaPilot",
    instructions=(
        "Controla únicamente el proyecto REAPER activo mediante acciones permitidas. "
        "Antes de mutar, llama health_check y conserva project_ref. Usa GUID, nunca "
        "índices observados previamente. Después de cada mutación inspecciona "
        "observations.state_verified. No afirmes verificación de señal o perceptual "
        "si sus indicadores son false. Las mutaciones producen transacciones undo."
    ),
)
_bridge = BridgeClient()


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
