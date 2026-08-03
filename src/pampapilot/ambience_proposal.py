"""Source-aware artistic starting points for reverb and delay buses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT


AmbienceType = Literal["reverb", "delay"]
AmbienceRole = Literal["lead_vocal", "backing_vocals", "guitar", "strings"]
SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]


def _load_knowledge(root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = root / "mixing" / "ambience-bus-starting-points.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), dict):
        raise ValueError("ambience bus knowledge is invalid")
    return document, path


def _select_profile(
    profiles: Mapping[str, Any], role: AmbienceRole, effect_type: AmbienceType
) -> tuple[str, dict[str, Any]]:
    for name, raw in profiles.items():
        if not isinstance(raw, dict):
            continue
        if raw.get("effect_type") == effect_type and role in raw.get("roles", []):
            return str(name), raw
    raise ValueError(f"no ambience profile for {role}/{effect_type}")


def build_ambience_proposal(
    metrics: Mapping[str, Any],
    role: AmbienceRole,
    effect_type: AmbienceType,
    bpm: float,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    if role not in {"lead_vocal", "backing_vocals", "guitar", "strings"}:
        raise ValueError(f"unsupported ambience role: {role}")
    if effect_type not in {"reverb", "delay"}:
        raise ValueError(f"unsupported ambience type: {effect_type}")
    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError(f"unsupported source kind: {source_kind}")
    if not 20.0 <= float(bpm) <= 400.0:
        raise ValueError("bpm must be between 20 and 400")

    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_knowledge(root)
    profile_name, profile = _select_profile(
        knowledge["profiles"], role, effect_type
    )
    parameters = dict(profile["parameters"])
    send_db = float(profile["send_db"])
    if source_kind == "suno_stems":
        parameters.update(dict(profile.get("suno_parameters", {})))
        send_db = float(profile.get("suno_send_db", send_db - 8.0))
    if effect_type == "delay":
        parameters["delay_ms"] = round(
            60_000.0 / float(bpm) * float(profile["delay_beats"]), 1
        )

    if source_kind == "unknown":
        decision = "source_confirmation_required"
        reason = "Ambience is artistic; confirm whether the source is already processed."
    elif source_kind == "suno_stems":
        decision = "audition_only"
        reason = "The processed Suno stem gets a deliberately subtle supplemental ambience."
    else:
        decision = "audition_only"
        reason = "The organic source supports a conservative spatial starting point."

    identity = {
        "source_sha256": metrics.get("sha256"),
        "role": role,
        "effect_type": effect_type,
        "source_kind": source_kind,
        "bpm": round(float(bpm), 6),
        "profile": profile_name,
        "decision": decision,
        "parameters": parameters,
        "send_db": send_db,
        "knowledge_id": knowledge.get("id"),
        "reviewed_at": str(knowledge.get("reviewed_at")),
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    processor = None
    if decision == "audition_only":
        processor = {
            "effect_type": effect_type,
            "profile": profile_name,
            "bus_name": profile["bus_name"],
            "send_db": send_db,
            "send_mode": "post_fader",
            "parameters": parameters,
        }
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_ambience_bus_proposal",
        "proposal_id": proposal_id,
        "execute": False,
        "review_status": "user_approval_required",
        "decision": decision,
        "reason": reason,
        "source": {
            "file_name": metrics.get("file_name"),
            "file_path": metrics.get("file_path"),
            "sha256": metrics.get("sha256"),
            "role": role,
            "source_kind": source_kind,
        },
        "tempo_bpm": float(bpm),
        "processor": processor,
        "knowledge": {
            "id": knowledge.get("id"),
            "path": str(knowledge_path),
            "confidence": knowledge.get("confidence"),
            "reviewed_at": str(knowledge.get("reviewed_at")),
        },
        "warnings": [
            "Reverb and delay are artistic choices, not corrections proven by WAV metrics.",
            "Compare the bus muted and active at matched direct-track level.",
            "Check phrase endings, low-mid buildup and stereo distraction.",
        ],
        "verification_plan": {
            "state": "verify bus/FX GUIDs, 100% wet state and every send field",
            "signal": "render the same range with the ambience bus muted and active",
            "perceptual": "approve depth, intelligibility and arrangement space by listening",
        },
    }


def propose_ambience(
    audio_path: Path,
    role: AmbienceRole,
    effect_type: AmbienceType,
    bpm: float,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    return build_ambience_proposal(
        analyze_audio_file(Path(audio_path)),
        role,
        effect_type,
        bpm,
        source_kind,
        knowledge_root=knowledge_root,
    )


def build_ambience_application_payload(
    proposal: Mapping[str, Any], approved_proposal_id: str
) -> dict[str, Any]:
    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False or proposal.get("decision") != "audition_only":
        raise ValueError("only an audition-only ambience proposal can be approved")
    source = proposal.get("source")
    processor = proposal.get("processor")
    if not isinstance(source, dict) or not isinstance(processor, dict):
        raise ValueError("proposal is missing source or processor data")
    sha256 = source.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError("proposal source does not contain a SHA-256 identity")
    parameters = processor.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("proposal has no ambience parameters")
    return {
        "proposal_id": approved_proposal_id,
        "source_sha256": sha256,
        "effect_type": processor["effect_type"],
        "bus_name": processor["bus_name"],
        "send_db": processor["send_db"],
        "parameters": dict(parameters),
    }
