"""Versioned provider-neutral contract between PampaPilot and an LLM."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


AGENT_PROTOCOL_NAME = "pampapilot-agent"
AGENT_PROTOCOL_VERSION = "1.0"

ACTION_FIELDS: dict[str, frozenset[str]] = {
    "static_mix": frozenset({"target", "volume_delta_db", "volume_db", "pan", "muted", "soloed"}),
    "filter": frozenset({"target", "filter_type", "preset_name", "source_kind"}),
    "adjust_compressor": frozenset({"target", "attack_percent_delta"}),
    "producer_chain": frozenset({"target", "include_artistic_saturation", "source_kind"}),
    "ambience": frozenset({"target", "effect_type", "source_kind"}),
    "vocal_rider": frozenset({"target", "source_kind"}),
    "section_volume": frozenset({"target", "source_kind"}),
    "mastering": frozenset(),
    "render": frozenset(),
    "midi_cleanup": frozenset({"target"}),
    "song_structure": frozenset(),
    "analyze_project": frozenset(),
    "request_evidence": frozenset({"evidence_type", "target", "query"}),
}

EVIDENCE_TYPES = frozenset({
    "project_analysis", "track_analysis", "reaper_track_state",
    "fx_parameters", "knowledge",
})


def protocol_header(message_type: str) -> dict[str, str]:
    return {
        "name": AGENT_PROTOCOL_NAME,
        "version": AGENT_PROTOCOL_VERSION,
        "message_type": message_type,
    }


def context_envelope(context: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(context))
    value["agent_protocol"] = protocol_header("context")
    return value


def result_envelope(*, status: str, data: Mapping[str, Any]) -> dict[str, Any]:
    if status not in {"ok", "rejected", "failed"}:
        raise ValueError("invalid agent result status")
    return {
        "agent_protocol": protocol_header("result"),
        "status": status,
        "data": deepcopy(dict(data)),
    }


def error_envelope(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "agent_protocol": protocol_header("error"),
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def normalize_actions(raw_actions: object) -> list[dict[str, Any]]:
    if not isinstance(raw_actions, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in raw_actions[:12]:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in ACTION_FIELDS:
            continue
        action = {"kind": kind}
        for key in ACTION_FIELDS[kind]:
            if key in item:
                action[key] = item[key]
        if kind == "request_evidence" and action.get("evidence_type") not in EVIDENCE_TYPES:
            continue
        actions.append(action)
    return actions
