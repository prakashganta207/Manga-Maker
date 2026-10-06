"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fileUrl, type Series } from "@/lib/api";

export default function SeriesList() {
  const [series, setSeries] = useState<Series[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.series().then(setSeries).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-black">Series</h1>
        <p className="max-w-3xl text-ink/70">
          Every manga starts a series. New chapters reuse the approved cast, character LoRAs and art style, and the Writer keeps a
          running &ldquo;story so far&rdquo; so each chapter remembers what happened before.
        </p>
      </header>
      {error && <p className="border-2 border-red-700 bg-red-50 p-3 text-sm text-red-800">Could not load series: {error}</p>}
      {!series && !error && (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading series">
          {[0, 1, 2].map((i) => (
            <div key={i} className="panel h-72 animate-pulse bg-tone/40" />
          ))}
        </div>
      )}
      {series && series.length === 0 && (
        <div className="panel p-6 text-sm">
          No series yet.{" "}
          <Link href="/" className="font-bold underline">
            Make your first manga →
          </Link>
        </div>
      )}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {series?.map((s) => {
          const cover = s.chapters.find((c) => c.cover);
          return (
            <Link key={s.project_id} href={`/projects/${s.project_id}`} className="panel group block overflow-hidden transition hover:-translate-y-0.5">
              <div className="aspect-[4/3] overflow-hidden border-b-4 border-ink bg-tone">
                {cover?.cover ? (
                  <img src={fileUrl(`/files/${cover.job_id}/${cover.cover}`)} alt="" className="w-full object-cover object-top" />
                ) : (
                  <div className="flex h-full items-center justify-center text-4xl">▦</div>
                )}
              </div>
              <div className="space-y-1 p-3">
                <h2 className="text-lg font-black group-hover:underline">{s.title || s.project_id}</h2>
                <p className="text-xs text-ink/60">
                  {s.chapters.length} chapter{s.chapters.length === 1 ? "" : "s"} · {s.cast.length} in the cast ·{" "}
                  {s.cast.filter((c) => c.lora === "ready").length} LoRA
                </p>
                <p className="line-clamp-3 text-sm text-ink/80">{s.story_so_far || "No summary yet."}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
