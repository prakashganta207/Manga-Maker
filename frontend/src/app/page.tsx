import StoryForm from "@/components/StoryForm";

export default function Home() {
  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-4xl font-black leading-tight">Paste a short story. Get a manga page.</h1>
        <p className="mt-2 max-w-2xl text-ink/70">
          An LLM turns your story into a panel-by-panel script, an image model draws each panel in
          black-and-white manga style, and the app letters speech bubbles and lays out the page.
        </p>
      </section>
      <StoryForm />
    </div>
  );
}
