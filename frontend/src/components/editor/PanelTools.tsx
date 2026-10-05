"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import { useState } from "react";
import { api, jobFileUrl, type EditorPanel, type Job, type MangaProject } from "@/lib/api";
import type { MaskState } from "./PageCanvas";

const SUGGESTIONS = ["make the emotion stronger", "camera from below", "zoom in on the face", "wide shot, show the place", "add rain"];

export default function PanelTools({
  job,
  project,
  page,
  panel,
  mask,
  setMask,
  onQueued,
  onError,
}: {
  job: Job;
  project: MangaProject;
  page: number;
  panel: EditorPanel;
  mask: MaskState | null;
  setMask: (m: MaskState | null) => void;
  onQueued: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [sending, setSending] = useState(false);
  const result = project.panels.find((r) => r.page === page && r.panel === panel.panel);
  const busy = !!job.busy || job.status !== "done";

  async function revise() {
    if (instruction.trim().length < 2) return;
    setSending(true);
    try {
      await api.revisePanel(job.id, page, panel.panel, instruction.trim());
      onQueued(`Revising panel ${panel.panel}: “${instruction.trim()}”. The Editor reviews the new drawing too.`);
      setInstruction("");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="panel space-y-3 p-4 text-sm">
      <div className="flex items-start gap-3">
        {result?.image && (
          <img src={jobFileUrl(project, result.image, job.updated_at)} alt="" className="h-16 w-16 shrink-0 border-2 border-ink object-cover" />
        )}
        <div className="min-w-0">
          <h3 className="font-black">Panel {panel.panel}</h3>
          <p className="line-clamp-3 text-xs text-ink/70">{panel.action}</p>
          {result && (
            <p className="mt-0.5 text-[11px] text-ink/50">
              {result.status.replace("_", " ")} · {result.attempts.length} attempt(s) · <i>{panel.emotion}</i>
            </p>
          )}
        </div>
      </div>

      <section className="space-y-2 border-t-2 border-ink/10 pt-3">
        <h4 className="text-xs font-black uppercase tracking-wide">Tell the director</h4>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) revise();
          }}
          rows={2}
          maxLength={300}
          placeholder='e.g. "make her angrier", "camera from below"'
          className="w-full border-2 border-ink bg-white p-2"
          disabled={busy}
        />
        <div className="flex flex-wrap gap-1">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" disabled={busy} onClick={() => setInstruction(s)} className="border border-ink/40 px-1.5 text-[11px] hover:bg-white">
              {s}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-primary w-full justify-center" onClick={revise} disabled={busy || sending || instruction.trim().length < 2}>
          {sending ? "Sending…" : "Redraw with this note"}
        </button>
        <p className="text-[11px] text-ink/50">
          The Panel Revision agent rewrites the panel spec, then the panel is redrawn and checked by the Editor.
        </p>
      </section>

      <InpaintSection job={job} page={page} panel={panel} mask={mask} setMask={setMask} busy={busy} onQueued={onQueued} onError={onError} />
    </div>
  );
}

function InpaintSection({
  job,
  page,
  panel,
  mask,
  setMask,
  busy,
  onQueued,
  onError,
}: {
  job: Job;
  page: number;
  panel: EditorPanel;
  mask: MaskState | null;
  setMask: (m: MaskState | null) => void;
  busy: boolean;
  onQueued: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [region, setRegion] = useState("");
  const [character, setCharacter] = useState("auto");
  const [strength, setStrength] = useState(0.9);
  const [sending, setSending] = useState(false);
  const active = mask?.panel === panel.panel;

  async function send() {
    if (!mask || !mask.strokes.length || region.trim().length < 2) return;
    // Page pixels -> fractions of the panel's slot (the backend maps them onto the panel image).
    const r = panel.rect;
    const strokes = mask.strokes.map((s) => ({
      points: s.points.map((v, i) => (i % 2 === 0 ? (v - r.x) / r.w : (v - r.y) / r.h)),
      size: s.size / r.w,
      erase: s.erase,
    }));
    setSending(true);
    try {
      await api.inpaintPanel(job.id, page, panel.panel, { strokes, prompt: region.trim(), character, denoise: strength });
      onQueued(`Inpainting panel ${panel.panel}: “${region.trim()}”. Only the painted area is redrawn.`);
      setMask(null);
      setRegion("");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  if (!active) {
    return (
      <section className="space-y-2 border-t-2 border-ink/10 pt-3">
        <h4 className="text-xs font-black uppercase tracking-wide">Fix one region (inpainting)</h4>
        <button
          type="button"
          className="btn w-full justify-center"
          disabled={busy}
          onClick={() => setMask({ panel: panel.panel, brush: 40, erase: false, strokes: [] })}
        >
          🖌 Paint a region to redraw
        </button>
      </section>
    );
  }

  return (
    <section className="space-y-2 border-t-2 border-ink/10 pt-3">
      <h4 className="text-xs font-black uppercase tracking-wide">Paint the region on the page</h4>
      <p className="text-[11px] text-ink/60">Red = will be redrawn. Everything else in the panel stays exactly the same.</p>
      <div className="flex items-center gap-2">
        <div className="flex border-2 border-ink" role="group" aria-label="Brush mode">
          {[
            [false, "Paint"],
            [true, "Erase"],
          ].map(([erase, label]) => (
            <button
              key={String(label)}
              type="button"
              onClick={() => setMask({ ...mask!, erase: erase as boolean })}
              className={`px-2 py-0.5 text-xs font-bold ${mask!.erase === erase ? "bg-ink text-paper" : "bg-paper"}`}
            >
              {label as string}
            </button>
          ))}
        </div>
        <label className="flex flex-1 items-center gap-1 text-xs">
          Brush
          <input
            type="range"
            min={8}
            max={160}
            value={mask!.brush}
            onChange={(e) => setMask({ ...mask!, brush: Number(e.target.value) })}
            className="flex-1 accent-black"
            aria-label="Brush size"
          />
        </label>
        <button type="button" className="text-xs underline" onClick={() => setMask({ ...mask!, strokes: [] })}>
          Clear
        </button>
      </div>
      <input
        value={region}
        onChange={(e) => setRegion(e.target.value)}
        maxLength={300}
        placeholder='What should be there? e.g. "a surprised face"'
        className="w-full border-2 border-ink bg-white p-2"
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs">
          <span className="font-bold uppercase text-ink/60">Character</span>
          <select value={character} onChange={(e) => setCharacter(e.target.value)} className="mt-0.5 w-full border-2 border-ink bg-white p-1">
            <option value="auto">Auto (face under mask)</option>
            <option value="">Nobody</option>
            {panel.characters.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="flex justify-between font-bold uppercase text-ink/60">
            Strength <span className="font-mono">{strength.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min={0.3}
            max={1}
            step={0.05}
            value={strength}
            onChange={(e) => setStrength(Number(e.target.value))}
            className="mt-1.5 w-full accent-black"
            aria-label="Inpainting strength"
          />
        </label>
      </div>
      <div className="flex gap-2">
        <button type="button" className="btn flex-1 justify-center" onClick={() => setMask(null)}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary flex-1 justify-center"
          disabled={busy || sending || !mask!.strokes.length || region.trim().length < 2}
          onClick={send}
        >
          {sending ? "Sending…" : "Redraw region"}
        </button>
      </div>
      <p className="text-[11px] text-ink/50">
        The character&apos;s reference sheet guides the region (IP-Adapter) when a character is chosen. Strength 1 redraws from
        scratch; lower keeps more of the old drawing.
      </p>
    </section>
  );
}
