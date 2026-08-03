"""Typed, provider-neutral actions exposed by the local web interface."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridge_client import BridgeClient, BridgeResult
from .producer_chain import (
    build_producer_chain_application_payload,
    build_track_producer_chain,
)


ROLE_ALIASES = {
    "lead_vocal": "lead_vocal",
    "backing_vocals": "backing_vocals",
    "choir": "backing_vocals",
    "bass": "bass",
    "drums": "drums",
    "percussion": "drums",
    "guitar": "guitar",
    "strings": "strings",
    "keys": "keys",
    "synth": "keys",
}


CAPABILITY_GROUPS = [
    {
        "id": "analyze",
        "title": "Analizar y organizar",
        "description": "Funciona offline, aunque REAPER esté cerrado.",
        "items": [
            ("wav_analysis", "Diagnóstico WAV", "ready"),
            ("midi_cleanup", "Limpieza y reconstrucción MIDI", "ready"),
            ("song_structure", "Secciones desde letra + audio", "ready"),
            ("source_classification", "Origen Suno u orgánico por stem", "ready"),
        ],
    },
    {
        "id": "mix",
        "title": "Mezcla",
        "description": "Previsualización y ejecución verificable por pista.",
        "items": [
            ("static_mix", "Volumen, paneo, mute y solo", "web_ready"),
            ("producer_chain", "Cadena recomendada por fuente", "web_ready"),
            ("compression", "Compresión ReaComp", "engine_ready"),
            ("equalization", "Ecualización ReaEQ", "engine_ready"),
            ("gate", "Puerta ReaGate", "engine_ready"),
            ("deesser", "De-esser ReaXcomp", "engine_ready"),
            ("dynamic_resonance", "Resonancias dinámicas", "engine_ready"),
            ("saturation", "Saturación con compensación", "engine_ready"),
            ("tuning", "Afinación ReaTune por preset", "engine_ready"),
            ("ambience", "Buses de reverb y delay", "engine_ready"),
            ("section_volume", "Volumen por secciones", "engine_ready"),
            ("vocal_rider", "Automatización de voz por frases", "engine_ready"),
        ],
    },
    {
        "id": "delivery",
        "title": "Master y entrega",
        "description": "Controles finales conservadores y reversibles.",
        "items": [
            ("mastering", "Limitador y propuesta de mastering", "engine_ready"),
            ("ab", "Comparación A/B igualada", "engine_ready"),
            ("delivery_qc", "QC de loudness, picos y mono", "ready"),
            ("render", "Render WAV verificable", "engine_ready"),
        ],
    },
]


def capability_catalog() -> list[dict[str, Any]]:
    return [
        {
            **group,
            "items": [
                {"id": item_id, "title": title, "status": status}
                for item_id, title, status in group["items"]
            ],
        }
        for group in CAPABILITY_GROUPS
    ]


def normalize_track_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = re.sub(r"^\s*\d+[\s._-]*", "", folded.casefold())
    return re.sub(r"[^a-z0-9]+", "", folded)


def match_reaper_track(
    tracks: list[Mapping[str, Any]], *candidates: str
) -> dict[str, Any] | None:
    wanted = {normalize_track_name(value) for value in candidates if value}
    matches = [
        dict(track)
        for track in tracks
        if normalize_track_name(str(track.get("name", ""))) in wanted
    ]
    return matches[0] if len(matches) == 1 else None


def bridge_project(client: BridgeClient) -> dict[str, Any]:
    return client.call("get_project_state").to_dict()


def track_producer_chain(
    path: Path,
    role: str,
    source_kind: str,
    *,
    existing_fx: Sequence[Mapping[str, Any]] = (),
    include_artistic_saturation: bool = False,
) -> dict[str, Any]:
    mapped_role = ROLE_ALIASES.get(role)
    if mapped_role is None:
        raise ValueError(f"Todavía no hay una cadena automática para el rol {role}")
    return build_track_producer_chain(
        path,
        mapped_role,  # type: ignore[arg-type]
        source_kind,  # type: ignore[arg-type]
        existing_fx=existing_fx,
        include_artistic_saturation=include_artistic_saturation,
    )


def apply_producer_chain(
    client: BridgeClient,
    *,
    project_ref: str,
    track_guid: str,
    chain: Mapping[str, Any],
    approved_chain_id: str,
) -> BridgeResult:
    payload = build_producer_chain_application_payload(chain, approved_chain_id)
    return client.call(
        "apply_producer_fx_chain",
        {"project_ref": project_ref, "track_guid": track_guid, **payload},
        timeout_seconds=60.0,
    )
