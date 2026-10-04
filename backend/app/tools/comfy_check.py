"""Check the ComfyUI connection and (optionally) generate ONE real test panel.

    cd backend
    .venv/Scripts/python -m app.tools.comfy_check              # discovery report only
    .venv/Scripts/python -m app.tools.comfy_check --generate   # + one 832x1216 test panel

The panel is saved to samples/comfyui_test_panel.png with a JSON report next to it.
Exit code 2 = ComfyUI not reachable (see SETUP_COMFYUI.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from ..comfy.client import ComfyClient
from ..config import REPO_DIR, Settings
from ..providers.base import ImageRequest, ProviderError
from ..providers.comfyui_image import ComfyUIImageProvider

TEST_PROMPT = (
    "monochrome, greyscale, manga panel, medium shot, eye level, 1girl, short black hair, "
    "school uniform, determined expression, standing on a rooftop at dusk, city skyline, "
    "wind, ink lines, screentone shading, high contrast, detailed linework"
)
TEST_NEGATIVE = "color, photo, 3d, text, speech bubble, watermark, signature, lowres, blurry, bad hands"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--generate", action="store_true", help="also generate one test panel")
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    client = ComfyClient(settings.comfyui_url, timeout=settings.comfyui_timeout)
    stats = client.ping()
    if stats is None:
        print(f"ComfyUI is NOT reachable at {settings.comfyui_url}. See SETUP_COMFYUI.md.")
        return 2

    devices = stats.get("devices", [])
    for device in devices:
        vram = device.get("vram_total", 0) / 1024**3
        print(f"GPU: {device.get('name')}  VRAM {vram:.1f} GB  free {device.get('vram_free', 0) / 1024**3:.1f} GB")
    caps = client.capabilities()
    report = caps.summary()
    print(json.dumps(report, indent=2))
    if not caps.checkpoints:
        print("No checkpoints installed. See SETUP_COMFYUI.md, step 3.")
        return 1
    if not caps.has_ipadapter:
        print("IP-Adapter is not fully installed: panels will work but without reference images.")

    if not args.generate:
        return 0

    provider = ComfyUIImageProvider(settings)
    started = time.monotonic()
    try:
        image = provider.generate(ImageRequest(prompt=TEST_PROMPT, negative_prompt=TEST_NEGATIVE,
                                               width=args.width, height=args.height, seed=1234))
    except ProviderError as exc:
        print(f"Generation failed: {exc}")
        return 1
    seconds = time.monotonic() - started
    out = REPO_DIR / "samples" / "comfyui_test_panel.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    after = client.ping() or {}
    report.update({
        "checkpoint": client.pick_checkpoint(settings.comfyui_checkpoint),
        "size": [args.width, args.height], "seconds": round(seconds, 1),
        "vram_free_after_gb": [round(d.get("vram_free", 0) / 1024**3, 2) for d in after.get("devices", [])],
        "prompt": TEST_PROMPT,
    })
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    provider.free_memory()
    print(f"Saved {out} in {seconds:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
