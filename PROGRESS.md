# Progress

## Phase 3–5 (quality loop, interactive editor, pro features) — in progress

Plan: PHASE_3_5_PLAN.md. Test command: `python scripts/tasks.py test` (mock mode, no GPU/keys).

### Start-of-phase check (2026-10-06)
- Phase 1+2 verified before new work: 124 passed / 2 skipped; drama sample end to end in mock mode (3 s).
  One existing bug found and fixed: `scripts/download_comfyui_models.py` crashed on Windows consoles
  (non-ASCII arrows in print).
- ComfyUI installed inside the project (`comfyui/`, DECISIONS #42) with all Phase 2 models + the
  ControlNet union model. `comfy_check`: 1071 nodes, checkpoint + IP-Adapter + CLIP vision found.
  First **real** panel: `samples/comfyui_test_panel.png`.

### Done
- **M1 Editor agent + schemas**: vision input in all LLM providers, `EditorReview` (9 criteria 1–5,
  verdict, problems, machine-applicable fix), Editor agent, mock Editor, combined Editor+CLIP score
  with configurable threshold (`agents/quality.py`). 32 tests.
- **M2 Redraw loop + budgets** (`agents/redraw.py`): every attempt stored (image, prompt, seed,
  scores, review, applied fix); failed panels redrawn with the Editor's fix; max 3 attempts; per-job
  budgets (LLM calls, LLM cost, GPU seconds) from `.env`; best attempt kept + "needs review";
  Editor errors never fail the job; resume redraws an interrupted panel. Only real CLIP votes in the
  combined score (the pixel fallback measures layout, not likeness). Benchmark tool
  `python -m app.tools.bench`. 13 tests.
  **Real run** (ComfyUI + CLIP + mock Editor, 1 page, action story): 5 panels, 12 images, 3 redraws,
  CLIP 0.83–0.96, all accepted; 497 GPU-seconds for the page incl. 4 character sheets (102 s).

### Measurements (RTX 4060 Laptop 8 GB, ComfyUI 0.38, torch 2.14 cu130, Animagine XL 3.1, 832×1216, 28 steps)
| Workflow | Time | Peak VRAM (nvidia-smi, idle 165 MiB) |
|---|---|---|
| txt2img (cold, incl. checkpoint load) | 31.0 s | 6981 MiB |
| txt2img (after /free) | 26.7 s | 6949 MiB |
| IP-Adapter, 1 reference | 35.4 s | 6853 MiB |
| IP-Adapter, 2 references | 51.2 s | 6597 MiB |
| character sheets (turnaround + expressions) | ~25 s each | — |

Cost per page (budget counters): mock LLM → $0. With a real vision Editor, estimate ≈ 3 images ×
~1k tokens + ~1.5k text per review ≈ 5k in / 0.6k out tokens; with Claude Opus 5.5 ($4/$20 per MTok)
≈ $0.03 per review, ≈ $0.2 per 5-panel page at ~1.4 reviews per panel (to be measured with a key).

- **M3 Attempts UI** (`components/QualityLoop.tsx`): a "Quality loop" entry in the Agent timeline
  (the Editor's reviews grouped instead of one timeline step per review) with accepted /
  needs-review counts, budget meters (LLM calls, cost, GPU time), filters, and per panel the
  attempts side by side: status stamps, combined-score gauge with the threshold marker, Editor/CLIP
  sub-scores, 9 criterion bars (failures in amber), problems, the Editor's reasoning as a speech
  balloon, suggested fix, and the fix applied between attempts; lightbox zoom. Reader gallery shows
  each panel's Editor status. `/jobs/<id>?tab=quality` deep link. Jobs are reloaded from
  `output/*/project.json` at startup (finished mangas survive a server restart). Verified in
  headless Edge against the real ComfyUI run; tsc + eslint clean.

- **M4 Canvas editor + bubble editing**: lettering stored as layers (`pipeline/bubbles.py`), pages
  rendered from them (thought bubbles added), editor API (`routes_editor.py`: page geometry, save →
  re-render page + PDFs, auto-place), "✎ Edit" tab with a react-konva canvas (`components/editor/`):
  panel art cover-fitted like the renderer, drag / resize / tail handle / double-click to edit,
  5 bubble types, speaker, max font size with auto-fit, vertical text, add/delete, local undo/redo,
  rendered-page preview. Browser smoke test `scripts/ui_smoke.py` (Playwright + installed Edge):
  select, drag, edit, save → stored, no console errors. 9 tests.

### Next
- M5 panel instructions (Panel Revision agent).

### Known issues
- No LLM key on this machine: the Editor runs as the mock (it can't see real flaws such as the
  duplicated heads two-reference IP-Adapter sometimes draws). Real providers are tested with fakes.
- Windows Application Control blocks newly installed DLLs on first load (allowed on the next load).
  If ComfyUI fails to start right after installing packages, start it again.
- `uvicorn --reload` hangs on Windows while the browser keeps connections open (old worker keeps
  serving). Restart the backend instead of relying on reload during development.
- Only ~1.3 GB of the 16 GB system RAM was free while ComfyUI ran (checkpoint offloading); close other
  apps for long runs.

---

## Phase 1 + 2 (agents, character bible, consistency) — all milestones M0–M8 done

`python scripts/tasks.py test` → 124 passed, 2 skipped (opt-in real-CLIP test, integration test).

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

- **M5** Reference sheets (`agents/sheets.py`): per main character a turnaround (front/side/back,
  1216×832) and an expression sheet (neutral/happy/angry/sad/surprised, 1536×640), each from the
  fixed seed stored in the bible, cropped into individual references (column split + autocrop).
  Per-project cast store (`agents/cast_store.py`, `output/projects/<id>/`): approved characters
  are saved with their images and reused by later chapters (`project_id`): the Character
  Designer skips them, same tags and seeds. Approval node + gate in the graph (auto-approve, or
  pause with status awaiting_approval). `GET /api/projects`. 113 tests passing.

- **M6** Cast approval: endpoints (`routes_cast.py`) to approve one/all, regenerate a sheet with a
  new reproducible seed (queued on the single GPU worker, version-numbered files), edit description
  and visual tags (needs re-approval). Approving the last main character re-queues the job; it
  resumes from project.json at the approval gate. Cast page (`components/CastView.tsx`): bible,
  turnaround + expression sheets with crops and seeds, New seed / Edit / Approve buttons,
  'Approve all & draw panels'. Auto-approve per job or via AUTO_APPROVE. Verified in headless Edge.
  Fixed: `tasks.py dev` now kills the whole process tree on Windows (orphaned uvicorn reload
  workers were holding ports and serving stale code).

- **M7** IP-Adapter panels: prompts carry the emotion-matched expression crop (or front view) of up
  to 2 characters; the ComfyUI provider picks ipadapter_1ref / ipadapter_2ref (reduced weight for
  2) with configurable weight; verified end to end against a fake ComfyUI (sheets via txt2img,
  /free between stages). Consistency score (`vision/consistency.py`): CLIP ViT-B/32 embeddings on
  CPU, cosine similarity per character, stored per panel and shown in the Reader gallery; simple
  fallback without torch. Measured on this laptop (CPU): first CLIP load ~106 s incl. download,
  then ~1 s per comparison; same mock character 0.84 vs unrelated scenery 0.54.

- **M8** Three sample stories (`samples/stories/`: action, emotional drama, comedy) run end to end
  with `python scripts/tasks.py sample`; outputs committed in `samples/output/<story>/` (mock LLM +
  mock images + real CLIP scores: 0.64–0.88 per panel, avg ≈0.75). Integration test
  (`tests/test_integration.py`) auto-skips without ComfyUI or an LLM key. Docker updated
  (workflows copied, optional CLIP build arg, samples mounted). README rewritten (agents,
  consistency, providers, ComfyUI, UI tour, tests, API). Final browser run: drama story →
  cast approval → reader with consistency badges, no console errors.
- Timings in mock mode (this laptop): agents + mock images + layout ≈3 s per 10-panel story; CLIP
  consistency ≈60 s per CLI run, of which ≈35 s is the `transformers` import on Windows (the
  server preloads it in the background at startup, so jobs only pay ≈15–25 s of embedding).
  Real SDXL timings/VRAM still need measuring (`comfy_check --generate` records them).

### Known issues / measurements
- **Not yet run against real services**: no ComfyUI install and no LLM key on this machine.
  Claude, Gemini, OpenAI-compatible and ComfyUI/IP-Adapter paths are tested with fakes that
  follow the documented APIs. First real things to check: `comfy_check --generate`, then one
  story with a real LLM (`pytest tests/test_integration.py -s`).
- Mock-mode heuristics are simple (names = capitalised words, one setting per page); real
  agents do this properly.
- Multi-character panels apply both IP-Adapter references to the whole image (no regional
  masks yet) — see DECISIONS.md #40.
- Jobs live in memory: restarting the server forgets job status (project folders remain on disk).
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
