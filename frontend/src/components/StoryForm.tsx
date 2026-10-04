"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Health, type ProjectInfo, type SampleStory } from "@/lib/api";

const MIN_LENGTH = 20;
const MAX_LENGTH = 20000;

export default function StoryForm() {
  const router = useRouter();
  const [story, setStory] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [samples, setSamples] = useState<SampleStory[]>([]);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [autoApprove, setAutoApprove] = useState(false);
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthError(true));
    api.samples().then(setSamples).catch(() => setSamples([]));
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, []);

  const length = story.trim().length;
  const valid = length >= MIN_LENGTH && length <= MAX_LENGTH;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJob(story, { auto_approve: autoApprove, ...(projectId ? { project_id: projectId } : {}) });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="panel space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor="story" className="text-lg font-bold">
          Your story
        </label>
        <ProviderBadge health={health} error={healthError} />
      </div>

      {samples.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-ink/60">Try a sample:</span>
          {samples.map((s) => (
            <button key={s.id} type="button" className="border-2 border-ink bg-white px-2 py-0.5 hover:bg-tone" onClick={() => setStory(s.story)}>
              {s.title}
            </button>
          ))}
        </div>
      )}

      <textarea
        id="story"
        value={story}
        onChange={(e) => setStory(e.target.value)}
        rows={12}
        maxLength={MAX_LENGTH}
        placeholder="Once upon a time, on a quiet rooftop..."
        className="w-full resize-y border-2 border-ink bg-white p-3 font-serif text-base leading-relaxed outline-none focus:ring-4 focus:ring-ink/20"
      />

      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} />
          <span>
            <b>Auto-approve the cast</b>
            <span className="block text-ink/60">Skip the review of character sheets (for unattended runs).</span>
          </span>
        </label>
        <label className="flex flex-col gap-1">
          <b>Continue an earlier project (reuse its cast)</b>
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="border-2 border-ink bg-white p-1.5">
            <option value="">New project</option>
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>
                {p.project_id} — {p.characters.map((c) => c.name).join(", ")}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-ink/60">
          {length} / {MAX_LENGTH} characters
          {length > 0 && length < MIN_LENGTH && ` · at least ${MIN_LENGTH} needed`}
        </span>
        <button type="submit" className="btn btn-primary" disabled={!valid || submitting}>
          {submitting ? "Starting…" : "Make my manga →"}
        </button>
      </div>
      {error && <p className="border-2 border-red-700 bg-red-50 p-3 text-sm text-red-800">Could not start: {error}</p>}
    </form>
  );
}

function ProviderBadge({ health, error }: { health: Health | null; error: boolean }) {
  if (error) {
    return <span className="border border-red-700 px-2 py-0.5 text-xs text-red-700">Backend not reachable — is it running?</span>;
  }
  if (!health) return <span className="text-xs text-ink/50">Checking backend…</span>;
  const mock = health.providers.llm === "mock" && health.providers.image === "mock";
  return (
    <span className="border border-ink px-2 py-0.5 text-xs" title="Set API keys / start ComfyUI to use real AI providers">
      LLM: <b>{health.providers.llm_model || health.providers.llm}</b> · Images: <b>{health.providers.image}</b>
      {mock && " (mock mode)"}
    </span>
  );
}
