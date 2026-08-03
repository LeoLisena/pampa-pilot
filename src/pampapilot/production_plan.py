"""Join offline song diagnosis with verified REAPER state."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _canonical_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _plan_item(
    identifier: str,
    priority: str,
    status: str,
    tracks: list[dict[str, Any]],
    evidence: Any,
    recommendation: str,
    *,
    executable_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "priority": priority,
        "status": status,
        "tracks": tracks,
        "evidence": evidence,
        "recommendation": recommendation,
        "executable_action": executable_action,
    }


def _track_reference(track: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": track["name"],
        "guid": track["guid"],
        "muted": bool(track["muted"]),
        "solo": int(track["solo"]),
        "volume_db": float(track["volume_db"]),
        "pan": float(track["pan"]),
        "fx_count": int(track["fx_count"]),
    }


def _bind_tracks(
    diagnosed_stems: list[Mapping[str, Any]], project_tracks: list[Mapping[str, Any]]
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]], set[str]]:
    project_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for track in project_tracks:
        project_by_name.setdefault(_canonical_name(str(track["name"])), []).append(track)
    bindings: dict[str, Mapping[str, Any]] = {}
    issues = []
    used_guids: set[str] = set()
    for stem in diagnosed_stems:
        name = str(stem["track_name"])
        matches = project_by_name.get(_canonical_name(name), [])
        if len(matches) == 1:
            bindings[name] = matches[0]
            used_guids.add(str(matches[0]["guid"]))
        elif not matches:
            issues.append(
                _plan_item(
                    "binding.missing_track",
                    "high",
                    "blocked",
                    [{"name": name, "guid": None}],
                    "No REAPER track matches the diagnosed stem name.",
                    "Bind or import the stem before planning processing.",
                )
            )
        else:
            issues.append(
                _plan_item(
                    "binding.ambiguous_track",
                    "high",
                    "blocked",
                    [_track_reference(track) for track in matches],
                    f"Multiple REAPER tracks match {name!r}.",
                    "Select the intended track by GUID.",
                )
            )
    return bindings, issues, used_guids


def build_production_plan(
    diagnosis: Mapping[str, Any],
    project_state: Mapping[str, Any],
    track_details: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a read-only producer plan tied to the current REAPER state."""

    if diagnosis.get("execute") is not False:
        raise ValueError("diagnosis must be non-executing")
    diagnosed_stems = diagnosis.get("stems")
    project_tracks = project_state.get("tracks")
    if not isinstance(diagnosed_stems, list) or not isinstance(project_tracks, list):
        raise ValueError("diagnosis or project state has no tracks")
    project_ref = project_state.get("project_ref")
    if not isinstance(project_ref, str) or not project_ref:
        raise ValueError("project state has no project_ref")
    details = track_details or {}
    bindings, items, used_guids = _bind_tracks(diagnosed_stems, project_tracks)

    for track in project_tracks:
        reference = _track_reference(track)
        if int(track["solo"]) != 0:
            items.append(
                _plan_item(
                    "project.active_solo",
                    "high",
                    "action_required",
                    [reference],
                    "A track is soloed, so normal full-mix evaluation is not possible.",
                    "Clear solo before judging balance or processing.",
                    executable_action={"action": "set_track_solo", "supported": False},
                )
            )
        if str(track["guid"]) not in used_guids:
            priority = "medium" if not bool(track["muted"]) else "info"
            status = "review_required" if not bool(track["muted"]) else "inactive_extra_track"
            items.append(
                _plan_item(
                    "project.unmanaged_track",
                    priority,
                    status,
                    [reference],
                    "The REAPER track is not represented by a diagnosed audio stem.",
                    (
                        "Mute, remove, or explicitly classify this track before evaluating the mix."
                        if not bool(track["muted"])
                        else "No action while the extra track remains muted."
                    ),
                )
            )

    severity_to_priority = {"high": "high", "medium": "medium", "low": "low", "info": "info"}
    for stem in diagnosed_stems:
        track = bindings.get(str(stem["track_name"]))
        if track is None:
            continue
        reference = _track_reference(track)
        for finding in stem.get("findings", []):
            muted = bool(track["muted"])
            items.append(
                _plan_item(
                    str(finding["id"]),
                    "info" if muted else severity_to_priority[str(finding["severity"])],
                    "deferred_track_muted" if muted else "review_required",
                    [reference],
                    {
                        "signal_observation": finding["observation"],
                        "confidence": finding["confidence"],
                        "source_kind": stem["source_kind"],
                    },
                    str(finding["suggested_action"]),
                )
            )

    for group in diagnosis.get("relationships", {}).get("exact_duplicate_groups", []):
        tracks = [bindings[name] for name in group if name in bindings]
        if len(tracks) < 2:
            continue
        active = [track for track in tracks if not bool(track["muted"])]
        resolved = len(active) <= 1
        items.append(
            _plan_item(
                "relationship.exact_duplicate",
                "info" if resolved else "high",
                "resolved_by_mute" if resolved else "action_required",
                [_track_reference(track) for track in tracks],
                "The diagnosed WAV files have the same SHA-256 identity.",
                (
                    "Keep only the selected version active."
                    if resolved
                    else "Mute all but one duplicate before summing the mix."
                ),
            )
        )

    for candidate in diagnosis.get("relationships", {}).get(
        "spectral_overlap_candidates", []
    ):
        names = candidate.get("tracks", [])
        tracks = [bindings[name] for name in names if name in bindings]
        if len(tracks) != 2:
            continue
        resolved = any(bool(track["muted"]) for track in tracks)
        items.append(
            _plan_item(
                "relationship.spectral_overlap_candidate",
                "info" if resolved else "low",
                "resolved_in_current_mix" if resolved else "review_required",
                [_track_reference(track) for track in tracks],
                {
                    "spectral_similarity": candidate["spectral_similarity"],
                    "priority_score": candidate["priority_score"],
                    "confidence": candidate["confidence"],
                },
                (
                    "No action while one candidate track remains muted."
                    if resolved
                    else "Listen in context before considering level, arrangement, or EQ changes."
                ),
            )
        )

    contexts = []
    for stem in diagnosed_stems:
        track = bindings.get(str(stem["track_name"]))
        if track is None:
            continue
        detail = details.get(str(track["guid"]), {})
        contexts.append(
            {
                "track_name": stem["track_name"],
                "track_guid": track["guid"],
                "role": stem["role"],
                "source_kind": stem["source_kind"],
                "state": _track_reference(track),
                "fx": [
                    {
                        "guid": fx["guid"],
                        "name": fx["name"],
                        "enabled": fx["enabled"],
                        "offline": fx["offline"],
                    }
                    for fx in detail.get("fx", [])
                ],
            }
        )

    items.sort(
        key=lambda item: (
            PRIORITY_ORDER[item["priority"]],
            item["id"],
            [track["name"] for track in item["tracks"]],
        )
    )
    priority_counts = Counter(item["priority"] for item in items)
    status_counts = Counter(item["status"] for item in items)
    identity = {
        "project_ref": project_ref,
        "project_state_change_count": project_state.get("project_state_change_count"),
        "audio_hashes": [stem["audio_identity"]["sha256"] for stem in diagnosed_stems],
        "items": items,
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_production_plan",
        "plan_id": plan_id,
        "execute": False,
        "project": {
            "project_ref": project_ref,
            "project_path": project_state.get("project_path"),
            "tempo_bpm": project_state.get("tempo_bpm"),
            "project_state_change_count": project_state.get("project_state_change_count"),
        },
        "summary": {
            "bound_stem_count": len(bindings),
            "project_track_count": len(project_tracks),
            "item_count": len(items),
            "priority_counts": dict(priority_counts),
            "status_counts": dict(status_counts),
        },
        "constraints": [
            "Suno stems are not processed by routine.",
            "Low-confidence spectral relationships require contextual listening.",
            "No action may target a track by visible index.",
        ],
        "track_contexts": contexts,
        "items": items,
        "verification": {
            "state_verified": True,
            "signal_verified": bool(
                diagnosis.get("verification", {}).get("signal_verified")
            ),
            "perceptually_evaluated": False,
        },
    }


def build_listening_preparation_payload(
    plan: Mapping[str, Any], approved_plan_id: str
) -> dict[str, Any]:
    """Derive only safe listening-state changes from an approved current plan."""

    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or approved_plan_id != plan_id:
        raise ValueError("approved_plan_id does not match the current production plan")
    if plan.get("execute") is not False:
        raise ValueError("only a non-executing production plan can be approved")
    items = plan.get("items")
    if not isinstance(items, list):
        raise ValueError("production plan has no items")

    clear_solo: set[str] = set()
    mute: set[str] = set()
    for item in items:
        if item.get("id") == "project.active_solo" and item.get("status") == "action_required":
            clear_solo.update(
                str(track["guid"])
                for track in item.get("tracks", [])
                if track.get("guid")
            )
        if item.get("id") == "project.unmanaged_track" and item.get("status") == "review_required":
            mute.update(
                str(track["guid"])
                for track in item.get("tracks", [])
                if track.get("guid") and not track.get("muted")
            )
    if not clear_solo and not mute:
        raise ValueError("the approved plan contains no listening preparation changes")
    return {
        "plan_id": approved_plan_id,
        "clear_solo_track_guids": sorted(clear_solo),
        "mute_track_guids": sorted(mute),
    }
