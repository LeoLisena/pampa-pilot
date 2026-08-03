"""Conservative, source-aware ReaGate starting-point proposals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT


GateRole = Literal["lead_vocal", "guitar"]
SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]


def _load_knowledge(root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = root / "mixing" / "reagate-starting-points.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), dict):
        raise ValueError("ReaGate knowledge is invalid")
    return document, path


def _number(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_reagate_proposal(
    metrics: Mapping[str, Any],
    role: GateRole,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Build a non-executing gate hypothesis from measured quiet passages."""

    if role not in {"lead_vocal", "guitar"}:
        raise ValueError(f"unsupported ReaGate role: {role}")
    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError(f"unsupported source kind: {source_kind}")
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_knowledge(root)
    profile_name = "organic_vocal_cleanup" if role == "lead_vocal" else "organic_guitar_cleanup"
    profile = knowledge["profiles"].get(profile_name)
    if not isinstance(profile, dict) or not isinstance(profile.get("starting_values"), dict):
        raise ValueError(f"ReaGate profile is invalid: {profile_name}")

    quiet_ratio = _number(metrics, "quiet_block_ratio_below_minus_40_dbfs")
    noise_floor = _number(metrics, "quiet_rms_dbfs_p90_below_minus_40")
    active_p90 = _number(metrics, "active_rms_dbfs_p90")
    values = dict(profile["starting_values"])
    evidence_sufficient = (
        quiet_ratio is not None
        and quiet_ratio >= float(profile["minimum_quiet_block_ratio"])
        and noise_floor is not None
        and active_p90 is not None
        and active_p90 - noise_floor >= float(profile["minimum_signal_noise_gap_db"])
    )
    threshold_db: float | None = None
    if evidence_sufficient:
        threshold_db = min(
            noise_floor + float(profile["threshold_margin_above_quiet_db"]),
            active_p90 - float(profile["minimum_threshold_below_active_p90_db"]),
        )
        # REAPER 7.78 exposes values below this point as -inf; -42 dB is the
        # lowest finite, reproducibly settable threshold through the adapter.
        threshold_db = round(max(-42.0, min(-18.0, threshold_db)), 1)
        values["threshold_db"] = threshold_db

    if source_kind == "suno_stems":
        decision = "not_recommended"
        reason = "Suno stems are already processed and their quiet passages may be intentional."
    elif not evidence_sufficient:
        decision = "insufficient_evidence"
        reason = "The WAV does not expose enough separated quiet and active passages."
    else:
        decision = "audition_only"
        reason = "Measured quiet passages support a conservative threshold hypothesis."

    identity = {
        "source_sha256": metrics.get("sha256"),
        "role": role,
        "source_kind": source_kind,
        "profile": profile_name,
        "decision": decision,
        "parameters": values if threshold_db is not None else None,
        "knowledge_id": knowledge.get("id"),
        "reviewed_at": str(knowledge.get("reviewed_at")),
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_reagate_proposal",
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
        "observations": {
            "quiet_block_ratio_below_minus_40_dbfs": quiet_ratio,
            "quiet_rms_dbfs_p90_below_minus_40": noise_floor,
            "active_rms_dbfs_p90": active_p90,
            "observed_quiet_to_active_gap_db": (
                round(active_p90 - noise_floor, 3)
                if active_p90 is not None and noise_floor is not None
                else None
            ),
        },
        "processor": (
            {
                "type": "reagate",
                "profile": profile_name,
                "parameters": values,
                "intent": profile.get("intent"),
                "fine_tuning": list(profile.get("fine_tuning", [])),
            }
            if threshold_db is not None and decision == "audition_only"
            else None
        ),
        "knowledge": {
            "id": knowledge.get("id"),
            "path": str(knowledge_path),
            "confidence": knowledge.get("confidence"),
            "reviewed_at": str(knowledge.get("reviewed_at")),
        },
        "warnings": [
            "A gate can cut breaths, consonants, guitar decay and room tone.",
            "Objective separation does not prove that gating improves the performance.",
            "Compare enabled and bypass on phrase endings before keeping it.",
        ],
        "verification_plan": {
            "state": "re-read ReaGate GUID and every requested parameter",
            "signal": "render the same range and inspect tails and quiet passages",
            "perceptual": "approve breaths, consonants, sustain and room tone by listening",
        },
    }


def propose_reagate(
    audio_path: Path,
    role: GateRole,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    return build_reagate_proposal(
        analyze_audio_file(Path(audio_path)),
        role,
        source_kind,
        knowledge_root=knowledge_root,
    )


def build_reagate_application_payload(
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    fx_guid: str | None,
) -> dict[str, Any]:
    """Bind an approved, still-current proposal to an optional ReaGate GUID."""

    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False or proposal.get("decision") != "audition_only":
        raise ValueError("only an audition-only ReaGate proposal can be approved")
    source = proposal.get("source")
    processor = proposal.get("processor")
    if not isinstance(source, dict) or not isinstance(processor, dict):
        raise ValueError("proposal is missing source or processor data")
    parameters = processor.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("proposal has no ReaGate parameters")
    source_sha256 = source.get("sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("proposal source does not contain a SHA-256 identity")
    if fx_guid is not None and (not isinstance(fx_guid, str) or not fx_guid.strip()):
        raise ValueError("fx_guid is invalid")
    return {
        "proposal_id": approved_proposal_id,
        "source_sha256": source_sha256,
        "mode": "reuse_existing" if fx_guid else "create_new",
        "fx_guid": fx_guid,
        "parameters": dict(parameters),
    }
