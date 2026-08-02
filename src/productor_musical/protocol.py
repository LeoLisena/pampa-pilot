"""Contrato versionado entre el servidor MCP y el puente de REAPER."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import time
from typing import Any, Mapping
from uuid import UUID, uuid4


PROTOCOL_VERSION = "0.1"
MAX_MESSAGE_BYTES = 1_000_000
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProtocolError(ValueError):
    """El mensaje no cumple el contrato local."""


def _require_uuid(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{field_name} debe ser texto")
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProtocolError(f"{field_name} no es un UUID válido") from exc
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{field_name} debe ser entero")
    return value


def _validate_version(value: object) -> str:
    if value != PROTOCOL_VERSION:
        raise ProtocolError(
            f"versión incompatible: {value!r}; se esperaba {PROTOCOL_VERSION!r}"
        )
    return PROTOCOL_VERSION


def _decode_json(payload: bytes) -> Mapping[str, Any]:
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("mensaje demasiado grande")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("JSON inválido") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError("la raíz del mensaje debe ser un objeto")
    return decoded


def _encode_json(value: Mapping[str, Any]) -> bytes:
    try:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("el mensaje contiene valores no serializables") from exc
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("mensaje demasiado grande")
    return payload


@dataclass(frozen=True, slots=True)
class Request:
    request_id: str
    action: str
    params: Mapping[str, Any]
    created_at_ms: int
    deadline_at_ms: int
    version: str = PROTOCOL_VERSION

    @classmethod
    def new(
        cls,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout_ms: int = 10_000,
        now_ms: int | None = None,
    ) -> "Request":
        if timeout_ms <= 0:
            raise ProtocolError("timeout_ms debe ser mayor que cero")
        created = int(time.time() * 1000) if now_ms is None else now_ms
        return cls(
            request_id=str(uuid4()),
            action=action,
            params={} if params is None else dict(params),
            created_at_ms=created,
            deadline_at_ms=created + timeout_ms,
        ).validated()

    def validated(self) -> "Request":
        _validate_version(self.version)
        _require_uuid(self.request_id, "request_id")
        if not isinstance(self.action, str) or not _ACTION_RE.fullmatch(self.action):
            raise ProtocolError("action tiene un formato inválido")
        if not isinstance(self.params, Mapping):
            raise ProtocolError("params debe ser un objeto")
        created = _require_int(self.created_at_ms, "created_at_ms")
        deadline = _require_int(self.deadline_at_ms, "deadline_at_ms")
        if deadline <= created:
            raise ProtocolError("deadline_at_ms debe ser posterior a created_at_ms")
        return self

    def is_expired(self, now_ms: int | None = None) -> bool:
        current = int(time.time() * 1000) if now_ms is None else now_ms
        return current > self.deadline_at_ms

    def to_dict(self) -> dict[str, Any]:
        self.validated()
        return {
            "version": self.version,
            "request_id": self.request_id,
            "action": self.action,
            "params": dict(self.params),
            "created_at_ms": self.created_at_ms,
            "deadline_at_ms": self.deadline_at_ms,
        }

    def to_json_bytes(self) -> bytes:
        return _encode_json(self.to_dict())

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "Request":
        value = _decode_json(payload)
        try:
            request = cls(
                version=value["version"],
                request_id=value["request_id"],
                action=value["action"],
                params=value["params"],
                created_at_ms=value["created_at_ms"],
                deadline_at_ms=value["deadline_at_ms"],
            )
        except KeyError as exc:
            raise ProtocolError(f"falta el campo {exc.args[0]}") from exc
        return request.validated()


@dataclass(frozen=True, slots=True)
class Response:
    request_id: str
    status: str
    completed_at_ms: int
    result: Mapping[str, Any] = field(default_factory=dict)
    error: Mapping[str, Any] | None = None
    observations: Mapping[str, Any] = field(default_factory=dict)
    version: str = PROTOCOL_VERSION

    def validated(self) -> "Response":
        _validate_version(self.version)
        _require_uuid(self.request_id, "request_id")
        _require_int(self.completed_at_ms, "completed_at_ms")
        if self.status not in {"ok", "error", "expired", "rejected"}:
            raise ProtocolError("status inválido")
        if not isinstance(self.result, Mapping):
            raise ProtocolError("result debe ser un objeto")
        if self.error is not None and not isinstance(self.error, Mapping):
            raise ProtocolError("error debe ser un objeto o null")
        if not isinstance(self.observations, Mapping):
            raise ProtocolError("observations debe ser un objeto")
        if self.status == "ok" and self.error is not None:
            raise ProtocolError("una respuesta ok no puede contener error")
        if self.status != "ok" and self.error is None:
            raise ProtocolError("una respuesta fallida debe contener error")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validated()
        return {
            "version": self.version,
            "request_id": self.request_id,
            "status": self.status,
            "completed_at_ms": self.completed_at_ms,
            "result": dict(self.result),
            "error": None if self.error is None else dict(self.error),
            "observations": dict(self.observations),
        }

    def to_json_bytes(self) -> bytes:
        return _encode_json(self.to_dict())

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "Response":
        value = _decode_json(payload)
        try:
            response = cls(
                version=value["version"],
                request_id=value["request_id"],
                status=value["status"],
                completed_at_ms=value["completed_at_ms"],
                result=value.get("result", {}),
                error=value.get("error"),
                observations=value.get("observations", {}),
            )
        except KeyError as exc:
            raise ProtocolError(f"falta el campo {exc.args[0]}") from exc
        return response.validated()

