# Progress

## Phase 1 + 2 (agents, character bible, consistency) — in progress

### Done
- **M0** ComfyUI layer: `app/comfy/client.py` (ping, `/object_info` discovery of nodes,
  checkpoints, IP-Adapter + CLIP-vision models, upload, run, `/free`), workflow templates in
  `backend/workflows/` (txt2img, IP-Adapter 1 ref, 2 refs) with typed placeholder injection,
  rewritten ComfyUI provider (template choice, IP-Adapter fallback, VRAM freeing),
  `python -m app.tools.comfy_check [--generate]`, `SETUP_COMFYUI.md`,
  `scripts/download_comfyui_models.py`. 74 tests passing.

- **M1** LLM providers in priority order Anthropic → Gemini (REST, JSON-schema mode with
  fallback) → OpenAI-compatible (JSON mode + schema in prompt) → mock. `LLMResponse` carries
  token usage. Agent schemas (`agents/schemas.py`), generic agent runner (`agents/runner.py`:
  structured output, Pydantic validation, 2 retries with error feedback, `AgentStep` trace
  record), cost table (`agents/cost.py`), copyright name guard. 92 tests passing.

- **M2** Writer agent (`agents/writer.py`): pass 1 beat sheet (beats, intensity, kinds, climax,
  characters; checks that names come from the story, beats capped by page budget), pass 2 page
  plan (purpose, size, characters, action, setting, emotion, dialogue, narration, SFX; checks
  beat coverage/order, speakers, page limits; code fixes for splash/large rules). Shared state
  `MangaProject` (`agents/state.py`) saved atomically as project.json after every node.
  LangGraph graph (`agents/graph.py`) with skip-if-done nodes (resume) and an approval gate.
  Mock writer in `providers/mock_agents.py`. 102 tests passing.

- **M3** Director agent (`agents/director.py`: layout per page + shot/angle/composition per panel,
  code-enforced rules: establishing on setting change, close-up on emotional peaks, max 2 identical
  shots in a row), library of 10 layout templates (`pipeline/templates.py`: splash, two tiers,
  three tiers, big top, classic 4, four-koma, tall vertical, action burst, conversation, 6-grid),
  template-driven layout + SFX lettering, prompt builder (`agents/prompt_builder.py`: shot/angle/
  expression tags, exact character tags, negative prompt, emotion-matched reference choice),
  Character Designer (text bible, moved forward from M5 so the graph could run end to end), full
  pipeline nodes (`agents/pipeline.py`), job queue/API/CLI switched to the agent graph, old one-shot
  script pipeline removed. 3 sample stories in `samples/stories/`. 107 tests passing.

- **M4** Frontend Agent timeline (`components/AgentTimeline.tsx`): summary strip (steps, time,
  tokens, cost, model), clickable step list with retries/notes, per-agent views (beat sheet with
  intensity chart, page plan cards with sizes/dialogue/SFX, Director plan with RTL layout
  thumbnails + shot/angle chips + rule fixes, character bible), raw JSON, pipeline timing bars.
  Job page tabs (Progress / Agent timeline / Cast / Read); Reader panel gallery with prompts, seeds,
  IP-Adapter refs and consistency badges; story form with sample stories, auto-approve, project
  reuse. Verified in headless Edge (no console errors).

### Known issues / measurements
- ComfyUI is not installed on this machine, so there's **no real test panel yet**. Run
  `python -m app.tools.comfy_check --generate` (in backend/) after following SETUP_COMFYUI.md;
  it writes `samples/comfyui_test_panel.png` plus timing and VRAM numbers.
- Ports on this machine: 8000 (another uvicorn app), 3000 (Grafana), 3200 (Grafana Tempo) are
  taken, and an orphaned socket from a killed process still holds 8100. The UI was tested on
  **8300/3300**: `BACKEND_PORT=8300 FRONTEND_PORT=3300 python scripts/tasks.py dev`.
- GPU detected: RTX 4060 Laptop, 8188 MiB (nvidia-smi, driver 610.88), idle.

---

# Phase 0 progress (original build)

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
