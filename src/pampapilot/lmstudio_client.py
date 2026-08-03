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


@dataclass(frozen=True, slots=True)
class LMStudioChatResult:
    content: str
    response_id: str | None
    stats: Mapping[str, Any]


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
    timeout_seconds: float = 180.0

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
        response = self._request("/api/v1/models", timeout_seconds=timeout_seconds)
        if "models" not in response:
            raise LMStudioError("LM Studio model list has no models field")
        values = response["models"]
        if not isinstance(values, list):
            raise LMStudioError("LM Studio model list is malformed")
        return [
            str(item["key"])
            for item in values
            if isinstance(item, Mapping)
            and item.get("type") == "llm"
            and isinstance(item.get("key"), str)
        ]

    def chat_result(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 900,
        reasoning: str = "off",
        previous_response_id: str | None = None,
        store: bool = True,
    ) -> LMStudioChatResult:
        if not 32 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 32 and 4096")
        if reasoning not in {"off", "on", "low", "medium", "high"}:
            raise ValueError("unsupported reasoning setting")
        model = self.config.model
        if not model:
            models = self.list_models()
            if not models:
                raise LMStudioError("LM Studio has no loaded model")
            model = models[0]
        system_prompt = "\n\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        transcript = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            label = "Usuario" if role == "user" else "Asistente"
            transcript.append(f"{label}: {message.get('content', '')}")
        payload: dict[str, Any] = {
            "model": model,
            "input": "\n\n".join(transcript),
            "temperature": 0.2,
            "max_output_tokens": max_tokens,
            "reasoning": reasoning,
            "store": store,
            "stream": False,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        response = self._request("/api/v1/chat", payload)
        output = response.get("output")
        if not isinstance(output, list):
            raise LMStudioError("LM Studio response contains no output list")
        text = "\n".join(
            str(item.get("content", ""))
            for item in output
            if isinstance(item, Mapping) and item.get("type") == "message"
        ).strip()
        if text:
            response_id = response.get("response_id")
            stats = response.get("stats", {})
            return LMStudioChatResult(
                content=text,
                response_id=response_id if isinstance(response_id, str) else None,
                stats=dict(stats) if isinstance(stats, Mapping) else {},
            )
        raise LMStudioError("LM Studio returned an empty assistant message")

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 900,
        reasoning: str = "off",
    ) -> str:
        """Compatibility helper for callers that only need text."""

        return self.chat_result(
            messages,
            max_tokens=max_tokens,
            reasoning=reasoning,
            store=False,
        ).content
