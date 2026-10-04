"""Download the models this app needs into an existing ComfyUI folder.

    backend\\.venv\\Scripts\\python scripts\\download_comfyui_models.py --comfyui-dir C:\\ComfyUI_windows_portable\\ComfyUI

Skips files that already exist. See SETUP_COMFYUI.md for what each model is for.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

MODELS = [
    # (subfolder, target file name, url)
    ("checkpoints", "animagine-xl-3.1.safetensors",
     "https://huggingface.co/cagliostrolab/animagine-xl-3.1/resolve/main/animagine-xl-3.1.safetensors"),
    ("ipadapter", "ip-adapter-plus_sdxl_vit-h.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"),
    ("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
     "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors"),
]


def download(url: str, target: Path) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with open(partial, "wb") as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e9:5.2f} / {total / 1e9:5.2f} GB", end="", flush=True)
    print()
    partial.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfyui-dir", required=True, type=Path, help="the ComfyUI folder (contains models/)")
    args = parser.parse_args()
    models_dir = args.comfyui_dir / "models"
    if not models_dir.is_dir():
        print(f"{models_dir} not found — point --comfyui-dir at the folder that contains 'models'.")
        return 1
    for sub, name, url in MODELS:
        target = models_dir / sub / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(f"✓ {sub}/{name} already present")
            continue
        print(f"↓ {sub}/{name}")
        download(url, target)
    print("Done. Restart ComfyUI, then run: python -m app.tools.comfy_check --generate (in backend/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
