"""Conservative, optional track-volume automation from approved song sections."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping, Sequence


TrackRole = Literal[
    "lead_vocal",
    "backing_vocals",
    "drums",
    "percussion",
    "bass",
    "guitar",
    "strings",
    "keys",
    "synth",
]
SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_SOURCE_SCALE = {
    "suno_stems": 0.50,
    "organic_multitrack": 1.00,
    "unknown": 0.65,
}

# These are relative artistic moves, not loudness targets.  Zero is deliberately
# the common case: section automation should support a mix, not remix it blindly.
_SECTION_MOVES_DB: dict[str, dict[str, float]] = {
    "intro": {"lead_vocal": -0.20, "backing_vocals": -0.20},
    "pre_chorus": {
        "lead_vocal": 0.10,
        "backing_vocals": 0.10,
        "drums": 0.15,
        "percussion": 0.10,
        "bass": 0.10,
        "guitar": 0.10,
        "strings": 0.10,
        "keys": 0.10,
        "synth": 0.10,
    },
    "chorus": {
        "lead_vocal": 0.25,
        "backing_vocals": 0.50,
        "drums": 0.40,
        "percussion": 0.25,
        "bass": 0.20,
        "guitar": 0.25,
        "strings": 0.25,
        "keys": 0.20,
        "synth": 0.20,
    },
    "final_chorus": {
        "lead_vocal": 0.30,
        "backing_vocals": 0.60,
        "drums": 0.50,
        "percussion": 0.30,
        "bass": 0.20,
        "guitar": 0.30,
        "strings": 0.30,
        "keys": 0.25,
        "synth": 0.25,
    },
    "outro": {
        "lead_vocal": -0.10,
        "backing_vocals": -0.20,
        "drums": -0.20,
        "percussion": -0.15,
    },
}


def _normalized_regions(regions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if len(regions) < 2:
        raise ValueError("at least two approved song sections are required")
    normalized: list[dict[str, Any]] = []
    previous_end: float | None = None
    for raw in regions:
        kind = str(raw.get("kind", "")).strip().lower()
        label = str(raw.get("label", kind)).strip()
        start = float(raw["start_seconds"])
        end = float(raw["end_seconds"])
        if not kind or not label or start < 0.0 or end <= start:
            raise ValueError("every region needs a valid kind, label, start and end")
        if previous_end is not None and abs(start - previous_end) > 0.002:
            raise ValueError("approved regions must be ordered and contiguous")
        normalized.append(
            {"kind": kind, "label": label, "start_seconds": start, "end_seconds": end}
        )
        previous_end = end
    return normalized


def _points_for_gains(
    regions: Sequence[Mapping[str, Any]], gains: Sequence[float], ramp_seconds: float
) -> list[dict[str, float | int]]:
    points: list[dict[str, float | int]] = [
        {
            "project_time_seconds": round(float(regions[0]["start_seconds"]), 6),
            "gain_db": round(float(gains[0]), 2),
            "shape": 0,
            "tension": 0.0,
        }
    ]
    for index in range(1, len(regions)):
        previous_gain, gain = float(gains[index - 1]), float(gains[index])
        if abs(previous_gain - gain) < 0.005:
            continue
        boundary = float(regions[index]["start_seconds"])
        left_room = boundary - float(regions[index - 1]["start_seconds"])
        right_room = float(regions[index]["end_seconds"]) - boundary
        half_ramp = min(ramp_seconds / 2.0, left_room / 4.0, right_room / 4.0)
        points.extend(
            [
                {
                    "project_time_seconds": round(boundary - half_ramp, 6),
                    "gain_db": round(previous_gain, 2),
                    "shape": 0,
                    "tension": 0.0,
                },
                {
                    "project_time_seconds": round(boundary + half_ramp, 6),
                    "gain_db": round(gain, 2),
                    "shape": 0,
                    "tension": 0.0,
                },
            ]
        )
    end = float(regions[-1]["end_seconds"])
    last_gain = float(gains[-1])
    if abs(last_gain) >= 0.005:
        last_start = float(regions[-1]["start_seconds"])
        half_ramp = min(ramp_seconds / 2.0, (end - last_start) / 4.0)
        points.append(
            {
                "project_time_seconds": round(end - half_ramp, 6),
                "gain_db": round(last_gain, 2),
                "shape": 0,
                "tension": 0.0,
            }
        )
        last_gain = 0.0
    points.append(
        {
            "project_time_seconds": round(end, 6),
            "gain_db": round(last_gain, 2),
            "shape": 0,
            "tension": 0.0,
        }
    )
    return points


def build_section_volume_proposal(
    regions: Sequence[Mapping[str, Any]],
    role: TrackRole,
    source_kind: SourceKind,
    *,
    ramp_seconds: float = 0.10,
) -> dict[str, Any]:
    """Return an audition-only relative-volume plan; never touch REAPER."""

    if source_kind not in _SOURCE_SCALE:
        raise ValueError("unsupported source kind")
    if not 0.02 <= ramp_seconds <= 2.0:
        raise ValueError("ramp_seconds must be between 0.02 and 2.0")
    normalized = _normalized_regions(regions)
    scale = _SOURCE_SCALE[source_kind]
    gains = [
        round(_SECTION_MOVES_DB.get(region["kind"], {}).get(role, 0.0) * scale, 2)
        for region in normalized
    ]
    maximum = 0.50 if source_kind == "suno_stems" else 0.75
    gains = [max(-maximum, min(maximum, gain)) for gain in gains]
    points = _points_for_gains(normalized, gains, ramp_seconds)
    section_moves = [
        {
            **region,
            "relative_gain_db": gain,
            "changed": abs(gain) >= 0.05,
        }
        for region, gain in zip(normalized, gains)
    ]
    identity = json.dumps(
        {
            "regions": normalized,
            "role": role,
            "source_kind": source_kind,
            "ramp_seconds": ramp_seconds,
            "points": points,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    changed_count = sum(section["changed"] for section in section_moves)
    return {
        "kind": "pampapilot_section_volume_proposal",
        "proposal_id": hashlib.sha256(identity).hexdigest()[:24],
        "status": "optional_audition" if changed_count else "not_needed",
        "enabled_by_default": False,
        "role": role,
        "source_kind": source_kind,
        "maximum_absolute_move_db": maximum,
        "ramp_seconds": ramp_seconds,
        "changed_section_count": changed_count,
        "sections": section_moves,
        "envelope_points": points,
        "reason": (
            "Subtle role-aware section moves; Suno stems use half strength because "
            "their internal balance is already processed."
        ),
        "verification": {
            "state": "application must reread every envelope point",
            "signal": "rendered A/B should be loudness matched",
            "perceptual": "keep only if transitions and section energy improve",
        },
    }


def build_section_volume_application_payload(
    proposal: Mapping[str, Any], approved_proposal_id: str
) -> dict[str, Any]:
    """Bind application to the exact preview accepted by the user."""

    if proposal.get("proposal_id") != approved_proposal_id:
        raise ValueError("approved_proposal_id does not match the current proposal")
    if proposal.get("status") != "optional_audition":
        raise ValueError("proposal has no useful section moves to apply")
    return {
        "proposal_id": approved_proposal_id,
        "points": list(proposal["envelope_points"]),
    }
