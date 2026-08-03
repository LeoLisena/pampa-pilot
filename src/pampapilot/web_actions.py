"""Typed, provider-neutral actions exposed by the local web interface."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridge_client import BridgeClient, BridgeResult
from .deesser_proposal import propose_deesser
from .dynamic_resonance import analyze_dynamic_resonance
from .gate_proposal import propose_reagate
from .processing_proposal import propose_track_processing
from .producer_chain import (
    build_producer_chain_application_payload,
    build_track_producer_chain,
)
from .saturation_proposal import propose_saturation


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

PROCESSING_ROLES = {
    "lead_vocal": "lead_vocal",
    "backing_vocals": "backing_vocals",
    "choir": "backing_vocals",
    "bass": "bass",
    "drums": "drums",
    "percussion": "drums",
    "guitar": "guitar",
    "strings": "strings",
}

FILTER_DEFINITIONS = {
    "eq": {"processor": "reaeq", "fragment": "reaeq", "title": "Ecualización ReaEQ"},
    "compressor": {"processor": "reacomp", "fragment": "reacomp", "title": "Compresión ReaComp"},
    "gate": {"processor": "reagate", "fragment": "reagate", "title": "Puerta ReaGate"},
    "deesser": {"processor": "deesser", "fragment": "reaxcomp", "title": "De-esser ReaXcomp"},
    "dynamic_resonance": {"processor": "dynamic_resonance", "fragment": "reaxcomp", "title": "Resonancia dinámica ReaXcomp"},
    "saturation": {"processor": "waveshaper", "fragment": "multi waveshaper", "title": "Saturación suave"},
    "tuning": {"processor": "reatune", "fragment": "reatune", "title": "Afinación ReaTune"},
}


CAPABILITY_GROUPS = [
    {
        "id": "analyze",
        "title": "Analizar y organizar",
        "description": "Funciona offline, aunque REAPER esté cerrado.",
        "items": [
            ("wav_analysis", "Diagnóstico WAV", "ready"),
            ("midi_cleanup", "Limpieza y reconstrucción MIDI", "chat_ready"),
            ("song_structure", "Secciones desde letra + audio", "chat_ready"),
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
            ("compression", "Compresión ReaComp", "web_ready"),
            ("equalization", "Ecualización ReaEQ", "web_ready"),
            ("gate", "Puerta ReaGate", "web_ready"),
            ("deesser", "De-esser ReaXcomp", "web_ready"),
            ("dynamic_resonance", "Resonancias dinámicas", "web_ready"),
            ("saturation", "Saturación con compensación", "web_ready"),
            ("tuning", "Afinación ReaTune por preset", "web_ready"),
            ("ambience", "Buses de reverb y delay", "chat_ready"),
            ("section_volume", "Volumen por secciones", "chat_ready"),
            ("vocal_rider", "Automatización de voz por frases", "chat_ready"),
        ],
    },
    {
        "id": "delivery",
        "title": "Master y entrega",
        "description": "Controles finales conservadores y reversibles.",
        "items": [
            ("mastering", "Limitador y propuesta de mastering", "chat_ready"),
            ("ab", "Comparación A/B igualada", "engine_ready"),
            ("delivery_qc", "QC de loudness, picos y mono", "ready"),
            ("render", "Render WAV verificable", "chat_ready"),
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


def _filter_identity(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def build_filter_proposal(
    path: Path,
    role: str,
    source_kind: str,
    filter_type: str,
    *,
    preset_name: str = "pampapilota#",
) -> dict[str, Any]:
    """Build one auditable filter proposal without touching REAPER."""

    definition = FILTER_DEFINITIONS.get(filter_type)
    if definition is None:
        raise ValueError(f"Filtro no soportado: {filter_type}")
    path = Path(path).resolve()
    decision = "audition_only"
    reason = "Punto de partida conservador para comparar en contexto."
    parameters: dict[str, Any]
    source_sha256: str

    if filter_type in {"eq", "compressor"}:
        mapped_role = PROCESSING_ROLES.get(role)
        if mapped_role is None:
            raise ValueError("Este rol todavía no tiene un perfil validado de EQ/compresión")
        origin = propose_track_processing(path, mapped_role, source_kind)  # type: ignore[arg-type]
        step = next(
            (item for item in origin["chain"] if item["processor"] == definition["processor"]),
            None,
        )
        if step is None:
            raise ValueError(f"No existe un perfil validado de {definition['title']} para este rol")
        parameters = dict(step["parameters"])
        source_sha256 = str(origin["source"]["sha256"])
        reason = str(step.get("intent") or reason)
        if source_kind == "suno_stems":
            reason = "Suno puede traer este procesamiento; usar sólo como comparación conservadora."
    elif filter_type == "gate":
        if role not in {"lead_vocal", "guitar"}:
            raise ValueError("ReaGate sólo está validado para voz principal o guitarra orgánica")
        origin = propose_reagate(path, role, source_kind)  # type: ignore[arg-type]
        decision, reason = str(origin["decision"]), str(origin["reason"])
        processor = origin.get("processor")
        parameters = dict(processor["parameters"]) if isinstance(processor, Mapping) else {}
        source_sha256 = str(origin["source"]["sha256"])
    elif filter_type == "deesser":
        if role != "lead_vocal":
            raise ValueError("El de-esser automático sólo está validado para voz principal")
        origin = propose_deesser(path, source_kind)  # type: ignore[arg-type]
        decision, reason = str(origin["decision"]), str(origin["reason"])
        processor = origin.get("processor")
        parameters = dict(processor["parameters"]) if isinstance(processor, Mapping) else {}
        source_sha256 = str(origin["source"]["sha256"])
    elif filter_type == "dynamic_resonance":
        mapped_role = ROLE_ALIASES.get(role)
        if mapped_role not in {"lead_vocal", "guitar", "strings", "keys"}:
            raise ValueError("El control dinámico no está validado para este rol")
        origin = analyze_dynamic_resonance(path, mapped_role, source_kind)  # type: ignore[arg-type]
        decision, reason = str(origin["decision"]), str(origin["reason"])
        processor = origin.get("processor")
        parameters = dict(processor["parameters"]) if isinstance(processor, Mapping) else {}
        source_sha256 = str(origin["source"]["sha256"])
    elif filter_type == "saturation":
        origin = propose_saturation(source_kind)  # type: ignore[arg-type]
        parameters = dict(origin["parameters"])
        reason = str(origin["reason"])
        source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        if role not in {"lead_vocal", "backing_vocals", "choir"}:
            raise ValueError("ReaTune sólo se ofrece para pistas vocales")
        preset_name = preset_name.strip()
        if not preset_name or len(preset_name) > 128:
            raise ValueError("El preset ReaTune debe tener entre 1 y 128 caracteres")
        parameters = {"preset_name": preset_name}
        source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        reason = "Carga un preset local existente por nombre exacto; la afinación se valida por escucha."

    identity = {
        "filter_type": filter_type,
        "source_sha256": source_sha256,
        "role": role,
        "source_kind": source_kind,
        "decision": decision,
        "parameters": parameters,
    }
    return {
        "proposal_id": _filter_identity(identity),
        "filter_type": filter_type,
        "title": definition["title"],
        "processor": definition["processor"],
        "fragment": definition["fragment"],
        "decision": decision,
        "reason": reason,
        "parameters": parameters,
        "source_sha256": source_sha256,
        "source_kind": source_kind,
        "role": role,
        "can_approve": decision == "audition_only" and bool(parameters),
    }


def filter_bindings(
    proposal: Mapping[str, Any], existing_fx: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    fragment = str(proposal["fragment"])
    matches = [
        {"guid": fx.get("guid"), "name": fx.get("name"), "preset_name": fx.get("preset_name", "")}
        for fx in existing_fx
        if fragment in str(fx.get("name", "")).casefold()
    ]
    processor = str(proposal["processor"])
    if not matches:
        return {"status": "create_new", "mode": "create_new", "fx_guid": None, "choices": []}
    if len(matches) == 1 and processor not in {"deesser", "dynamic_resonance"}:
        return {"status": "reuse_existing", "mode": "reuse_existing", "fx_guid": matches[0]["guid"], "choices": matches}
    return {
        "status": "selection_required",
        "mode": None,
        "fx_guid": None,
        "choices": matches,
        "reason": "Elegí explícitamente qué FX existente reutilizar; su propósito no puede inferirse sólo por el nombre.",
    }


def apply_filter_proposal(
    client: BridgeClient,
    *,
    project_ref: str,
    track_guid: str,
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    existing_fx: Sequence[Mapping[str, Any]],
    selected_fx_guid: str | None,
) -> BridgeResult:
    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("La propuesta cambió; volvé a previsualizarla")
    if not proposal.get("can_approve"):
        raise ValueError("La evidencia actual no permite aplicar este filtro")
    binding = filter_bindings(proposal, existing_fx)
    choices = {str(item["guid"]) for item in binding["choices"]}
    if binding["status"] == "selection_required":
        if selected_fx_guid == "__create_new__":
            mode, fx_guid = "create_new", None
        elif selected_fx_guid not in choices:
            raise ValueError("Debés elegir explícitamente un FX existente")
        else:
            mode, fx_guid = "reuse_existing", selected_fx_guid
    else:
        mode, fx_guid = str(binding["mode"]), binding["fx_guid"]
        if selected_fx_guid is not None and selected_fx_guid != fx_guid:
            raise ValueError("El FX seleccionado no coincide con la propuesta vigente")
    if proposal["filter_type"] == "tuning":
        return client.call(
            "apply_reatune_preset",
            {
                "project_ref": project_ref,
                "track_guid": track_guid,
                "mode": mode,
                "fx_guid": fx_guid,
                "preset_name": proposal["parameters"]["preset_name"],
            },
            timeout_seconds=30.0,
        )
    return client.call(
        "apply_producer_fx_chain",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "chain_id": approved_proposal_id,
            "source_sha256": proposal["source_sha256"],
            "steps": [
                {
                    "processor": proposal["processor"],
                    "mode": mode,
                    "fx_guid": fx_guid,
                    "parameters": proposal["parameters"],
                }
            ],
        },
        timeout_seconds=60.0,
    )
