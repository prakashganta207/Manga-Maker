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
  quality?: QualitySummary;
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

export type Criterion =
  | "script_action"
  | "characters"
  | "people_count"
  | "character_likeness"
  | "shot_angle"
  | "emotion"
  | "anatomy"
  | "manga_style"
  | "bubble_space";

export interface EditorFix {
  prompt_add: string[];
  prompt_remove: string[];
  negative_add: string[];
  ipadapter_weight: number | null;
  new_seed: boolean;
}

export interface EditorReview {
  scores: Record<Criterion, number>;
  verdict: "pass" | "fail";
  problems: string[];
  fix: EditorFix;
  reasoning: string;
}

export interface QualityScore {
  editor: number | null;
  clip: number | null;
  combined: number;
  threshold: number;
  passed: boolean;
  reasons: string[];
}

export type AttemptStatus = "pending" | "accepted" | "rejected" | "needs_review" | "unreviewed";

export interface PanelAttempt {
  attempt: number;
  round: number;
  source: "auto" | "redraw" | "revision" | "inpaint" | string;
  image: string;
  prompt: string;
  negative_prompt: string;
  seed: number;
  width: number;
  height: number;
  ipadapter_weight: number | null;
  workflow: string;
  seconds: number;
  consistency: Record<string, number>;
  consistency_method: string;
  review: EditorReview | null;
  quality: QualityScore | null;
  fix_applied: EditorFix | null;
  status: AttemptStatus;
  note: string;
  extra: Record<string, unknown>;
  created_at: string;
}

export interface PanelResult {
  page: number;
  panel: number;
  image: string;
  seconds: number;
  workflow: string;
  consistency: Record<string, number>;
  consistency_method: string;
  attempts: PanelAttempt[];
  chosen_attempt: number;
  status: "accepted" | "needs_review" | "unreviewed" | "drawing";
  review_note: string;
}

export interface BudgetUsage {
  llm_calls: number;
  gpu_seconds: number;
  images: number;
  redraws: number;
  exhausted: string | null;
  limits: Partial<Record<"llm_calls" | "llm_cost_usd" | "gpu_seconds" | "max_attempts" | "threshold", number>>;
}

export interface QualitySummary {
  accepted: number;
  needs_review: number;
  unreviewed: number;
  attempts: number;
  redraws: number;
  llm_calls: number;
  gpu_seconds: number;
  budget_exhausted: string | null;
  cost_per_page_usd: number;
  gpu_seconds_per_page: number;
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
  budget: BudgetUsage;
  timings: Record<string, number>;
  warnings: string[];
  error: string | null;
  files_base: string;
}

// ----------------------------------------------------------------------------- editor (Phase 4)
export type BubbleKind = "speech" | "thought" | "shout" | "narration" | "sfx";

/** One editable lettering layer. x/y/w/h/tail are fractions (0..1) of the panel's inner rectangle. */
export interface Bubble {
  id: string;
  panel: number;
  kind: BubbleKind;
  text: string;
  speaker: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
  tail: [number, number] | null;
  font_size: number;
  vertical: boolean;
  order: number;
}

export interface PageLettering {
  page: number;
  bubbles: Bubble[];
  source: "auto" | "edited";
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EditorPanel {
  panel: number;
  rect: Box;
  inner: Box;
  image: string | null;
  status: string | null;
  characters: string[];
  action: string;
  emotion: string;
  dialogue: DialogueLine[];
  narration: string | null;
  sfx: string[];
}

export interface EditorPage {
  page: number;
  direction: Direction;
  width: number;
  height: number;
  border: number;
  layout: string;
  panels: EditorPanel[];
  lettering: PageLettering | null;
  rendered: string | null;
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
    // Only send Content-Type with a body: on GETs it would trigger a CORS preflight per poll.
    headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers || {}) },
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
  // Editor (Phase 4)
  editorPage: (id: string, page: number, direction: Direction) =>
    request<EditorPage>(`/api/jobs/${encodeURIComponent(id)}/pages/${page}/editor?direction=${direction}`),
  saveLettering: (id: string, page: number, bubbles: Bubble[], label?: string) =>
    request<EditorPage>(`/api/jobs/${encodeURIComponent(id)}/pages/${page}/lettering`, {
      method: "PUT",
      body: JSON.stringify({ bubbles, ...(label ? { label } : {}) }),
    }),
  revisePanel: (id: string, page: number, panel: number, instruction: string) =>
    request<Job>(`/api/jobs/${encodeURIComponent(id)}/panels/${page}/${panel}/revise`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  inpaintPanel: (
    id: string,
    page: number,
    panel: number,
    body: { strokes: { points: number[]; size: number; erase: boolean }[]; prompt: string; character: string; denoise?: number },
  ) =>
    request<Job>(`/api/jobs/${encodeURIComponent(id)}/panels/${page}/${panel}/inpaint`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  resetLettering: (id: string, page: number) =>
    request<EditorPage>(`/api/jobs/${encodeURIComponent(id)}/pages/${page}/lettering/reset`, { method: "POST" }),
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
