"""Character LoRA training (optional, offline) with kohya-ss sd-scripts.

What a LoRA is: instead of changing the whole image model (billions of numbers), LoRA ("low-rank
adaptation") trains two small matrices next to some of its layers. Their product is a small
correction added to the original weights, so the model learns ONE new concept — here, one
character, tied to a made-up *trigger word* — from a handful of pictures. The result is a ~50-100 MB
file that can be switched on (with a strength) when drawing panels. It is the strongest consistency
tool after IP-Adapter: the character's look becomes part of the model itself.

Dataset: the character's approved references (front/side/back views, five expressions) plus
up to six accepted solo panels with a high CLIP score. Each image gets a caption built from the
fixed bible tags — "aya_chr, short black hair, school uniform, front view, monochrome..." — so the
trigger word absorbs "everything about this character that the tags don't already say".

8 GB settings (SDXL), each explained in `training_args`: rank 16, 768 px, batch 1, UNet only,
cached latents + text embeddings, gradient checkpointing, fp8 base weights, Adafactor optimizer.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from ..config import REPO_DIR, Settings
from ..agents.state import CharacterEntry, MangaProject

log = logging.getLogger("manga.lora")

ProgressFn = Callable[[float, str], None]


class TrainingError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- locations
def sd_scripts_dir(settings: Settings) -> Path:
    return Path(settings.sd_scripts_dir) if settings.sd_scripts_dir else REPO_DIR / "tools" / "sd-scripts"


def sd_scripts_python(settings: Settings) -> Path:
    if settings.sd_scripts_python:
        return Path(settings.sd_scripts_python)
    venv = sd_scripts_dir(settings) / "venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def comfy_models_dir(settings: Settings) -> Path | None:
    path = Path(settings.comfyui_models_dir) if settings.comfyui_models_dir else REPO_DIR / "comfyui" / "ComfyUI" / "models"
    return path if path.is_dir() else None


def base_model(settings: Settings) -> Path | None:
    if settings.lora_base_model:
        return Path(settings.lora_base_model)
    models = comfy_models_dir(settings)
    return models / "checkpoints" / settings.comfyui_checkpoint if models else None


def kohya_available(settings: Settings) -> bool:
    model = base_model(settings)
    return ((sd_scripts_dir(settings) / "sdxl_train_network.py").exists() and sd_scripts_python(settings).exists()
            and model is not None and model.exists())


def resolve_trainer(settings: Settings) -> str:
    if settings.trainer in ("kohya", "mock"):
        return settings.trainer
    return "kohya" if kohya_available(settings) else "mock"


def trigger_word(character: CharacterEntry) -> str:
    # A rare made-up token, so it doesn't collide with words the model already knows.
    return re.sub(r"[^a-z0-9]", "", character.slug.lower())[:12] + "_chr"


# ----------------------------------------------------------------------------- dataset
@dataclass
class Sample:
    source: Path
    caption: str


def caption(character: CharacterEntry, detail: str) -> str:
    """Trigger word + the fixed bible tags + what this picture shows + the style."""
    return ", ".join([trigger_word(character), character.tag_prompt(), detail, "monochrome, greyscale, manga"])


def collect_samples(project: MangaProject, character: CharacterEntry, job_dir: Path, max_panels: int = 6) -> list[Sample]:
    samples = []
    sheets = character.sheets
    for view, rel in sheets.views.items():
        samples.append(Sample(job_dir / rel, caption(character, f"{view} view, full body, simple background")))
    for expression, rel in sheets.expression_refs.items():
        samples.append(Sample(job_dir / rel, caption(character, f"{expression} expression, portrait, simple background")))
    # Accepted solo panels that clearly look like the character add poses and angles the sheets lack.
    prompts = {(s.page, s.panel): s for s in project.prompts}
    panels = []
    for result in project.panels:
        spec = prompts.get((result.page, result.panel))
        score = result.consistency.get(character.name)
        if spec and spec.characters == [character.name] and result.status == "accepted" and score and score >= 0.85:
            panels.append((score, result))
    for _, result in sorted(panels, key=lambda x: -x[0])[:max_panels]:
        samples.append(Sample(job_dir / result.image, caption(character, "manga panel, solo")))
    return [s for s in samples if s.source.exists()]


def build_dataset(samples: list[Sample], out_dir: Path, character: CharacterEntry, repeats: int,
                  resolution: int) -> Path:
    """kohya's folder convention: train/<repeats>_<trigger>/img_01.png + img_01.txt (the caption).
    `repeats` = how many times each image is shown per epoch (few images -> more repeats)."""
    folder = out_dir / "dataset" / f"{repeats}_{trigger_word(character)}"
    if folder.parent.exists():
        shutil.rmtree(folder.parent)
    folder.mkdir(parents=True)
    for index, sample in enumerate(samples, start=1):
        with Image.open(sample.source) as img:
            img = img.convert("RGB")
            img.thumbnail((resolution * 2, resolution * 2))           # keep files small; bucketing resizes
            img = ImageOps.pad(img, (max(img.size), max(img.size)), color="white") if min(img.size) < 256 else img
            img.save(folder / f"img_{index:02d}.png")
        (folder / f"img_{index:02d}.txt").write_text(sample.caption, encoding="utf-8")
    return folder.parent


# ----------------------------------------------------------------------------- kohya command
def training_args(settings: Settings, dataset: Path, output_dir: Path, name: str, model: Path) -> list[str]:
    """sdxl_train_network.py arguments tuned for an 8 GB GPU."""
    return [
        "sdxl_train_network.py",
        f"--pretrained_model_name_or_path={model}",
        f"--train_data_dir={dataset}",
        f"--output_dir={output_dir}", f"--output_name={name}",
        f"--resolution={settings.lora_resolution},{settings.lora_resolution}",  # 768 px: fits 8 GB, enough detail
        "--enable_bucket", "--min_bucket_reso=512", f"--max_bucket_reso={settings.lora_resolution + 256}",
        "--network_module=networks.lora",
        f"--network_dim={settings.lora_rank}",       # rank: size of the small matrices (16 = plenty for 1 character)
        f"--network_alpha={settings.lora_alpha}",    # scales the update; alpha = rank/2 is a stable default
        "--network_train_unet_only",                 # don't train the text encoders (saves ~2 GB, rarely needed)
        "--train_batch_size=1",
        f"--max_train_steps={settings.lora_steps}",
        f"--learning_rate={settings.lora_learning_rate}",
        "--optimizer_type=Adafactor",                # low-memory optimizer, no extra GPU library needed
        "--optimizer_args", "scale_parameter=False", "relative_step=False", "warmup_init=False",
        "--lr_scheduler=constant_with_warmup", "--lr_warmup_steps=30",
        "--mixed_precision=fp16", "--save_precision=fp16",
        "--fp8_base",                                # keep the frozen SDXL weights in 8-bit floats (~halves VRAM)
        "--gradient_checkpointing",                  # recompute activations instead of storing them
        "--cache_latents", "--cache_latents_to_disk",  # encode images with the VAE once, then unload it
        "--cache_text_encoder_outputs",              # same for the captions' text embeddings
        "--sdpa",                                    # PyTorch's memory-efficient attention
        "--no_half_vae",                             # SDXL's VAE overflows in fp16
        "--caption_extension=.txt", "--shuffle_caption", "--keep_tokens=1",  # trigger word always first
        "--save_model_as=safetensors", "--save_every_n_steps=10000",
        "--seed=42", "--max_data_loader_n_workers=0",
    ]


def write_scripts(out_dir: Path, args: list[str]) -> None:
    """Re-runnable scripts (also what CLOUD_TRAINING.md tells you to run on a rented GPU)."""
    quoted = " ".join(f'"{a}"' if " " in a else a for a in args)
    (out_dir / "train.sh").write_text(f"#!/bin/sh\n# Run inside sd-scripts with its venv active\npython {quoted}\n",
                                      encoding="utf-8")
    (out_dir / "train.ps1").write_text(f"# Run inside sd-scripts with its venv active\npython {quoted}\n", encoding="utf-8")
    (out_dir / "train_args.json").write_text(json.dumps(args, indent=1), encoding="utf-8")


_STEP = re.compile(r"(\d+)/(\d+) \[")


def parse_progress(line: str) -> tuple[int, int] | None:
    """Training progress from kohya's tqdm line 'steps:  12%|##  | 75/600 [01:52<13:07, 1.50s/it, ...]'.
    Other progress bars (caching latents...) are ignored so the bar doesn't jump back and forth."""
    if "steps" not in line:
        return None
    found = _STEP.findall(line)
    if not found:
        return None
    done, total = map(int, found[-1])
    return (done, total) if total > 1 else None


def run_kohya(settings: Settings, args: list[str], log_path: Path, progress: ProgressFn,
              cancelled: Callable[[], bool]) -> None:
    cwd = sd_scripts_dir(settings)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    command = [str(sd_scripts_python(settings)), "-m", "accelerate.commands.launch", "--num_cpu_threads_per_process=2",
               *args]
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("$ " + " ".join(command) + "\n")
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout is not None
        buffer = ""
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            log_file.write(chunk)
            log_file.flush()
            buffer = (buffer + chunk)[-2000:]
            for part in re.split(r"[\r\n]", buffer)[-3:]:
                step = parse_progress(part)
                if step:
                    progress(step[0] / step[1], f"step {step[0]}/{step[1]}")
            if cancelled():
                proc.kill()
                raise TrainingError("cancelled")
        if proc.wait() != 0:
            raise TrainingError(f"sd-scripts exited with code {proc.returncode}; see the log")


def run_mock(settings: Settings, output: Path, progress: ProgressFn, cancelled: Callable[[], bool],
             log_path: Path, seconds: float = 1.5) -> None:
    """Pretend training (no GPU): progress ticks and a small placeholder file, for demos and tests."""
    steps = 20
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("mock trainer: no GPU training was done (TRAINER=mock or sd-scripts not installed)\n")
        for step in range(1, steps + 1):
            if cancelled():
                raise TrainingError("cancelled")
            time.sleep(seconds / steps)
            log_file.write(f"steps: {step * 100 // steps}%| {step}/{steps} [mock]\n")
            progress(step / steps, f"step {step}/{steps} (mock)")
    header = json.dumps({"__metadata__": {"ss_network_module": "networks.lora", "mock": "true"}}).encode()
    output.write_bytes(len(header).to_bytes(8, "little") + header)


# ----------------------------------------------------------------------------- the whole job
def install_lora(settings: Settings, source: Path) -> str | None:
    """Copy the LoRA into ComfyUI's models/loras so workflows can load it by name."""
    models = comfy_models_dir(settings)
    if models is None:
        return None
    target = models / "loras" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return source.name


def train_character_lora(project: MangaProject, character: CharacterEntry, job_dir: Path, store_dir: Path,
                         settings: Settings, progress: ProgressFn, cancelled: Callable[[], bool] = lambda: False,
                         on_log: Callable[[Path], None] = lambda path: None) -> dict:
    """Build the dataset, train, install. Returns the fields to store on `character.lora`."""
    trainer = resolve_trainer(settings)
    work = store_dir / "loras" / character.slug
    work.mkdir(parents=True, exist_ok=True)
    samples = collect_samples(project, character, job_dir)
    if len(samples) < 4:
        raise TrainingError(f"only {len(samples)} usable images for {character.name}; approve the reference sheets first")
    progress(0.0, f"dataset: {len(samples)} images")
    dataset = build_dataset(samples, work, character, settings.lora_repeats, settings.lora_resolution)
    name = f"{character.slug}_lora_v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    output = work / f"{name}.safetensors"
    log_path = work / f"{name}.log"
    on_log(log_path)
    started = time.monotonic()
    model = base_model(settings)
    args = training_args(settings, dataset, work, name, model or Path(settings.comfyui_checkpoint))
    write_scripts(work, args)
    if trainer == "kohya":
        if not kohya_available(settings):
            raise TrainingError("kohya-ss sd-scripts or the base model was not found (see CLOUD_TRAINING.md)")
        run_kohya(settings, args, log_path, progress, cancelled)
        if not output.exists():
            raise TrainingError("training finished but no LoRA file was written; see the log")
    else:
        run_mock(settings, output, progress, cancelled, log_path)
    installed = install_lora(settings, output) if trainer == "kohya" else None
    return {"status": "ready", "trigger": trigger_word(character), "file": installed or output.name,
            "path": output.as_posix(), "trainer": trainer, "dataset_size": len(samples),
            "steps": settings.lora_steps if trainer == "kohya" else 20, "seconds": round(time.monotonic() - started, 1),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": None}


__all__ = ["train_character_lora", "collect_samples", "build_dataset", "training_args", "parse_progress",
           "trigger_word", "resolve_trainer", "TrainingError", "install_lora"]
