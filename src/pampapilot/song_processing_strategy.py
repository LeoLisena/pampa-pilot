"""Build conservative, source-aware processing strategy from a song diagnosis."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .media_discovery import WORKSPACE_ROOT
from .processing_proposal import build_processing_proposal


SUPPORTED_ROLES = {
    "lead_vocal",
    "backing_vocals",
    "bass",
    "drums",
    "guitar",
    "strings",
}


def _proposal_metrics(stem: Mapping[str, Any]) -> dict[str, Any]:
    identity = stem["audio_identity"]
    observations = stem["observations"]
    path = Path(str(identity["file_path"]))
    return {
        "file_name": path.name,
        "file_path": str(path),
        "sha256": identity["sha256"],
        **dict(observations),
    }


def build_song_processing_strategy(
    diagnosis: Mapping[str, Any], *, knowledge_root: Path | None = None
) -> dict[str, Any]:
    """Select only evidence-backed audition candidates; never execute processing."""

    if diagnosis.get("execute") is not False:
        raise ValueError("diagnosis must be non-executing")
    stems = diagnosis.get("stems")
    if not isinstance(stems, list) or not stems:
        raise ValueError("diagnosis contains no stems")
    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    items: list[dict[str, Any]] = []
    disposition_counts: Counter[str] = Counter()

    for stem in stems:
        name = str(stem["track_name"])
        role = str(stem["role"])
        source_kind = str(stem["source_kind"])
        finding_ids = {str(item["id"]) for item in stem.get("findings", [])}
        selected_chain: list[dict[str, Any]] = []

        if source_kind == "suno_stems":
            disposition = "preserve_existing_processing"
            rationale = (
                "The stem may already contain EQ and dynamics from Suno; no routine "
                "processing is proposed. Review diagnosed defects only."
            )
        elif source_kind == "unknown":
            disposition = "classify_source_first"
            rationale = "Source provenance is required before source-dependent processing."
        elif role not in SUPPORTED_ROLES:
            disposition = "knowledge_profile_not_available"
            rationale = f"No versioned processing profile exists yet for organic role {role}."
        else:
            proposal = build_processing_proposal(
                _proposal_metrics(stem),
                role,  # type: ignore[arg-type]
                "organic_multitrack",
                knowledge_root=root,
            )
            for step in proposal["chain"]:
                processor = step["processor"]
                triggers: list[str] = []
                if processor == "reaeq" and "spectrum.vocal_low_frequency_candidate" in finding_ids:
                    triggers.append("spectrum.vocal_low_frequency_candidate")
                if processor == "reacomp" and "dynamics.wide_organic_performance" in finding_ids:
                    triggers.append("dynamics.wide_organic_performance")
                if triggers:
                    selected_chain.append({**step, "trigger_finding_ids": triggers})
            if selected_chain:
                disposition = "audition_candidates"
                rationale = (
                    "Objective candidates and source-aware knowledge support a supervised A/B; "
                    "the chain remains unapproved and non-executing."
                )
            else:
                disposition = "no_observed_processing_trigger"
                rationale = "No current finding justifies routine EQ or compression."

        disposition_counts[disposition] += 1
        items.append(
            {
                "track_name": name,
                "role": role,
                "source_kind": source_kind,
                "source_sha256": stem["audio_identity"]["sha256"],
                "disposition": disposition,
                "rationale": rationale,
                "diagnosed_finding_ids": sorted(finding_ids),
                "chain": selected_chain,
            }
        )

    identity = {
        "diagnosis_song": diagnosis.get("song"),
        "knowledge": diagnosis.get("knowledge"),
        "items": items,
    }
    strategy_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    candidate_count = sum(bool(item["chain"]) for item in items)
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_song_processing_strategy",
        "strategy_id": strategy_id,
        "execute": False,
        "review_status": (
            "user_approval_required" if candidate_count else "no_processing_recommended"
        ),
        "summary": {
            "stem_count": len(items),
            "audition_candidate_count": candidate_count,
            "disposition_counts": dict(disposition_counts),
        },
        "items": items,
        "constraints": [
            "Suno stems are preserved unless an observable defect supports intervention.",
            "Unknown sources must be classified before source-dependent processing.",
            "Every proposed step is an audition candidate, not an automatic correction.",
        ],
        "verification": {
            "state_verified": False,
            "signal_verified": bool(
                diagnosis.get("verification", {}).get("signal_verified")
            ),
            "perceptually_evaluated": False,
        },
    }
