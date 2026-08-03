"""Source-aware, non-executing diagnosis across all song stems."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .media_discovery import WORKSPACE_ROOT
from .song_preparation import SongPreparationConfig, build_song_manifest


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]
BAND_ORDER = (
    "sub_bass_20_60",
    "bass_60_250",
    "low_mid_250_500",
    "mid_500_2000",
    "presence_2000_5000",
    "sibilance_5000_10000",
    "air_10000_20000",
)


def _load_policy(knowledge_root: Path) -> dict[str, Any]:
    import yaml

    path = knowledge_root / "workflow" / "source-aware-diagnosis.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("source-aware diagnosis knowledge must be an object")
    for field in ("id", "policies", "thresholds", "limitations", "confidence"):
        if field not in policy:
            raise ValueError(f"source-aware diagnosis knowledge is missing {field}")
    return policy


def _finding(
    identifier: str,
    severity: str,
    confidence: str,
    observation: str,
    implication: str,
    suggested_action: str,
    *,
    automatically_actionable: bool = False,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "severity": severity,
        "confidence": confidence,
        "observation": observation,
        "implication": implication,
        "suggested_action": suggested_action,
        "automatically_actionable": automatically_actionable,
    }


def _stem_findings(
    stem: Mapping[str, Any], source_kind: SourceKind, thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    audio = stem["audio"]
    role = stem["role"]
    findings: list[dict[str, Any]] = []
    clipped = int(audio.get("samples_at_or_above_0_dbfs") or 0)
    if clipped:
        findings.append(
            _finding(
                "signal.clipping",
                "high",
                "high",
                f"{clipped} samples are at or above 0 dBFS.",
                "The source contains objective clipping or over-range samples.",
                "Inspect the source export; prefer a clean re-export or re-recording.",
            )
        )
    dc = max((abs(float(value)) for value in audio.get("dc_offset", [])), default=0.0)
    if dc >= float(thresholds["dc_offset_absolute"]):
        findings.append(
            _finding(
                "signal.dc_offset",
                "medium",
                "high",
                f"Absolute DC offset reaches {dc:.5f}.",
                "DC can consume headroom and bias later processing.",
                "Audition a DC-removal filter and verify the rendered result.",
            )
        )
    correlation = audio.get("stereo_correlation")
    if isinstance(correlation, (int, float)) and correlation < float(
        thresholds["stereo_correlation_mono_risk"]
    ):
        findings.append(
            _finding(
                "stereo.negative_correlation",
                "medium",
                "medium",
                f"Stereo correlation is {correlation:.3f}.",
                "The stem may lose energy or change timbre when summed to mono.",
                "Render a mono check before narrowing or changing the stereo image.",
            )
        )
    spread = audio.get("active_rms_spread_db")
    if isinstance(spread, (int, float)):
        if source_kind == "organic_multitrack" and spread >= float(
            thresholds["organic_active_rms_spread_wide_db"]
        ):
            findings.append(
                _finding(
                    "dynamics.wide_organic_performance",
                    "medium",
                    "medium",
                    f"Active RMS p90-p10 spread is {spread:.2f} dB.",
                    "The organic performance has wide level variation.",
                    "Evaluate clip gain or automation before gentle compression.",
                )
            )
        elif source_kind == "suno_stems" and spread <= float(
            thresholds["active_rms_spread_already_controlled_db"]
        ):
            findings.append(
                _finding(
                    "dynamics.already_controlled_suno",
                    "info",
                    "medium",
                    f"Active RMS p90-p10 spread is only {spread:.2f} dB.",
                    "The generated stem may already have controlled dynamics.",
                    "Do not add compression without a specific audible reason.",
                )
            )
    low_ratio = audio.get("low_frequency_ratio_below_100_hz_p95")
    if role in {"lead_vocal", "backing_vocals"} and isinstance(
        low_ratio, (int, float)
    ) and low_ratio >= float(thresholds["vocal_low_frequency_ratio_p95"]):
        findings.append(
            _finding(
                "spectrum.vocal_low_frequency_candidate",
                "low",
                "medium",
                f"95th-percentile energy ratio below 100 Hz is {low_ratio:.3f}.",
                "Some vocal frames contain substantial very-low-frequency energy.",
                "Audition a conservative high-pass filter; reject it if body is lost.",
            )
        )
    sibilance = audio.get("sibilance_ratio_p95")
    if role in {"lead_vocal", "backing_vocals"} and isinstance(
        sibilance, (int, float)
    ) and sibilance >= float(thresholds["vocal_sibilance_ratio_p95"]):
        findings.append(
            _finding(
                "spectrum.vocal_sibilance_candidate",
                "low",
                "medium",
                f"95th-percentile 5-10 kHz ratio is {sibilance:.3f}.",
                "Some frames concentrate energy in the common sibilance region.",
                "Listen for harsh consonants before proposing de-essing.",
            )
        )
    bands = audio.get("spectral_band_energy_ratio", {})
    if isinstance(bands, Mapping):
        eligible_tonal_roles = {
            "lead_vocal", "backing_vocals", "guitar", "strings", "keys", "synth"
        }
        sub_ratio = bands.get("sub_bass_20_60", 0.0)
        bass_ratio = bands.get("bass_60_250", 0.0)
        low_end = (
            float(sub_ratio) + float(bass_ratio)
            if isinstance(sub_ratio, (int, float))
            and isinstance(bass_ratio, (int, float))
            else 0.0
        )
        if (
            role in eligible_tonal_roles
            and low_end >= float(thresholds["non_bass_low_end_ratio"])
        ):
            findings.append(
                _finding(
                    "spectrum.low_end_concentration_candidate",
                    "low",
                    "low",
                    f"Average 20-250 Hz energy ratio is {low_end:.3f}.",
                    "The stem has broad low-end concentration for its inferred role.",
                    "Confirm the role and audition EQ; do not infer muddiness from this metric alone.",
                )
            )
        raw_presence = bands.get("presence_2000_5000", 0.0)
        presence = float(raw_presence) if isinstance(raw_presence, (int, float)) else 0.0
        if (
            role in eligible_tonal_roles
            and presence >= float(thresholds["presence_band_ratio"])
        ):
            findings.append(
                _finding(
                    "spectrum.presence_concentration_candidate",
                    "low",
                    "low",
                    f"Average 2-5 kHz energy ratio is {presence:.3f}.",
                    "The stem concentrates energy in a band often associated with presence or hardness.",
                    "Run time-varying resonance analysis before considering dynamic control.",
                )
            )
    quiet_ratio = audio.get("quiet_block_ratio_below_minus_40_dbfs")
    quiet_floor = audio.get("quiet_rms_dbfs_p90_below_minus_40")
    active_p90 = audio.get("active_rms_dbfs_p90")
    quiet_metrics_present = all(
        isinstance(value, (int, float))
        for value in (quiet_ratio, quiet_floor, active_p90)
    )
    quiet_gap = (
        float(active_p90) - float(quiet_floor) if quiet_metrics_present else 0.0
    )
    if (
        source_kind == "organic_multitrack"
        and role in {"lead_vocal", "guitar"}
        and quiet_metrics_present
        and float(quiet_ratio) >= float(thresholds["organic_quiet_block_ratio"])
        and quiet_gap >= float(thresholds["minimum_quiet_active_gap_db"])
    ):
        findings.append(
            _finding(
                "capture.quiet_floor_candidate",
                "low",
                "medium",
                f"Quiet blocks occupy {float(quiet_ratio):.1%} with a {quiet_gap:.1f} dB active gap.",
                "The recording exposes separated quiet passages that may contain room or equipment noise.",
                "Inspect the quiet passages, then audition a conservative gate only if noise is audible.",
            )
        )
    return findings


def _spectral_vector(stem: Mapping[str, Any]) -> list[float]:
    bands = stem["audio"].get("spectral_band_energy_ratio", {})
    return [float(bands.get(name, 0.0)) for name in BAND_ORDER]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _relationships(stems: Sequence[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    hashes: dict[str, list[str]] = defaultdict(list)
    for stem in stems:
        hashes[str(stem["audio"]["sha256"])].append(str(stem["suggested_track_name"]))
    duplicates = [names for names in hashes.values() if len(names) > 1]

    candidates = []
    for left_index, left in enumerate(stems):
        for right in stems[left_index + 1 :]:
            similarity = _cosine(_spectral_vector(left), _spectral_vector(right))
            left_active = 1.0 - float(
                left["audio"].get("near_silence_ratio_below_minus_60_dbfs", 0.0)
            )
            right_active = 1.0 - float(
                right["audio"].get("near_silence_ratio_below_minus_60_dbfs", 0.0)
            )
            priority = similarity * math.sqrt(max(0.0, left_active * right_active))
            if priority >= threshold:
                candidates.append(
                    {
                        "tracks": [left["suggested_track_name"], right["suggested_track_name"]],
                        "spectral_similarity": round(similarity, 4),
                        "priority_score": round(priority, 4),
                        "confidence": "low_candidate_only",
                        "interpretation": (
                            "Similar average spectra and activity make this pair worth checking; "
                            "this does not prove perceptual masking."
                        ),
                    }
                )
    candidates.sort(key=lambda item: (-item["priority_score"], item["tracks"]))
    return {
        "exact_duplicate_groups": duplicates,
        "spectral_overlap_candidates": candidates[:10],
    }


def build_song_diagnosis(
    manifest: Mapping[str, Any],
    default_source_kind: SourceKind,
    source_overrides: Sequence[Mapping[str, str]] = (),
    *,
    knowledge_root: Path | None = None,
) -> dict[str, Any]:
    """Build a diagnosis from a fresh signal manifest without applying changes."""

    root = (knowledge_root or (WORKSPACE_ROOT / "knowledge")).resolve()
    policy = _load_policy(root)
    policies = policy["policies"]
    if default_source_kind not in policies:
        raise ValueError(f"unsupported default source kind: {default_source_kind}")
    stems = manifest.get("stems")
    if not isinstance(stems, list) or not stems:
        raise ValueError("manifest contains no stems")
    names = {str(stem["suggested_track_name"]) for stem in stems}
    overrides: dict[str, str] = {}
    for override in source_overrides:
        name = override.get("track_name")
        source_kind = override.get("source_kind")
        if name not in names:
            raise ValueError(f"source override track does not exist: {name}")
        if name in overrides:
            raise ValueError(f"duplicate source override: {name}")
        if source_kind not in policies:
            raise ValueError(f"unsupported source kind in override: {source_kind}")
        overrides[name] = source_kind

    diagnosed = []
    source_counts: Counter[str] = Counter()
    finding_counts: Counter[str] = Counter()
    for stem in stems:
        name = str(stem["suggested_track_name"])
        source_kind = overrides.get(name, default_source_kind)
        source_counts[source_kind] += 1
        findings = _stem_findings(stem, source_kind, policy["thresholds"])
        finding_counts.update(finding["severity"] for finding in findings)
        diagnosed.append(
            {
                "track_name": name,
                "role": stem["role"],
                "source_kind": source_kind,
                "policy": dict(policies[source_kind]),
                "audio_identity": {
                    "file_path": stem["audio"]["file_path"],
                    "sha256": stem["audio"]["sha256"],
                },
                "observations": {
                    key: stem["audio"].get(key)
                    for key in (
                        "integrated_lufs",
                        "sample_peak_dbfs",
                        "crest_factor_db",
                        "active_rms_spread_db",
                        "stereo_correlation",
                        "spectral_centroid_hz",
                        "sibilance_ratio_p95",
                        "low_frequency_ratio_below_100_hz_p95",
                        "quiet_block_ratio_below_minus_40_dbfs",
                        "quiet_rms_dbfs_p90_below_minus_40",
                        "active_rms_dbfs_p90",
                        "spectral_band_energy_ratio",
                    )
                },
                "findings": findings,
            }
        )

    relationships = _relationships(
        stems, float(policy["thresholds"]["spectral_relationship_priority_score"])
    )
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_song_diagnosis",
        "execute": False,
        "song": dict(manifest.get("song", {})),
        "source_model": {
            "default": default_source_kind,
            "overrides": dict(overrides),
            "counts": dict(source_counts),
        },
        "knowledge": {
            "id": policy["id"],
            "confidence": policy["confidence"],
            "reviewed_at": str(policy.get("reviewed_at", "")),
        },
        "summary": {
            "stem_count": len(diagnosed),
            "finding_counts_by_severity": dict(finding_counts),
            "exact_duplicate_group_count": len(relationships["exact_duplicate_groups"]),
            "spectral_overlap_candidate_count": len(
                relationships["spectral_overlap_candidates"]
            ),
        },
        "stems": diagnosed,
        "relationships": relationships,
        "limitations": list(policy["limitations"]),
        "verification": {
            "state_verified": False,
            "signal_verified": True,
            "perceptually_evaluated": False,
            "note": "Signal observations were computed offline; no DAW state was changed.",
        },
    }


def diagnose_song(
    song_name: str,
    bpm: float,
    default_source_kind: SourceKind,
    source_overrides: Sequence[Mapping[str, str]] = (),
    *,
    knowledge_root: Path | None = None,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Reanalyze all stems and build a source-aware diagnosis without writing."""

    manifest = build_song_manifest(
        song_name,
        SongPreparationConfig(
            bpm=bpm,
            source_kind=default_source_kind,
            analysis_level="signal",
        ),
        workspace_root=workspace_root,
    )
    return build_song_diagnosis(
        manifest,
        default_source_kind,
        source_overrides,
        knowledge_root=knowledge_root,
    )
