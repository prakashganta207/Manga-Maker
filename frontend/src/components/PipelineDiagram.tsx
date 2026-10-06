// The agent pipeline as a diagram: stages left to right (wrapping on small screens), the
// human-in-the-loop checkpoints marked, and the quality loop drawn as a cycle.

const STAGES: { icon: string; name: string; who: string; text: string; kind?: "human" | "loop" | "code" }[] = [
  { icon: "✎", name: "Writer", who: "LLM agent", text: "Beat sheet, then pages and panels with manga pacing. Remembers the story so far across chapters." },
  { icon: "🎬", name: "Director", who: "LLM agent", text: "A layout template per page, shot and camera angle per panel. House rules enforced in code." },
  { icon: "☺", name: "Character Designer", who: "LLM agent", text: "Character bible with fixed visual tags; turnaround + expression sheets from fixed seeds." },
  { icon: "⏸", name: "Cast approval", who: "you", text: "Approve, edit or redraw each character. Optional: train a character LoRA.", kind: "human" },
  { icon: "▤", name: "Storyboard", who: "image model", text: "A fast rough per panel → pose skeleton or line art → ControlNet guide.", kind: "code" },
  { icon: "🖌", name: "Artist", who: "SDXL + IP-Adapter", text: "Each panel drawn with the characters' reference images (and LoRAs), one at a time on 8 GB." },
  { icon: "🔍", name: "Editor", who: "vision LLM", text: "Grades 9 criteria + CLIP likeness. Fails are redrawn with its fix — max 3 tries, budgeted.", kind: "loop" },
  { icon: "💬", name: "Letterer", who: "code + face detector", text: "Bubbles in reading order, away from faces, tails aimed at the speaker." },
  { icon: "✋", name: "Your edits", who: "you", text: "Canvas editor: bubbles, “make her angrier”, inpainting, locks, undo / versions.", kind: "human" },
  { icon: "⇩", name: "Export", who: "code", text: "PNG pages, PDF, CBZ for comic readers and a vertical webtoon strip.", kind: "code" },
];

const KIND_STYLE: Record<string, string> = {
  human: "bg-amber-100 border-amber-800",
  loop: "bg-ink text-paper border-ink",
  code: "bg-white border-ink border-dashed",
};

export default function PipelineDiagram() {
  return (
    <figure className="space-y-3" aria-label="The agent pipeline">
      <ol className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-5">
        {STAGES.map((stage, i) => (
          <li key={stage.name} className="relative">
            <div className={`h-full border-[3px] p-3 shadow-[4px_4px_0_#111] ${KIND_STYLE[stage.kind ?? ""] ?? "border-ink bg-paper"}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-lg font-black">
                  <span aria-hidden className="mr-1">
                    {stage.icon}
                  </span>
                  {stage.name}
                </span>
                <span className="font-mono text-[10px] opacity-60">{String(i + 1).padStart(2, "0")}</span>
              </div>
              <div className="text-[10px] font-bold uppercase tracking-wide opacity-70">{stage.who}</div>
              <p className="mt-1 text-xs leading-snug opacity-90">{stage.text}</p>
              {stage.kind === "loop" && (
                <div className="mt-2 flex items-center gap-1 text-[10px] font-bold">
                  <span className="animate-spin [animation-duration:3s]" aria-hidden>
                    ↻
                  </span>
                  redraw until it passes
                </div>
              )}
            </div>
            {i < STAGES.length - 1 && i % 5 !== 4 && (
              <span aria-hidden className="absolute -right-5 top-1/2 hidden -translate-y-1/2 text-xl font-black lg:block">
                →
              </span>
            )}
          </li>
        ))}
      </ol>
      <figcaption className="flex flex-wrap gap-4 text-xs text-ink/70">
        <span>
          <span className="mr-1 inline-block h-3 w-3 border-2 border-ink bg-paper align-middle" /> AI agent
        </span>
        <span>
          <span className="mr-1 inline-block h-3 w-3 border-2 border-amber-800 bg-amber-100 align-middle" /> human in the loop
        </span>
        <span>
          <span className="mr-1 inline-block h-3 w-3 border-2 border-ink bg-ink align-middle" /> quality loop
        </span>
        <span>
          <span className="mr-1 inline-block h-3 w-3 border-2 border-dashed border-ink bg-white align-middle" /> plain code / tools
        </span>
      </figcaption>
    </figure>
  );
}
