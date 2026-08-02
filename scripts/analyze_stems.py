"""CLI local para medir todos los WAV de una carpeta de stems."""

from __future__ import annotations

import argparse
from pathlib import Path

from pampapilot.audio_analysis import analyze_stems, write_analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stem_directory", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    paths = sorted(
        args.stem_directory.glob("*.wav"),
        key=lambda path: int(path.name.split(" ", 1)[0]),
    )
    if not paths:
        raise SystemExit("no se encontraron archivos WAV")
    report = analyze_stems(paths)
    write_analysis(report, args.output_json)
    print(f"analizados={len(paths)} salida={args.output_json}")


if __name__ == "__main__":
    main()
