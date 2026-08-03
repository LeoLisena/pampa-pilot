"""Build and bind conservative ReaLimit mastering proposals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .media_discovery import WORKSPACE_ROOT


def _load_knowledge(root: Path) -> tuple[dict[str, Any], Path]:
    import yaml

    path = root / "mastering" / "realimit-starting-points.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("profile"), dict):
        raise ValueError("ReaLimit mastering knowledge is invalid")
    return document, path


def build_mastering_proposal(
    file_report: Mapping[str, Any], *, knowledge_root: Path | None = None
) -> dict[str, Any]:
    """Propose peak safety only when measured true peak exceeds platform guidance."""

    if file_report.get("kind") != "pampapilot_master_delivery_qc":
        raise ValueError("file_report is not a master delivery QC report")
    measurements = file_report.get("measurements")
    source = file_report.get("source")
    if not isinstance(measurements, dict) or not isinstance(source, dict):
        raise ValueError("file report is missing source or measurements")
    integrated_lufs = float(measurements["integrated_lufs"])
    true_peak = float(measurements["estimated_true_peak_dbtp"])
    platform_limit = -2.0 if integrated_lufs > -14.0 else -1.0
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    knowledge, knowledge_path = _load_knowledge(root)
    profile = knowledge["profile"]
    chain = []
    if true_peak > platform_limit:
        ceiling = platform_limit - float(profile["safety_margin_below_platform_peak_db"])
        chain.append(
            {
                "order": 1,
                "processor": "realimit",
                "decision": "audition_only",
                "intent": "Create conservative peak headroom without routine loudness gain.",
                "parameters": {
                    "threshold_db": ceiling,
                    "ceiling_db": ceiling,
                    "release_ms": float(profile["release_ms"]),
                },
                "evidence": {
                    "integrated_lufs": integrated_lufs,
                    "estimated_true_peak_dbtp": true_peak,
                    "platform_guidance_dbtp": platform_limit,
                    "estimated_peak_reduction_required_db": round(true_peak - ceiling, 3),
                },
                "limitations": [
                    "The source true peak is estimated, not certified.",
                    "Plugin state cannot prove rendered true peak compliance.",
                ],
            }
        )

    identity = {
        "file_report_id": file_report["report_id"],
        "source_sha256": source["sha256"],
        "knowledge_id": knowledge["id"],
        "reviewed_at": str(knowledge["reviewed_at"]),
        "chain": chain,
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_mastering_proposal",
        "proposal_id": proposal_id,
        "execute": False,
        "review_status": "user_approval_required" if chain else "no_action_recommended",
        "source": {
            "file_path": source["file_path"],
            "sha256": source["sha256"],
            "file_report_id": file_report["report_id"],
        },
        "chain": chain,
        "knowledge": {
            "id": knowledge["id"],
            "path": str(knowledge_path),
            "reviewed_at": str(knowledge["reviewed_at"]),
        },
        "verification_plan": {
            "state": "re-read ReaLimit identity, GUID and all requested parameters",
            "signal": "render a candidate master and run delivery QC again",
            "perceptual": "audition transients and pumping against bypass",
        },
    }


def build_mastering_application_payload(
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    fx_guid: str | None,
) -> dict[str, Any]:
    """Bind an approved mastering proposal to new or existing ReaLimit."""

    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False:
        raise ValueError("only a non-executing proposal can be approved")
    chain = proposal.get("chain")
    source = proposal.get("source")
    if not isinstance(chain, list) or len(chain) != 1 or chain[0].get("processor") != "realimit":
        raise ValueError("proposal contains no applicable ReaLimit step")
    if not isinstance(source, dict) or not isinstance(source.get("sha256"), str):
        raise ValueError("proposal source has no SHA-256 identity")
    if fx_guid is not None and not fx_guid.strip():
        raise ValueError("fx_guid cannot be empty")
    return {
        "proposal_id": approved_proposal_id,
        "source_sha256": source["sha256"],
        "fx_guid": fx_guid,
        "parameters": dict(chain[0]["parameters"]),
    }
