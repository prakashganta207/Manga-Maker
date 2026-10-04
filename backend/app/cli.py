"""Command line: run the whole agent pipeline on a story file (no web app needed).

    python -m app.cli ../samples/stories/action_rooftop_chase.txt --out ../samples/output/action

The CLI auto-approves the cast (unattended run) unless --wait-for-approval is given.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from .agents.pipeline import manifest, new_project, run_project
from .agents.state import MangaProject
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Story to Manga (agent pipeline)")
    parser.add_argument("story_file", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="Output folder (re-run to resume)")
    parser.add_argument("--project-id", default=None, help="Reuse an earlier project's cast")
    parser.add_argument("--wait-for-approval", action="store_true", help="Stop after the character sheets")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if MangaProject.exists(args.out):
        project = MangaProject.load(args.out)
        print(f"Resuming {args.out}")
    else:
        story = args.story_file.read_text(encoding="utf-8")
        project = new_project(story, uuid.uuid4().hex[:12], settings, project_id=args.project_id,
                              auto_approve=not args.wait_for_approval)
    last = {"stage": None}

    def progress(stage: str, fraction: float, message: str) -> None:
        if stage != last["stage"]:
            print(f"\n[{stage}]")
            last["stage"] = stage
        print(f"  {fraction:4.0%}  {message}")

    project = run_project(project, settings=settings, job_dir=args.out, progress=progress)
    info = manifest(project)
    print(f"\n{project.status}: '{info['title']}' - {info['page_count']} page(s), {info['panel_count']} panels "
          f"in {args.out}")
    print(f"LLM usage: {project.usage.input_tokens} in / {project.usage.output_tokens} out tokens, "
          f"${project.usage.cost_usd:.4f}")
    for warning in info["warnings"]:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
