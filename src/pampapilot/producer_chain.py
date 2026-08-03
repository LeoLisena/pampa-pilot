"""Compose existing source-aware proposals into one auditable track FX chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .audio_analysis import analyze_audio_file
from .deesser_proposal import build_deesser_proposal
from .dynamic_resonance import analyze_dynamic_resonance
from .gate_proposal import build_reagate_proposal
from .processing_proposal import build_processing_proposal
from .saturation_proposal import propose_saturation


Role = Literal[
    "lead_vocal", "backing_vocals", "bass", "drums", "guitar", "strings", "keys"
]
SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_ORDER = {
    "reagate": 10,
    "reaeq": 20,
    "dynamic_resonance": 30,
    "reacomp": 40,
    "deesser": 50,
    "waveshaper": 60,
}
_NAME_FRAGMENT = {
    "reagate": "reagate",
    "reaeq": "reaeq",
    "dynamic_resonance": "reaxcomp",
    "reacomp": "reacomp",
    "deesser": "reaxcomp",
    "waveshaper": "multi waveshaper",
}


def _step(
    processor: str,
    parameters: Mapping[str, Any],
    origin: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "order": _ORDER[processor],
        "processor": processor,
        "decision": "audition_only",
        "parameters": dict(parameters),
        "origin_proposal_id": origin.get("proposal_id"),
        "reason": reason,
    }


def _bind_existing(
    steps: list[dict[str, Any]], existing_fx: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    reaxcomp_steps = [
        step for step in steps if step["processor"] in {"dynamic_resonance", "deesser"}
    ]
    reaxcomp_fx = [
        fx for fx in existing_fx if "reaxcomp" in str(fx.get("name", "")).lower()
    ]
    if reaxcomp_fx and reaxcomp_steps:
        conflicts.append(
            {
                "kind": "ambiguous_existing_reaxcomp",
                "fx_guids": [fx.get("guid") for fx in reaxcomp_fx],
                "processors": [step["processor"] for step in reaxcomp_steps],
                "reason": "ReaXcomp purpose cannot be inferred safely from its name.",
            }
        )

    bound: list[dict[str, Any]] = []
    for step in steps:
        fragment = _NAME_FRAGMENT[step["processor"]]
        matches = [
            fx for fx in existing_fx if fragment in str(fx.get("name", "")).lower()
        ]
        if step["processor"] in {"dynamic_resonance", "deesser"}:
            binding = "blocked_existing_fx" if matches else "create_new"
            suggested_guid = None
        elif len(matches) == 0:
            binding, suggested_guid = "create_new", None
        elif len(matches) == 1:
            binding, suggested_guid = "reuse_existing", matches[0].get("guid")
        else:
            binding, suggested_guid = "blocked_multiple_fx", None
            conflicts.append(
                {
                    "kind": "multiple_existing_processor_instances",
                    "processor": step["processor"],
                    "fx_guids": [fx.get("guid") for fx in matches],
                }
            )
        bound.append(
            {
                **step,
                "binding": binding,
                "suggested_fx_guid": suggested_guid,
            }
        )
    return bound, conflicts


def build_track_producer_chain(
    path: Path,
    role: Role,
    source_kind: SourceKind,
    *,
    existing_fx: Sequence[Mapping[str, Any]] = (),
    include_artistic_saturation: bool = False,
) -> dict[str, Any]:
    """Select compatible evidence-backed FX steps without changing anything."""

    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError(f"unsupported source kind: {source_kind}")
    if role not in {
        "lead_vocal", "backing_vocals", "bass", "drums", "guitar", "strings", "keys"
    }:
        raise ValueError(f"unsupported role: {role}")
    path = Path(path).resolve()
    metrics = analyze_audio_file(path)
    selected: list[dict[str, Any]] = []
    considered: list[dict[str, Any]] = []

    if source_kind == "organic_multitrack" and role in {"lead_vocal", "guitar"}:
        gate = build_reagate_proposal(metrics, role, source_kind)
        considered.append({"processor": "reagate", "decision": gate["decision"]})
        if gate["decision"] == "audition_only":
            selected.append(
                _step(
                    "reagate",
                    gate["processor"]["parameters"],
                    gate,
                    gate["reason"],
                )
            )

    if source_kind == "organic_multitrack" and role != "keys":
        base = build_processing_proposal(metrics, role, source_kind)
        for candidate in base["chain"]:
            processor = str(candidate["processor"])
            considered.append({"processor": processor, "decision": "audition_only"})
            selected.append(
                _step(
                    processor,
                    candidate["parameters"],
                    base,
                    str(candidate.get("intent", "source-aware starting point")),
                )
            )

    if role in {"lead_vocal", "guitar", "strings", "keys"}:
        resonance = analyze_dynamic_resonance(path, role, source_kind)
        considered.append(
            {"processor": "dynamic_resonance", "decision": resonance["decision"]}
        )
        if resonance["decision"] == "audition_only":
            selected.append(
                _step(
                    "dynamic_resonance",
                    resonance["processor"]["parameters"],
                    resonance,
                    resonance["reason"],
                )
            )

    if source_kind == "organic_multitrack" and role == "lead_vocal":
        deesser = build_deesser_proposal(metrics, source_kind)
        considered.append({"processor": "deesser", "decision": deesser["decision"]})
        if deesser["decision"] == "audition_only":
            selected.append(
                _step(
                    "deesser",
                    deesser["processor"]["parameters"],
                    deesser,
                    deesser["reason"],
                )
            )

    if include_artistic_saturation and source_kind != "unknown":
        saturation = propose_saturation(source_kind)
        considered.append({"processor": "waveshaper", "decision": "audition_only"})
        selected.append(
            _step(
                "waveshaper",
                saturation["parameters"],
                saturation,
                str(saturation["reason"]),
            )
        )

    selected.sort(key=lambda value: value["order"])
    bound, conflicts = _bind_existing(selected, existing_fx)
    blocked = bool(conflicts) or any(
        step["binding"].startswith("blocked") for step in bound
    )
    identity = {
        "source_sha256": metrics["sha256"],
        "role": role,
        "source_kind": source_kind,
        "steps": bound,
        "existing_fx": [
            {"guid": fx.get("guid"), "name": fx.get("name")} for fx in existing_fx
        ],
    }
    chain_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_track_producer_chain",
        "chain_id": chain_id,
        "execute": False,
        "review_status": (
            "blocked_existing_fx"
            if blocked
            else "user_approval_required"
            if bound
            else "no_processing_recommended"
        ),
        "source": {
            "file_name": path.name,
            "file_path": str(path),
            "sha256": metrics["sha256"],
            "role": role,
            "source_kind": source_kind,
        },
        "steps": bound,
        "considered": considered,
        "conflicts": conflicts,
        "existing_fx_preserved": [
            {"guid": fx.get("guid"), "name": fx.get("name")} for fx in existing_fx
        ],
        "deferred_stages": [
            "vocal_rider_envelope",
            "ambience_routing",
            "loudness_matched_ab",
        ],
        "verification_plan": {
            "state": "apply all approved FX in one undo transaction and re-read every instance",
            "signal": "render the same range before and after at matched loudness",
            "perceptual": "approve the complete chain and each bypassed stage by listening",
        },
    }


def build_producer_chain_application_payload(
    chain: Mapping[str, Any], approved_chain_id: str
) -> dict[str, Any]:
    if chain.get("chain_id") != approved_chain_id:
        raise ValueError("approved_chain_id does not match the current chain")
    if chain.get("execute") is not False:
        raise ValueError("only a non-executing chain can be approved")
    if chain.get("review_status") != "user_approval_required":
        raise ValueError("producer chain is blocked or contains no processing")
    source = chain.get("source")
    steps = chain.get("steps")
    if not isinstance(source, Mapping) or not isinstance(steps, list) or not steps:
        raise ValueError("producer chain is missing source or steps")
    payload_steps = []
    for step in steps:
        binding = step.get("binding")
        if binding not in {"create_new", "reuse_existing"}:
            raise ValueError("producer chain contains an unresolved FX binding")
        payload_steps.append(
            {
                "processor": step["processor"],
                "mode": binding,
                "fx_guid": step.get("suggested_fx_guid"),
                "parameters": dict(step["parameters"]),
            }
        )
    return {
        "chain_id": approved_chain_id,
        "source_sha256": source["sha256"],
        "steps": payload_steps,
    }
