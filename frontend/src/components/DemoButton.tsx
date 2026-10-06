"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type DemoInfo } from "@/lib/api";

/** "Open the demo": loads the pre-generated sample series instantly (no GPU, no API keys). */
export default function DemoButton() {
  const router = useRouter();
  const [demo, setDemo] = useState<DemoInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.demoStatus().then(setDemo).catch(() => setDemo({ available: false }));
  }, []);

  async function open() {
    setBusy(true);
    setError(null);
    try {
      const info = await api.loadDemo();
      router.push(`/projects/${info.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  if (demo === null) return <span className="btn opacity-50">Checking demo…</span>;
  if (!demo.available) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <button type="button" className="btn btn-primary" onClick={open} disabled={busy}>
        {busy ? "Loading the demo…" : `▶ Open the demo${demo.title ? `: ${demo.title}` : ""}`}
      </button>
      <span className="text-xs text-ink/60">A finished 2-chapter series made with the real pipeline — opens instantly, no GPU needed.</span>
      {error && <span className="text-xs text-red-800">{error}</span>}
    </div>
  );
}
