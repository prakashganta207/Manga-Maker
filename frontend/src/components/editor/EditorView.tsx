"use client";

/* eslint-disable @next/next/no-img-element -- images come from the backend, plain <img> is simplest */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  fileUrl,
  type Bubble,
  type BubbleKind,
  type Direction,
  type EditorPage,
  type HistorySummary,
  type Job,
  type MangaProject,
} from "@/lib/api";
import { KIND_LABEL, newBubbleId } from "@/lib/bubbles";
import type { MaskState } from "./PageCanvas";
import PanelTools from "./PanelTools";
import VersionList from "./VersionList";

// Konva needs the browser (window, canvas), so the canvas is never rendered on the server.
const PageCanvas = dynamic(() => import("./PageCanvas"), {
  ssr: false,
  loading: () => <div className="flex aspect-[1240/1754] items-center justify-center bg-white text-sm text-ink/50">Loading canvas…</div>,
});

const KINDS: BubbleKind[] = ["speech", "thought", "shout", "narration", "sfx"];
const HISTORY_LIMIT = 100;

export default function EditorView({
  job,
  project,
  onChanged,
}: {
  job: Job;
  project: MangaProject;
  onChanged: () => void;
}) {
  const pageCount = project.page_plan?.pages.length ?? 0;
  const [page, setPage] = useState(1);
  const [direction, setDirection] = useState<Direction>("rtl");
  const [data, setData] = useState<EditorPage | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [saved, setSaved] = useState<Bubble[]>([]);
  const [past, setPast] = useState<Bubble[][]>([]);
  const [future, setFuture] = useState<Bubble[][]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedPanel, setSelectedPanel] = useState<number | null>(null);
  const [mask, setMask] = useState<MaskState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [width, setWidth] = useState(640);
  const [hist, setHist] = useState<HistorySummary | null>(null);
  const [showFaces, setShowFaces] = useState(false);
  const [tick, setTick] = useState(0); // bump to re-fetch page + history after a server-side change
  const holder = useRef<HTMLDivElement>(null);
  const textBox = useRef<HTMLTextAreaElement>(null);
  const dirty = JSON.stringify(bubbles) !== JSON.stringify(saved);
  const version = `${job.updated_at}`;

  // Reload the page after a background action (redraw, inpaint...) finishes, unless you have
  // unsaved bubble edits ("adjust state while rendering" pattern, no effect needed).
  const [seenUpdate, setSeenUpdate] = useState(job.updated_at);
  if (!job.busy && !dirty && job.updated_at !== seenUpdate) setSeenUpdate(job.updated_at);

  const apply = useCallback((next: EditorPage) => {
    setData(next);
    const list = next.lettering?.bubbles ?? [];
    setBubbles(list);
    setSaved(list);
    setPast([]);
    setFuture([]);
    setError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .editorPage(job.id, page, direction)
      .then((next) => !cancelled && apply(next))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [job.id, page, direction, seenUpdate, tick, apply]);

  useEffect(() => {
    let cancelled = false;
    api
      .history(job.id)
      .then((h) => !cancelled && setHist(h))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [job.id, seenUpdate, tick]);

  /** Server-side history action (undo / redo / restore): re-render happens on the backend. */
  const serverHistory = useCallback(
    async (action: () => Promise<HistorySummary>, message: string) => {
      setBusy(message);
      setError(null);
      try {
        const result = await action();
        setHist(result);
        if (result.page && result.page !== page) setPage(result.page);
        setTick((t) => t + 1);
        setNotice(`${message.replace("…", "")} done.`);
        onChanged();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [page, onChanged],
  );

  // Fit the canvas to its column.
  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(280, Math.min(900, el.clientWidth))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const change = useCallback(
    (next: Bubble[]) => {
      setPast((p) => [...p.slice(-HISTORY_LIMIT), bubbles]);
      setFuture([]);
      setBubbles(next);
    },
    [bubbles],
  );
  const updateBubble = useCallback((b: Bubble) => change(bubbles.map((x) => (x.id === b.id ? b : x))), [bubbles, change]);

  const undoLocal = useCallback(() => {
    if (!past.length) return;
    setFuture((f) => [bubbles, ...f]);
    setBubbles(past[past.length - 1]);
    setPast((p) => p.slice(0, -1));
  }, [past, bubbles]);
  const redoLocal = useCallback(() => {
    if (!future.length) return;
    setPast((p) => [...p, bubbles]);
    setBubbles(future[0]);
    setFuture((f) => f.slice(1));
  }, [future, bubbles]);

  // Unsaved bubble edits are undone locally; once saved, undo/redo walk the server's version history.
  const localMode = dirty || past.length > 0 || future.length > 0;
  const canUndo = localMode ? past.length > 0 : !!hist?.can_undo;
  const canRedo = localMode ? future.length > 0 : !!hist?.can_redo;
  const undo = useCallback(() => {
    if (localMode) undoLocal();
    else if (hist?.can_undo) serverHistory(() => api.undo(job.id), `Undoing “${hist.undo_label}”…`);
  }, [localMode, undoLocal, hist, job.id, serverHistory]);
  const redo = useCallback(() => {
    if (localMode) redoLocal();
    else if (hist?.can_redo) serverHistory(() => api.redo(job.id), `Redoing “${hist.redo_label}”…`);
  }, [localMode, redoLocal, hist, job.id, serverHistory]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y" && !typing) {
        e.preventDefault();
        redo();
      } else if ((e.key === "Delete" || e.key === "Backspace") && selectedId && !typing) {
        change(bubbles.filter((b) => b.id !== selectedId));
        setSelectedId(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, selectedId, bubbles, change]);

  function addBubble(kind: BubbleKind) {
    const panel = selectedPanel ?? data?.panels[0]?.panel ?? 1;
    const info = data?.panels.find((p) => p.panel === panel);
    const b: Bubble = {
      id: newBubbleId(),
      panel,
      kind,
      text: kind === "sfx" ? "BAM!" : kind === "narration" ? "Meanwhile…" : "…",
      speaker: kind === "speech" || kind === "shout" || kind === "thought" ? info?.characters[0] ?? null : null,
      x: 0.3,
      y: 0.3,
      w: kind === "sfx" ? 0.4 : 0.36,
      h: kind === "sfx" ? 0.18 : 0.22,
      tail: kind === "speech" || kind === "shout" || kind === "thought" ? [0.5, 0.75] : null,
      font_size: kind === "sfx" ? 52 : 26,
      vertical: false,
      order: bubbles.length,
    };
    change([...bubbles, b]);
    setSelectedId(b.id);
    setTimeout(() => textBox.current?.select(), 50);
  }

  async function save() {
    setBusy("Saving and re-rendering the page…");
    setError(null);
    try {
      apply(await api.saveLettering(job.id, page, bubbles));
      setTick((t) => t + 1);
      setNotice("Saved. The page PNG and PDFs were re-rendered.");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    if (!window.confirm("Replace this page's lettering with the automatic placement?")) return;
    setBusy("Re-planning bubbles…");
    try {
      apply(await api.resetLettering(job.id, page));
      setTick((t) => t + 1);
      setSelectedId(null);
      setNotice("Automatic placement restored.");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  function switchPage(next: number) {
    if (dirty && !window.confirm("You have unsaved bubble edits on this page. Discard them?")) return;
    setPage(next);
    setMask(null);
    setSelectedId(null);
    setSelectedPanel(null);
  }

  const selected = bubbles.find((b) => b.id === selectedId) ?? null;
  const panelInfo = data?.panels.find((p) => p.panel === (selected?.panel ?? selectedPanel));
  const locked = job.busy !== null || job.status !== "done";

  return (
    <div className="space-y-4">
      <div className="panel flex flex-wrap items-center gap-2 p-3">
        <div className="flex items-center gap-1" role="group" aria-label="Page">
          {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => switchPage(n)}
              className={`border-2 border-ink px-2.5 py-1 text-sm font-bold ${n === page ? "bg-ink text-paper" : "bg-paper"}`}
            >
              p{n}
            </button>
          ))}
        </div>
        <span className="mx-1 h-6 w-px bg-ink/30" />
        <label className="flex items-center gap-1 text-sm">
          <select
            value={direction}
            onChange={(e) => {
              setDirection(e.target.value as Direction);
              setSelectedId(null);
            }}
            className="border-2 border-ink bg-paper px-1 py-1 text-sm"
            aria-label="Reading direction"
          >
            <option value="rtl">Right → left (manga)</option>
            <option value="ltr">Left → right</option>
          </select>
        </label>
        <span className="mx-1 h-6 w-px bg-ink/30" />
        <span className="text-xs font-bold uppercase text-ink/60">Add</span>
        {KINDS.map((k) => (
          <button key={k} type="button" className="btn !px-2 !py-1 text-xs" onClick={() => addBubble(k)} disabled={locked || !!mask}>
            + {KIND_LABEL[k]}
          </button>
        ))}
        <span className="mx-1 h-6 w-px bg-ink/30" />
        <button
          type="button"
          className={`btn !px-2 !py-1 text-xs ${bubbles.some((b) => b.vertical) ? "btn-primary" : ""}`}
          disabled={locked || !!mask || !bubbles.length}
          title="Vertical (top-to-bottom, right-to-left columns) or horizontal text for this page's balloons"
          onClick={() => {
            const vertical = !bubbles.some((b) => b.vertical);
            change(bubbles.map((b) => (b.kind === "sfx" || b.kind === "narration" ? b : { ...b, vertical })));
          }}
        >
          縦 Vertical text
        </button>
        <label className="flex items-center gap-1 text-xs" title="Show the faces the Letterer avoided (blue = detected, grey = estimated)">
          <input type="checkbox" checked={showFaces} onChange={(e) => setShowFaces(e.target.checked)} /> Faces
        </label>
        <span className="ml-auto flex items-center gap-2">
          <button
            type="button"
            className="btn !px-2 !py-1 text-sm"
            onClick={undo}
            disabled={!canUndo || locked || !!busy}
            title={localMode ? "Undo unsaved edit (Ctrl+Z)" : hist?.undo_label ? `Undo: ${hist.undo_label} (Ctrl+Z)` : "Nothing to undo"}
          >
            ↶
          </button>
          <button
            type="button"
            className="btn !px-2 !py-1 text-sm"
            onClick={redo}
            disabled={!canRedo || locked || !!busy}
            title={localMode ? "Redo (Ctrl+Y)" : hist?.redo_label ? `Redo: ${hist.redo_label} (Ctrl+Y)` : "Nothing to redo"}
          >
            ↷
          </button>
          <button type="button" className="btn !px-2 !py-1 text-sm" onClick={reset} disabled={locked || !!busy}>
            Auto-place
          </button>
          <button type="button" className="btn btn-primary !py-1" onClick={save} disabled={!dirty || locked || !!busy}>
            {dirty ? "Save page" : "Saved ✓"}
          </button>
        </span>
      </div>

      {(error || notice || busy || job.busy) && (
        <div
          className={`border-2 p-2 text-sm ${error ? "border-red-700 bg-red-50 text-red-800" : "border-ink bg-white"}`}
          role={error ? "alert" : "status"}
        >
          {error ?? (job.busy ? `⏳ ${job.busy}… (the page refreshes when it's done)` : busy ?? notice)}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div ref={holder} className="panel min-w-0 p-2">
          {data ? (
            <PageCanvas
              data={data}
              showFaces={showFaces}
              bubbles={bubbles}
              displayWidth={width - 16}
              selectedId={selectedId}
              selectedPanel={selectedPanel}
              imageVersion={version}
              mask={mask && { ...mask, onStrokes: (strokes) => setMask((m) => (m ? { ...m, strokes } : m)) }}
              onSelectBubble={setSelectedId}
              onSelectPanel={setSelectedPanel}
              onChange={updateBubble}
              onEditText={(id) => {
                setSelectedId(id);
                setTimeout(() => textBox.current?.focus(), 30);
              }}
            />
          ) : (
            <div className="p-8 text-center text-sm text-ink/60">{error ? "Could not load the page." : "Loading page…"}</div>
          )}
          <p className="mt-2 text-xs text-ink/60">
            Click a panel to select it · drag bubbles to move · drag the corners to resize · drag the orange dot to aim the tail ·
            double-click to edit text · Delete removes · Ctrl+Z / Ctrl+Y undo / redo (unsaved edits).
          </p>
        </div>

        <aside className="space-y-4">
          {selected ? (
            <BubbleInspector
              key={`${selected.id}:${selected.text}`}
              bubble={selected}
              characters={panelInfo?.characters ?? []}
              textBox={textBox}
              onChange={updateBubble}
              onDelete={() => {
                change(bubbles.filter((b) => b.id !== selected.id));
                setSelectedId(null);
              }}
            />
          ) : (
            <div className="panel p-4 text-sm text-ink/70">
              <h3 className="mb-1 font-black">Lettering</h3>
              Select a bubble to edit its text, type and speaker. {bubbles.length} layer(s) on this page
              {data?.lettering?.source === "edited" ? " (edited by you)" : " (automatic placement)"}.
              {hist && (
                <VersionList
                  title="Lettering versions"
                  history={hist}
                  target={`lettering:${page}`}
                  disabled={locked || !!busy || dirty}
                  onRestore={(v) => serverHistory(() => api.restore(job.id, v.id), `Restoring “${v.label}”…`)}
                />
              )}
            </div>
          )}
          {panelInfo && data && (
            <PanelTools
              job={job}
              project={project}
              page={page}
              panel={panelInfo}
              mask={mask}
              setMask={setMask}
              history={hist}
              onRestore={(v) => serverHistory(() => api.restore(job.id, v.id), `Restoring “${v.label}”…`)}
              onLocked={() => onChanged()}
              onQueued={(message) => {
                setNotice(message);
                onChanged();
              }}
              onError={setError}
            />
          )}
          {data?.rendered && (
            <div className="panel p-3 text-sm">
              <div className="mb-1 font-bold">Rendered page ({direction})</div>
              <a href={fileUrl(data.files_base + data.rendered)} target="_blank" rel="noreferrer">
                <img src={`${fileUrl(data.files_base + data.rendered)}?v=${version}-${saved.length}`} alt="Rendered page" className="w-full border border-ink" />
              </a>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function BubbleInspector({
  bubble,
  characters,
  textBox,
  onChange,
  onDelete,
}: {
  bubble: Bubble;
  characters: string[];
  textBox: React.RefObject<HTMLTextAreaElement | null>;
  onChange: (b: Bubble) => void;
  onDelete: () => void;
}) {
  const [text, setText] = useState(bubble.text); // remounted (key) when the bubble or its text changes
  const talks = bubble.kind === "speech" || bubble.kind === "shout" || bubble.kind === "thought";
  return (
    <div className="panel space-y-3 p-4 text-sm">
      <div className="flex items-center justify-between">
        <h3 className="font-black">{KIND_LABEL[bubble.kind]}</h3>
        <span className="font-mono text-xs text-ink/50">panel {bubble.panel}</span>
      </div>
      <label className="block">
        <span className="text-xs font-bold uppercase text-ink/60">Text</span>
        <textarea
          ref={textBox}
          value={text}
          rows={3}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text !== bubble.text && onChange({ ...bubble, text })}
          className="mt-1 w-full border-2 border-ink bg-white p-2"
        />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-xs font-bold uppercase text-ink/60">Type</span>
          <select
            value={bubble.kind}
            onChange={(e) => {
              const kind = e.target.value as BubbleKind;
              const tail = kind === "narration" || kind === "sfx" ? null : bubble.tail ?? [0.5, 0.75];
              onChange({ ...bubble, kind, tail });
            }}
            className="mt-1 w-full border-2 border-ink bg-white p-1"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-bold uppercase text-ink/60">Speaker</span>
          <select
            value={bubble.speaker ?? ""}
            disabled={!talks}
            onChange={(e) => onChange({ ...bubble, speaker: e.target.value || null })}
            className="mt-1 w-full border-2 border-ink bg-white p-1"
          >
            <option value="">—</option>
            {[...new Set([...characters, ...(bubble.speaker ? [bubble.speaker] : [])])].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block">
        <span className="flex justify-between text-xs font-bold uppercase text-ink/60">
          Max font size <span className="font-mono">{bubble.font_size}px</span>
        </span>
        <input
          type="range"
          min={12}
          max={bubble.kind === "sfx" ? 120 : 48}
          value={bubble.font_size}
          onChange={(e) => onChange({ ...bubble, font_size: Number(e.target.value) })}
          className="w-full accent-black"
        />
        <span className="text-[11px] text-ink/50">Text shrinks automatically to fit the bubble.</span>
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={!!bubble.tail}
            disabled={!talks}
            onChange={(e) => onChange({ ...bubble, tail: e.target.checked ? [0.5, 0.75] : null })}
          />
          Tail
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={bubble.vertical}
            disabled={bubble.kind === "sfx"}
            onChange={(e) => onChange({ ...bubble, vertical: e.target.checked })}
          />
          Vertical text
        </label>
      </div>
      <button type="button" className="btn w-full justify-center !border-red-800 text-red-800" onClick={onDelete}>
        Delete layer
      </button>
    </div>
  );
}
