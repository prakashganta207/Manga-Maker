"""App settings, read from environment variables (and an optional .env file).

Nothing secret is ever logged: `Settings.describe()` only reports *whether* a key
is set, never its value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# .env at the repo root is the main one; backend/.env is also accepted.
# override=False means real environment variables always win over the file.
load_dotenv(REPO_DIR / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)

# Hugging Face downloads (the CLIP model for consistency scores) stay inside the project.
os.environ.setdefault("HF_HOME", str(BACKEND_DIR / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # harmless on Windows, just noisy


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name, "")
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # auto = first configured of anthropic -> gemini -> openai (compatible) -> mock
    llm_provider: str = "auto"
    # auto = comfyui if reachable at COMFYUI_URL, else hosted if configured, else mock
    image_provider: str = "auto"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"
    # Optional price override (USD per million tokens) for the cost counter.
    llm_input_price: float | None = None
    llm_output_price: float | None = None

    comfyui_url: str = ""
    # Anime-style SDXL checkpoint (see SETUP_COMFYUI.md). Falls back to any installed one.
    comfyui_checkpoint: str = "animagine-xl-3.1.safetensors"
    comfyui_steps: int = 28
    comfyui_cfg: float = 6.0
    comfyui_sampler: str = "euler_ancestral"
    comfyui_scheduler: str = "normal"
    comfyui_timeout: int = 900
    comfyui_workflow_dir: str = ""
    comfyui_free_vram: bool = True
    # IP-Adapter: how strongly the character reference steers the image (0..1).
    ipadapter_weight: float = 0.7
    ipadapter_preset: str = "PLUS (high strength)"
    ipadapter_end_at: float = 0.8

    hosted_image_api_url: str = ""
    hosted_image_api_key: str = ""

    # Panels are generated at about IMAGE_BASE_SIZE² pixels in the panel's shape.
    # 1008² ≈ 832x1216, the SDXL portrait size that fits comfortably in 8 GB VRAM.
    image_base_size: int = 1008
    output_dir: Path = BACKEND_DIR / "output"
    max_pages: int = 2
    max_panels_per_page: int = 6
    lettering_font: str = ""

    # Pause after character sheets until the cast is approved (unless auto-approve).
    auto_approve: bool = False
    # Consistency score: auto (CLIP if installed) | clip | simple | off
    consistency_scorer: str = "auto"
    clip_model: str = "openai/clip-vit-base-patch32"

    # --- Phase 3: Editor agent + redraw loop (see app/agents/quality.py) ---
    editor_enabled: bool = True
    editor_max_attempts: int = 3          # attempts per panel, first drawing included
    # A panel passes when combined score >= quality_threshold AND no criterion <= quality_min_criterion
    # AND the Editor's verdict is "pass". combined = editor_weight * editor + (1 - editor_weight) * clip.
    quality_threshold: float = 0.65
    quality_editor_weight: float = 0.7
    quality_min_criterion: int = 2
    # CLIP similarity is mapped to 0..1 between these two values (0.60 -> 0, 0.90 -> 1).
    clip_score_low: float = 0.60
    clip_score_high: float = 0.90
    # Per-job budgets. When one runs out, no more redraws: the best attempt is kept and the
    # panel is marked "needs human review".
    job_max_llm_calls: int = 150
    job_max_llm_cost_usd: float = 3.0
    job_max_gpu_seconds: float = 3600.0

    # --- Phase 4: inpainting ---
    inpaint_denoise: float = 0.9          # how much of the masked region is redrawn (1 = from scratch)
    inpaint_grow: int = 12                # px the mask grows so seams fall outside the edited area
    inpaint_feather: int = 10             # px of soft edge when pasting the region back

    @classmethod
    def from_env(cls) -> "Settings":
        output = Path(_env("OUTPUT_DIR", "output"))
        if not output.is_absolute():
            output = BACKEND_DIR / output
        input_price = _env("LLM_INPUT_PRICE_PER_MTOK")
        output_price = _env("LLM_OUTPUT_PRICE_PER_MTOK")
        return cls(
            llm_provider=_env("LLM_PROVIDER", "auto").lower() or "auto",
            image_provider=_env("IMAGE_PROVIDER", "auto").lower() or "auto",
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
            gemini_api_key=_env("GEMINI_API_KEY"),
            gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash",
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_base_url=_env("OPENAI_BASE_URL").rstrip("/"),
            openai_model=_env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
            llm_input_price=float(input_price) if input_price else None,
            llm_output_price=float(output_price) if output_price else None,
            comfyui_url=_env("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/"),
            comfyui_checkpoint=_env("COMFYUI_CHECKPOINT", "animagine-xl-3.1.safetensors"),
            comfyui_steps=_env_int("COMFYUI_STEPS", 28),
            comfyui_cfg=_env_float("COMFYUI_CFG", 6.0),
            comfyui_sampler=_env("COMFYUI_SAMPLER", "euler_ancestral"),
            comfyui_scheduler=_env("COMFYUI_SCHEDULER", "normal"),
            comfyui_timeout=_env_int("COMFYUI_TIMEOUT", 900),
            comfyui_workflow_dir=_env("COMFYUI_WORKFLOW_DIR"),
            comfyui_free_vram=_env_bool("COMFYUI_FREE_VRAM", True),
            ipadapter_weight=max(0.0, min(1.5, _env_float("IPADAPTER_WEIGHT", 0.7))),
            ipadapter_preset=_env("IPADAPTER_PRESET", "PLUS (high strength)"),
            ipadapter_end_at=max(0.1, min(1.0, _env_float("IPADAPTER_END_AT", 0.8))),
            hosted_image_api_url=_env("HOSTED_IMAGE_API_URL"),
            hosted_image_api_key=_env("HOSTED_IMAGE_API_KEY"),
            image_base_size=max(256, min(1536, _env_int("IMAGE_BASE_SIZE", 1008))),
            output_dir=output,
            max_pages=max(1, min(10, _env_int("MAX_PAGES", 2))),
            max_panels_per_page=max(1, min(6, _env_int("MAX_PANELS_PER_PAGE", 6))),
            lettering_font=_env("LETTERING_FONT"),
            auto_approve=_env_bool("AUTO_APPROVE", False),
            consistency_scorer=_env("CONSISTENCY_SCORER", "auto").lower() or "auto",
            clip_model=_env("CLIP_MODEL", "openai/clip-vit-base-patch32"),
            editor_enabled=_env_bool("EDITOR_ENABLED", True),
            editor_max_attempts=max(1, min(10, _env_int("EDITOR_MAX_ATTEMPTS", 3))),
            quality_threshold=max(0.0, min(1.0, _env_float("QUALITY_THRESHOLD", 0.65))),
            quality_editor_weight=max(0.0, min(1.0, _env_float("QUALITY_EDITOR_WEIGHT", 0.7))),
            quality_min_criterion=max(0, min(4, _env_int("QUALITY_MIN_CRITERION", 2))),
            clip_score_low=_env_float("CLIP_SCORE_LOW", 0.60),
            clip_score_high=_env_float("CLIP_SCORE_HIGH", 0.90),
            job_max_llm_calls=max(0, _env_int("JOB_MAX_LLM_CALLS", 150)),
            job_max_llm_cost_usd=max(0.0, _env_float("JOB_MAX_LLM_COST_USD", 3.0)),
            job_max_gpu_seconds=max(0.0, _env_float("JOB_MAX_GPU_SECONDS", 3600.0)),
            inpaint_denoise=max(0.1, min(1.0, _env_float("INPAINT_DENOISE", 0.9))),
            inpaint_grow=max(0, min(64, _env_int("INPAINT_GROW", 12))),
            inpaint_feather=max(0, min(64, _env_int("INPAINT_FEATHER", 10))),
        )

    def describe(self) -> dict:
        """Safe summary for logs / the health endpoint (no secret values)."""
        return {
            "llm_provider": self.llm_provider,
            "image_provider": self.image_provider,
            "anthropic_key_set": bool(self.anthropic_api_key),
            "gemini_key_set": bool(self.gemini_api_key),
            "openai_compatible_set": bool(self.openai_base_url and self.openai_api_key),
            "comfyui_url": self.comfyui_url,
            "hosted_image_configured": bool(self.hosted_image_api_url),
            "max_pages": self.max_pages,
            "auto_approve": self.auto_approve,
            "consistency_scorer": self.consistency_scorer,
            "editor_enabled": self.editor_enabled,
            "quality_threshold": self.quality_threshold,
        }
