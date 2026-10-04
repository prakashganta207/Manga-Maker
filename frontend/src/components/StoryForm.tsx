"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";

const MIN_LENGTH = 20;
const MAX_LENGTH = 20000;

const SAMPLE_STORY = `Mira climbed the stairs to the school rooftop. The wind tugged at her scarf. Below, the city lights flickered on one by one.
Kaito was already there, leaning on the fence. "You came," Kaito said quietly. "I promised," Mira answered with a small smile.
Suddenly a strange glow rose from the river. They ran to the edge and stared. "What is that?" Mira whispered.`;

export default function StoryForm() {
  const router = useRouter();
  const [story, setStory] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthError(true));
  }, []);

  const length = story.trim().length;
  const valid = length >= MIN_LENGTH && length <= MAX_LENGTH;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJob(story);
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
      <textarea
        id="story"
        value={story}
        onChange={(e) => setStory(e.target.value)}
        rows={12}
        maxLength={MAX_LENGTH}
        placeholder="Once upon a time, on a quiet rooftop..."
        className="w-full resize-y border-2 border-ink bg-white p-3 font-serif text-base leading-relaxed outline-none focus:ring-4 focus:ring-ink/20"
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-sm text-ink/60">
          <span>
            {length} / {MAX_LENGTH} characters
            {length > 0 && length < MIN_LENGTH && ` · at least ${MIN_LENGTH} needed`}
          </span>
          <button type="button" className="underline underline-offset-4 hover:text-ink" onClick={() => setStory(SAMPLE_STORY)}>
            Use sample story
          </button>
        </div>
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
    return (
      <span className="border border-red-700 px-2 py-0.5 text-xs text-red-700">
        Backend not reachable — is it running on port 8000?
      </span>
    );
  }
  if (!health) return <span className="text-xs text-ink/50">Checking backend…</span>;
  const mock = health.providers.llm === "mock" && health.providers.image === "mock";
  return (
    <span className="border border-ink px-2 py-0.5 text-xs" title="Set API keys in .env to use real AI providers">
      LLM: <b>{health.providers.llm}</b> · Images: <b>{health.providers.image}</b>
      {mock && " (mock mode)"}
    </span>
  );
}
