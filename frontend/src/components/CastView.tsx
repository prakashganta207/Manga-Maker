"use client";

import type { Job, MangaProject } from "@/lib/api";

/** Cast page — filled in with approval controls in the next milestone. */
export default function CastView({ project }: { job: Job; project: MangaProject; onChange: () => void }) {
  return (
    <div className="panel p-6">
      <h2 className="text-xl font-black">Cast</h2>
      <ul className="mt-2 list-disc pl-5">
        {project.characters.map((c) => (
          <li key={c.name}>
            <b>{c.name}</b> — {c.description}
          </li>
        ))}
      </ul>
    </div>
  );
}
