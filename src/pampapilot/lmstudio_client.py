"""Small provider adapter for LM Studio's OpenAI-compatible HTTP API."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class LMStudioError(RuntimeError):
    """LM Studio was unavailable or returned an invalid response."""


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LM Studio URL must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LM Studio URL cannot contain credentials, query or fragment")
    return value


@dataclass(frozen=True, slots=True)
class LMStudioConfig:
    base_url: str = "http://127.0.0.1:1234"
    model: str = ""
    token: str = ""
    authentication_required: bool = True
    timeout_seconds: float = 45.0

    def validated(self) -> "LMStudioConfig":
        normalize_base_url(self.base_url)
        if not 0.1 <= self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be between 0.1 and 300")
        return self


class LMStudioClient:
    def __init__(self, config: LMStudioConfig) -> None:
        self.config = config.validated()

    def _request(
        self,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        if self.config.authentication_required and not self.config.token:
            raise LMStudioError(
                "LM Studio token is required by PampaPilot security settings"
            )
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        request = Request(
            f"{normalize_base_url(self.config.base_url)}{path}",
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urlopen(
                request,
                timeout=self.config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds,
            ) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LMStudioError(f"LM Studio returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise LMStudioError(f"Cannot reach LM Studio: {exc}") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LMStudioError("LM Studio returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise LMStudioError("LM Studio response root is not an object")
        return decoded

    def list_models(self, *, timeout_seconds: float = 2.0) -> list[str]:
        response = self._request("/v1/models", timeout_seconds=timeout_seconds)
        if "data" not in response:
            raise LMStudioError("LM Studio model list has no data field")
        values = response["data"]
        if not isinstance(values, list):
            raise LMStudioError("LM Studio model list is malformed")
        return [
            str(item["id"])
            for item in values
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        ]

    def chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        model = self.config.model
        if not model:
            models = self.list_models()
            if not models:
                raise LMStudioError("LM Studio has no loaded model")
            model = models[0]
        response = self._request(
            "/v1/chat/completions",
            {
                "model": model,
                "messages": [dict(message) for message in messages],
                "temperature": 0.2,
                "stream": False,
            },
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LMStudioError("LM Studio response contains no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, Mapping)
            ).strip()
            if text:
                return text
        raise LMStudioError("LM Studio returned an empty assistant message")
