from __future__ import annotations

from pathlib import Path
import json
import hashlib

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


def test_lyrics_quality_prefers_clean_repeated_sections_and_downgrades_damage(
    tmp_path: Path,
) -> None:
    clean, damaged = tmp_path / "clean.txt", tmp_path / "damaged.txt"
    clean.write_text(
        "[Verse 1]\nUna línea\n[Pre-Chorus]\nSube la voz\n"
        "[Chorus]\nSoltá mi sombra\n[Verse 2]\nOtra línea\n"
        "[Pre-Chorus]\nSube la voz\n[Chorus]\nSoltá mi sombra\n",
        encoding="utf-8",
    )
    damaged.write_text(
        "[Verse 1]\nUna línea\n[Pre-Chorus]\nSube la voz\n"
        "[Chorus]\nSol Sol sombrasombra [Full band]\n[Verse 2]\nOtra línea\n"
        "[Pre-Chorus]\nSube la voz\n[Chorus]\nvo zzz zzz cantarrrcantarrr\n",
        encoding="utf-8",
    )

    assert parse_structured_lyrics(clean)["quality"]["profile"] == "clean"
    damaged_quality = parse_structured_lyrics(damaged)["quality"]
    assert damaged_quality["profile"] != "clean"
    assert damaged_quality["overall_score"] < 0.85


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


def test_ensemble_uses_specialist_macro_anchors_and_repeated_pre_choruses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio, lyrics, specialist = (
        tmp_path / "mix.wav",
        tmp_path / "lyrics.txt",
        tmp_path / "specialist.json",
    )
    _write_audio(audio)
    lyrics.write_text(
        "[Intro]\n[Verse 1]\na\nb\nc\nd\n[Pre-Chorus]\ne\nf\ng\nh\n"
        "[Chorus]\ni\n[Verse 2]\na\nb\nc\nd\n[Pre-Chorus]\ne\nf\ng\nh\n"
        "[Chorus]\ni\n[Bridge]\nj\n[Final Chorus]\nk\n[Outro]\nl\n",
        encoding="utf-8",
    )
    segments = [
        (0, 4, "inst"), (4, 16, "verse"), (16, 24, "chorus"),
        (24, 36, "verse"), (36, 44, "chorus"), (44, 52, "inst"),
        (52, 56, "verse"), (56, 64, "chorus"), (64, 68, "inst"),
    ]
    specialist.write_text(
        json.dumps(
            {
                "bpm": 120,
                "downbeats": list(range(1, 68)),
                "segments": [
                    {"start": start, "end": end, "label": label}
                    for start, end, label in segments
                ],
            }
        ),
        encoding="utf-8",
    )
    interval_count = 68
    embedding = np.zeros((interval_count, 18), dtype=float).tolist()
    evidence = []
    for second in range(1, 68):
        strong = second in {12, 32}
        evidence.append(
            {
                "time_seconds": float(second),
                "multistem_change": 2.0 if strong else 0.2,
                "change_consensus": 0.8 if strong else 0.1,
                "role_changes": {"drums": 1.0},
                "role_energy_delta_db": {
                    "drums": 8.0 if strong else 0.0,
                    "bass": 8.0 if strong else 0.0,
                    "lead_vocal": 4.0 if strong else 0.0,
                },
            }
        )
    timeline = {
        "analysis_version": "test",
        "bpm": 120,
        "duration_seconds": 68.0,
        "grid_source": "external_downbeats",
        "interval_boundaries_seconds": [float(value) for value in range(69)],
        "stems": [
            {"role": role, "standardized_embedding": embedding}
            for role in ("drums", "bass", "keys", "guitar", "lead_vocal", "backing_vocals")
        ],
        "boundary_evidence": evidence,
        "reuse_contract": {"observations_not_mix_decisions": True},
    }
    monkeypatch.setattr("pampapilot.song_structure.analyze_music_timeline", lambda *a, **k: timeline)

    proposal = build_song_structure_proposal(
        audio,
        lyrics,
        bpm=120,
        stem_paths=[audio],
        specialist_analysis_path=specialist,
    )

    starts = {region["label"]: region["start_seconds"] for region in proposal["regions"]}
    assert starts["Verse 1"] == 4
    assert starts["Verse 2"] == 24
    assert [region["start_seconds"] for region in proposal["regions"] if region["kind"] == "pre_chorus"] == [12, 32]
    assert starts["Bridge"] == 44
    assert starts["Final Chorus"] == 56
    assert starts["Outro"] == 64
    assert proposal["timing_evidence"]["timeline_summary"]["stem_count"] == 6

    alignment = tmp_path / "alignment.json"
    alignment.write_text(
        json.dumps(
            {
                "kind": "pampapilot_vocal_lyric_alignment",
                "lyrics_sha256": hashlib.sha256(lyrics.read_bytes()).hexdigest(),
                "model": {"name": "test"},
                "alignments": [
                    {
                        "section_index": 2,
                        "occurrence": 1,
                        "status": "matched",
                        "match": {
                            "detected_start_seconds": 12.1,
                            "confidence": 0.95,
                            "text_match_score": 1.0,
                            "mean_word_probability": 0.95,
                        },
                    },
                    {
                        "section_index": 5,
                        "occurrence": 2,
                        "status": "matched",
                        "match": {
                            "detected_start_seconds": 31.4,
                            "confidence": 0.92,
                            "text_match_score": 1.0,
                            "mean_word_probability": 0.9,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    tuned = build_song_structure_proposal(
        audio,
        lyrics,
        bpm=120,
        stem_paths=[audio],
        specialist_analysis_path=specialist,
        vocal_alignment_path=alignment,
    )
    tuned_pre_starts = [
        region["start_seconds"] for region in tuned["regions"]
        if region["kind"] == "pre_chorus"
    ]
    assert tuned_pre_starts == [12.0, 31.4]
    second_evidence = tuned["timing_evidence"]["boundary_evidence"][4]
    assert second_evidence["source"] == "clean_lyrics_vocal_phrase_alignment"
