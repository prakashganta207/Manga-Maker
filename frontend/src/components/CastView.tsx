"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend */

import { useState } from "react";
import { api, jobFileUrl, type CharacterEntry, type Job, type MangaProject, type VisualTags } from "@/lib/api";

const EXPRESSIONS = ["neutral", "happy", "angry", "sad", "surprised"];
const VIEWS = ["front", "side", "back"];
const TAG_FIELDS: (keyof VisualTags)[] = ["hair", "eyes", "outfit", "accessories", "distinguishing_marks"];

export default function CastView({ job, project, onChange }: { job: Job; project: MangaProject; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const waiting = job.status === "awaiting_approval";
  const locked = !waiting || !!job.busy || busy !== null;

  const mainNames = new Set(
    (project.beat_sheet?.characters ?? []).filter((c) => c.importance === "main").map((c) => c.name.toLowerCase()),
  );
  const main = project.characters.filter((c) => mainNames.has(c.name.toLowerCase()));
  const supporting = project.characters.filter((c) => !mainNames.has(c.name.toLowerCase()));
  const approvedCount = main.filter((c) => c.approved).length;

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <section className={`panel flex flex-wrap items-center justify-between gap-4 p-4 ${waiting ? "bg-amber-50" : ""}`}>
        <div>
          <h2 className="text-xl font-black">
            {waiting ? "Approve the cast" : "Cast"} · {approvedCount}/{main.length} approved
          </h2>
          <p className="text-sm text-ink/70">
            {waiting
              ? "Panels are drawn only after every main character is approved. Their reference images guide every panel (IP-Adapter)."
              : project.auto_approve
                ? "This job was auto-approved (unattended run)."
                : "Approved — these references were used to draw the panels."}
          </p>
          {job.busy && <p className="mt-1 text-sm font-semibold">⏳ {job.busy}…</p>}
        </div>
        {waiting && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={locked}
            onClick={() => act("approve-all", () => api.approveAll(job.id))}
          >
            {busy === "approve-all" ? "Starting…" : "Approve all & draw panels →"}
          </button>
        )}
      </section>
      {error && <p className="border-2 border-red-700 bg-red-50 p-3 text-sm text-red-800">{error}</p>}

      {main.map((c) => (
        <CharacterCard key={c.name} job={job} project={project} character={c} locked={locked} busy={busy} act={act} />
      ))}

      {supporting.length > 0 && (
        <section className="panel p-4">
          <h3 className="font-bold">Supporting characters (text tags only, no sheets)</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {supporting.map((c) => (
              <li key={c.name}>
                <b>{c.name}</b> — {Object.values(c.visual_tags).filter((v) => v && v !== "none").join(", ")}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function CharacterCard({
  job,
  project,
  character: c,
  locked,
  busy,
  act,
}: {
  job: Job;
  project: MangaProject;
  character: CharacterEntry;
  locked: boolean;
  busy: string | null;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(c.description);
  const [tags, setTags] = useState<VisualTags>(c.visual_tags);
  const img = (rel: string | null | undefined) => (rel ? jobFileUrl(project, rel, c.version) : null);
  const statusStyle =
    c.status === "approved"
      ? "bg-ink text-paper"
      : c.status === "generating"
        ? "bg-amber-200"
        : c.status === "edited"
          ? "bg-amber-100 border border-amber-700"
          : "bg-tone";

  return (
    <article className="panel space-y-4 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-2xl font-black">{c.name}</h3>
            <span className={`px-2 py-0.5 text-xs font-bold uppercase ${statusStyle}`}>{c.status}</span>
            {c.reused_from && <span className="border border-ink px-1.5 text-xs">from project {c.reused_from}</span>}
          </div>
          <p className="text-sm text-ink/70">
            {c.role} · {c.age_range} · {c.body_type} · {c.personality}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={`btn ${c.approved ? "" : "btn-primary"}`}
            disabled={locked}
            onClick={() => act(`approve-${c.name}`, () => api.approveCharacter(job.id, c.name, !c.approved))}
          >
            {c.approved ? "Unapprove" : "✓ Approve"}
          </button>
          <button type="button" className="btn" disabled={locked || c.look_locked} onClick={() => setEditing((v) => !v)}>
            {editing ? "Cancel edit" : "✎ Edit"}
          </button>
          <button
            type="button"
            className={`btn ${c.look_locked ? "btn-primary" : ""}`}
            disabled={!!job.busy || busy !== null}
            title="A locked look can't be edited or regenerated, and automatic redraws may not change this character's tags or reference strength"
            onClick={() => act(`lock-${c.name}`, () => api.lockCharacter(job.id, c.name, !c.look_locked))}
          >
            {c.look_locked ? "🔒 Look locked" : "🔓 Lock look"}
          </button>
        </div>
      </header>

      {editing ? (
        <form
          className="grid gap-2 border-2 border-ink bg-white p-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            act(`edit-${c.name}`, () => api.editCharacter(job.id, c.name, { description, visual_tags: tags })).then(() =>
              setEditing(false),
            );
          }}
        >
          <label className="grid gap-1">
            <b>Canonical description</b>
            <textarea className="border-2 border-ink p-2" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            {TAG_FIELDS.map((field) => (
              <label key={field} className="grid gap-1">
                <b>{field.replace("_", " ")}</b>
                <input className="border-2 border-ink p-1.5" value={tags[field]} onChange={(e) => setTags({ ...tags, [field]: e.target.value })} />
              </label>
            ))}
          </div>
          <p className="text-xs text-ink/60">Saving marks the character as edited — regenerate the sheets to see the new look.</p>
          <button type="submit" className="btn btn-primary w-fit" disabled={busy !== null}>
            Save changes
          </button>
        </form>
      ) : (
        <div className="space-y-2">
          <p>{c.description}</p>
          <div className="flex flex-wrap gap-1.5">
            {TAG_FIELDS.filter((f) => c.visual_tags[f] && c.visual_tags[f] !== "none").map((f) => (
              <span key={f} className="border-2 border-ink bg-white px-2 py-0.5 text-xs" title={`${f} — reused word-for-word in every prompt`}>
                {c.visual_tags[f]}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <SheetBlock
          title="Turnaround"
          seed={c.turnaround_seed}
          sheet={img(c.sheets.turnaround)}
          crops={VIEWS.map((v) => ({ label: v, src: img(c.sheets.views[v]) }))}
          disabled={locked || c.look_locked}
          onRegenerate={() => act(`regen-${c.name}-t`, () => api.regenerateSheet(job.id, c.name, "turnaround"))}
        />
        <SheetBlock
          title="Expressions"
          seed={c.expression_seed}
          sheet={img(c.sheets.expressions)}
          crops={EXPRESSIONS.map((e) => ({ label: e, src: img(c.sheets.expression_refs[e]) }))}
          disabled={locked || c.look_locked}
          onRegenerate={() => act(`regen-${c.name}-e`, () => api.regenerateSheet(job.id, c.name, "expressions"))}
        />
      </div>
    </article>
  );
}

function SheetBlock({
  title,
  seed,
  sheet,
  crops,
  disabled,
  onRegenerate,
}: {
  title: string;
  seed: number;
  sheet: string | null;
  crops: { label: string; src: string | null }[];
  disabled: boolean;
  onRegenerate: () => void;
}) {
  return (
    <div className="border-2 border-ink bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <b>{title}</b> <span className="font-mono text-xs text-ink/60">seed {seed}</span>
        </div>
        <button type="button" className="btn px-2 py-1 text-xs" disabled={disabled} onClick={onRegenerate}>
          ↻ New seed
        </button>
      </div>
      {sheet ? <img src={sheet} alt={`${title} sheet`} className="w-full border border-ink/30" /> : <div className="h-32 bg-tone" />}
      <div className="mt-2 flex gap-2">
        {crops.map((crop) => (
          <figure key={crop.label} className="min-w-0 flex-1 text-center">
            {crop.src ? (
              <img src={crop.src} alt={crop.label} className="mx-auto h-24 w-full border border-ink/30 bg-white object-contain" />
            ) : (
              <div className="h-24 bg-tone" />
            )}
            <figcaption className="text-[10px] uppercase">{crop.label}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
