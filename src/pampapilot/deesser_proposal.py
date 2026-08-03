"""Source-aware ReaXcomp de-esser proposals derived from WAV observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]


def _load_knowledge(root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = root / "mixing" / "reaxcomp-deesser-starting-points.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), dict):
        raise ValueError("ReaXcomp de-esser knowledge is invalid")
    return document, path


def _number(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_deesser_proposal(
    metrics: Mapping[str, Any],
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Build a non-executing high-band compression hypothesis for lead vocals."""

    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError(f"unsupported source kind: {source_kind}")
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_knowledge(root)
    profile = knowledge["profiles"].get("organic_lead_vocal")
    if not isinstance(profile, dict) or not isinstance(profile.get("starting_values"), dict):
        raise ValueError("ReaXcomp de-esser profile is invalid")

    ratio_p95 = _number(metrics, "sibilance_ratio_p95")
    band_p50 = _number(metrics, "sibilance_band_rms_dbfs_p50")
    band_p95 = _number(metrics, "sibilance_band_rms_dbfs_p95")
    peak_to_median = _number(metrics, "sibilance_peak_to_median_db")
    evidence_sufficient = (
        ratio_p95 is not None
        and ratio_p95 >= float(profile["minimum_sibilance_ratio_p95"])
        and band_p50 is not None
        and band_p95 is not None
        and band_p95 >= float(profile["minimum_sibilance_band_p95_dbfs"])
        and peak_to_median is not None
        and peak_to_median >= float(profile["minimum_sibilance_peak_to_median_db"])
    )

    values = dict(profile["starting_values"])
    if evidence_sufficient:
        threshold = max(
            band_p95 - float(profile["threshold_below_p95_db"]),
            band_p50 + float(profile["threshold_above_median_db"]),
        )
        values["threshold_db"] = round(max(-36.0, min(-8.0, threshold)), 1)

    if source_kind == "suno_stems":
        decision = "not_recommended"
        reason = "Suno vocals are already processed; high-frequency energy may be intentional."
    elif not evidence_sufficient:
        decision = "insufficient_evidence"
        reason = "The WAV does not show distinct, sufficiently strong sibilant peaks."
    else:
        decision = "audition_only"
        reason = "Intermittent 5-10 kHz peaks support a high-band compression audition."

    identity = {
        "source_sha256": metrics.get("sha256"),
        "source_kind": source_kind,
        "decision": decision,
        "parameters": values if evidence_sufficient else None,
        "knowledge_id": knowledge.get("id"),
        "reviewed_at": str(knowledge.get("reviewed_at")),
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_reaxcomp_deesser_proposal",
        "proposal_id": proposal_id,
        "execute": False,
        "review_status": "user_approval_required",
        "decision": decision,
        "reason": reason,
        "source": {
            "file_name": metrics.get("file_name"),
            "file_path": metrics.get("file_path"),
            "sha256": metrics.get("sha256"),
            "role": "lead_vocal",
            "source_kind": source_kind,
        },
        "observations": {
            "sibilance_ratio_p95": ratio_p95,
            "sibilance_band_rms_dbfs_p50": band_p50,
            "sibilance_band_rms_dbfs_p95": band_p95,
            "sibilance_peak_to_median_db": peak_to_median,
        },
        "processor": (
            {
                "type": "reaxcomp_deesser",
                "profile": "organic_lead_vocal",
                "parameters": values,
                "intent": profile.get("intent"),
                "fine_tuning": list(profile.get("fine_tuning", [])),
            }
            if evidence_sufficient and decision == "audition_only"
            else None
        ),
        "knowledge": {
            "id": knowledge.get("id"),
            "path": str(knowledge_path),
            "confidence": knowledge.get("confidence"),
            "reviewed_at": str(knowledge.get("reviewed_at")),
        },
        "warnings": [
            "A de-esser can dull the vocal or create a lisp.",
            "High-frequency energy is not automatically excessive sibilance.",
            "Compare bypass on consonants, breath and sustained vowels.",
        ],
        "verification_plan": {
            "state": "re-read ReaXcomp GUID and every requested band parameter",
            "signal": "compare high-band gain reduction on the same vocal range",
            "perceptual": "approve sibilance, clarity and air by listening",
        },
    }


def propose_deesser(
    audio_path: Path,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    return build_deesser_proposal(
        analyze_audio_file(Path(audio_path)),
        source_kind,
        knowledge_root=knowledge_root,
    )


def build_deesser_application_payload(
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    fx_guid: str | None,
) -> dict[str, Any]:
    """Bind an approved current proposal to a new or exact existing ReaXcomp."""

    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False or proposal.get("decision") != "audition_only":
        raise ValueError("only an audition-only de-esser proposal can be approved")
    source = proposal.get("source")
    processor = proposal.get("processor")
    if not isinstance(source, dict) or not isinstance(processor, dict):
        raise ValueError("proposal is missing source or processor data")
    parameters = processor.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("proposal has no ReaXcomp parameters")
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
