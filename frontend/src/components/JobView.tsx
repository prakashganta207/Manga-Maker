"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type LayoutTemplate, type MangaProject, type Stage } from "@/lib/api";
import AgentTimeline from "./AgentTimeline";
import CastView from "./CastView";
import Reader from "./Reader";

const POLL_MS = 1000;

const STAGE_LABELS: Record<string, string> = {
  writer: "Writer agent — beat sheet & page plan",
  director: "Director agent — layouts & camera",
  characters: "Character Designer — character bible",
  sheets: "Reference sheets (turnaround + expressions)",
  approval: "Cast approval",
  prompts: "Prompt builder",
  panels: "Drawing panels (image model)",
  consistency: "Consistency score (CLIP)",
  layout: "Layout, lettering & SFX",
  export: "Export PNG + PDF",
};

export type Tab = "progress" | "agents" | "quality" | "cast" | "read";

export default function JobView({ id, initialTab }: { id: string; initialTab?: Tab }) {
  const [job, setJob] = useState<Job | null>(null);
  const [project, setProject] = useState<MangaProject | null>(null);
  const [layouts, setLayouts] = useState<LayoutTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);
  // "quality" is the Agent timeline opened on the quality loop.
  const [tab, setTab] = useState<Tab | null>(initialTab ?? null); // null = follow the job automatically
  const lastProjectFetch = useRef(0);

  useEffect(() => {
    api.layouts().then(setLayouts).catch(() => setLayouts([]));
  }, []);

  const refreshProject = useCallback(async () => {
    try {
      setProject(await api.getProject(id));
      lastProjectFetch.current = Date.now();
    } catch {
      /* project.json not written yet */
    }
  }, [id]);

  // Poll the job; refresh the (bigger) project state every ~2 s while work is happening.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.getJob(id);
        if (cancelled) return;
        setJob(next);
        setError(null);
        const active = next.status === "queued" || next.status === "running" || !!next.busy;
        if (active && Date.now() - lastProjectFetch.current > 2000) await refreshProject();
        if (!active && lastProjectFetch.current < next.updated_at * 1000) await refreshProject();
        timer = setTimeout(poll, active ? POLL_MS : POLL_MS * 4);
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
  }, [id, refreshProject]);

  if (!job) {
    return (
      <div className="panel p-6">{error ? <p className="text-red-800">Could not load job: {error}</p> : <p>Loading job…</p>}</div>
    );
  }

  const autoTab: Tab = job.status === "done" ? "read" : job.status === "awaiting_approval" ? "cast" : "progress";
  const current = tab === "quality" ? "agents" : (tab ?? autoTab);
  const tabs: { id: Tab; label: string; enabled: boolean; badge?: string }[] = [
    { id: "progress", label: "Progress", enabled: true },
    { id: "agents", label: "Agent timeline", enabled: !!project?.trace.length, badge: project ? String(project.trace.length) : undefined },
    {
      id: "cast",
      label: "Cast",
      enabled: !!project?.characters.length,
      badge: job.status === "awaiting_approval" ? "!" : undefined,
    },
    { id: "read", label: "Read", enabled: job.status === "done" && !!job.result },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black">{project?.title || job.result?.title || "New manga"}</h1>
          <p className="font-mono text-xs text-ink/60">
            job {job.id} · {job.status.replace("_", " ")}
            {job.busy ? ` · ${job.busy}…` : ""}
          </p>
        </div>
        <nav className="flex flex-wrap gap-2" aria-label="Job views">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={!t.enabled}
              onClick={() => setTab(t.id)}
              className={`btn ${current === t.id ? "btn-primary" : ""}`}
            >
              {t.label}
              {t.badge && <span className="ml-1 bg-paper px-1 text-xs text-ink">{t.badge}</span>}
            </button>
          ))}
        </nav>
      </div>

      {job.status === "awaiting_approval" && current !== "cast" && (
        <div className="border-2 border-ink bg-amber-50 p-3 text-sm">
          Paused: approve the cast to start drawing panels.{" "}
          <button type="button" className="font-bold underline" onClick={() => setTab("cast")}>
            Open the Cast page →
          </button>
        </div>
      )}
      {error && <p className="text-sm text-red-800">Connection problem: {error} (retrying)</p>}

      {current === "progress" && <ProgressPanel job={job} project={project} onOpenAgents={() => setTab("agents")} />}
      {current === "agents" && project && (
        <AgentTimeline project={project} layouts={layouts} initial={tab === "quality" ? "quality" : undefined} />
      )}
      {current === "cast" && project && <CastView job={job} project={project} onChange={refreshProject} />}
      {current === "read" && job.result && <Reader jobId={job.id} result={job.result} project={project} />}
    </div>
  );
}

function ProgressPanel({ job, project, onOpenAgents }: { job: Job; project: MangaProject | null; onOpenAgents: () => void }) {
  const failed = job.status === "failed";
  return (
    <div className="panel space-y-5 p-6">
      <ProgressBar value={job.progress} failed={failed} />
      <ol className="space-y-3">
        {job.stages.map((stage) => (
          <StageRow key={stage.name} stage={stage} />
        ))}
      </ol>
      {project && project.trace.length > 0 && (
        <button type="button" className="btn" onClick={onOpenAgents}>
          See what the agents did ({project.trace.length} steps) →
        </button>
      )}
      {failed && (
        <div className="space-y-3">
          <pre className="whitespace-pre-wrap border-2 border-red-700 bg-red-50 p-3 text-sm text-red-800">{job.error}</pre>
          <Link href="/" className="btn">
            ← Try another story
          </Link>
        </div>
      )}
    </div>
  );
}

function ProgressBar({ value, failed }: { value: number; failed?: boolean }) {
  return (
    <div className="h-4 w-full border-2 border-ink bg-white" role="progressbar" aria-valuenow={Math.round(value * 100)}>
      <div className={`h-full transition-all duration-500 ${failed ? "bg-red-700" : "bg-ink"}`} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

function StageRow({ stage }: { stage: Stage }) {
  const icon = { pending: "○", running: "◐", done: "●", failed: "✕", waiting: "⏸" }[stage.status];
  return (
    <li className="grid grid-cols-[1.5rem_1fr_3.5rem] items-center gap-3">
      <span
        className={`text-lg ${stage.status === "running" ? "animate-spin" : ""} ${stage.status === "failed" ? "text-red-700" : ""} ${
          stage.status === "waiting" ? "text-amber-700" : ""
        }`}
      >
        {icon}
      </span>
      <div>
        <div className={`font-semibold ${stage.status === "pending" ? "text-ink/40" : ""}`}>{STAGE_LABELS[stage.name] ?? stage.name}</div>
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
