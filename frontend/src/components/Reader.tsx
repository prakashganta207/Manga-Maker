"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { downloadFile, fileUrl, jobFileUrl, type Direction, type JobResult, type MangaProject } from "@/lib/api";
import { SHOT_ABBR } from "./LayoutThumb";

const DIRECTION_KEY = "manga-reading-direction";

function slug(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "manga";
}

export function ScoreBadge({ score, method }: { score: number | undefined; method?: string }) {
  if (score === undefined) return <span className="border border-ink/30 px-1 text-[10px] text-ink/50">no score</span>;
  // CLIP image similarity: ~0.85+ looks like the same character, below ~0.7 likely drifted.
  const tone = score >= 0.85 ? "bg-ink text-paper" : score >= 0.7 ? "bg-tone text-ink" : "bg-amber-200 text-amber-950";
  return (
    <span className={`px-1.5 font-mono text-[11px] font-bold ${tone}`} title={`${method || "similarity"} score`}>
      {score.toFixed(2)}
    </span>
  );
}

export default function Reader({ jobId, result, project }: { jobId: string; result: JobResult; project: MangaProject | null }) {
  // Remember the reader's preferred direction (per browser). Rendered client-side only.
  const [direction, setDirection] = useState<Direction>(() => {
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem(DIRECTION_KEY) : null;
      return saved === "ltr" ? "ltr" : "rtl";
    } catch {
      return "rtl";
    }
  });
  const [pageIndex, setPageIndex] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const rtl = direction === "rtl";
  const output = result.outputs[direction] ?? { pages: [], pdf: null };
  const pages = output.pages;
  const pageCount = pages.length;

  const next = useCallback(() => setPageIndex((i) => Math.min(pageCount - 1, i + 1)), [pageCount]);
  const prev = useCallback(() => setPageIndex((i) => Math.max(0, i - 1)), []);

  // Arrow keys: in right-to-left manga, "left" means the next page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowLeft") (rtl ? next : prev)();
      if (e.key === "ArrowRight") (rtl ? prev : next)();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rtl, next, prev]);

  function toggleDirection() {
    const value: Direction = rtl ? "ltr" : "rtl";
    setDirection(value);
    try {
      localStorage.setItem(DIRECTION_KEY, value);
    } catch {
      /* ignore */
    }
  }

  async function download(url: string, filename: string, label: string) {
    setBusy(label);
    setDownloadError(null);
    try {
      await downloadFile(url, filename);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (pageCount === 0) return <div className="panel p-6">No pages yet.</div>;
  const base = `${slug(result.title)}-${direction}`;
  const pageNumber = pageIndex + 1;
  const leftButton = rtl
    ? { label: "Next ←", onClick: next, disabled: pageIndex >= pageCount - 1 }
    : { label: "← Previous", onClick: prev, disabled: pageIndex === 0 };
  const rightButton = rtl
    ? { label: "→ Previous", onClick: prev, disabled: pageIndex === 0 }
    : { label: "Next →", onClick: next, disabled: pageIndex >= pageCount - 1 };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="text-sm text-ink/60">
          {result.page_count} page(s) · {result.panel_count} panels · LLM: {result.providers.llm} · images: {result.providers.image}
          {result.usage.cost_usd > 0 && ` · $${result.usage.cost_usd.toFixed(4)}`}
          {result.quality && ` · Editor: ${result.quality.accepted} accepted, ${result.quality.needs_review} need review`}
        </p>
        <label className="flex cursor-pointer select-none items-center gap-3 font-semibold">
          <span className={rtl ? "text-ink/40" : ""}>Left → right</span>
          <button
            type="button"
            role="switch"
            aria-checked={rtl}
            aria-label="Right-to-left reading order"
            onClick={toggleDirection}
            className="relative h-7 w-14 border-2 border-ink bg-white"
          >
            <span className={`absolute top-0.5 h-5 w-6 bg-ink transition-all ${rtl ? "left-[1.6rem]" : "left-0.5"}`} />
          </button>
          <span className={rtl ? "" : "text-ink/40"}>Right ← left (manga)</span>
        </label>
      </div>

      {result.warnings.length > 0 && (
        <ul className="border-2 border-amber-700 bg-amber-50 p-3 text-sm text-amber-900">
          {result.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}

      <div className="panel p-3">
        <img key={pages[pageIndex]} src={fileUrl(pages[pageIndex])} alt={`Page ${pageNumber} of ${result.title}`} className="mx-auto h-auto w-full max-w-3xl bg-white" />
        <div className="mt-3 flex items-center justify-between">
          <button type="button" className="btn" onClick={leftButton.onClick} disabled={leftButton.disabled}>
            {leftButton.label}
          </button>
          <span className="font-mono">
            page {pageNumber} / {pageCount}
          </span>
          <button type="button" className="btn" onClick={rightButton.onClick} disabled={rightButton.disabled}>
            {rightButton.label}
          </button>
        </div>
      </div>

      <section className="panel space-y-3 p-4">
        <h2 className="text-lg font-bold">Download ({rtl ? "right-to-left" : "left-to-right"})</h2>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={() => download(pages[pageIndex], `${base}-page-${String(pageNumber).padStart(2, "0")}.png`, "png")}
          >
            {busy === "png" ? "Downloading…" : `PNG · page ${pageNumber}`}
          </button>
          {pageCount > 1 && (
            <button
              type="button"
              className="btn"
              disabled={busy !== null}
              onClick={async () => {
                for (const [i, url] of pages.entries()) {
                  await download(url, `${base}-page-${String(i + 1).padStart(2, "0")}.png`, "all");
                }
              }}
            >
              {busy === "all" ? "Downloading…" : `All ${pageCount} PNGs`}
            </button>
          )}
          {output.pdf && (
            <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => download(output.pdf!, `${base}.pdf`, "pdf")}>
              {busy === "pdf" ? "Downloading…" : "PDF · all pages"}
            </button>
          )}
        </div>
        {downloadError && <p className="text-sm text-red-800">{downloadError}</p>}
      </section>

      {project && project.panels.length > 0 && <PanelGallery project={project} page={pageNumber} />}

      <div className="flex flex-wrap gap-4 text-sm">
        {result.project_url && (
          <a className="underline underline-offset-4" href={fileUrl(result.project_url)} target="_blank" rel="noreferrer">
            View full agent state (project.json)
          </a>
        )}
        <span className="font-mono text-ink/50">job {jobId}</span>
        <Link href="/" className="ml-auto font-semibold underline underline-offset-4">
          ← Make another
        </Link>
      </div>
    </div>
  );
}

function QualityPill({ panel }: { panel: MangaProject["panels"][number] }) {
  if (!panel.attempts?.length) return null;
  const chosen = panel.attempts.find((a) => a.attempt === panel.chosen_attempt);
  const tone =
    panel.status === "accepted"
      ? "bg-ink text-paper"
      : panel.status === "needs_review"
        ? "bg-amber-300 text-amber-950 border border-amber-800"
        : "border border-ink/40";
  const label = panel.status === "accepted" ? "✓ Editor accepted" : panel.status === "needs_review" ? "⚑ Needs review" : "Unreviewed";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={`px-1.5 text-[10px] font-black uppercase ${tone}`}>{label}</span>
      {chosen?.quality && <span className="font-mono text-[10px]">score {chosen.quality.combined.toFixed(2)}</span>}
      <span className="text-[10px] text-ink/50">
        {panel.attempts.length} attempt{panel.attempts.length > 1 ? "s" : ""}
      </span>
    </div>
  );
}

function PanelGallery({ project, page }: { project: MangaProject; page: number }) {
  const directed = project.director?.pages[page - 1]?.panels ?? [];
  const panels = project.panels.filter((p) => p.page === page).sort((a, b) => a.panel - b.panel);
  const prompts = project.prompts.filter((p) => p.page === page);
  return (
    <section className="panel space-y-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">Panels on page {page} — character consistency</h2>
        <span className="text-xs text-ink/60">
          Score = CLIP image similarity between the panel and the character&apos;s reference images.
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {panels.map((p) => {
          const shot = directed[p.panel - 1];
          const prompt = prompts.find((x) => x.panel === p.panel);
          return (
            <figure key={p.panel} className="border-2 border-ink bg-white p-2">
              <img src={jobFileUrl(project, p.image)} alt={`Panel ${p.panel}`} className="aspect-[4/3] w-full bg-tone object-cover" />
              <figcaption className="mt-2 space-y-1 text-xs">
                <div className="flex items-center justify-between">
                  <b>
                    Panel {p.panel} {shot && `· ${SHOT_ABBR[shot.shot]} · ${shot.angle}`}
                  </b>
                  <span className="font-mono text-ink/50">{p.seconds.toFixed(1)}s</span>
                </div>
                <QualityPill panel={p} />
                <div className="flex flex-wrap gap-1.5">
                  {(prompt?.characters ?? []).map((name) => (
                    <span key={name} className="flex items-center gap-1 border border-ink/30 px-1">
                      {name} <ScoreBadge score={p.consistency[name]} method={p.consistency_method} />
                    </span>
                  ))}
                </div>
                {prompt && prompt.reference_kinds.length > 0 && (
                  <div className="text-ink/60">IP-Adapter refs: {prompt.reference_kinds.join(", ")}</div>
                )}
                {prompt && (
                  <details>
                    <summary className="cursor-pointer text-ink/60">Prompt (seed {prompt.seed})</summary>
                    <p className="mt-1 break-words font-mono text-[10px]">{prompt.prompt}</p>
                  </details>
                )}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}
