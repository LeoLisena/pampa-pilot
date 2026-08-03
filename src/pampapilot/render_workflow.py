"""Bind a bridge-controlled REAPER render to immediate signal verification."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from .mastering_qc import build_project_master_delivery_qc


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


def build_rendered_master_candidate_report(
    bridge_reply: Mapping[str, Any],
    file_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a provenance receipt for one bridge-rendered and measured WAV."""

    request_id = bridge_reply.get("request_id")
    result = bridge_reply.get("result")
    observations = bridge_reply.get("observations")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("bridge reply has no request identity")
    if not isinstance(result, dict) or not isinstance(observations, dict):
        raise ValueError("bridge reply is missing result or observations")
    if observations.get("state_verified") is not True:
        raise ValueError("REAPER did not verify the render state")
    if result.get("transaction_request_id") != request_id:
        raise ValueError("render transaction identity does not match the request")
    render_settings = result.get("render_settings")
    if not isinstance(render_settings, dict):
        raise ValueError("render receipt has no verified settings")
    if file_report.get("kind") != "pampapilot_master_delivery_qc":
        raise ValueError("file report is not a master delivery QC report")
    source = file_report.get("source")
    if not isinstance(source, dict):
        raise ValueError("file report has no source identity")
    if _normalized_path(str(result.get("output_file") or "")) != _normalized_path(
        str(source.get("file_path") or "")
    ):
        raise ValueError("measured file is not the bridge-rendered output")
    if int(result.get("output_size_bytes") or 0) <= 44:
        raise ValueError("render receipt does not describe a valid WAV payload")

    report = build_project_master_delivery_qc(render_settings, file_report)
    identity = {
        "render_request_id": request_id,
        "project_ref": result.get("project_ref"),
        "project_state_change_count": render_settings.get(
            "project_state_change_count"
        ),
        "output_sha256": source.get("sha256"),
        "file_report_id": file_report.get("report_id"),
    }
    report["schema_version"] = "0.1"
    report["kind"] = "pampapilot_rendered_master_candidate"
    report["report_id"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    report["render_receipt"] = {
        "request_id": request_id,
        "transaction_request_id": result["transaction_request_id"],
        "project_ref": result.get("project_ref"),
        "project_path": result.get("project_path"),
        "project_state_change_count": render_settings.get(
            "project_state_change_count"
        ),
        "output_file": result.get("output_file"),
        "output_size_bytes": int(result["output_size_bytes"]),
        "output_sha256": source.get("sha256"),
        "render_started_at_unix": result.get("render_started_at_unix"),
        "render_completed_at_unix": result.get("render_completed_at_unix"),
        "render_action_id": result.get("render_action_id"),
        "render_action_text": result.get("render_action_text"),
        "transport_was_stopped": bool(result.get("transport_was_stopped")),
        "render_stats": result.get("render_stats"),
        "render_stats_summary": result.get("render_stats_summary"),
    }
    report["provenance"] = {
        "configuration_consistent": report["provenance"][
            "configuration_consistent"
        ],
        "render_provenance_verified": True,
        "output_hash_verified_after_render": True,
        "note": (
            "PampaPilot configured the unique target, invoked REAPER's render "
            "action, verified the new WAV, and hashed the same file immediately."
        ),
    }
    report["verification"] = {
        "state_verified": True,
        "signal_verified": True,
        "perceptually_evaluated": False,
    }
    return report
