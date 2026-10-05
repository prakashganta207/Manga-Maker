# Setting up ComfyUI on Windows (RTX 4060 Laptop, 8 GB VRAM)

Phases 1–2 were built without ComfyUI (mock images). For Phases 3–5 it was installed **inside the
project** (`comfyui/`, git-ignored, see "Option B" below) and every workflow was measured on an RTX 4060
Laptop (8 GB). Follow these steps once. Then the app switches to real images automatically: `IMAGE_PROVIDER=auto`
uses ComfyUI whenever it answers at `COMFYUI_URL`.

Disk space needed: about 15 GB (ComfyUI ≈ 5 GB, models ≈ 10 GB).

## 1. Install ComfyUI (portable build)

1. Install [7-Zip](https://www.7-zip.org/) if you don't have it.
2. Download `ComfyUI_windows_portable_nvidia.7z` from
   https://github.com/comfyanonymous/ComfyUI/releases (latest release, "Assets").
3. Extract it to a short path without spaces, e.g. `C:\ComfyUI_windows_portable`.
4. Double-click `run_nvidia_gpu.bat`. A browser tab opens at http://127.0.0.1:8188.

Below, `COMFY` means `C:\ComfyUI_windows_portable\ComfyUI`.

## 2. Install the IP-Adapter custom nodes

IP-Adapter lets the model look at a character's reference picture while drawing.
That is the core of character consistency in this app.

```powershell
cd C:\ComfyUI_windows_portable\ComfyUI\custom_nodes
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
```

(No git? Download the repo as ZIP and extract it into `custom_nodes\ComfyUI_IPAdapter_plus`.)
Restart ComfyUI afterwards.

## 2b. Install the ControlNet preprocessor nodes (Phase 5 storyboard)

The storyboard stage turns a quick rough into a **pose skeleton** (DWPose) or **line art**, and the final
panel follows it with ControlNet. The preprocessors come from comfyui_controlnet_aux:

```powershell
cd C:\ComfyUI_windows_portable\ComfyUI\custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
..\..\python_embeded\python.exe -m pip install -r comfyui_controlnet_auxequirements.txt
```

On first use it downloads its small annotator models from Hugging Face by itself: DWPose
(`yzd-v/DWPose`, Apache-2.0) + YOLOX person detector (Apache-2.0) for poses, and the anime line-art
model (Anime2Sketch, MIT). The app uses **DWPose** rather than the original CMU OpenPose weights (those are
non-commercial); the output is the same OpenPose-format skeleton.

**Fallback:** without these nodes (or without the ControlNet model) the storyboard stage is skipped
automatically and panels are drawn from the prompt only (a warning is shown). `STORYBOARD=off` disables it.

## 3. Download the models

| What | File | Put it in | Size | License |
|---|---|---|---|---|
| Anime-style SDXL checkpoint | `animagine-xl-3.1.safetensors` from https://huggingface.co/cagliostrolab/animagine-xl-3.1 | `COMFY\models\checkpoints\` | 6.9 GB | Fair AI Public License 1.0-SD |
| IP-Adapter Plus for SDXL | `ip-adapter-plus_sdxl_vit-h.safetensors` from https://huggingface.co/h94/IP-Adapter (folder `sdxl_models`) | `COMFY\models\ipadapter\` (create the folder) | 0.85 GB | Apache-2.0 |
| CLIP vision encoder (ViT-H) | `models/image_encoder/model.safetensors` from https://huggingface.co/h94/IP-Adapter, **renamed to** `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `COMFY\models\clip_vision\` | 2.5 GB | MIT (OpenCLIP) |
| ControlNet union SDXL (Phase 5, optional) | `diffusion_pytorch_model.safetensors` from https://huggingface.co/xinsir/controlnet-union-sdxl-1.0, **renamed to** `controlnet-union-sdxl-1.0.safetensors` | `COMFY\models\controlnet\` | 2.5 GB | Apache-2.0 |

The IP-Adapter "PLUS" preset looks for exactly these two file names, so keep them as shown.

**Automatic download** (from the project folder, with your ComfyUI path):

```powershell
backend\.venv\Scripts\python scripts\download_comfyui_models.py --comfyui-dir C:\ComfyUI_windows_portable\ComfyUI
```

**Manual download** (PowerShell):

```powershell
$C = "C:\ComfyUI_windows_portable\ComfyUI\models"
mkdir "$C\ipadapter" -Force
curl.exe -L -o "$C\checkpoints\animagine-xl-3.1.safetensors" https://huggingface.co/cagliostrolab/animagine-xl-3.1/resolve/main/animagine-xl-3.1.safetensors
curl.exe -L -o "$C\ipadapter\ip-adapter-plus_sdxl_vit-h.safetensors" https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors
curl.exe -L -o "$C\clip_vision\CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors" https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors
```

Restart ComfyUI after adding models.

## Option B: install inside the project (how the build machine was set up)

```powershell
mkdir comfyui; cd comfyui
git clone --depth 1 https://github.com/comfyanonymous/ComfyUI
git clone --depth 1 https://github.com/cubiq/ComfyUI_IPAdapter_plus ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus
git clone --depth 1 https://github.com/Fannovel16/comfyui_controlnet_aux ComfyUI/custom_nodes/comfyui_controlnet_aux
python -m venv .venv
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
.venv\Scripts\python -m pip install -r ComfyUI/requirements.txt -r ComfyUI/custom_nodes/comfyui_controlnet_aux/requirements.txt
..ackend\.venv\Scripts\python ..\scripts\download_comfyui_models.py --comfyui-dir ComfyUI
.venv\Scripts\python ComfyUI/main.py --port 8188 --disable-auto-launch
```

Windows "Smart App Control" may block a freshly installed DLL on its *first* load (an error like
"An Application Control policy has blocked this file"); starting again works once the check is done.

## 4. Fit in 8 GB of VRAM

- The default `run_nvidia_gpu.bat` usually works for SDXL at 832×1216 on 8 GB.
- If you see "out of memory": edit `run_nvidia_gpu.bat` and add `--lowvram` after `main.py`
  (slower, but swaps model parts to system RAM). If that's still not enough, set
  `IMAGE_BASE_SIZE=896` in `.env`.
- The app already: loads a single checkpoint, generates panels **one at a time**, and calls
  ComfyUI's `/free` endpoint between stages (`COMFYUI_FREE_VRAM=true`).
- Close other GPU-heavy apps (games, Blender, browser video) while generating.
- The consistency-score CLIP model runs on the **CPU**, so it doesn't compete for VRAM.
- **Measured** (RTX 4060 Laptop, 832×1216, 28 steps; times include reloading models after `/free`):

  | Workflow | Time | Peak VRAM |
  |---|---|---|
  | txt2img | 27 s | 6.9 GB |
  | IP-Adapter, 1 / 2 references | 35 / 51 s | 6.9 / 6.6 GB |
  | inpaint (+ reference) | 30 (38) s | 7.0 (6.8) GB |
  | storyboard rough (768 px, 16 steps) | 18 s cold | 6.9 GB |
  | DWPose / line art preprocess | 2 / 10 s | < 1 GB |
  | ControlNet + 0 / 1 / 2 references | 45 / 58 / 75 s | 7.0 / 6.8 / 6.6 GB |

  ControlNet + two IP-Adapter references fit at full resolution: ComfyUI streams model weights in and
  out of VRAM (it reports "NORMAL_VRAM" mode and offloads with pinned memory), so the cost is time,
  not out-of-memory errors. If a workflow does run out of memory, the app retries once without
  ControlNet (or at 85% resolution) and shows a warning.

## 5. Connect the app

In the project's `.env` (copy `.env.example`):

```ini
IMAGE_PROVIDER=auto
COMFYUI_URL=http://127.0.0.1:8188
COMFYUI_CHECKPOINT=animagine-xl-3.1.safetensors
```

Check the connection and generate one real test panel:

```powershell
cd backend
.venv\Scripts\python -m app.tools.comfy_check            # lists installed nodes and models
.venv\Scripts\python -m app.tools.comfy_check --generate # writes samples\comfyui_test_panel.png
```

Then restart the app (`python scripts/tasks.py dev`). The home page badge should say
`Images: comfyui`.

## 6. Tuning (in `.env`)

| Setting | Default | Meaning |
|---|---|---|
| `COMFYUI_STEPS` | 28 | denoising steps; 20 is faster, 30+ rarely helps |
| `COMFYUI_CFG` | 6.0 | prompt strictness; Animagine likes 5–7 |
| `COMFYUI_SAMPLER` / `COMFYUI_SCHEDULER` | euler_ancestral / normal | recommended for Animagine XL |
| `IPADAPTER_WEIGHT` | 0.7 | how strongly the character reference steers the panel. Raise it if characters drift; lower it if every panel copies the reference pose |
| `IPADAPTER_END_AT` | 0.8 | stop applying the reference for the last 20% of steps, so the prompt controls final details |
| `IMAGE_BASE_SIZE` | 1008 | ≈ 832×1216 total pixels per panel (SDXL's native size) |

## Troubleshooting

- `comfy_check` says "missing nodes IPAdapterUnifiedLoader": step 2 wasn't done, or ComfyUI
  needs a restart. Panels still work, just without reference images.
- "ClipVision model not found": the clip_vision file name must match exactly (step 3).
- Panels come out in colour: the prompts already say `monochrome, greyscale`, and the app
  converts to greyscale when laying out pages anyway.
