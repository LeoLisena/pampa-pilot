from pampapilot.agent_protocol import (
    AGENT_PROTOCOL_VERSION,
    context_envelope,
    error_envelope,
    normalize_actions,
    result_envelope,
)


def test_context_result_and_error_have_explicit_versions() -> None:
    assert context_envelope({"song": {}})["agent_protocol"] == {
        "name": "pampapilot-agent", "version": AGENT_PROTOCOL_VERSION,
        "message_type": "context",
    }
    assert result_envelope(status="ok", data={})["agent_protocol"]["message_type"] == "result"
    assert error_envelope("bridge.offline", "offline")["error"]["retryable"] is False


def test_action_normalization_is_a_closed_allowlist() -> None:
    actions = normalize_actions([
        {"kind": "static_mix", "target": "Bass", "pan": -0.2, "command": "bad"},
        {"kind": "request_evidence", "evidence_type": "fx_parameters", "target": "Bass"},
        {"kind": "request_evidence", "evidence_type": "secrets"},
        {"kind": "shell", "command": "bad"},
    ])
    assert actions == [
        {"kind": "static_mix", "target": "Bass", "pan": -0.2},
        {"kind": "request_evidence", "evidence_type": "fx_parameters", "target": "Bass"},
    ]
