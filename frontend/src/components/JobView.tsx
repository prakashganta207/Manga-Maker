"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Job, type Stage } from "@/lib/api";
import Reader from "./Reader";

const POLL_MS = 1000;

const STAGE_LABELS: Record<string, string> = {
  script: "Writing the script (LLM)",
  characters: "Character sheets",
  panels: "Drawing panels (image model)",
  layout: "Layout & lettering",
  export: "Export PNG + PDF",
};

export default function JobView({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the job status until it is done or failed.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.getJob(id);
        if (cancelled) return;
        setJob(next);
        setError(null);
        if (next.status === "queued" || next.status === "running") timer = setTimeout(poll, POLL_MS);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        timer = setTimeout(poll, POLL_MS * 3);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id]);

  if (!job) {
    return (
      <div className="panel p-6">
        {error ? <p className="text-red-800">Could not load job: {error}</p> : <p>Loading job…</p>}
      </div>
    );
  }

  if (job.status === "done" && job.result) {
    return <Reader jobId={job.id} result={job.result} />;
  }

  return (
    <div className="panel space-y-5 p-6">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-black">
          {job.status === "failed" ? "Something went wrong" : job.status === "queued" ? "Waiting in queue…" : "Making your manga…"}
        </h1>
        <span className="font-mono text-sm text-ink/60">job {job.id}</span>
      </div>

      <ProgressBar value={job.progress} failed={job.status === "failed"} />

      <ol className="space-y-3">
        {job.stages.map((stage) => (
          <StageRow key={stage.name} stage={stage} />
        ))}
      </ol>

      {job.status === "failed" && (
        <div className="space-y-3">
          <pre className="whitespace-pre-wrap border-2 border-red-700 bg-red-50 p-3 text-sm text-red-800">{job.error}</pre>
          <Link href="/" className="btn">
            ← Try another story
          </Link>
        </div>
      )}
      {error && <p className="text-sm text-red-800">Connection problem: {error} (retrying)</p>}
    </div>
  );
}

function ProgressBar({ value, failed }: { value: number; failed?: boolean }) {
  return (
    <div className="h-4 w-full border-2 border-ink bg-white" role="progressbar" aria-valuenow={Math.round(value * 100)}>
      <div
        className={`h-full transition-all duration-500 ${failed ? "bg-red-700" : "bg-ink"}`}
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

function StageRow({ stage }: { stage: Stage }) {
  const icon = { pending: "○", running: "◐", done: "●", failed: "✕" }[stage.status];
  return (
    <li className="grid grid-cols-[1.5rem_1fr_3.5rem] items-center gap-3">
      <span className={`text-lg ${stage.status === "running" ? "animate-spin" : ""} ${stage.status === "failed" ? "text-red-700" : ""}`}>
        {icon}
      </span>
      <div>
        <div className={`font-semibold ${stage.status === "pending" ? "text-ink/40" : ""}`}>
          {STAGE_LABELS[stage.name] ?? stage.name}
        </div>
        {stage.message && <div className="text-xs text-ink/60">{stage.message}</div>}
        {stage.status === "running" && (
          <div className="mt-1 h-1.5 w-full bg-tone">
            <div className="h-full bg-ink transition-all" style={{ width: `${Math.round(stage.progress * 100)}%` }} />
          </div>
        )}
      </div>
      <span className="text-right font-mono text-sm">{Math.round(stage.progress * 100)}%</span>
    </li>
  );
}
