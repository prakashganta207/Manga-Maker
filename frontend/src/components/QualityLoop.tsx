"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import { useEffect, useMemo, useState } from "react";
import {
  jobFileUrl,
  type AttemptStatus,
  type Criterion,
  type EditorFix,
  type MangaProject,
  type PanelAttempt,
  type PanelResult,
  type StoryboardFrame,
} from "@/lib/api";
import { SHOT_ABBR } from "./LayoutThumb";

// The Editor's nine criteria, in the order it grades them.
export const CRITERIA: { id: Criterion; label: string; hint: string }[] = [
  { id: "script_action", label: "Action", hint: "shows the action in the panel spec" },
  { id: "characters", label: "Characters", hint: "the right characters, nobody missing or extra" },
  { id: "people_count", label: "People count", hint: "number of people matches the spec" },
  { id: "character_likeness", label: "Likeness", hint: "hair, face, outfit match the reference sheets" },
  { id: "shot_angle", label: "Shot / angle", hint: "shot type and camera angle match the Director" },
  { id: "emotion", label: "Emotion", hint: "faces and body language show the emotion" },
  { id: "anatomy", label: "Anatomy", hint: "hands, faces, limbs well formed" },
  { id: "manga_style", label: "Manga style", hint: "black and white ink, screentone, no colour or text" },
  { id: "bubble_space", label: "Bubble space", hint: "calm areas left for speech bubbles" },
];

const STATUS: Record<AttemptStatus | "drawing", { label: string; stamp: string; card: string }> = {
  accepted: { label: "✓ Accepted", stamp: "bg-ink text-paper border-ink", card: "border-ink" },
  rejected: { label: "✕ Rejected", stamp: "bg-paper text-ink/60 border-ink/40", card: "border-ink/30" },
  needs_review: { label: "⚑ Needs review", stamp: "bg-amber-300 text-amber-950 border-amber-800", card: "border-amber-700" },
  unreviewed: { label: "○ Unreviewed", stamp: "bg-paper text-ink/70 border-ink/50 border-dashed", card: "border-ink/40" },
  pending: { label: "… Pending", stamp: "bg-paper text-ink/60 border-ink/30", card: "border-ink/30" },
  drawing: { label: "◐ Drawing", stamp: "bg-paper text-ink border-ink", card: "border-ink/30" },
};

const SOURCE_LABEL: Record<string, string> = {
  auto: "first drawing",
  redraw: "Editor redraw",
  revision: "your instruction",
  inpaint: "inpaint",
  restore: "restored",
};

type Filter = "all" | "needs_review" | "redrawn";

export default function QualityLoop({ project }: { project: MangaProject }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [zoom, setZoom] = useState<{ src: string; caption: string } | null>(null);
  const panels = useMemo(
    () => [...project.panels].sort((a, b) => a.page - b.page || a.panel - b.panel),
    [project.panels],
  );
  const shown = panels.filter((p) =>
    filter === "needs_review" ? p.status === "needs_review" : filter === "redrawn" ? p.attempts.length > 1 : true,
  );
  const counts = {
    accepted: panels.filter((p) => p.status === "accepted").length,
    needs_review: panels.filter((p) => p.status === "needs_review").length,
    unreviewed: panels.filter((p) => p.status === "unreviewed").length,
  };
  const attempts = panels.reduce((n, p) => n + p.attempts.length, 0);
  const limits = project.budget?.limits ?? {};
  const threshold = limits.threshold ?? 0.65;
  const reviews = project.trace.filter((s) => s.agent === "editor");

  if (panels.length === 0) {
    return (
      <section className="panel p-6 text-ink/60">
        The Editor reviews each panel as soon as it is drawn. No panels yet…
      </section>
    );
  }

  return (
    <section className="space-y-5">
      <div className="panel space-y-4 p-5">
        <header className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-2xl font-black">🔍 Quality loop</h2>
          <span className="text-xs text-ink/60">
            Editor model: {reviews[0]?.model || project.providers.llm_model || project.providers.llm || "—"}
          </span>
        </header>
        <p className="max-w-3xl text-sm text-ink/80">
          A vision LLM (the <b>Editor</b>) looks at every panel next to the character references and grades nine criteria from 1 to
          5. Its grade is combined with the CLIP likeness score; panels below the threshold are redrawn with the Editor&apos;s fix
          (up to {limits.max_attempts ?? 3} attempts). If they still fail, the best attempt is kept and marked for your review.
        </p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Count label="Accepted" value={counts.accepted} total={panels.length} tone="ink" />
          <Count label="Needs review" value={counts.needs_review} total={panels.length} tone="amber" />
          <Count label="Attempts drawn" value={attempts} sub={`${project.budget?.redraws ?? 0} redraws`} />
          <Count label="Editor reviews" value={reviews.length} sub={`threshold ${threshold.toFixed(2)}`} />
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <Meter label="LLM calls" used={project.budget?.llm_calls ?? 0} limit={limits.llm_calls} />
          <Meter label="LLM cost" used={project.usage.cost_usd} limit={limits.llm_cost_usd} money />
          <Meter label="GPU time" used={project.budget?.gpu_seconds ?? 0} limit={limits.gpu_seconds} unit="s" />
        </div>
        {project.budget?.exhausted && (
          <p className="border-2 border-amber-700 bg-amber-50 p-2 text-sm text-amber-900">⚠ {project.budget.exhausted}</p>
        )}
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filter panels">
          {(
            [
              ["all", `All panels (${panels.length})`],
              ["needs_review", `Needs review (${counts.needs_review})`],
              ["redrawn", `Redrawn (${panels.filter((p) => p.attempts.length > 1).length})`],
            ] as [Filter, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className={`border-2 border-ink px-3 py-1 text-sm font-bold ${filter === id ? "bg-ink text-paper" : "bg-paper hover:bg-white"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 && <div className="panel p-6 text-sm text-ink/60">Nothing here — every panel passed. 🎉</div>}
      {shown.map((panel) => (
        <PanelRow key={`${panel.page}-${panel.panel}`} panel={panel} project={project} threshold={threshold} onZoom={setZoom} />
      ))}
      {zoom && <Lightbox src={zoom.src} caption={zoom.caption} onClose={() => setZoom(null)} />}
    </section>
  );
}

function Count({ label, value, total, sub, tone }: { label: string; value: number; total?: number; sub?: string; tone?: "ink" | "amber" }) {
  return (
    <div className={`border-2 px-3 py-2 ${tone === "amber" && value > 0 ? "border-amber-700 bg-amber-50" : "border-ink bg-white"}`}>
      <div className="text-[11px] uppercase tracking-wide text-ink/60">{label}</div>
      <div className="text-2xl font-black">
        {value}
        {total !== undefined && <span className="text-sm font-bold text-ink/50"> / {total}</span>}
      </div>
      {sub && <div className="text-[11px] text-ink/60">{sub}</div>}
    </div>
  );
}

function Meter({ label, used, limit, unit = "", money }: { label: string; used: number; limit?: number; unit?: string; money?: boolean }) {
  const fmt = (v: number) => (money ? `$${v.toFixed(v < 1 ? 3 : 2)}` : `${Math.round(v)}${unit}`);
  const ratio = limit ? Math.min(1, used / limit) : 0;
  return (
    <div className="text-xs">
      <div className="flex justify-between">
        <b>{label}</b>
        <span className="font-mono">
          {fmt(used)} {limit ? `/ ${fmt(limit)}` : ""}
        </span>
      </div>
      <div className="mt-1 h-2.5 border border-ink bg-white">
        <div className={`h-full ${ratio >= 1 ? "bg-amber-600" : "bg-ink"}`} style={{ width: `${Math.max(ratio * 100, used > 0 ? 1 : 0)}%` }} />
      </div>
    </div>
  );
}

function PanelRow({
  panel,
  project,
  threshold,
  onZoom,
}: {
  panel: PanelResult;
  project: MangaProject;
  threshold: number;
  onZoom: (z: { src: string; caption: string }) => void;
}) {
  const planned = project.page_plan?.pages[panel.page - 1]?.panels.find((p) => p.panel_number === panel.panel);
  const directed = project.director?.pages[panel.page - 1]?.panels.find((p) => p.panel_number === panel.panel);
  const status = STATUS[panel.status] ?? STATUS.unreviewed;
  const frame = project.storyboards?.find((f) => f.page === panel.page && f.panel === panel.panel);
  // Newest round first is confusing in a "story" of attempts: keep chronological order, left to right.
  const attempts = [...panel.attempts].sort((a, b) => a.attempt - b.attempt);
  return (
    <article className={`panel space-y-3 p-4 ${panel.status === "needs_review" ? "!border-amber-700" : ""}`}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-lg font-black">
            Page {panel.page} · Panel {panel.panel}
            {directed && (
              <span className="ml-2 bg-ink px-1.5 py-0.5 align-middle text-xs font-bold text-paper">
                {SHOT_ABBR[directed.shot] ?? directed.shot} · {directed.angle}
              </span>
            )}
          </h3>
          {planned && (
            <p className="text-sm text-ink/70">
              {planned.action} <i className="text-ink/50">— {planned.emotion}</i>
              {planned.characters.length > 0 && <span className="text-ink/50"> · {planned.characters.join(", ")}</span>}
            </p>
          )}
        </div>
        <span className={`shrink-0 border-2 px-2 py-1 text-xs font-black uppercase tracking-wide ${status.stamp}`}>{status.label}</span>
      </header>
      {panel.review_note && <p className="text-xs text-amber-900">{panel.review_note}</p>}

      <div className="flex items-stretch gap-0 overflow-x-auto pb-2">
        {frame && <StoryboardCard frame={frame} project={project} onZoom={onZoom} />}
        {frame && (
          <div className="flex w-24 shrink-0 flex-col items-center justify-center px-1 text-center text-[10px]">
            <div className="font-black uppercase tracking-wide text-ink/60">{frame.control ? "ControlNet" : "no guide"}</div>
            <div className="my-1 text-2xl leading-none">→</div>
            {frame.control && <span className="border border-ink/40 bg-white px-1">{frame.control_type === "openpose" ? "follow pose" : "follow lines"}</span>}
          </div>
        )}
        {attempts.map((attempt, i) => (
          <div key={attempt.attempt} className="flex items-stretch">
            {i > 0 && <FixArrow fix={attempt.fix_applied} source={attempt.source} newRound={attempt.round !== attempts[i - 1].round} />}
            <AttemptCard
              attempt={attempt}
              chosen={attempt.attempt === panel.chosen_attempt}
              threshold={threshold}
              project={project}
              onZoom={() =>
                onZoom({
                  src: jobFileUrl(project, attempt.image),
                  caption: `Page ${panel.page} panel ${panel.panel} — attempt ${attempt.attempt} (${attempt.status.replace("_", " ")})`,
                })
              }
            />
          </div>
        ))}
      </div>
    </article>
  );
}

/** The storyboard rough and the control image ControlNet followed. */
function StoryboardCard({
  frame,
  project,
  onZoom,
}: {
  frame: StoryboardFrame;
  project: MangaProject;
  onZoom: (z: { src: string; caption: string }) => void;
}) {
  const images = [
    { src: frame.rough, label: "rough" },
    ...(frame.control ? [{ src: frame.control, label: frame.control_type === "openpose" ? "pose" : "line art" }] : []),
  ];
  return (
    <div className="flex w-44 shrink-0 flex-col border-[3px] border-dashed border-ink/50 bg-white">
      <div className="grid grid-cols-2 gap-0.5 bg-tone p-0.5">
        {images.map((img) => (
          <button
            key={img.label}
            type="button"
            title={`Enlarge the ${img.label}`}
            onClick={() => onZoom({ src: jobFileUrl(project, img.src), caption: `Storyboard ${img.label} — page ${frame.page} panel ${frame.panel}` })}
            className="relative"
          >
            <img src={jobFileUrl(project, img.src)} alt={img.label} loading="lazy" className="aspect-[3/4] w-full bg-ink object-cover" />
            <span className="absolute bottom-0.5 left-0.5 bg-paper/90 px-1 text-[9px] font-bold uppercase">{img.label}</span>
          </button>
        ))}
      </div>
      <div className="flex-1 space-y-1 p-2 text-[11px]">
        <b className="text-sm">Storyboard</b>
        <p className="text-ink/70">Fast rough ({frame.seconds.toFixed(1)}s) → {frame.control ? frame.control_type : "no usable guide"}.</p>
        {frame.note && <p className="text-amber-900">{frame.note}</p>}
      </div>
    </div>
  );
}

function FixArrow({ fix, source, newRound }: { fix: EditorFix | null; source: string; newRound: boolean }) {
  const chips = fixChips(fix);
  return (
    <div className="flex w-28 shrink-0 flex-col items-center justify-center px-1 text-center text-[10px]" aria-hidden={!chips.length}>
      <div className="font-black uppercase tracking-wide text-ink/60">{newRound ? SOURCE_LABEL[source] ?? source : "redraw"}</div>
      <div className="my-1 text-2xl leading-none">→</div>
      <div className="flex flex-col gap-0.5">
        {chips.slice(0, 5).map((c) => (
          <span key={c} className="break-words border border-ink/40 bg-white px-1">
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

function fixChips(fix: EditorFix | null): string[] {
  if (!fix) return [];
  return [
    ...fix.prompt_add.map((t) => `+ ${t}`),
    ...fix.prompt_remove.map((t) => `− ${t}`),
    ...fix.negative_add.map((t) => `no ${t}`),
    ...(fix.ipadapter_weight !== null ? [`ref weight ${fix.ipadapter_weight}`] : []),
    ...(fix.new_seed ? ["new seed"] : []),
  ];
}

function AttemptCard({
  attempt,
  chosen,
  threshold,
  project,
  onZoom,
}: {
  attempt: PanelAttempt;
  chosen: boolean;
  threshold: number;
  project: MangaProject;
  onZoom: () => void;
}) {
  const status = STATUS[attempt.status] ?? STATUS.pending;
  const q = attempt.quality;
  const review = attempt.review;
  const [open, setOpen] = useState(attempt.status !== "rejected");
  const aspect = attempt.width && attempt.height ? `${attempt.width} / ${attempt.height}` : "3 / 4";
  return (
    <div className={`relative flex w-64 shrink-0 flex-col border-[3px] bg-white ${status.card} ${chosen ? "shadow-[5px_5px_0_#111]" : "opacity-95"}`}>
      <button type="button" onClick={onZoom} className="group relative block bg-tone" style={{ aspectRatio: aspect }} title="Enlarge">
        <img
          src={jobFileUrl(project, attempt.image)}
          alt={`Attempt ${attempt.attempt}`}
          loading="lazy"
          className={`h-full w-full object-cover ${attempt.status === "rejected" ? "grayscale-[60%] opacity-80" : ""}`}
        />
        <span
          className={`absolute left-2 top-2 -rotate-6 border-2 px-1.5 py-0.5 text-[11px] font-black uppercase shadow-[2px_2px_0_rgba(0,0,0,.35)] ${status.stamp}`}
        >
          {status.label}
        </span>
        {chosen && <span className="absolute bottom-2 right-2 bg-ink px-1.5 text-[10px] font-black text-paper">IN USE</span>}
        <span className="absolute right-2 top-2 hidden bg-paper/90 px-1 text-xs group-hover:block">⤢</span>
      </button>

      <div className="flex flex-1 flex-col gap-2 p-2.5 text-xs">
        <div className="flex items-baseline justify-between">
          <b className="text-sm">Attempt {attempt.attempt}</b>
          <span className="text-ink/60">{SOURCE_LABEL[attempt.source] ?? attempt.source}</span>
        </div>

        {q ? <ScoreGauge value={q.combined} threshold={q.threshold || threshold} passed={q.passed} /> : <div className="text-ink/50">No combined score</div>}
        {q && (
          <div className="flex justify-between font-mono text-[11px] text-ink/70">
            <span>Editor {q.editor !== null ? q.editor.toFixed(2) : "—"}</span>
            <span title="CLIP likeness, rescaled to 0..1 (weakest character)">CLIP {q.clip !== null ? q.clip.toFixed(2) : "—"}</span>
          </div>
        )}
        {Object.keys(attempt.consistency).length > 0 && (
          <div className="flex flex-wrap gap-1">
            {Object.entries(attempt.consistency).map(([name, v]) => (
              <span key={name} className="border border-ink/30 px-1 font-mono text-[10px]" title={`${attempt.consistency_method} similarity`}>
                {name} {v.toFixed(2)}
              </span>
            ))}
          </div>
        )}

        {review && <CriteriaBars scores={review.scores} />}

        {review && (
          <button type="button" onClick={() => setOpen((v) => !v)} className="self-start text-[11px] font-bold underline underline-offset-2">
            {open ? "Hide" : "Show"} the Editor&apos;s notes
          </button>
        )}
        {review && open && (
          <div className="space-y-2">
            {review.problems.length > 0 && (
              <ul className="space-y-0.5">
                {review.problems.map((p, i) => (
                  <li key={i} className="border-l-4 border-amber-600 bg-amber-50 px-1.5 py-0.5 text-amber-950">
                    {p}
                  </li>
                ))}
              </ul>
            )}
            <EditorBalloon text={review.reasoning} />
            {review.verdict === "fail" && fixChips(review.fix).length > 0 && (
              <div>
                <div className="text-[10px] font-bold uppercase text-ink/60">Suggested fix</div>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {fixChips(review.fix).map((c) => (
                    <span key={c} className="border border-ink bg-paper px-1">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {attempt.note && <p className="text-[11px] text-ink/60">{attempt.note}</p>}
        {q && q.reasons.length > 0 && attempt.status !== "accepted" && (
          <p className="text-[11px] text-ink/60">Why not accepted: {q.reasons.join("; ")}</p>
        )}

        <details className="mt-auto text-[10px] text-ink/60">
          <summary className="cursor-pointer">
            seed {attempt.seed} · {attempt.workflow} · {attempt.seconds.toFixed(1)}s
          </summary>
          <p className="mt-1 break-words font-mono">{attempt.prompt}</p>
          <p className="mt-1 break-words font-mono text-ink/40">neg: {attempt.negative_prompt}</p>
          {attempt.ipadapter_weight !== null && <p className="mt-1">IP-Adapter weight {attempt.ipadapter_weight}</p>}
        </details>
      </div>
    </div>
  );
}

function ScoreGauge({ value, threshold, passed }: { value: number; threshold: number; passed: boolean }) {
  return (
    <div title={`combined ${value.toFixed(2)} — threshold ${threshold.toFixed(2)}`}>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-bold uppercase text-ink/60">Combined</span>
        <span className={`font-mono text-lg font-black ${passed ? "" : "text-amber-800"}`}>{value.toFixed(2)}</span>
      </div>
      <div className="relative h-3 border-2 border-ink bg-white">
        <div className={`h-full ${passed ? "bg-ink" : "bg-amber-500"}`} style={{ width: `${Math.round(value * 100)}%` }} />
        <div className="absolute -top-1 h-4 w-0.5 bg-red-700" style={{ left: `${threshold * 100}%` }} title="pass threshold" />
      </div>
    </div>
  );
}

function CriteriaBars({ scores }: { scores: Record<Criterion, number> }) {
  return (
    <ul className="grid grid-cols-1 gap-0.5">
      {CRITERIA.map(({ id, label, hint }) => {
        const s = scores[id] ?? 0;
        return (
          <li key={id} className="grid grid-cols-[5.5rem_1fr_0.75rem] items-center gap-1.5" title={`${label}: ${hint}`}>
            <span className={`truncate ${s <= 2 ? "font-bold text-amber-900" : "text-ink/70"}`}>{label}</span>
            <span className="flex gap-0.5">
              {[1, 2, 3, 4, 5].map((n) => (
                <span
                  key={n}
                  className={`h-2 flex-1 border border-ink/60 ${n <= s ? (s <= 2 ? "bg-amber-500" : "bg-ink") : "bg-white"}`}
                />
              ))}
            </span>
            <span className="text-right font-mono">{s}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** The Editor's reasoning, drawn as a little manga speech balloon. */
function EditorBalloon({ text }: { text: string }) {
  return (
    <div className="relative mt-1 rounded-[45%/35%] border-2 border-ink bg-paper px-3 py-2 text-[11px] italic leading-snug">
      {text}
      <span className="absolute -bottom-2 left-6 h-3 w-3 rotate-45 border-b-2 border-r-2 border-ink bg-paper" aria-hidden />
      <span className="mt-1 block text-right text-[10px] not-italic font-bold">— Editor</span>
    </div>
  );
}

function Lightbox({ src, caption, onClose }: { src: string; caption: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-modal="true" aria-label={caption} className="fixed inset-0 z-50 flex items-center justify-center bg-ink/80 p-4" onClick={onClose}>
      <figure className="max-h-full max-w-3xl border-4 border-paper bg-paper p-2" onClick={(e) => e.stopPropagation()}>
        <img src={src} alt={caption} className="max-h-[80vh] w-auto" />
        <figcaption className="mt-2 flex items-center justify-between gap-4 text-sm">
          <span>{caption}</span>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </figcaption>
      </figure>
    </div>
  );
}
