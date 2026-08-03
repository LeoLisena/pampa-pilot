from __future__ import annotations

from pampapilot.problem_routing import route_stem_findings


def test_routes_findings_by_priority_without_executing() -> None:
    routes = route_stem_findings(
        [
            {"id": "spectrum.vocal_sibilance_candidate"},
            {"id": "signal.clipping"},
            {"id": "spectrum.vocal_sibilance_candidate"},
        ],
        "organic_multitrack",
    )

    assert [route["finding_id"] for route in routes] == [
        "signal.clipping",
        "spectrum.vocal_sibilance_candidate",
    ]
    assert routes[0]["processor"] is None
    assert routes[1]["processor"] == "deesser"
    assert all(route["execute"] is False for route in routes)


def test_suno_route_requires_observed_defect_posture() -> None:
    route = route_stem_findings(
        [{"id": "spectrum.presence_concentration_candidate"}], "suno_stems"
    )[0]
    assert route["source_posture"] == "correct_observed_defect_only"
    assert route["next_stage"] == "preview_dynamic_resonance_proposal"
