"""Route diagnosed stem problems to reusable producer stages without executing them."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_ROUTES: dict[str, dict[str, Any]] = {
    "signal.clipping": {
        "category": "source_repair",
        "next_stage": "replace_or_reexport_source",
        "processor": None,
        "priority": 100,
        "reason": "A filter cannot restore samples already clipped in the source.",
    },
    "signal.dc_offset": {
        "category": "cleanup",
        "next_stage": "dc_removal_audition",
        "processor": "reaeq",
        "priority": 80,
        "reason": "A verified high-pass/DC-removal stage may recover headroom.",
    },
    "stereo.negative_correlation": {
        "category": "translation",
        "next_stage": "preview_mono_compatibility",
        "processor": None,
        "priority": 75,
        "reason": "Mono rendering must confirm a real cancellation problem first.",
    },
    "capture.quiet_floor_candidate": {
        "category": "cleanup",
        "next_stage": "preview_reagate_proposal",
        "processor": "reagate",
        "priority": 55,
        "reason": "Separated quiet and active passages can support a conservative gate audition.",
    },
    "spectrum.vocal_low_frequency_candidate": {
        "category": "tonal_balance",
        "next_stage": "propose_track_processing",
        "processor": "reaeq",
        "priority": 50,
        "reason": "A conservative high-pass audition can test whether low energy is unwanted.",
    },
    "spectrum.low_end_concentration_candidate": {
        "category": "tonal_balance",
        "next_stage": "propose_track_processing",
        "processor": "reaeq",
        "priority": 45,
        "reason": "Broad low-end concentration warrants an EQ audition, not an automatic cut.",
    },
    "spectrum.vocal_sibilance_candidate": {
        "category": "harshness",
        "next_stage": "preview_deesser_proposal",
        "processor": "deesser",
        "priority": 50,
        "reason": "The dedicated analyzer must confirm intermittent strong 5-10 kHz peaks.",
    },
    "spectrum.presence_concentration_candidate": {
        "category": "harshness",
        "next_stage": "preview_dynamic_resonance_proposal",
        "processor": "dynamic_resonance",
        "priority": 40,
        "reason": "A specialist can distinguish a time-varying prominence from normal timbre.",
    },
    "dynamics.wide_organic_performance": {
        "category": "dynamics",
        "next_stage": "preview_track_producer_chain",
        "processor": "reacomp",
        "priority": 45,
        "reason": "Automation or clip gain should be considered before gentle compression.",
    },
    "dynamics.already_controlled_suno": {
        "category": "preservation",
        "next_stage": "leave_unchanged",
        "processor": None,
        "priority": 5,
        "reason": "Narrow dynamics in a Suno stem is evidence against routine compression.",
    },
}


def route_stem_findings(
    findings: Sequence[Mapping[str, Any]], source_kind: str
) -> list[dict[str, Any]]:
    """Return deterministic follow-ups; never imply that a candidate is a defect."""

    routed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in findings:
        identifier = str(finding.get("id", ""))
        route = _ROUTES.get(identifier)
        if route is None or identifier in seen:
            continue
        seen.add(identifier)
        posture = (
            "correct_observed_defect_only"
            if source_kind == "suno_stems" and route["category"] != "preservation"
            else "supervised_audition"
        )
        routed.append(
            {
                "finding_id": identifier,
                **route,
                "source_posture": posture,
                "execute": False,
                "requires_perceptual_approval": route["next_stage"] != "leave_unchanged",
            }
        )
    return sorted(routed, key=lambda item: (-int(item["priority"]), item["finding_id"]))
