"""Final run + demo bundle: a 2-chapter series from samples/stories with the same cast.

    backend\\.venv\\Scripts\\python scripts\\make_demo.py                 # providers from .env (ComfyUI if running)
    backend\\.venv\\Scripts\\python scripts\\make_demo.py --train-lora    # + a character LoRA between chapters

1. Chapter 1 = samples/stories/action_rooftop_chase.txt (cast auto-approved, saved to the project).
2. Optional: train each main character's LoRA (kohya, real GPU) and compare consistency before/after.
3. Chapter 2 = samples/stories/action_rooftop_chase_ch2.txt with the same project id: same cast,
   LoRAs, style and the Writer's story so far.
4. Copies the result to samples/demo/ (what "Open the demo" loads) and samples/output/rooftop_series/.
   Images are re-saved as greyscale PNG to keep the repository small; LoRA weights and training
   datasets are left out (their scores and test drawings are kept).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image  # noqa: E402

from app.agents.cast_store import CastStore  # noqa: E402
from app.agents.pipeline import new_project, run_project, scorer_for  # noqa: E402
from app.config import Settings  # noqa: E402
from app.providers import get_image_provider, get_llm_provider  # noqa: E402

STORIES = ROOT / "samples" / "stories"
PROJECT = "rooftop-ch1"
CHAPTERS = [("rooftop-ch1", "action_rooftop_chase.txt"), ("rooftop-ch2", "action_rooftop_chase_ch2.txt")]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run_chapter(settings: Settings, llm, image, job_id: str, story_file: str) -> None:
    story = (STORIES / story_file).read_text(encoding="utf-8")
    job_dir = settings.output_dir / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    project = new_project(story, job_id, settings, project_id=PROJECT, auto_approve=True)
    started = time.monotonic()
    last = {"stage": ""}

    def progress(stage: str, fraction: float, message: str) -> None:
        if stage != last["stage"] or fraction >= 1.0:
            log(f"  {job_id} [{stage}] {message}")
            last["stage"] = stage

    project = run_project(project, settings=settings, job_dir=job_dir, llm=llm, image=image, progress=progress)
    q = {r.status for r in project.panels}
    log(f"{job_id}: {project.status} in {time.monotonic() - started:.0f}s, chapter {project.chapter}, "
        f"{len(project.panels)} panels {q}, GPU {project.budget.gpu_seconds:.0f}s, ${project.usage.cost_usd:.3f}")


def train_loras(settings: Settings, image) -> None:
    from app.agents.state import MangaProject
    from app.training.lora import train_character_lora
    from app.training.manager import evaluate

    job_dir = settings.output_dir / CHAPTERS[0][0]
    project = MangaProject.load(job_dir)
    store = CastStore(settings.output_dir).root / project.project_id
    for name in project.main_character_names():
        character = project.character(name)
        log(f"training {name}'s LoRA ...")
        image.free_memory()
        decile = {"last": -1}

        def progress(fraction: float, message: str, name=name, decile=decile) -> None:
            if int(fraction * 10) != decile["last"]:          # log every 10%
                decile["last"] = int(fraction * 10)
                log(f"  {name}: {message}")

        result = train_character_lora(project, character, job_dir, store, settings, progress=progress)
        for key, value in result.items():
            setattr(character.lora, key, value)
        lora_file = result["file"] if result["trainer"] == "kohya" else None
        scores = evaluate(project, character, job_dir, image, settings, scorer_for(settings), lora_file)
        for key, value in scores.items():
            setattr(character.lora, key, value)
        log(f"  {name}: {result['trainer']} LoRA in {result['seconds']:.0f}s, consistency "
            f"{scores.get('before')} -> {scores.get('after')}")
        project.save(job_dir)
    CastStore(settings.output_dir).save(project, job_dir)


def slim_copy(source: Path, target: Path) -> None:
    """Copy a folder; PNGs re-saved as greyscale (manga is black and white anyway), heavy training
    files skipped."""
    if target.exists():
        shutil.rmtree(target)
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if path.is_dir() or path.suffix in (".safetensors", ".npz", ".tmp") or "dataset" in rel.parts:
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".png" and "pdf" not in path.name:
            with Image.open(path) as img:
                img.convert("L").save(out, optimize=True)
        else:
            shutil.copy2(path, out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-lora", action="store_true")
    parser.add_argument("--work", type=Path, default=ROOT / "backend" / "output" / "demo_build")
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.output_dir = args.work
    settings.max_pages = args.pages
    settings.auto_approve = True
    if (args.work / "projects").exists():
        shutil.rmtree(args.work / "projects")
    llm, image = get_llm_provider(settings), get_image_provider(settings)
    log(f"providers: llm={llm.name} image={image.name}; work dir {args.work}")

    run_chapter(settings, llm, image, *CHAPTERS[0])
    if args.train_lora:
        train_loras(settings, image)
    run_chapter(settings, llm, image, *CHAPTERS[1])

    demo = ROOT / "samples" / "demo"
    for job_id, _ in CHAPTERS:
        slim_copy(args.work / job_id, demo / "jobs" / job_id)
    slim_copy(args.work / "projects" / PROJECT, demo / "projects" / PROJECT)
    (demo / "demo.json").write_text(json.dumps({
        "project_id": PROJECT, "jobs": [j for j, _ in CHAPTERS], "title": "Rooftop Courier",
        "providers": {"llm": llm.name, "image": image.name},
        "made_at": time.strftime("%Y-%m-%d %H:%M"),
    }, indent=2), encoding="utf-8")
    readable = ROOT / "samples" / "output" / "rooftop_series"
    if readable.exists():
        shutil.rmtree(readable)
    for job_id, _ in CHAPTERS:
        for name in ("pages", "webtoon"):
            if (demo / "jobs" / job_id / name).exists():
                shutil.copytree(demo / "jobs" / job_id / name, readable / job_id / name)
        for pdf in (demo / "jobs" / job_id).glob("manga_*.*"):
            (readable / job_id).mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, readable / job_id / pdf.name)
    size = sum(f.stat().st_size for f in demo.rglob("*") if f.is_file()) / 1e6
    log(f"demo bundle: {demo} ({size:.1f} MB); readable copy: {readable}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
