"""Build auditable processing hypotheses without touching REAPER."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .audio_analysis import analyze_audio_file
from .media_discovery import WORKSPACE_ROOT


TrackRole = Literal[
    "lead_vocal", "backing_vocals", "bass", "drums", "guitar", "strings"
]
SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

COMPRESSOR_PROFILES = {
    "lead_vocal": "vocal_gentle",
    "backing_vocals": "backing_vocals_glue",
    "bass": "bass_control",
    "drums": "drum_bus_gentle",
    "guitar": "acoustic_guitar_gentle",
    "strings": "strings_gentle",
}
EQ_PROFILES = {
    "lead_vocal": "lead_vocal_cleanup",
    "backing_vocals": "backing_vocals_cleanup",
    "guitar": "acoustic_guitar_cleanup",
    "strings": "strings_cleanup",
}


class KnowledgeError(ValueError):
    """The selected knowledge rule is missing or malformed."""


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        raise KnowledgeError(f"knowledge file does not exist: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise KnowledgeError(f"knowledge file must contain an object: {path}")
    for field in ("id", "title", "profiles", "confidence", "reviewed_at"):
        if field not in document:
            raise KnowledgeError(f"knowledge file is missing {field}: {path}")
    if not isinstance(document["profiles"], dict):
        raise KnowledgeError(f"knowledge profiles must be an object: {path}")
    return document


def _profile(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    profiles = document["profiles"]
    candidate = profiles.get(name)
    if not isinstance(candidate, dict):
        raise KnowledgeError(f"knowledge profile does not exist: {name}")
    values = candidate.get("starting_values")
    if not isinstance(values, dict):
        raise KnowledgeError(f"knowledge profile has no starting_values: {name}")
    return candidate


def _knowledge_reference(document: Mapping[str, Any], path: Path) -> dict[str, Any]:
    return {
        "id": document["id"],
        "title": document["title"],
        "path": str(path.resolve()),
        "confidence": document["confidence"],
        "reviewed_at": str(document["reviewed_at"]),
    }


def _required_number(metrics: Mapping[str, Any], name: str) -> float:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"audio metrics do not contain numeric {name}")
    return float(value)


def _predicted_peak_reduction(
    sample_peak_dbfs: float, threshold_db: float, ratio: float
) -> float:
    if sample_peak_dbfs <= threshold_db:
        return 0.0
    return (sample_peak_dbfs - threshold_db) * (1.0 - 1.0 / ratio)


def build_processing_proposal(
    metrics: Mapping[str, Any],
    role: TrackRole,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Turn observations and versioned rules into a non-executing proposal."""

    if role not in COMPRESSOR_PROFILES:
        raise ValueError(f"unsupported track role: {role}")
    if source_kind not in {"suno_stems", "organic_multitrack", "unknown"}:
        raise ValueError(f"unsupported source kind: {source_kind}")

    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    compressor_path = root / "mixing" / "reacomp-starting-points.yaml"
    eq_path = root / "mixing" / "eq-starting-points.yaml"
    compressor_knowledge = _load_yaml(compressor_path)
    compressor_name = COMPRESSOR_PROFILES[role]
    compressor_profile = _profile(compressor_knowledge, compressor_name)
    compressor_values = dict(compressor_profile["starting_values"])

    sample_peak_dbfs = _required_number(metrics, "sample_peak_dbfs")
    integrated_lufs = metrics.get("integrated_lufs")
    crest_factor_db = metrics.get("crest_factor_db")
    threshold_db = float(compressor_values["threshold_db"])
    ratio = float(compressor_values["ratio"])
    predicted_reduction = _predicted_peak_reduction(
        sample_peak_dbfs, threshold_db, ratio
    )

    chain: list[dict[str, Any]] = []
    knowledge = [_knowledge_reference(compressor_knowledge, compressor_path)]
    if role in EQ_PROFILES:
        eq_knowledge = _load_yaml(eq_path)
        eq_name = EQ_PROFILES[role]
        eq_profile = _profile(eq_knowledge, eq_name)
        chain.append(
            {
                "order": 1,
                "processor": "reaeq",
                "profile": eq_name,
                "decision": "audition_only",
                "confidence": "low_until_spectral_or_perceptual_evidence",
                "intent": eq_profile.get("intent"),
                "parameters": dict(eq_profile["starting_values"]),
                "evidence": [
                    f"track role is {role}",
                    "broadband metrics do not prove unwanted low-frequency energy",
                ],
                "rejection_condition": eq_profile.get("rejection_condition"),
            }
        )
        knowledge.append(_knowledge_reference(eq_knowledge, eq_path))

    chain.append(
        {
            "order": len(chain) + 1,
            "processor": "reacomp",
            "profile": compressor_name,
            "decision": "audition_only",
            "confidence": compressor_knowledge["confidence"],
            "intent": compressor_profile.get("intent"),
            "parameters": compressor_values,
            "evidence": {
                "sample_peak_dbfs": sample_peak_dbfs,
                "integrated_lufs": integrated_lufs,
                "crest_factor_db": crest_factor_db,
                "theoretical_peak_reduction_ceiling_db": round(predicted_reduction, 3),
                "note": "This is a static ceiling, not measured gain reduction.",
            },
            "expected_gain_reduction_db": compressor_profile.get(
                "expected_gain_reduction_db"
            ),
            "fine_tuning": list(compressor_profile.get("fine_tuning", [])),
        }
    )

    warnings = [
        "Broadband metrics alone cannot prove that EQ or compression will improve the mix.",
        "Gain reduction must be measured from the running plugin or a rendered signal.",
        "Perceptual approval is still required.",
    ]
    if source_kind == "suno_stems":
        warnings.insert(
            0,
            "This Suno stem may already contain EQ and dynamics; do not process it by routine.",
        )

    identity_payload = {
        "source_sha256": metrics.get("sha256"),
        "role": role,
        "source_kind": source_kind,
        "knowledge": knowledge,
        "chain": chain,
    }
    proposal_id = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_processing_proposal",
        "proposal_id": proposal_id,
        "execute": False,
        "review_status": "user_approval_required",
        "source": {
            "file_name": metrics.get("file_name"),
            "file_path": metrics.get("file_path"),
            "sha256": metrics.get("sha256"),
            "role": role,
            "source_kind": source_kind,
        },
        "observations": {
            "integrated_lufs": integrated_lufs,
            "sample_peak_dbfs": sample_peak_dbfs,
            "rms_dbfs": metrics.get("rms_dbfs"),
            "crest_factor_db": crest_factor_db,
            "samples_at_or_above_0_dbfs": metrics.get("samples_at_or_above_0_dbfs"),
            "stereo_correlation": metrics.get("stereo_correlation"),
        },
        "knowledge": knowledge,
        "chain": chain,
        "warnings": warnings,
        "verification_plan": {
            "state": "re-read FX identity, GUID, enabled state and every requested parameter",
            "signal": "measure actual gain reduction or render an objective A/B",
            "perceptual": "compare enabled and bypass at similar perceived loudness",
        },
    }


def propose_track_processing(
    audio_path: Path,
    role: TrackRole,
    source_kind: SourceKind = "unknown",
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Analyze one WAV and return a proposal without writing or touching REAPER."""

    return build_processing_proposal(
        analyze_audio_file(Path(audio_path)),
        role,
        source_kind,
        knowledge_root=knowledge_root,
    )


def build_processing_application_payload(
    proposal: Mapping[str, Any],
    approved_proposal_id: str,
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind an approved proposal to explicit FX identities for one transaction."""

    observed_id = proposal.get("proposal_id")
    if not isinstance(observed_id, str) or approved_proposal_id != observed_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("execute") is not False:
        raise ValueError("only a non-executing proposal can be approved")
    source = proposal.get("source")
    chain = proposal.get("chain")
    if not isinstance(source, dict) or not isinstance(chain, list) or not chain:
        raise ValueError("proposal is missing source or chain data")

    binding_by_processor: dict[str, Mapping[str, Any]] = {}
    for binding in bindings:
        processor = binding.get("processor")
        if processor not in {"reaeq", "reacomp"}:
            raise ValueError(f"unsupported processor binding: {processor}")
        if processor in binding_by_processor:
            raise ValueError(f"duplicate processor binding: {processor}")
        fx_guid = binding.get("fx_guid")
        if fx_guid is not None and (not isinstance(fx_guid, str) or not fx_guid.strip()):
            raise ValueError(f"invalid fx_guid binding for {processor}")
        binding_by_processor[processor] = binding

    expected_processors = [step.get("processor") for step in chain]
    if set(binding_by_processor) != set(expected_processors):
        raise ValueError("bindings must match every proposed processor exactly")

    steps = []
    for step in chain:
        processor = step["processor"]
        parameters = step.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"proposal step has no parameters: {processor}")
        fx_guid = binding_by_processor[processor].get("fx_guid")
        steps.append(
            {
                "processor": processor,
                "mode": "reuse_existing" if fx_guid else "create_new",
                "fx_guid": fx_guid,
                "parameters": dict(parameters),
            }
        )

    source_sha256 = source.get("sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("proposal source does not contain a SHA-256 identity")
    return {
        "proposal_id": approved_proposal_id,
        "source_sha256": source_sha256,
        "steps": steps,
    }
