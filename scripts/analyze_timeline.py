from __future__ import annotations

import argparse
import json
from pathlib import Path

from pampapilot.timeline_analysis import (
    analyze_music_timeline,
    write_music_timeline_analysis,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze aligned stems by musical interval for reusable producer features."
    )
    parser.add_argument("stems_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bpm", type=float, required=True)
    parser.add_argument(
        "--specialist-analysis",
        type=Path,
        help="Optional JSON containing a downbeats array.",
    )
    args = parser.parse_args()

    stems = sorted(
        path for path in args.stems_directory.iterdir()
        if path.is_file() and path.suffix.casefold() in {".wav", ".flac"}
    )
    downbeats = None
    if args.specialist_analysis is not None:
        specialist = json.loads(args.specialist_analysis.read_text(encoding="utf-8"))
        downbeats = specialist.get("downbeats")
        if not isinstance(downbeats, list):
            raise ValueError("specialist analysis contains no downbeats array")
    report = analyze_music_timeline(stems, bpm=args.bpm, downbeats=downbeats)
    write_music_timeline_analysis(report, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "stem_count": len(report["stems"]),
                "interval_count": len(report["interval_boundaries_seconds"]) - 1,
                "roles": sorted({stem["role"] for stem in report["stems"]}),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
