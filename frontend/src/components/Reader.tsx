"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { downloadFile, fileUrl, type Direction, type JobResult } from "@/lib/api";

const DIRECTION_KEY = "manga-reading-direction";

function slug(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "manga";
}

export default function Reader({ jobId, result }: { jobId: string; result: JobResult }) {
  // Remember the reader's preferred direction (per browser). The reader only renders
  // in the browser (after the job is fetched), so localStorage is available here.
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
  const pages = result.outputs[direction].pages;
  const pageCount = pages.length;

  const next = useCallback(() => setPageIndex((i) => Math.min(pageCount - 1, i + 1)), [pageCount]);
  const prev = useCallback(() => setPageIndex((i) => Math.max(0, i - 1)), []);

  // Arrow keys: in right-to-left manga, "left" means the next page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
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

  const base = `${slug(result.title)}-${direction}`;
  const pageNumber = pageIndex + 1;

  // Left/right buttons swap meaning with the reading direction.
  const leftButton = rtl
    ? { label: "Next ←", onClick: next, disabled: pageIndex >= pageCount - 1 }
    : { label: "← Previous", onClick: prev, disabled: pageIndex === 0 };
  const rightButton = rtl
    ? { label: "→ Previous", onClick: prev, disabled: pageIndex === 0 }
    : { label: "Next →", onClick: next, disabled: pageIndex >= pageCount - 1 };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black">{result.title}</h1>
          <p className="text-sm text-ink/60">
            {result.page_count} page(s) · {result.panel_count} panels · LLM: {result.providers.llm} · images:{" "}
            {result.providers.image}
          </p>
        </div>
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
        <img
          key={pages[pageIndex]}
          src={fileUrl(pages[pageIndex])}
          alt={`Page ${pageNumber} of ${result.title}`}
          className="mx-auto h-auto w-full max-w-3xl bg-white"
        />
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
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={() => download(result.outputs[direction].pdf, `${base}.pdf`, "pdf")}
          >
            {busy === "pdf" ? "Downloading…" : "PDF · all pages"}
          </button>
        </div>
        {downloadError && <p className="text-sm text-red-800">{downloadError}</p>}
      </section>

      {result.characters.length > 0 && (
        <section className="panel space-y-3 p-4">
          <h2 className="text-lg font-bold">Character sheets</h2>
          <p className="text-sm text-ink/60">
            Each description is repeated in every panel prompt to keep characters looking the same.
          </p>
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {result.characters.map((c) => (
              <figure key={c.name} className="border-2 border-ink bg-white p-2">
                {c.reference_image_url && (
                  <img src={fileUrl(c.reference_image_url)} alt={`${c.name} reference`} className="aspect-square w-full object-cover" />
                )}
                <figcaption className="mt-2 text-sm">
                  <b>{c.name}</b> — {c.description}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-wrap gap-4 text-sm">
        <a className="underline underline-offset-4" href={fileUrl(result.script_url)} target="_blank" rel="noreferrer">
          View script JSON
        </a>
        <a className="underline underline-offset-4" href={fileUrl(result.prompts_url)} target="_blank" rel="noreferrer">
          View image prompts
        </a>
        <span className="font-mono text-ink/50">job {jobId}</span>
        <Link href="/" className="ml-auto font-semibold underline underline-offset-4">
          ← Make another
        </Link>
      </div>
    </div>
  );
}
