"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import { useState } from "react";
import { api, jobFileUrl, type EditorPanel, type Job, type MangaProject } from "@/lib/api";
import type { MaskTool } from "./PageCanvas";

const SUGGESTIONS = ["make the emotion stronger", "camera from below", "zoom in on the face", "wide shot, show the place", "add rain"];

export default function PanelTools({
  job,
  project,
  page,
  panel,
  onQueued,
  onError,
}: {
  job: Job;
  project: MangaProject;
  page: number;
  panel: EditorPanel;
  mask: MaskTool | null;
  setMask: (m: MaskTool | null) => void;
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
    </div>
  );
}
