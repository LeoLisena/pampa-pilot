from __future__ import annotations

from pathlib import Path

from pampapilot.vocal_alignment import _best_word_alignment, build_vocal_lyric_alignment


def test_best_word_alignment_finds_repeated_clean_phrase_inside_transcript() -> None:
    words = [
        {"word": "termina", "start": 40.0, "end": 40.5, "probability": 0.9},
        {"word": "No", "start": 45.86, "end": 46.1, "probability": 0.9},
        {"word": "busco", "start": 46.1, "end": 46.5, "probability": 0.98},
        {"word": "verte", "start": 46.5, "end": 47.0, "probability": 0.99},
        {"word": "caer", "start": 47.0, "end": 48.0, "probability": 0.99},
        {"word": "Ni", "start": 48.1, "end": 48.5, "probability": 0.92},
        {"word": "demostrar", "start": 48.5, "end": 49.4, "probability": 0.97},
    ]
    match = _best_word_alignment("No busco verte caer, ni demostrar", words)
    assert match is not None
    assert match["detected_start_seconds"] == 45.86
    assert match["text_match_score"] == 1.0
    assert match["confidence"] > 0.9


def test_alignment_report_is_provider_independent(tmp_path: Path) -> None:
    vocal, lyrics = tmp_path / "voice.wav", tmp_path / "lyrics.txt"
    vocal.write_bytes(b"vocal")
    lyrics.write_text("[Verse]\nA\n[Pre-Chorus]\nNo busco verte caer\n[Chorus]\nB", encoding="utf-8")
    sections = [
        {"label": "Verse", "kind": "verse", "lyrics_text": "A"},
        {"label": "Pre-Chorus", "kind": "pre_chorus", "lyrics_text": "No busco verte caer"},
        {"label": "Chorus", "kind": "chorus", "lyrics_text": "B"},
    ]
    regions = [
        {"start_seconds": 0.0, "end_seconds": 10.0},
        {"start_seconds": 10.0, "end_seconds": 20.0},
        {"start_seconds": 20.0, "end_seconds": 30.0},
    ]

    def fake_transcriber(*args, **kwargs):
        return [[
            {"word": "No", "start": 11.2, "end": 11.5, "probability": 0.95},
            {"word": "busco", "start": 11.5, "end": 12.0, "probability": 0.98},
            {"word": "verte", "start": 12.0, "end": 12.4, "probability": 0.99},
            {"word": "caer", "start": 12.4, "end": 13.0, "probability": 0.99},
        ]]

    report = build_vocal_lyric_alignment(
        vocal, lyrics, sections, regions, transcriber=fake_transcriber
    )
    assert report["alignments"][0]["status"] == "matched"
    assert report["alignments"][0]["match"]["detected_start_seconds"] == 11.2
    assert report["observations_not_ground_truth"] is True
