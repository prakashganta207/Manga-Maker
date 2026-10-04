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


@dataclass
class Settings:
    llm_provider: str = "auto"
    image_provider: str = "auto"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"

    comfyui_url: str = ""
    comfyui_checkpoint: str = "sd_xl_base_1.0.safetensors"
    comfyui_steps: int = 25
    comfyui_cfg: float = 6.5
    comfyui_width: int = 832
    comfyui_height: int = 832
    comfyui_timeout: int = 600

    hosted_image_api_url: str = ""
    hosted_image_api_key: str = ""

    output_dir: Path = BACKEND_DIR / "output"
    panels_per_page: int = 4
    max_pages: int = 2
    lettering_font: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        output = Path(_env("OUTPUT_DIR", "output"))
        if not output.is_absolute():
            output = BACKEND_DIR / output
        return cls(
            llm_provider=_env("LLM_PROVIDER", "auto").lower() or "auto",
            image_provider=_env("IMAGE_PROVIDER", "auto").lower() or "auto",
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
            comfyui_url=_env("COMFYUI_URL").rstrip("/"),
            comfyui_checkpoint=_env("COMFYUI_CHECKPOINT", "sd_xl_base_1.0.safetensors"),
            comfyui_steps=_env_int("COMFYUI_STEPS", 25),
            comfyui_cfg=_env_float("COMFYUI_CFG", 6.5),
            comfyui_width=_env_int("COMFYUI_WIDTH", 832),
            comfyui_height=_env_int("COMFYUI_HEIGHT", 832),
            comfyui_timeout=_env_int("COMFYUI_TIMEOUT", 600),
            hosted_image_api_url=_env("HOSTED_IMAGE_API_URL"),
            hosted_image_api_key=_env("HOSTED_IMAGE_API_KEY"),
            output_dir=output,
            panels_per_page=max(1, min(6, _env_int("PANELS_PER_PAGE", 4))),
            max_pages=max(1, min(10, _env_int("MAX_PAGES", 2))),
            lettering_font=_env("LETTERING_FONT"),
        )

    def describe(self) -> dict:
        """Safe summary for logs / the health endpoint (no secret values)."""
        return {
            "llm_provider": self.llm_provider,
            "image_provider": self.image_provider,
            "anthropic_key_set": bool(self.anthropic_api_key),
            "anthropic_model": self.anthropic_model,
            "comfyui_url_set": bool(self.comfyui_url),
            "hosted_image_configured": bool(self.hosted_image_api_url),
            "panels_per_page": self.panels_per_page,
            "max_pages": self.max_pages,
        }
