from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pampapilot.song_structure import (
    build_song_structure_proposal,
    build_structure_region_payload,
    parse_structured_lyrics,
)


def _write_audio(path: Path) -> None:
    sample_rate = 22_050
    sections = []
    for index, frequency in enumerate((220.0, 330.0, 440.0, 550.0)):
        time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
        sections.append((0.04 + index * 0.02) * np.sin(2 * np.pi * frequency * time))
    sf.write(path, np.concatenate(sections), sample_rate, subtype="PCM_24")


def test_parser_keeps_structure_and_separates_arrangement_notes(tmp_path: Path) -> None:
    path = tmp_path / "lyrics.txt"
    path.write_text(
        "[Intro]\n[Soft guitar]\n[Verse 1]\nHello world\n"
        "[Chorus]\nSol[Full band]\n[Outro]\nGoodbye\n",
        encoding="utf-8",
    )
    parsed = parse_structured_lyrics(path)

    assert [section["kind"] for section in parsed["sections"]] == [
        "intro", "verse", "chorus", "outro"
    ]
    assert parsed["sections"][0]["arrangement_notes"] == ["Soft guitar"]
    assert parsed["sections"][2]["lyrics_text"] == "Sol[Full band]"


def test_structure_proposal_is_contiguous_and_approval_bound(tmp_path: Path) -> None:
    audio, lyrics = tmp_path / "mix.wav", tmp_path / "lyrics.txt"
    _write_audio(audio)
    lyrics.write_text(
        "[Intro]\n[Verse 1]\nLine one\n[Chorus]\nLine two\n[Outro]\nEnd\n",
        encoding="utf-8",
    )
    proposal = build_song_structure_proposal(audio, lyrics, bpm=120.0)

    assert len(proposal["regions"]) == 4
    assert proposal["regions"][0]["start_seconds"] == 0.0
    assert proposal["regions"][-1]["end_seconds"] == pytest.approx(12.0)
    assert all(
        left["end_seconds"] == right["start_seconds"]
        for left, right in zip(proposal["regions"], proposal["regions"][1:])
    )
    payload = build_structure_region_payload(proposal, proposal["structure_id"])
    assert payload["regions"][1]["name"] == "\u200bVerse 1"
    assert payload["regions"][1]["display_name"] == "Verse 1"
    with pytest.raises(ValueError, match="does not match"):
        build_structure_region_payload(proposal, "0" * 24)


def test_vocal_stem_anchors_intro_end_to_first_sustained_voice(tmp_path: Path) -> None:
    audio, vocal, lyrics = tmp_path / "mix.wav", tmp_path / "vocal.wav", tmp_path / "lyrics.txt"
    sample_rate = 22_050
    duration = 20
    time = np.arange(sample_rate * duration, dtype=np.float64) / sample_rate
    sf.write(audio, 0.1 * np.sin(2 * np.pi * 220 * time), sample_rate)
    voice = np.zeros_like(time)
    voice[round(6.1 * sample_rate):] = 0.1 * np.sin(
        2 * np.pi * 330 * time[: len(voice) - round(6.1 * sample_rate)]
    )
    sf.write(vocal, voice, sample_rate)
    lyrics.write_text("[Intro]\n[Verse]\nHello\n[Chorus]\nWorld\n", encoding="utf-8")

    proposal = build_song_structure_proposal(audio, lyrics, bpm=120.0, vocal_path=vocal)

    assert proposal["timing_evidence"]["first_sustained_vocal_start_seconds"] == pytest.approx(6.1)
    assert proposal["regions"][0]["end_seconds"] == pytest.approx(6.0)
