"""Prepare or preview a PampaPilot song manifest without opening REAPER."""

from __future__ import annotations

import argparse
import json

from pampapilot.song_preparation import (
    SongPreparationConfig,
    build_song_manifest,
    prepare_song,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("song_name")
    parser.add_argument("bpm", type=float)
    parser.add_argument(
        "--source-kind",
        choices=("suno_stems", "organic_multitrack", "unknown"),
        default="suno_stems",
    )
    parser.add_argument(
        "--analysis-level", choices=("metadata", "signal"), default="metadata"
    )
    parser.add_argument("--numerator", type=int, default=4)
    parser.add_argument("--denominator", type=int, default=4)
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args()
    config = SongPreparationConfig(
        bpm=arguments.bpm,
        numerator=arguments.numerator,
        denominator=arguments.denominator,
        source_kind=arguments.source_kind,
        analysis_level=arguments.analysis_level,
    )
    manifest = (
        build_song_manifest(arguments.song_name, config)
        if arguments.preview
        else prepare_song(arguments.song_name, config)
    )
    print(
        json.dumps(
            {
                "status": manifest["validation"]["status"],
                "summary": manifest["summary"],
                "manifest_path": manifest["paths"]["manifest"],
                "outputs_written": manifest["outputs_written"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
