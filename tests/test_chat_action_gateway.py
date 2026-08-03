from unittest.mock import patch

import pytest

from pampapilot.agent_context import parse_agent_response
from pampapilot.web_server import _build_chat_action_plan


def test_agent_parser_keeps_only_typed_chat_actions() -> None:
    response = parse_agent_response(
        '{"message":"Listo","proposal":null,"actions":['
        '{"kind":"static_mix","target":"1 Percussion","volume_delta_db":-2},'
        '{"kind":"static_mix","target":"10 Vocals","pan":-0.15},'
        '{"kind":"shell","command":"bad"}]}'
    )

    assert response["actions"] == [
        {"kind": "static_mix", "target": "1 Percussion", "volume_delta_db": -2},
        {"kind": "static_mix", "target": "10 Vocals", "pan": -0.15},
    ]


@patch("pampapilot.web_server._source_kind_for_stem", return_value="suno_stems")
@patch("pampapilot.web_server._stem_descriptor")
@patch("pampapilot.web_server.bridge_project")
@patch("pampapilot.web_server._project_view")
def test_compound_static_mix_is_resolved_into_one_absolute_batch(
    project_view, bridge_project, stem_descriptor, _source
) -> None:
    project_view.return_value = {
        "stems": [
            {"name": "1 Percussion", "track_name": "Percussion", "role": "percussion"},
            {"name": "10 Vocals", "track_name": "Vocals", "role": "lead_vocal"},
        ]
    }
    bridge_project.return_value = {
        "result": {
            "project_ref": "project.rpp",
            "tracks": [
                {"guid": "{PERC}", "name": "Percussion", "volume_db": -1.0},
                {"guid": "{VOX}", "name": "Vocals", "volume_db": 0.0},
            ],
        }
    }
    stem_descriptor.side_effect = lambda _project, name: {
        "name": name,
        "role": "percussion" if "Percussion" in name else "lead_vocal",
        "path": "unused.wav",
    }

    plan = _build_chat_action_plan(
        "Song",
        [
            {"kind": "static_mix", "target": "1 Percussion", "volume_delta_db": -2},
            {"kind": "static_mix", "target": "10 Vocals", "pan": -0.15},
        ],
    )

    assert plan["risk"] == "low"
    assert plan["operations"] == [
        {
            "kind": "static_mix",
            "items": [
                {"track_guid": "{PERC}", "volume_db": -3.0},
                {"track_guid": "{VOX}", "pan": -0.15},
            ],
            "targets": ["1 Percussion", "10 Vocals"],
        }
    ]


@patch("pampapilot.web_server._project_view")
def test_ambiguous_role_alias_is_rejected(project_view) -> None:
    project_view.return_value = {
        "stems": [
            {"name": "5 Drums", "track_name": "Drums 1", "role": "drums"},
            {"name": "7 Drums", "track_name": "Drums 2", "role": "drums"},
        ]
    }
    with patch("pampapilot.web_server.bridge_project") as bridge_project:
        bridge_project.return_value = {
            "result": {
                "project_ref": "project.rpp",
                "tracks": [
                    {"guid": "{A}", "name": "Drums 1", "volume_db": 0.0},
                    {"guid": "{B}", "name": "Drums 2", "volume_db": 0.0},
                ],
            }
        }
        with pytest.raises(ValueError, match="más de una pista"):
            _build_chat_action_plan(
                "Song", [{"kind": "static_mix", "target": "bateria", "muted": True}]
            )
