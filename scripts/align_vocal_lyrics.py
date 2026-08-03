from __future__ import annotations

import argparse
import json
from pathlib import Path

from pampapilot.vocal_alignment import (
    build_vocal_lyric_alignment,
    write_vocal_lyric_alignment,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fine-tune selected clean lyric sections against an isolated vocal stem."
    )
    parser.add_argument("vocal", type=Path)
    parser.add_argument("lyrics", type=Path)
    parser.add_argument("base_proposal", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-kind", action="append", default=["pre_chorus"])
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--compute-type")
    parser.add_argument("--language", default="es")
    parser.add_argument("--model-cache", type=Path, default=Path(".runtime/models/faster-whisper"))
    parser.add_argument("--cuda-runtime", type=Path, default=Path(".runtime/cuda"))
    args = parser.parse_args()

    proposal = json.loads(args.base_proposal.read_text(encoding="utf-8"))
    report = build_vocal_lyric_alignment(
        args.vocal,
        args.lyrics,
        proposal["regions"],
        proposal["regions"],
        target_kinds=args.target_kind,
        model_name=args.model,
        model_cache=args.model_cache,
        device=args.device,
        compute_type=args.compute_type,
        cuda_runtime_root=args.cuda_runtime,
        language=args.language,
    )
    write_vocal_lyric_alignment(report, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "model": report["model"],
                "alignments": [
                    {
                        "label": entry["section_label"],
                        "occurrence": entry["occurrence"],
                        "status": entry["status"],
                        "match": entry["match"],
                    }
                    for entry in report["alignments"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
