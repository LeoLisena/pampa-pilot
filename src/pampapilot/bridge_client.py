"""Cliente síncrono del puente local que corre dentro de REAPER."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .actions import require_action
from .ipc import FilesystemIPC
from .protocol import Request, Response


DEFAULT_TIMEOUT_SECONDS = 5.0


class BridgeError(RuntimeError):
    """REAPER respondió con un error estructurado."""

    def __init__(self, response: Response) -> None:
        error = {} if response.error is None else response.error
        self.response = response
        self.code = str(error.get("code", "bridge_error"))
        self.details = dict(error)
        super().__init__(str(error.get("message", "el puente rechazó la operación")))


@dataclass(frozen=True, slots=True)
class BridgeResult:
    result: Mapping[str, Any]
    observations: Mapping[str, Any]
    request_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "result": dict(self.result),
            "observations": dict(self.observations),
        }


def default_ipc_root() -> Path:
    """Resuelve la misma carpeta que usa el script Lua de REAPER."""

    configured = os.environ.get("PAMPAPILOT_IPC_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    config_candidates = [(
        Path(__file__).resolve().parents[2]
        / "reaper"
        / "bridge_config.local.json"
    )]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            config_candidates.append(
                Path(appdata)
                / "REAPER"
                / "Scripts"
                / "PampaPilot"
                / "bridge_config.local.json"
            )

    for config_path in config_candidates:
        if not config_path.is_file():
            continue
        try:
            decoded = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"no se pudo leer la configuración del Bridge: {config_path}"
            ) from exc
        ipc_root = decoded.get("ipc_root") if isinstance(decoded, dict) else None
        if not isinstance(ipc_root, str) or not ipc_root.strip():
            raise RuntimeError(
                f"bridge_config.local.json no contiene ipc_root válido: {config_path}"
            )
        return Path(ipc_root).expanduser().resolve()

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA no está definido; configure PAMPAPILOT_IPC_ROOT")
        return Path(appdata) / "REAPER" / "PampaPilot" / "ipc"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "REAPER" / "PampaPilot" / "ipc"
    return Path.home() / ".config" / "REAPER" / "PampaPilot" / "ipc"


class BridgeClient:
    def __init__(
        self,
        ipc_root: Path | str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero")
        self.ipc = FilesystemIPC(default_ipc_root() if ipc_root is None else ipc_root)
        self.timeout_seconds = timeout_seconds

    def call(
        self,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> BridgeResult:
        require_action(action)
        wait_seconds = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if wait_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero")
        request = Request.new(
            action,
            params,
            timeout_ms=max(1, int(wait_seconds * 1000)),
        )
        self.ipc.submit(request)
        response = self.ipc.wait_response(
            request.request_id,
            timeout_seconds=wait_seconds,
        )
        if response.status != "ok":
            raise BridgeError(response)
        return BridgeResult(
            result=response.result,
            observations=response.observations,
            request_id=response.request_id,
        )
