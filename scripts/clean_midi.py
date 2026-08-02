from __future__ import annotations

import argparse
import json
from pathlib import Path

from pampapilot.midi_cleanup import CleanupConfig, INSTRUMENT_PROFILES, run_cleanup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean any note-based MIDI against a reference WAV without opening a DAW."
    )
    parser.add_argument("midi", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument(
        "--bpm",
        type=float,
        help="Replace the tempo map with this BPM; omit to preserve the MIDI tempo map.",
    )
    parser.add_argument(
        "--profile", choices=sorted(INSTRUMENT_PROFILES), default="generic"
    )
    parser.add_argument("--min-pitch", type=int)
    parser.add_argument("--max-pitch", type=int)
    parser.add_argument("--quantize-division", type=int, default=16)
    parser.add_argument("--quantize-tolerance", type=float, default=0.125)
    parser.add_argument(
        "--quantize",
        action="store_true",
        help="Enable conservative grid snapping in the reconstructed variant.",
    )
    parser.add_argument("--no-missing-note-proposals", action="store_true")
    arguments = parser.parse_args()
    config = CleanupConfig(
        bpm=arguments.bpm,
        profile=arguments.profile,
        minimum_pitch=arguments.min_pitch,
        maximum_pitch=arguments.max_pitch,
        quantize_division=arguments.quantize_division,
        quantize_tolerance_fraction=arguments.quantize_tolerance,
        enable_quantization=arguments.quantize,
        propose_missing_notes=not arguments.no_missing_note_proposals,
    )
    report = run_cleanup(
        arguments.midi,
        arguments.audio,
        arguments.output_directory,
        config=config,
    )
    print(json.dumps({"report_path": report["report_path"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
