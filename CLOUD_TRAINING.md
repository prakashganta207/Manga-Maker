# Training a character LoRA on a rented cloud GPU

Training a character LoRA locally on an 8 GB laptop GPU works (see "Local training" below), but it
blocks the GPU for half an hour or more. A rented GPU (24 GB+) does the same job in a few minutes
for well under a dollar. The app prepares everything you need, so the cloud machine only runs one
command.

## What the app prepares

Click **Train character LoRA** once on the Cast page, or let a training run start and cancel it.
Either way, the app writes this folder for the character:

```
backend/output/projects/<project_id>/loras/<character>/
  dataset/10_<trigger>/img_01.png, img_01.txt, ...   # images + captions (built from the fixed tags)
  train.sh / train.ps1                                # the exact sd-scripts command (8 GB settings)
  train_args.json                                     # the same arguments as a list
```

- `<trigger>` is the character's trigger word (for example `aya_chr`). The captions start with it,
  followed by the character's fixed visual tags and what the picture shows (view, expression).
- `10_` = each image is repeated 10 times per epoch (kohya's folder convention).

## Run it on a cloud GPU (RunPod, Vast.ai, Lambda, a Colab notebook, ...)

1. Rent a machine with an NVIDIA GPU (an RTX 4090 / A5000 / L4 or better; 24 GB lets you drop the
   memory-saving flags) and a PyTorch image.
2. Install kohya-ss sd-scripts (Apache-2.0):

   ```bash
   git clone https://github.com/kohya-ss/sd-scripts && cd sd-scripts
   python -m venv venv && . venv/bin/activate
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   pip install -r requirements.txt
   accelerate config default
   ```

3. Download the base model (the same one the app draws with):

   ```bash
   wget -O /workspace/animagine-xl-3.1.safetensors \
     https://huggingface.co/cagliostrolab/animagine-xl-3.1/resolve/main/animagine-xl-3.1.safetensors
   ```

4. Upload the character's `dataset/` folder (for example with `scp` or the provider's file browser).
5. Run the command from `train.sh`, changing three paths: `--pretrained_model_name_or_path` (the
   model), `--train_data_dir` (the uploaded `dataset/`) and `--output_dir`. Run it with
   `accelerate launch` in front:

   ```bash
   accelerate launch --num_cpu_threads_per_process=2 sdxl_train_network.py \
     --pretrained_model_name_or_path=/workspace/animagine-xl-3.1.safetensors \
     --train_data_dir=/workspace/dataset --output_dir=/workspace/out --output_name=aya_lora \
     ... (the other arguments from train.sh, unchanged)
   ```

   On a 24 GB GPU you may remove `--fp8_base` and `--gradient_checkpointing` (faster) and use
   `--resolution=1024,1024`. Expect about 5–10 minutes for 600 steps on an RTX 4090.
6. Download `out/aya_lora.safetensors`.

## Import the result

On the **Cast** page, open the character's *Character LoRA* box → **Import a LoRA trained
elsewhere**, choose the `.safetensors` file and keep the suggested trigger word (it must be the one in
the captions). The app:

- stores it with the project (later chapters reuse it),
- copies it into ComfyUI's `models/loras/` (when the app knows where ComfyUI is: `COMFYUI_MODELS_DIR`,
  or the in-project install `comfyui/ComfyUI/models`); otherwise copy it there yourself,
- uses it automatically from then on: the trigger word goes into the character's prompt tags, a
  `LoraLoader` (strength `LORA_STRENGTH`, default 0.8) is added to the panel workflows, and the
  IP-Adapter reference is turned down to `IPADAPTER_WEIGHT_WITH_LORA` (default 0.45).

The same import works from the command line:

```bash
curl -F file=@aya_lora.safetensors -F trigger=aya_chr \
  http://localhost:8000/api/jobs/<job_id>/characters/Aya/lora/import
```

## Local training (8 GB GPU)

```powershell
git clone https://github.com/kohya-ss/sd-scripts tools/sd-scripts
cd tools/sd-scripts
python -m venv venv
venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
venv\Scripts\python -m pip install -r requirements.txt
```

With `TRAINER=auto` (the default), the app uses it as soon as `tools/sd-scripts/venv` exists and the base
model file is found (`LORA_BASE_MODEL`, or the ComfyUI checkpoint). Training runs in the background with
progress and logs on the Cast page. Panel drawing waits while it trains (one GPU). The 8 GB settings
are explained in `backend/app/training/lora.py`: rank 16, 768 px, batch 1, UNet only, cached latents
and text embeddings, gradient checkpointing, fp8 base weights, Adafactor. See PROGRESS.md for the
measured time on the build machine.
