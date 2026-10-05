# Phase 3–5 Plan — Quality loop, human-in-the-loop editor, pro features

Upgrade of the Phase 1+2 app (see PHASE_1_2_PLAN.md). We keep the LangGraph pipeline,
`MangaProject` state, providers, workflow templates, job queue and UI, and extend them.

## Environment found at start (2026-10-06)
- Phase 1+2 verified: `python scripts/tasks.py test` → 124 passed, 2 skipped; the drama sample
  story runs end to end in mock mode in ~3 s. Nothing broken.
- GPU: RTX 4060 Laptop, 8 GB (idle). Python 3.14 only. Node 25. 425 GB free on E:.
- No `.env`, no LLM keys → the Editor / Panel Revision / Writer summary agents run on the mock
  LLM; real vision providers are tested with fakes that follow the documented APIs.
- ComfyUI was **not installed**. New: it is installed **inside the project** (`comfyui/`,
  git-ignored) with its own venv + CUDA torch, IP-Adapter Plus and controlnet_aux custom nodes,
  so new workflows can be checked against `/object_info` and measured (VRAM, time) for real.

## Target pipeline

```
story (+ story so far, for chapter 2+)
  ├─ Writer ─────────── beat sheet, page plan
  ├─ Director ───────── layouts, shots
  ├─ Character Designer ─ bible, sheets, ⏸ cast approval (reused cast + LoRA for later chapters)
  ├─ Prompt builder
  ├─ Storyboard (new) ── fast low-res rough → pose / line-art control image per panel
  ├─ Panels ─────────── ComfyUI + IP-Adapter (+ ControlNet from the rough, + character LoRA)
  │    └─ Editor loop (new): vision LLM scores each panel (9 criteria) + CLIP score
  │         → pass, or redraw with the Editor's fixes (max 3 attempts, job budgets)
  │         → best attempt kept, "needs review" when limits hit
  ├─ Letterer (new) ─── face-aware bubble placement, reading order, tails at faces,
  │                      vertical/horizontal text, comic fonts, styled SFX → editable layers
  ├─ Layout ─────────── pages rendered from the editable lettering layers
  ├─ Export ─────────── PNG, PDF, CBZ, webtoon strip
  └─ Writer summary ─── "story so far" for the next chapter
After the run (human in the loop): canvas editor → bubble edits, panel instructions
(Panel Revision agent → Editor loop), inpainting, locks, versions with undo/redo.
```

## Milestones

### Phase 3 — Editor agent with a quality loop
- **M1 Editor agent + schemas**: vision support in every LLM provider (images in the request),
  `EditorReview` schema (9 criteria scored 1–5, pass/fail, problems, concrete fix), mock vision
  Editor, combined score = Editor score ⊕ CLIP score with a documented configurable threshold.
- **M2 Redraw loop + budgets**: `PanelAttempt` history in the job state; failed panels redrawn
  with the Editor's fixes (prompt changes, negative additions, IP-Adapter weight, seed); max 3
  attempts per panel; per-job budgets for LLM calls, LLM cost and GPU seconds from `.env`;
  best attempt kept and marked "needs human review" when limits hit.
- **M3 Attempts UI**: in the Agent timeline, a "Quality loop" view with every panel's attempts
  side by side, score bars per criterion, the Editor's reasoning and fixes, accepted / rejected /
  needs review markers, budget meters.

### Phase 4 — Interactive editor
- **M4 Canvas editor + bubble editing**: lettering becomes stored, editable layers in the job
  state (bubbles, narration boxes, SFX, positions relative to the panel); react-konva page
  editor (drag, resize, edit text, change type, drag the tail); saving re-renders the pages.
- **M5 Panel instructions**: Panel Revision agent turns "make her angrier" into an updated
  panel spec + prompt; the panel regenerates through the normal pipeline + Editor loop.
- **M6 Inpainting**: paint a mask on a panel, describe the region, regenerate only that region
  (ComfyUI inpaint workflow, IP-Adapter when the region holds a character).
- **M7 Lock + version history**: lock panels / characters' looks against automatic redraws;
  every change makes a version; undo / redo; per-panel version list with restore.
  Long actions report progress through the job status API (polling, as today).

### Phase 5 — Pro features and polish
- **M8 Letterer + face detection**: anime face detector (lbpcascade_animeface, OpenCV; estimated
  positions as fallback), bubbles placed away from faces in reading order, tails to the
  speaker's face, vertical/horizontal text, auto-fit font size, styled SFX, OFL comic fonts.
- **M9 ControlNet storyboard**: rough low-res image per panel → OpenPose (line-art fallback)
  control image → ControlNet guidance on the final panel; strength configurable; rough + control
  image shown in the timeline; measured 8 GB limits documented.
- **M10 Character LoRA training**: dataset from approved references with captions from the fixed
  tags, kohya-ss sd-scripts SDXL LoRA with 8 GB settings, background job with progress/logs,
  `CLOUD_TRAINING.md`; panels use the LoRA automatically (IP-Adapter reduced), before/after scores.
- **M11 Series memory + exports**: projects with chapters, reused cast / LoRAs / style, Writer's
  running "story so far"; project and chapter pages; PNG, PDF, CBZ and webtoon exports.
- **M12 Demo mode + polish + final run**: landing page with pipeline diagram, instant demo
  project (no GPU), consistent styling, loading/error states; final 2-chapter run from
  `samples/stories` with the same cast, saved in `samples/`.

## Working rules
- One phase at a time, tests included. After each milestone: tests → fix → commit → PROGRESS.md
  (done, next, known issues, VRAM/timing, cost per page from the budget counters).
- Mock LLM + mock images keep every unit test GPU-free and key-free. Integration tests skip
  themselves when ComfyUI / an LLM key / training tools are missing.
- Decisions go to DECISIONS.md (#42 onward). Repeated failures go to PROGRESS.md with a fallback.
