"""Cola local de archivos con publicación y reclamo atómicos."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time

from .protocol import ProtocolError, Request, Response


@dataclass(frozen=True, slots=True)
class ClaimedRequest:
    request: Request
    path: Path


class FilesystemIPC:
    """Transporte simple; un productor y un consumidor pueden correr separados."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.pending = self.root / "requests" / "pending"
        self.processing = self.root / "requests" / "processing"
        self.responses = self.root / "responses"
        self.quarantine = self.root / "quarantine"

    def initialize(self) -> None:
        for directory in (
            self.pending,
            self.processing,
            self.responses,
            self.quarantine,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(destination: Path, payload: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.stem}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def submit(self, request: Request) -> Path:
        request.validated()
        destination = self.pending / f"{request.request_id}.json"
        if (
            destination.exists()
            or (self.processing / destination.name).exists()
            or (self.responses / destination.name).exists()
        ):
            raise FileExistsError(f"la solicitud {request.request_id} ya existe")
        self._atomic_write(destination, request.to_json_bytes())
        return destination

    def claim_oldest(self, *, now_ms: int | None = None) -> ClaimedRequest | None:
        self.initialize()
        for source in sorted(self.pending.glob("*.json"), key=lambda path: path.stat().st_mtime_ns):
            claimed_path = self.processing / source.name
            try:
                os.replace(source, claimed_path)
            except FileNotFoundError:
                continue
            try:
                request = Request.from_json_bytes(claimed_path.read_bytes())
            except (OSError, ProtocolError):
                os.replace(claimed_path, self.quarantine / claimed_path.name)
                continue
            if request.is_expired(now_ms):
                response = Response(
                    request_id=request.request_id,
                    status="expired",
                    completed_at_ms=(
                        int(time.time() * 1000) if now_ms is None else now_ms
                    ),
                    error={"code": "deadline_exceeded", "message": "solicitud vencida"},
                )
                self.complete(ClaimedRequest(request, claimed_path), response)
                continue
            return ClaimedRequest(request=request, path=claimed_path)
        return None

    def complete(self, claimed: ClaimedRequest, response: Response) -> Path:
        response.validated()
        if response.request_id != claimed.request.request_id:
            raise ProtocolError("la respuesta no corresponde a la solicitud")
        destination = self.responses / f"{response.request_id}.json"
        self._atomic_write(destination, response.to_json_bytes())
        claimed.path.unlink(missing_ok=True)
        return destination

    def load_response(self, request_id: str) -> Response | None:
        destination = self.responses / f"{request_id}.json"
        try:
            payload = destination.read_bytes()
        except FileNotFoundError:
            return None
        return Response.from_json_bytes(payload)

    def wait_response(
        self, request_id: str, *, timeout_seconds: float, poll_seconds: float = 0.02
    ) -> Response:
        if timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("los tiempos deben ser mayores que cero")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = self.load_response(request_id)
            except PermissionError:
                # Windows puede negar brevemente la lectura mientras otro
                # proceso termina de publicar o inspeccionar el archivo.
                response = None
            if response is not None:
                return response
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(f"no llegó respuesta para {request_id}")
