import StoryForm from "@/components/StoryForm";

const AGENTS = [
  ["✎", "Writer", "beat sheet, then pages & panels with manga pacing"],
  ["🎬", "Director", "a layout per page, a shot and camera angle per panel"],
  ["☺", "Character Designer", "a character bible + reference sheets you approve"],
  ["🖌", "Artist", "panels drawn with your characters' references (IP-Adapter)"],
];

export default function Home() {
  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-4xl font-black leading-tight">Paste a short story. Get a manga.</h1>
        <p className="mt-2 max-w-2xl text-ink/70">
          A small team of AI agents adapts your story into black-and-white manga pages. Every step is visible in the
          agent timeline, and you approve the cast before anything is drawn.
        </p>
        <ol className="mt-4 grid gap-2 sm:grid-cols-4">
          {AGENTS.map(([icon, name, text], i) => (
            <li key={name} className="border-2 border-ink bg-white p-2 text-sm">
              <div className="font-black">
                {i + 1}. {icon} {name}
              </div>
              <div className="text-ink/70">{text}</div>
            </li>
          ))}
        </ol>
      </section>
      <StoryForm />
    </div>
  );
}
