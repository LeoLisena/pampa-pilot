from pathlib import Path


BRIDGE_PATH = Path(__file__).parents[1] / "reaper" / "PampaPilot_Bridge.lua"


def test_static_mix_fields_are_independently_optional() -> None:
    source = BRIDGE_PATH.read_text(encoding="utf-8")
    block = source.split("function ACTIONS.apply_track_mix_batch", 1)[1].split(
        "function ACTIONS.", 1
    )[0]

    for field in ("volume_db", "pan", "muted", "soloed"):
        assert f"if item.{field} ~= nil then" in block
        assert f"item.{field} == nil" not in block
