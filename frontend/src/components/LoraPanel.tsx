"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend */

import { useEffect, useState } from "react";
import { api, jobFileUrl, type CharacterEntry, type Job, type MangaProject, type Training, type TrainingInfo } from "@/lib/api";

const POLL_MS = 1500;

/** "Train character LoRA" for one character: start, follow progress and logs, compare before/after. */
export default function LoraPanel({
  job,
  project,
  character,
  info,
  onChange,
}: {
  job: Job;
  project: MangaProject;
  character: CharacterEntry;
  info: TrainingInfo | null;
  onChange: () => void;
}) {
  const lora = character.lora;
  const [training, setTraining] = useState<Training | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [upload, setUpload] = useState<File | null>(null);
  const [trigger, setTrigger] = useState("");
  const active = training ? training.status === "queued" || training.status === "running" : lora.status === "queued" || lora.status === "training";
  const trainingId = training?.id ?? lora.training_id;

  // Follow a running training (also after a page reload, via the id stored on the character).
  useEffect(() => {
    if (!trainingId || !active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.training(trainingId!);
        if (cancelled) return;
        setTraining(next);
        if (next.status === "queued" || next.status === "running") timer = setTimeout(poll, POLL_MS);
        else onChange();
      } catch {
        if (!cancelled) timer = setTimeout(poll, POLL_MS * 3);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [trainingId, active, onChange]);

  async function start() {
    setError(null);
    try {
      setTraining(await api.trainLora(job.id, character.name));
      setShowLog(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function importFile() {
    if (!upload) return;
    setError(null);
    try {
      await api.importLora(job.id, character.name, upload, trigger);
      setUpload(null);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const progress = training?.progress ?? 0;
  const ready = lora.status === "ready";
  const delta = lora.before !== null && lora.after !== null ? lora.after - lora.before : null;
  const canTrain = character.approved && !job.busy && !active && job.status !== "running" && job.status !== "queued";

  return (
    <section className="space-y-3 border-2 border-ink bg-white p-3 text-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="font-black">Character LoRA</h4>
          <p className="text-xs text-ink/60">
            A small add-on to the image model trained on {character.name}&apos;s approved references, summoned by a trigger
            word. Strongest consistency; IP-Adapter is turned down when it&apos;s used.
          </p>
        </div>
        <span
          className={`px-2 py-0.5 text-xs font-black uppercase ${
            ready ? "bg-ink text-paper" : lora.status === "failed" ? "bg-red-100 text-red-900" : active ? "bg-amber-200" : "border border-ink/40"
          }`}
        >
          {active ? "training…" : ready ? `ready (${lora.trainer})` : lora.status === "failed" ? "failed" : "not trained"}
        </span>
      </header>

      {!ready && !active && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn btn-primary !py-1" disabled={!canTrain} onClick={start}>
            ⚙ Train character LoRA
          </button>
          <span className="text-xs text-ink/60">
            {info?.trainer === "kohya"
              ? `kohya-ss sd-scripts · ${info.steps} steps at ${info.resolution}px · roughly 25–45 min on an 8 GB GPU`
              : "Mock trainer (sd-scripts not installed): shows the flow in seconds — see CLOUD_TRAINING.md"}
          </span>
        </div>
      )}
      {!character.approved && <p className="text-xs text-amber-900">Approve the character first.</p>}

      {(active || (training && training.status !== "done")) && training && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span>{training.message || "starting…"}</span>
            <span className="font-mono">{Math.round(progress * 100)}%</span>
          </div>
          <div className="h-3 border-2 border-ink bg-paper">
            <div className="h-full bg-ink transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          {active && (
            <button type="button" className="text-xs underline" onClick={() => api.cancelTraining(training.id).then(setTraining)}>
              Cancel training
            </button>
          )}
          {training.error && <p className="text-xs text-red-800">{training.error}</p>}
        </div>
      )}
      {lora.status === "failed" && lora.error && !active && <p className="text-xs text-red-800">Last training failed: {lora.error}</p>}

      {training && training.log_tail.length > 0 && (
        <div>
          <button type="button" className="text-xs underline" onClick={() => setShowLog((v) => !v)}>
            {showLog ? "Hide" : "Show"} training log
          </button>
          {showLog && (
            <pre className="mt-1 max-h-48 overflow-auto bg-ink p-2 font-mono text-[10px] leading-snug text-paper">{training.log_tail.join("\n")}</pre>
          )}
        </div>
      )}

      {ready && (
        <div className="space-y-2">
          <p className="text-xs">
            Trigger word <code className="bg-tone px-1">{lora.trigger}</code> · {lora.dataset_size} training images · {lora.steps} steps
            {lora.seconds ? ` · ${Math.round(lora.seconds / 60)} min` : ""}
          </p>
          {lora.before !== null && lora.after !== null && (
            <div className="grid gap-2 sm:grid-cols-2">
              {(["before", "after"] as const).map((label) => (
                <figure key={label} className="border border-ink/30 p-1.5">
                  <figcaption className="mb-1 flex justify-between text-xs">
                    <b>{label === "before" ? "Without LoRA" : "With LoRA"}</b>
                    <span className="font-mono">{(label === "before" ? lora.before : lora.after)!.toFixed(3)}</span>
                  </figcaption>
                  <div className="flex gap-1">
                    {(lora.eval_images[label] ?? []).map((src) => (
                      <img key={src} src={jobFileUrl(project, src)} alt={`${label} test`} className="h-24 w-auto border border-ink/30 object-cover" />
                    ))}
                  </div>
                </figure>
              ))}
            </div>
          )}
          {delta !== null && (
            <p className={`text-xs font-bold ${delta > 0.005 ? "" : "text-ink/60"}`}>
              Consistency (CLIP vs references): {lora.before!.toFixed(3)} → {lora.after!.toFixed(3)} ({delta >= 0 ? "+" : ""}
              {delta.toFixed(3)}){lora.trainer === "mock" && " — mock trainer: no real change expected"}
            </p>
          )}
          <button type="button" className="btn !py-1 text-xs" disabled={!canTrain} onClick={start}>
            Retrain
          </button>
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer font-bold">Import a LoRA trained elsewhere (cloud GPU)</summary>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input type="file" accept=".safetensors" onChange={(e) => setUpload(e.target.files?.[0] ?? null)} aria-label="LoRA file" />
          <input
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
            placeholder={`trigger word (default ${character.slug.replace(/[^a-z0-9]/g, "")}_chr)`}
            className="border-2 border-ink px-1 py-0.5"
          />
          <button type="button" className="btn !py-1" disabled={!upload} onClick={importFile}>
            Import
          </button>
        </div>
      </details>
      {error && <p className="text-xs text-red-800">{error}</p>}
    </section>
  );
}
