"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, fileUrl, type Series } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  done: "✓ done",
  running: "◐ drawing",
  queued: "… queued",
  awaiting_approval: "⏸ cast approval",
  failed: "✕ failed",
};

export default function SeriesView({ id }: { id: string }) {
  const router = useRouter();
  const [series, setSeries] = useState<Series | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [story, setStory] = useState("");
  const [autoApprove, setAutoApprove] = useState(true);
  const [title, setTitle] = useState("");
  const [style, setStyle] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0); // bump to retry loading

  useEffect(() => {
    let cancelled = false;
    api
      .seriesOne(id)
      .then((next) => {
        if (cancelled) return;
        setSeries(next);
        setTitle(next.title);
        setStyle(next.style_tags);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [id, attempt]);

  async function saveSettings() {
    setBusy("settings");
    try {
      setSeries(await api.patchSeries(id, { title, style_tags: style }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function addChapter() {
    setBusy("chapter");
    try {
      const job = await api.newChapter(id, story.trim(), autoApprove);
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  }

  if (error && !series) {
    return (
      <div className="panel space-y-3 p-6">
        <p className="text-red-800">Could not load this series: {error}</p>
        <button type="button" className="btn" onClick={() => setAttempt((n) => n + 1)}>
          Retry
        </button>
      </div>
    );
  }
  if (!series) return <div className="panel h-64 animate-pulse bg-tone/40" aria-busy="true" aria-label="Loading series" />;

  const next = Math.max(0, ...series.chapters.map((c) => c.number)) + 1;
  const loras = series.cast.filter((c) => c.lora === "ready").length;
  return (
    <div className="space-y-6">
      <header>
        <Link href="/projects" className="text-sm underline">
          ← All series
        </Link>
        <h1 className="text-3xl font-black">{series.title || series.project_id}</h1>
        <p className="font-mono text-xs text-ink/60">project {series.project_id}</p>
      </header>
      {error && <p className="text-sm text-red-800">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <section className="space-y-4">
          <h2 className="text-xl font-black">Chapters</h2>
          <ol className="grid gap-4 sm:grid-cols-2">
            {series.chapters.map((c) => (
              <li key={c.job_id}>
                <Link href={`/jobs/${c.job_id}`} className="panel group flex h-full gap-3 p-3 hover:bg-white">
                  <div className="h-32 w-24 shrink-0 overflow-hidden border-2 border-ink bg-tone">
                    {c.cover && <img src={fileUrl(`/files/${c.job_id}/${c.cover}`)} alt="" className="h-full w-full object-cover object-top" />}
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs font-bold uppercase text-ink/60">Chapter {c.number}</div>
                    <div className="font-black group-hover:underline">{c.title || "Untitled"}</div>
                    <div className="text-xs">{STATUS_LABEL[c.status] ?? c.status}</div>
                    {c.summary && <p className="mt-1 line-clamp-4 text-xs text-ink/70">{c.summary}</p>}
                  </div>
                </Link>
              </li>
            ))}
          </ol>

          <div className="panel space-y-3 p-4">
            <h3 className="font-black">Write chapter {next}</h3>
            <p className="text-xs text-ink/60">
              Reuses the approved cast (same tags, seeds and reference sheets{loras ? `, ${loras} LoRA` : ""}), the series style and
              the story so far. Use the same character names.
            </p>
            <textarea
              value={story}
              onChange={(e) => setStory(e.target.value)}
              rows={6}
              placeholder="What happens next?"
              className="w-full border-2 border-ink bg-white p-2 text-sm"
              aria-label="Next chapter story"
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} /> Auto-approve new
              characters
            </label>
            <button type="button" className="btn btn-primary" disabled={story.trim().length < 20 || busy !== null} onClick={addChapter}>
              {busy === "chapter" ? "Starting…" : `Make chapter ${next} →`}
            </button>
          </div>
        </section>

        <aside className="space-y-4">
          <section className="panel space-y-2 p-4 text-sm">
            <h3 className="font-black">Story so far</h3>
            <p className="whitespace-pre-line text-ink/80">{series.story_so_far || "The Writer writes this after the first chapter."}</p>
            {series.open_threads.length > 0 && (
              <>
                <h4 className="pt-2 text-xs font-black uppercase">Open threads</h4>
                <ul className="list-disc pl-5 text-ink/80">
                  {series.open_threads.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
          <section className="panel space-y-2 p-4 text-sm">
            <h3 className="font-black">Cast</h3>
            <ul className="space-y-2">
              {series.cast.map((c) => (
                <li key={c.name} className="flex items-center gap-2">
                  <div className="h-12 w-10 shrink-0 overflow-hidden border border-ink bg-tone">
                    {c.image && (
                      <img src={fileUrl(`/files/projects/${series.project_id}/${c.image}`)} alt="" className="h-full w-full object-cover" />
                    )}
                  </div>
                  <div className="min-w-0 text-xs">
                    <b className="text-sm">{c.name}</b> · {c.role}
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {c.look_locked && <span className="bg-ink px-1 text-paper">🔒 look</span>}
                      {c.lora === "ready" && <span className="border border-ink px-1">LoRA · {c.lora_trainer}</span>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel space-y-2 p-4 text-sm">
            <h3 className="font-black">Series settings</h3>
            <label className="block text-xs">
              <b>Title</b>
              <input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-0.5 w-full border-2 border-ink p-1" />
            </label>
            <label className="block text-xs">
              <b>Art style tags</b> (added to every panel prompt)
              <input
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                placeholder="e.g. heavy shadows, thick lines"
                className="mt-0.5 w-full border-2 border-ink p-1"
              />
            </label>
            <button type="button" className="btn" disabled={busy !== null} onClick={saveSettings}>
              {busy === "settings" ? "Saving…" : "Save"}
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
