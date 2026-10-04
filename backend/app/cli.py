"""Command line: turn a story file into manga pages without the web app.

    python -m app.cli ../samples/rooftop_glow.txt --out ../samples/rooftop_glow_output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings
from .pipeline.run import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Story to Manga")
    parser.add_argument("story_file", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="Output folder")
    args = parser.parse_args(argv)

    story = args.story_file.read_text(encoding="utf-8")
    settings = Settings.from_env()
    last_stage = {"name": None}

    def progress(stage: str, fraction: float, message: str) -> None:
        if stage != last_stage["name"]:
            print(f"\n[{stage}]")
            last_stage["name"] = stage
        print(f"  {fraction:4.0%}  {message}")

    manifest = run_pipeline(story, settings=settings, out_dir=args.out, progress=progress)
    print(f"\nDone: '{manifest['title']}' — {manifest['page_count']} page(s) in {args.out}")
    for warning in manifest["warnings"]:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
