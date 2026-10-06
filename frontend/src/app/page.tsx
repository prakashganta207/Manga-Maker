import Link from "next/link";
import DemoButton from "@/components/DemoButton";
import PipelineDiagram from "@/components/PipelineDiagram";
import StoryForm from "@/components/StoryForm";

const FEATURES = [
  ["🔍", "Quality loop", "A vision Editor grades every panel; failures are redrawn with its fixes and you see every attempt."],
  ["✎", "Human in the loop", "Approve the cast, edit bubbles on a canvas, say “make her angrier”, or repaint one region."],
  ["☺", "Consistent characters", "Reference sheets + IP-Adapter, ControlNet layouts, optional character LoRAs, CLIP scores."],
  ["📚", "Series memory", "Chapters share the cast, style and a running story so far. Export PDF, CBZ and webtoon."],
];

export default function Home() {
  return (
    <div className="space-y-10">
      <section className="grid items-center gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-4">
          <h1 className="text-4xl font-black leading-tight sm:text-5xl">
            Paste a short story.
            <br />
            <span className="-skew-x-6 inline-block bg-ink px-2 text-paper">A team of AI agents</span> draws the manga.
          </h1>
          <p className="max-w-2xl text-ink/75">
            Writer, Director, Character Designer, Artist, Editor and Letterer work through your story step by step. Every decision
            is visible in the agent timeline, you approve the cast before anything is drawn, and you can change any panel afterwards.
          </p>
          <div className="flex flex-wrap items-start gap-4">
            <a href="#start" className="btn">
              ✎ Start with a story ↓
            </a>
            <DemoButton />
          </div>
          <p className="text-sm">
            <Link href="/projects" className="font-semibold underline underline-offset-4">
              Your series →
            </Link>
          </p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2">
          {FEATURES.map(([icon, title, text]) => (
            <li key={title} className="panel p-3">
              <div className="font-black">
                <span aria-hidden className="mr-1">
                  {icon}
                </span>
                {title}
              </div>
              <p className="mt-1 text-sm text-ink/70">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-2xl font-black">How the agents work</h2>
        <PipelineDiagram />
      </section>

      <section id="start" className="scroll-mt-6 space-y-3">
        <h2 className="text-2xl font-black">Start a new manga</h2>
        <StoryForm />
      </section>
    </div>
  );
}
