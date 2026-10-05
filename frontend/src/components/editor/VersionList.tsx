"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import { useState } from "react";
import { jobFileUrl, type HistorySummary, type MangaProject, type Version } from "@/lib/api";

const KIND_ICON: Record<string, string> = {
  generate: "✦",
  auto_place: "▦",
  bubbles: "💬",
  revision: "✎",
  inpaint: "🖌",
  redraw: "↻",
  auto: "↻",
};

function when(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Every version of one target (a panel or a page's lettering), newest first, with Restore. */
export default function VersionList({
  title,
  history,
  target,
  project,
  disabled,
  onRestore,
}: {
  title: string;
  history: HistorySummary;
  target: string;
  project?: MangaProject;
  disabled?: boolean;
  onRestore: (v: Version) => void;
}) {
  const [open, setOpen] = useState(false);
  const versions = history.versions.filter((v) => v.target === target).reverse();
  const current = history.current[target];
  if (versions.length === 0) return null;
  const shown = open ? versions : versions.slice(0, 3);
  return (
    <div className="mt-3 border-t-2 border-ink/10 pt-3 text-ink">
      <h4 className="mb-1.5 flex items-baseline justify-between text-xs font-black uppercase tracking-wide">
        {title} <span className="font-mono font-normal normal-case text-ink/50">{versions.length}</span>
      </h4>
      <ol className="space-y-1.5">
        {shown.map((v) => {
          const isCurrent = v.id === current;
          return (
            <li key={v.id} className={`flex items-center gap-2 border-2 p-1.5 ${isCurrent ? "border-ink bg-white" : "border-ink/20"}`}>
              {project && v.data.image ? (
                <img src={jobFileUrl(project, v.data.image)} alt="" className="h-10 w-10 shrink-0 border border-ink/40 object-cover" />
              ) : (
                <span className="flex h-10 w-10 shrink-0 items-center justify-center border border-ink/30 text-lg">{KIND_ICON[v.kind] ?? "•"}</span>
              )}
              <div className="min-w-0 flex-1 text-xs">
                <div className="truncate font-bold" title={v.label}>
                  {KIND_ICON[v.kind] ?? "•"} {v.label}
                </div>
                <div className="text-[10px] text-ink/50">
                  v{v.id} · {when(v.created_at)}
                  {v.data.bubbles && ` · ${v.data.bubbles.length} layers`}
                </div>
              </div>
              {isCurrent ? (
                <span className="bg-ink px-1.5 text-[10px] font-black text-paper">CURRENT</span>
              ) : (
                <button type="button" className="border border-ink px-1.5 text-[11px] font-bold hover:bg-ink hover:text-paper disabled:opacity-40" disabled={disabled} onClick={() => onRestore(v)}>
                  Restore
                </button>
              )}
            </li>
          );
        })}
      </ol>
      {versions.length > 3 && (
        <button type="button" className="mt-1 text-[11px] underline" onClick={() => setOpen((o) => !o)}>
          {open ? "Show fewer" : `Show all ${versions.length}`}
        </button>
      )}
    </div>
  );
}
