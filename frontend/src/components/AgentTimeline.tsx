"use client";

import { useMemo, useState } from "react";
import type { AgentStep, BeatSheet, LayoutTemplate, MangaProject, PlannedPanel } from "@/lib/api";
import LayoutThumb, { ANGLE_ICON, SHOT_ABBR } from "./LayoutThumb";
import QualityLoop from "./QualityLoop";

const AGENT_STYLE: Record<string, { name: string; badge: string; icon: string }> = {
  writer: { name: "Writer", badge: "bg-ink text-paper", icon: "✎" },
  director: { name: "Director", badge: "bg-white text-ink border-2 border-ink", icon: "🎬" },
  character_designer: { name: "Character Designer", badge: "bg-tone text-ink", icon: "☺" },
  studio: { name: "Studio", badge: "bg-amber-100 text-ink border border-amber-700", icon: "✓" },
  editor: { name: "Editor", badge: "bg-amber-300 text-ink border-2 border-ink", icon: "🔍" },
};

const NODE_LABELS: Record<string, string> = {
  writer_beats: "Writer · beats",
  writer_pages: "Writer · pages",
  director: "Director",
  character_designer: "Character designer",
  reference_sheets: "Reference sheets",
  prompts: "Prompt builder",
  panels: "Panels + Editor loop",
  consistency: "Consistency score",
  layout: "Layout + lettering",
  export: "Export",
};

function fmtSeconds(s: number) {
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function fmtTokens(n: number) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

const QUALITY = -1; // pseudo step: the Editor's quality loop (all its reviews, grouped per panel)

export default function AgentTimeline({
  project,
  layouts,
  initial,
}: {
  project: MangaProject;
  layouts: LayoutTemplate[];
  initial?: "quality";
}) {
  // Editor reviews (one per panel attempt) are grouped into a single "Quality loop" entry.
  const steps = project.trace.filter((s) => s.agent !== "editor");
  const reviews = project.trace.filter((s) => s.agent === "editor");
  const hasQuality = reviews.length > 0 || project.panels.some((p) => p.attempts?.length);
  const [selected, setSelected] = useState(initial === "quality" ? QUALITY : 0);
  const showQuality = selected === QUALITY && hasQuality;
  const step = steps[Math.min(Math.max(selected, 0), steps.length - 1)];
  const totalTime = Object.values(project.timings).reduce((a, b) => a + b, 0);
  const qualityStats = {
    accepted: project.panels.filter((p) => p.status === "accepted").length,
    review: project.panels.filter((p) => p.status === "needs_review").length,
    reviewTokens: reviews.reduce((n, s) => n + s.input_tokens + s.output_tokens, 0),
    reviewCost: reviews.reduce((n, s) => n + s.cost_usd, 0),
    seconds: reviews.reduce((n, s) => n + s.duration_s, 0),
  };

  if (steps.length === 0) {
    return <div className="panel p-6 text-ink/60">The agents haven&apos;t started yet…</div>;
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Agent steps" value={String(steps.length)} />
        <Stat label="Pipeline time" value={fmtSeconds(totalTime)} />
        <Stat label="Tokens in / out" value={`${fmtTokens(project.usage.input_tokens)} / ${fmtTokens(project.usage.output_tokens)}`} />
        <Stat label="LLM cost" value={`$${project.usage.cost_usd.toFixed(4)}`} />
        <Stat label="Model" value={project.providers.llm_model || project.providers.llm || "—"} />
      </div>

      <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
        <ol className="relative space-y-3 border-l-4 border-ink pl-5">
          {steps.map((s, i) => {
            const style = AGENT_STYLE[s.agent] ?? { name: s.agent, badge: "bg-white", icon: "•" };
            const active = i === selected && !showQuality;
            return (
              <li key={i} className="relative">
                <span
                  className={`absolute -left-[2.05rem] top-3 flex h-6 w-6 items-center justify-center rounded-full border-2 border-ink text-xs ${
                    s.status === "failed" ? "bg-red-700 text-white" : active ? "bg-ink text-paper" : "bg-paper"
                  }`}
                >
                  {s.status === "failed" ? "✕" : i + 1}
                </span>
                <button
                  type="button"
                  onClick={() => setSelected(i)}
                  className={`w-full border-2 border-ink p-3 text-left transition ${
                    active ? "bg-white shadow-[4px_4px_0_#111]" : "bg-paper hover:bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`px-1.5 py-0.5 text-[11px] font-bold ${style.badge}`}>
                      {style.icon} {style.name}
                    </span>
                    <span className="font-mono text-xs text-ink/60">{fmtSeconds(s.duration_s)}</span>
                  </div>
                  <div className="mt-1 font-bold">{s.label}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                    <Chip>{fmtTokens(s.input_tokens + s.output_tokens)} tok</Chip>
                    {s.cost_usd > 0 && <Chip>${s.cost_usd.toFixed(4)}</Chip>}
                    {s.attempts > 1 && <Chip tone="warn">{s.attempts} tries</Chip>}
                    {s.notes.length > 0 && <Chip>{s.notes.length} notes</Chip>}
                    {s.status !== "ok" && <Chip tone="warn">{s.status}</Chip>}
                  </div>
                </button>
              </li>
            );
          })}
          {hasQuality && (
            <li className="relative">
              <span
                className={`absolute -left-[2.05rem] top-3 flex h-6 w-6 items-center justify-center rounded-full border-2 border-ink text-xs ${
                  showQuality ? "bg-ink text-paper" : "bg-amber-300"
                }`}
              >
                ★
              </span>
              <button
                type="button"
                onClick={() => setSelected(QUALITY)}
                className={`w-full border-2 border-ink p-3 text-left transition ${
                  showQuality ? "bg-white shadow-[4px_4px_0_#111]" : "bg-paper hover:bg-white"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`px-1.5 py-0.5 text-[11px] font-bold ${AGENT_STYLE.editor.badge}`}>
                    {AGENT_STYLE.editor.icon} {AGENT_STYLE.editor.name}
                  </span>
                  <span className="font-mono text-xs text-ink/60">{fmtSeconds(qualityStats.seconds)}</span>
                </div>
                <div className="mt-1 font-bold">Quality loop</div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                  <Chip>{reviews.length} reviews</Chip>
                  <Chip>✓ {qualityStats.accepted}</Chip>
                  {qualityStats.review > 0 && <Chip tone="warn">⚑ {qualityStats.review} need review</Chip>}
                  {qualityStats.reviewCost > 0 && <Chip>${qualityStats.reviewCost.toFixed(4)}</Chip>}
                </div>
              </button>
            </li>
          )}
        </ol>

        <div className="min-w-0">
          {showQuality ? <QualityLoop project={project} /> : step && <StepDetail step={step} project={project} layouts={layouts} />}
        </div>
      </div>

      <PipelineTimings timings={project.timings} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-ink/60">{label}</div>
      <div className="truncate text-lg font-black" title={value}>
        {value}
      </div>
    </div>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: "warn" }) {
  return (
    <span className={`border px-1.5 py-0.5 ${tone === "warn" ? "border-amber-700 bg-amber-50 text-amber-900" : "border-ink/40"}`}>
      {children}
    </span>
  );
}

function StepDetail({ step, project, layouts }: { step: AgentStep; project: MangaProject; layouts: LayoutTemplate[] }) {
  const [showJson, setShowJson] = useState(false);
  let body: React.ReactNode = null;
  if (step.status === "ok" || step.status === "skipped") {
    if (step.label === "Beat sheet" && project.beat_sheet) body = <BeatSheetView sheet={project.beat_sheet} />;
    else if (step.label === "Page plan" && project.page_plan) body = <PagePlanView project={project} />;
    else if (step.label === "Director plan" && project.director) body = <DirectorView project={project} layouts={layouts} />;
    else if (step.label === "Character bible") body = <BibleView project={project} />;
  }
  return (
    <section className="panel space-y-4 p-5">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-2xl font-black">{step.label}</h2>
        <span className="font-mono text-xs text-ink/60">
          {step.model || "—"} · {step.started_at.replace("T", " ").replace("+00:00", " UTC")}
        </span>
      </header>

      {Object.keys(step.inputs).length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="font-bold">Inputs:</span>
          {Object.entries(step.inputs).map(([k, v]) => (
            <Chip key={k}>
              {k}: {Array.isArray(v) ? v.join(", ") || "—" : String(v)}
            </Chip>
          ))}
        </div>
      )}

      {step.errors.length > 0 && (
        <div className="border-2 border-amber-700 bg-amber-50 p-3 text-sm">
          <div className="font-bold text-amber-900">Validation feedback sent back to the model ({step.errors.length})</div>
          <ul className="mt-1 list-disc pl-5 text-amber-900">
            {step.errors.slice(0, 8).map((e, i) => (
              <li key={i} className="font-mono text-xs">
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}

      {step.notes.length > 0 && (
        <div className="border-2 border-ink bg-white p-3 text-sm">
          <div className="font-bold">⚖ Rules applied in code</div>
          <ul className="mt-1 list-disc pl-5">
            {step.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      {body}

      <button type="button" className="text-sm underline underline-offset-4" onClick={() => setShowJson((v) => !v)}>
        {showJson ? "Hide" : "Show"} raw JSON output
      </button>
      {showJson && (
        <pre className="max-h-96 overflow-auto border-2 border-ink bg-white p-3 text-xs">{JSON.stringify(step.output, null, 2)}</pre>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------- beat sheet
function BeatSheetView({ sheet }: { sheet: BeatSheet }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="text-xl font-black">{sheet.title}</div>
        <p className="italic text-ink/80">{sheet.logline}</p>
        <p className="mt-1 text-sm">
          <b>Emotional arc:</b> {sheet.emotional_arc}
        </p>
      </div>
      <div>
        <div className="mb-1 text-xs font-bold uppercase tracking-wide text-ink/60">Intensity</div>
        <div className="flex h-32 items-end gap-1 border-b-2 border-ink">
          {sheet.beats.map((b) => {
            const climax = b.id === sheet.climax_beat;
            return (
              <div key={b.id} className="flex h-full flex-1 flex-col items-center justify-end" title={`${b.id}. ${b.summary}`}>
                <div
                  className={`relative w-full border-2 border-ink ${climax ? "bg-ink" : "bg-tone"}`}
                  style={{ height: `${b.intensity * 18}%` }}
                >
                  {climax && <span className="absolute -top-6 left-1/2 -translate-x-1/2 text-sm">★ climax</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex gap-1">
          {sheet.beats.map((b) => (
            <div key={b.id} className="flex-1 text-center font-mono text-[10px]">
              {b.id}
            </div>
          ))}
        </div>
      </div>
      <ol className="space-y-2">
        {sheet.beats.map((b) => (
          <li key={b.id} className={`border-l-4 pl-3 ${b.id === sheet.climax_beat ? "border-ink bg-white" : "border-tone"}`}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <b className="text-sm">Beat {b.id}</b>
              <Chip>{b.kind}</Chip>
              <Chip>{b.emotion}</Chip>
              <span className="font-mono">{"●".repeat(b.intensity)}{"○".repeat(5 - b.intensity)}</span>
            </div>
            <p className="text-sm">{b.summary}</p>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        {sheet.characters.map((c) => (
          <span key={c.name} className="border-2 border-ink bg-white px-2 py-1 text-sm">
            <b>{c.name}</b> · {c.role} {c.importance === "main" && "★"}
          </span>
        ))}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- page plan
const SIZE_STYLE: Record<string, string> = {
  splash: "bg-ink text-paper",
  large: "bg-ink/80 text-paper",
  medium: "bg-tone",
  small: "bg-white border border-ink",
};

function PanelLine({ panel }: { panel: PlannedPanel }) {
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-2 border-t border-ink/20 py-2 first:border-t-0">
      <div className="text-center">
        <div className="font-black">{panel.panel_number}</div>
        <div className={`mt-1 px-0.5 text-[9px] font-bold uppercase ${SIZE_STYLE[panel.size]}`}>{panel.size}</div>
      </div>
      <div className="min-w-0 text-sm">
        <div className="text-xs text-ink/60">
          Beat {panel.beat} · {panel.purpose} · <i>{panel.emotion}</i> · {panel.setting}
        </div>
        <div>{panel.action}</div>
        {panel.dialogue.map((d, i) => (
          <div key={i} className="text-xs">
            <b>{d.speaker}:</b> “{d.text}”
          </div>
        ))}
        {panel.narration && <div className="text-xs italic">▭ {panel.narration}</div>}
        {panel.sfx.length > 0 && (
          <div className="mt-1 flex gap-1">
            {panel.sfx.map((s) => (
              <span key={s} className="-skew-x-12 bg-ink px-1.5 text-[11px] font-black text-paper">
                {s}
              </span>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}

function PagePlanView({ project }: { project: MangaProject }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {project.page_plan!.pages.map((page) => (
        <div key={page.page_number} className="border-2 border-ink bg-white p-3">
          <div className="flex items-baseline justify-between">
            <h3 className="font-black">Page {page.page_number}</h3>
            <span className="text-xs text-ink/60">{page.panels.length} panels</span>
          </div>
          <ol>
            {page.panels.map((p) => (
              <PanelLine key={p.panel_number} panel={p} />
            ))}
          </ol>
          {page.page_turn && <div className="mt-2 border-t-2 border-ink pt-2 text-xs">↪ Page turn: {page.page_turn}</div>}
        </div>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------- director
function DirectorView({ project, layouts }: { project: MangaProject; layouts: LayoutTemplate[] }) {
  const byId = useMemo(() => Object.fromEntries(layouts.map((l) => [l.id, l])), [layouts]);
  const [rtl, setRtl] = useState(true);
  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={rtl} onChange={(e) => setRtl(e.target.checked)} /> Show right-to-left (manga) order
      </label>
      {project.director!.pages.map((page, pi) => {
        const template = byId[page.layout];
        const planned = project.page_plan?.pages[pi]?.panels ?? [];
        return (
          <div key={page.page_number} className="grid gap-4 border-2 border-ink bg-white p-3 sm:grid-cols-[8rem_1fr]">
            <div className="text-center">
              {template ? <LayoutThumb template={template} panels={page.panels} rtl={rtl} className="w-32" /> : null}
              <div className="mt-1 text-xs font-bold">{template?.name ?? page.layout}</div>
              <div className="text-[10px] text-ink/60">Page {page.page_number}</div>
            </div>
            <ol className="space-y-1.5 text-sm">
              {page.panels.map((p, i) => (
                <li key={p.panel_number} className="flex gap-2">
                  <span className="w-5 shrink-0 text-right font-black">{p.panel_number}</span>
                  <span className="w-12 shrink-0 bg-ink px-1 text-center text-xs font-bold text-paper">{SHOT_ABBR[p.shot]}</span>
                  <span className="w-20 shrink-0 text-xs">
                    {ANGLE_ICON[p.angle]} {p.angle}
                  </span>
                  <span className="min-w-0 text-xs text-ink/80">
                    {p.composition}
                    {planned[i] && <span className="text-ink/50"> — {planned[i].emotion}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        );
      })}
      <div className="text-xs text-ink/60">
        ECU extreme close-up · CU close-up · MS medium · WS wide · EST establishing · OTS over-the-shoulder · → eye level ·
        ↗ low · ↘ high · ↓ bird&apos;s eye
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- bible
function BibleView({ project }: { project: MangaProject }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {project.characters.map((c) => (
        <div key={c.name} className="border-2 border-ink bg-white p-3 text-sm">
          <div className="flex items-baseline justify-between">
            <b className="text-lg">{c.name}</b>
            <span className="text-xs">{c.role}</span>
          </div>
          <div className="text-xs text-ink/60">
            {c.age_range} · {c.body_type}
          </div>
          <p className="mt-1">{c.description}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(c.visual_tags)
              .filter(([, v]) => v && v !== "none")
              .map(([k, v]) => (
                <span key={k} className="border border-ink px-1.5 text-[11px]" title={k}>
                  {v}
                </span>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------- timings
function PipelineTimings({ timings }: { timings: Record<string, number> }) {
  const entries = Object.entries(timings);
  const max = Math.max(0.001, ...entries.map(([, v]) => v));
  if (entries.length === 0) return null;
  return (
    <section className="panel p-4">
      <h3 className="mb-2 font-bold">Pipeline timings</h3>
      <div className="space-y-1">
        {entries.map(([name, seconds]) => (
          <div key={name} className="grid grid-cols-[9rem_1fr_4.5rem] items-center gap-2 text-xs">
            <span>{NODE_LABELS[name] ?? name}</span>
            <div className="h-3 border border-ink bg-white">
              <div className="h-full bg-ink" style={{ width: `${Math.max(1, (seconds / max) * 100)}%` }} />
            </div>
            <span className="text-right font-mono">{fmtSeconds(seconds)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
