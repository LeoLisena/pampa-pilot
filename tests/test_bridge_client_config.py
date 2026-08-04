from __future__ import annotations

import json
from pathlib import Path

import pampapilot.bridge_client as bridge_client


def test_worktree_uses_installed_reaper_bridge_config(
    tmp_path: Path, monkeypatch
) -> None:
    workspace_module = (
        tmp_path / "worktree" / "src" / "pampapilot" / "bridge_client.py"
    )
    appdata = tmp_path / "appdata"
    installed_config = (
        appdata
        / "REAPER"
        / "Scripts"
        / "PampaPilot"
        / "bridge_config.local.json"
    )
    expected_ipc = tmp_path / "canonical" / ".runtime" / "reaper-ipc"
    installed_config.parent.mkdir(parents=True)
    installed_config.write_text(
        json.dumps({"ipc_root": str(expected_ipc)}), encoding="utf-8"
    )

    monkeypatch.delenv("PAMPAPILOT_IPC_ROOT", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(bridge_client, "__file__", str(workspace_module))

    assert bridge_client.default_ipc_root() == expected_ipc.resolve()


def test_environment_ipc_root_has_priority(tmp_path: Path, monkeypatch) -> None:
    expected_ipc = tmp_path / "explicit-ipc"
    monkeypatch.setenv("PAMPAPILOT_IPC_ROOT", str(expected_ipc))

    assert bridge_client.default_ipc_root() == expected_ipc.resolve()
