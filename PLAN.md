# PLAN — Story to Manga

Turn a short story into a black-and-white manga page: panels, characters and
speech bubbles, shown in a web reader with PNG and PDF export.

## Architecture

```
story text
   │
   ▼
[1] Script stage (LLM)  ──►  MangaScript JSON (pages → panels), validated by Pydantic
   │
   ▼
[2] Character sheets    ──►  fixed text description + 1 reference image per character
   │
   ▼
[3] Panel prompts + image generation (image provider) ──► one image per panel
   │
   ▼
[4] Layout + lettering (plain Pillow code, no AI) ──► page PNGs
   │
   ▼
[5] Export ──► page_01.png … + manga.pdf
```

Providers are plug-ins chosen by environment variables:

| Kind  | Mock (default, no keys)        | Real                               |
|-------|--------------------------------|------------------------------------|
| LLM   | `mock` — splits story sentences | `anthropic` — Claude, structured JSON |
| Image | `mock` — Pillow placeholders    | `comfyui` — local ComfyUI HTTP API; `hosted` — stub |

Backend: FastAPI + in-process job queue (one worker thread).
Frontend: Next.js + TypeScript + Tailwind.

## Milestones

- **M1** Project skeleton, config, provider interfaces, mock providers.
- **M2** Story → script stage with Pydantic validation (+ repair/retry for real LLMs). Tests.
- **M3** Character sheets + panel prompt builder + panel image stage. Tests.
- **M4** Layout & lettering engine (grid, borders, gutters, bubbles that avoid panel centers). Tests.
- **M5** Export (PNG + PDF), pipeline orchestrator, FastAPI job API, end-to-end mock run. Tests.
- **M6** Next.js frontend: story form, progress view, reader with RTL toggle, downloads.
- **M7** Real Claude + ComfyUI providers, hosted-image stub, docker-compose, README, sample output.

After each milestone: run tests → fix → commit → update PROGRESS.md.
