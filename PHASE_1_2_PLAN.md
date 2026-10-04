# Phase 1 + 2 Plan — Agents, Character Bible, Visual Consistency

Upgrade of the existing Story-to-Manga app (see PLAN.md for phase 0). We keep the
provider interfaces, job queue, layout/lettering engine, exporter and frontend, and
replace the single "story → script" LLM call with a multi-agent pipeline.

## Environment found at start (2026-10-05)
- GPU: NVIDIA RTX 4060 Laptop, 8 GB VRAM. Python 3.14, Node 25.
- ComfyUI: **not installed / not reachable** at http://127.0.0.1:8188 → write
  `SETUP_COMFYUI.md`, build the real path fully, run everything in mock mode for now.
- No `.env`, no LLM keys → mock LLM for all agents; real providers tested with fakes.

## Target pipeline (LangGraph state graph, state = one `MangaProject` saved per job)

```
story
  ├─ Writer pass 1 ── beat sheet (beats, emotional arc, climax, characters)
  ├─ Writer pass 2 ── page plan (pages → panels: purpose, size, characters, action,
  │                    setting, emotion, dialogue, narration, SFX)
  ├─ Director ─────── layout template per page + shot / angle / composition per panel
  │                    (+ code-enforced rules: shot variety, establishing, close-ups)
  ├─ Character Designer ─ character bible (fixed visual tags, seeds)
  ├─ Reference sheets ─── turnaround (front/side/back) + expressions (5) → cropped refs
  ├─ ⏸ Cast approval ──── waits for the user (or auto-approve), job resumes from disk
  ├─ Prompt builder ───── manga prompt + negative prompt per panel
  ├─ Panels ───────────── ComfyUI + IP-Adapter with the matching character reference
  ├─ Consistency ──────── CLIP similarity panel ↔ character references
  ├─ Layout + lettering ─ (existing engine, now template-driven, + SFX)
  └─ Export ───────────── PNG per page + PDF, RTL default + LTR
```

Every agent step is recorded in a trace (inputs, outputs, retries, duration, tokens,
cost) shown in an "Agent timeline" in the frontend.

## Milestones
- **M0** ComfyUI: reachability + `/object_info` discovery, workflow JSON templates in
  `backend/workflows/`, parameter injection, VRAM freeing (`/free`), one-panel test
  script, `SETUP_COMFYUI.md`.
- **M1** LLM providers in priority order Anthropic → Gemini → OpenAI-compatible → mock;
  `LLMResponse` with token usage; per-job token/cost counter; generic structured-output
  agent runner (Pydantic validation + 2 retries with error feedback); all schemas.
- **M2** Writer agent (beat sheet, page plan with manga pacing rules); LangGraph graph;
  `MangaProject` persistence + resume.
- **M3** Director agent + library of 10 page layout templates + rule enforcement +
  template-driven layout and SFX lettering; prompt builder with shot/angle tags.
- **M4** Frontend: Agent timeline (trace, beat sheet, page plan, director decisions with
  layout thumbnails).
- **M5** Character Designer agent (bible) + reference sheets (turnaround + expressions,
  fixed seeds, cropping) + per-project cast persistence.
- **M6** Cast page: bible + sheets, regenerate (new seed), edit, approve, auto-approve;
  job pauses at approval and resumes.
- **M7** IP-Adapter panel workflows (1 and 2 references, emotion-matched expression ref,
  configurable weight) + CLIP consistency score (shown next to each panel).
- **M8** 3 sample stories (action, drama, comedy) run end to end, outputs in `samples/`;
  integration test (auto-skips without ComfyUI / LLM key); README.

After each milestone: tests → fix → commit → PROGRESS.md (done, next, issues, VRAM/timing).
