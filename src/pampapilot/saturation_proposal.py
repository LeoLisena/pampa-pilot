"""Conservative, source-aware starting points for stock saturation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal


SourceKind = Literal["suno_stems", "organic_multitrack", "unknown"]

_PROFILES: dict[str, dict[str, float]] = {
    "suno_stems": {
        "drive_percent": 5.0,
        "muffle_percent": 0.0,
        "output_gain_db": -0.2,
    },
    "organic_multitrack": {
        "drive_percent": 12.0,
        "muffle_percent": 2.0,
        "output_gain_db": -0.6,
    },
    "unknown": {
        "drive_percent": 7.0,
        "muffle_percent": 1.0,
        "output_gain_db": -0.3,
    },
}


def propose_saturation(source_kind: SourceKind) -> dict[str, object]:
    """Return a restrained audition-only recipe; no signal is analyzed or changed."""

    if source_kind not in _PROFILES:
        raise ValueError("unsupported source kind")
    parameters = dict(_PROFILES[source_kind])
    identity = json.dumps(
        {"source_kind": source_kind, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "proposal_id": hashlib.sha256(identity).hexdigest()[:24],
        "status": "audition_only",
        "processor": "waveshaper",
        "plugin": "JS: Multi Waveshaper",
        "source_kind": source_kind,
        "parameters": parameters,
        "fixed_controls": {
            "processing": "stereo",
            "waveshaper": "type_1",
            "limiter": False,
            "oversample_x2": True,
        },
        "level_compensation": {
            "kind": "static_starting_point",
            "measured": False,
            "requires_loudness_matched_audition": True,
        },
        "reason": (
            "Suno already contains production processing, so the starting point is subtle."
            if source_kind == "suno_stems"
            else "Organic sources allow a wider but still conservative starting point."
            if source_kind == "organic_multitrack"
            else "Unknown sources use the more conservative neutral profile."
        ),
    }
