# Progress

## Status: all milestones (M1–M7) done. `python scripts/tasks.py test` → 62 passed (mock mode).

## Done
- **M1** Skeleton, settings (`backend/app/config.py`), script schema (`models.py`),
  provider interfaces (`providers/base.py`), mock LLM and mock image providers,
  provider factory, task runner (`scripts/tasks.py`) and Makefile.
- **M2** Story → script stage (`pipeline/script.py`): system prompt, JSON Schema from
  Pydantic, validation + repair loop (errors fed back to the LLM), copyright-name guard,
  page/panel normalisation.
- **M3** Character sheets with reference images (`pipeline/characters.py`), panel prompt
  builder with shot/mood/style phrases and a negative prompt (`pipeline/prompts.py`), panel
  image stage with per-panel seeds and a saved prompt log (`pipeline/panels.py`).
- **M4** Layout engine (`pipeline/layout.py`: A4 page, row templates for 1–6 panels,
  margins, gutters, ink borders, LTR/RTL mirroring, cover-fit images) and lettering engine
  (`pipeline/lettering.py`: word wrap, ellipse/shout balloons, narration boxes, tails toward
  the speaker, centre keep-out zone, reading-order placement, font shrinking).
- **M5** Export (PNG per page + combined PDF), orchestrator (`pipeline/run.py`, renders both
  RTL and LTR), in-process job queue with per-stage progress (`jobs.py`), FastAPI app
  (`main.py`), CLI (`cli.py`). Verified with tests and a live uvicorn smoke test.
- **M6** Next.js 16 + TypeScript + Tailwind 4 frontend: story form with provider badge and
  sample story, live per-stage progress (polling), reader with RTL/LTR toggle, arrow-key
  navigation, PNG/PDF downloads, character sheets, links to the script/prompt JSON.
  Lint, type check and production build pass. Verified end to end in headless Edge
  (submit → progress → reader → toggle → PNG + PDF download, no console errors).
- **M7** Claude provider (structured outputs, refusal fallbacks, typed error handling),
  ComfyUI provider (default txt2img workflow, custom API-format workflows with placeholders,
  reference-image upload), hosted image API stub, Dockerfiles + docker-compose, README,
  sample story and committed output in `samples/`.

## Next (suggested)
- Try a real run with `ANTHROPIC_API_KEY` set (see "Known issues").
- Add IP-Adapter to a ComfyUI workflow (README → next steps).
- Persist jobs (SQLite) so they survive restarts; add job cancellation.
- Let the LLM give per-panel character positions for better bubble tails.

## Known issues
- **Not verified against live services**: no API key or ComfyUI server was available. The
  Claude and ComfyUI providers are tested with fake clients that match the documented APIs.
  The first real Claude call is the main thing to check (schema accepted, output quality).
- `make` and Docker aren't installed on the build machine. The Makefile wraps
  `scripts/tasks.py` (tested). `docker-compose.yml` and the Dockerfiles are written but untested.
- Ports 8000/3000 were busy on the build machine (other apps), so the UI was tested on
  8100/3100. Use `BACKEND_PORT` / `FRONTEND_PORT` with `scripts/tasks.py` if you hit the same.
- `NEXT_PUBLIC_API_URL` is baked in at frontend build time (a Next.js rule), so rebuild after changing it.
- Pillow's bundled font lacks dashes and accents, so `safe_text()` maps them to ASCII. Set
  `LETTERING_FONT` to a .ttf (ideally a comic font) for full Unicode and nicer lettering.
- The mock script uses simple heuristics: names = capitalised words, speakers = a name near
  the quote. It's fine for testing, but the real LLM does much better.
- Jobs are in memory and run one at a time.
- PROGRESS.md wasn't updated in the M2–M6 commits (a scripted edit silently failed); the
  commit messages describe each milestone accurately.
