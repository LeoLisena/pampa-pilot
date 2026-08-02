"""Prueba reversible contra el puente ejecutándose dentro de REAPER."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pampapilot.bridge_client import BridgeClient


def normalized(path: str | Path) -> Path:
    return Path(path).resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--ipc-root", type=Path, required=True)
    args = parser.parse_args()

    expected_project = normalized(args.project)
    client = BridgeClient(args.ipc_root, timeout_seconds=5)
    health = client.call("health_check").result
    actual_project = normalized(str(health["project_path"]))
    if actual_project != expected_project:
        raise RuntimeError(
            f"prueba abortada: REAPER tiene otro proyecto activo: {actual_project}"
        )

    project_ref = str(health["project_ref"])
    before = client.call("get_project_state").result
    before_guids = {track["guid"] for track in before["tracks"]}
    transactions: list[str] = []
    created_guid: str | None = None

    try:
        created = client.call(
            "create_track",
            {"project_ref": project_ref, "name": "Codex POC - prueba reversible"},
        ).result
        transactions.append(str(created["transaction_request_id"]))
        created_guid = str(created["track"]["guid"])

        panned = client.call(
            "set_track_pan",
            {"project_ref": project_ref, "track_guid": created_guid, "pan": -0.35},
        ).result
        transactions.append(str(panned["transaction_request_id"]))
        if abs(float(panned["track"]["pan"]) - (-0.35)) > 0.000001:
            raise AssertionError("el paneo leído no coincide")

        reread = client.call(
            "get_track_state",
            {"project_ref": project_ref, "track_guid": created_guid},
        ).result
        if abs(float(reread["track"]["pan"]) - (-0.35)) > 0.000001:
            raise AssertionError("la segunda lectura del paneo no coincide")
    finally:
        while transactions:
            transaction_id = transactions.pop()
            client.call(
                "undo_transaction",
                {
                    "project_ref": project_ref,
                    "transaction_request_id": transaction_id,
                },
            )

    after = client.call("get_project_state").result
    after_guids = {track["guid"] for track in after["tracks"]}
    if after_guids != before_guids:
        raise AssertionError("el proyecto no volvió a su estructura inicial")

    report: dict[str, Any] = {
        "ok": True,
        "reaper_version": health["reaper_version"],
        "bridge_version": health["bridge_version"],
        "created_track_guid": created_guid,
        "pan_verified": -0.35,
        "undo_verified": True,
        "final_track_count": after["track_count"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
