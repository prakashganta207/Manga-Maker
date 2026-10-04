// Tiny typed client for the FastAPI backend.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type JobStatus = "queued" | "running" | "done" | "failed";
export type StageStatus = "pending" | "running" | "done" | "failed";
export type Direction = "rtl" | "ltr";

export interface Stage {
  name: string;
  status: StageStatus;
  progress: number;
  message: string;
}

export interface CharacterInfo {
  name: string;
  description: string;
  reference_image: string | null;
  reference_image_url: string | null;
}

export interface JobResult {
  title: string;
  page_count: number;
  panel_count: number;
  providers: { llm: string; image: string };
  warnings: string[];
  script_url: string;
  prompts_url: string;
  characters: CharacterInfo[];
  outputs: Record<Direction, { pages: string[]; pdf: string }>;
}

export interface Job {
  id: string;
  status: JobStatus;
  progress: number;
  created_at: number;
  updated_at: number;
  stages: Stage[];
  error: string | null;
  result: JobResult | null;
}

export interface Health {
  status: string;
  providers: { llm: string; image: string };
  panels_per_page: number;
  max_pages: number;
}

/** Backend file paths ("/files/...") -> absolute URL. */
export function fileUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_URL}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  createJob: (story: string) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ story }) }),
  getJob: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
};

/** Download a (cross-origin) file with a proper filename instead of opening it in a tab. */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const response = await fetch(fileUrl(url));
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
