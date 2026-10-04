// Tiny typed client for the FastAPI backend.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type JobStatus = "queued" | "running" | "done" | "failed" | "awaiting_approval";
export type StageStatus = "pending" | "running" | "done" | "failed" | "waiting";
export type Direction = "rtl" | "ltr";

export interface Stage {
  name: string;
  status: StageStatus;
  progress: number;
  message: string;
}

export interface CharacterSummary {
  name: string;
  description: string;
  tags: string;
  approved: boolean;
  reference_image: string | null;
  reference_image_url: string | null;
}

export interface JobResult {
  title: string;
  status: string;
  page_count: number;
  panel_count: number;
  providers: { llm: string; image: string; llm_model?: string };
  warnings: string[];
  usage: Usage;
  characters: CharacterSummary[];
  outputs: Partial<Record<Direction, { pages: string[]; pdf: string | null }>>;
  files_base: string;
  project_url: string;
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
  options: { auto_approve?: boolean; project_id?: string };
  busy: string | null;
}

export interface Health {
  status: string;
  providers: { llm: string; image: string; llm_model?: string };
  max_pages: number;
  auto_approve: boolean;
}

// ----------------------------------------------------------------------------- agent state
export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface AgentStep {
  agent: string;
  label: string;
  started_at: string;
  duration_s: number;
  status: "ok" | "failed" | "skipped";
  attempts: number;
  errors: string[];
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  inputs: Record<string, unknown>;
  output: unknown;
  notes: string[];
}

export interface Beat {
  id: number;
  summary: string;
  emotion: string;
  intensity: number;
  kind: string;
}

export interface BeatSheet {
  title: string;
  logline: string;
  emotional_arc: string;
  beats: Beat[];
  climax_beat: number;
  characters: { name: string; role: string; importance: string; summary: string }[];
}

export interface DialogueLine {
  speaker: string;
  text: string;
}

export interface PlannedPanel {
  panel_number: number;
  beat: number;
  purpose: string;
  size: "splash" | "large" | "medium" | "small";
  characters: string[];
  action: string;
  setting: string;
  emotion: string;
  dialogue: DialogueLine[];
  narration: string | null;
  sfx: string[];
}

export interface PagePlan {
  pages: { page_number: number; panels: PlannedPanel[]; page_turn: string }[];
}

export interface DirectedPanel {
  panel_number: number;
  shot: string;
  angle: string;
  composition: string;
}

export interface DirectorPlan {
  pages: { page_number: number; layout: string; panels: DirectedPanel[] }[];
}

export interface VisualTags {
  hair: string;
  eyes: string;
  outfit: string;
  accessories: string;
  distinguishing_marks: string;
}

export interface CharacterEntry {
  name: string;
  role: string;
  age_range: string;
  body_type: string;
  description: string;
  visual_tags: VisualTags;
  personality: string;
  expression_range: string[];
  slug: string;
  turnaround_seed: number;
  expression_seed: number;
  sheets: {
    turnaround: string | null;
    expressions: string | null;
    views: Record<string, string>;
    expression_refs: Record<string, string>;
  };
  status: string;
  approved: boolean;
  version: number;
  reused_from: string | null;
}

export interface PanelPrompt {
  page: number;
  panel: number;
  prompt: string;
  negative_prompt: string;
  seed: number;
  width: number;
  height: number;
  characters: string[];
  references: string[];
  reference_kinds: string[];
  ipadapter_weight: number | null;
}

export interface PanelResult {
  page: number;
  panel: number;
  image: string;
  seconds: number;
  workflow: string;
  consistency: Record<string, number>;
  consistency_method: string;
}

export interface MangaProject {
  job_id: string;
  project_id: string;
  story: string;
  title: string;
  status: string;
  auto_approve: boolean;
  providers: Record<string, string>;
  beat_sheet: BeatSheet | null;
  page_plan: PagePlan | null;
  director: DirectorPlan | null;
  rule_fixes: string[];
  characters: CharacterEntry[];
  prompts: PanelPrompt[];
  panels: PanelResult[];
  trace: AgentStep[];
  usage: Usage;
  timings: Record<string, number>;
  warnings: string[];
  error: string | null;
  files_base: string;
}

export interface LayoutTemplate {
  id: string;
  name: string;
  panels: number;
  description: string;
  slots: { size: string; shape: string; x: number; y: number; w: number; h: number }[];
}

export interface SampleStory {
  id: string;
  title: string;
  story: string;
}

export interface ProjectInfo {
  project_id: string;
  characters: { name: string; approved: boolean; image: string | null }[];
  updated_at: string;
}

/** Backend file paths ("/files/...") -> absolute URL. */
export function fileUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_URL}${path}`;
}

/** A path relative to a job folder -> absolute URL (cache-busted when `version` is given). */
export function jobFileUrl(project: { files_base: string }, relative: string, version?: number | string): string {
  const url = fileUrl(project.files_base + relative);
  return version === undefined ? url : `${url}?v=${version}`;
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
  createJob: (story: string, options: { auto_approve?: boolean; project_id?: string } = {}) =>
    request<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ story, ...options }) }),
  getJob: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  getProject: (id: string) => request<MangaProject>(`/api/jobs/${encodeURIComponent(id)}/project`),
  layouts: () => request<LayoutTemplate[]>("/api/layouts"),
  samples: () => request<SampleStory[]>("/api/samples"),
  projects: () => request<ProjectInfo[]>("/api/projects"),
  // Cast approval
  approveCharacter: (id: string, name: string, approved = true) =>
    request<MangaProject>(`/api/jobs/${encodeURIComponent(id)}/characters/${encodeURIComponent(name)}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  approveAll: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}/approve`, { method: "POST" }),
  regenerateSheet: (id: string, name: string, sheet: "turnaround" | "expressions" | "both") =>
    request<Job>(`/api/jobs/${encodeURIComponent(id)}/characters/${encodeURIComponent(name)}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ sheet }),
    }),
  editCharacter: (
    id: string,
    name: string,
    patch: Partial<Pick<CharacterEntry, "description" | "personality" | "age_range" | "body_type">> & {
      visual_tags?: Partial<VisualTags>;
    },
  ) =>
    request<MangaProject>(`/api/jobs/${encodeURIComponent(id)}/characters/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
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
