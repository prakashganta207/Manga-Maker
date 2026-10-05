"use client";

import type { EditorPanel, Job, MangaProject } from "@/lib/api";
import type { MaskTool } from "./PageCanvas";

export default function PanelTools({
  panel,
}: {
  job: Job;
  project: MangaProject;
  page: number;
  panel: EditorPanel;
  mask: MaskTool | null;
  setMask: (m: MaskTool | null) => void;
  onQueued: (message: string) => void;
  onError: (message: string) => void;
}) {
  return (
    <div className="panel space-y-2 p-4 text-sm">
      <h3 className="font-black">Panel {panel.panel}</h3>
      <p className="text-ink/70">{panel.action}</p>
    </div>
  );
}
