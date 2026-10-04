export type ProjectStatus =
  | 'created'
  | 'running'
  | 'paused'
  | 'awaiting_approval'
  | 'needs_attention'
  | 'completed'
  | 'stopped'
  | 'failed'

export type TaskStatus =
  | 'backlog'
  | 'planned'
  | 'in_progress'
  | 'testing'
  | 'review'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface Project {
  id: string
  name: string
  slug: string
  objective: string
  status: ProjectStatus
  phase: string
  iteration: number
  progress: number
  workspace_path: string
  settings: Record<string, unknown>
  status_reason: string
  preview_url: string | null
  summary: string
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  description: string
  role: string
  kind: string
  status: TaskStatus
  priority: number
  depends_on: string[]
  iteration: number
  attempts: number
  max_attempts: number
  input: Record<string, unknown>
  output: Record<string, unknown>
  summary: string
  error: string
  created_by: string
  seq: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AgentInfo {
  role: string
  title: string
  description: string
  kinds: string[]
  uses_llm: boolean
  status: 'idle' | 'working' | 'retrying' | 'error'
  current_task: {
    id: string
    title: string
    project_id: string
    elapsed_s: number
    attempt: number
    tokens: number
  } | null
  last_activity: number | null
  last_summary: string
  last_error: string
  completed: number
  failed: number
}

export interface Snapshot {
  project: Project
  tasks: Task[]
  counts: Partial<Record<TaskStatus, number>>
  agents: AgentInfo[]
  open_bugs: number
  runner_active: boolean
  running_tasks: number
  usage: { calls: number; input_tokens: number; output_tokens: number; latency_ms: number }
  phases: string[]
  iteration_scores: Record<string, { score: number; blocking: number; commit: string | null }>
}

export interface EventItem {
  id: number | null
  project_id: string | null
  ts: string
  type: string
  level: 'info' | 'warning' | 'error'
  agent: string | null
  task_id: string | null
  message: string
  data: Record<string, unknown>
}

export interface Issue {
  severity: string
  category: string
  message: string
  file: string
  line: number
  source: string
  evidence: string
  suggestion: string
  fingerprint: string
}

export interface Report {
  id: string
  project_id: string
  task_id: string | null
  kind: 'test' | 'security' | 'review' | 'final_review' | 'deploy'
  iteration: number
  passed: boolean
  score: number
  summary: string
  details: Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  commit: string | null
  created_at: string
}

export interface MemoryItem {
  id: number
  kind: string
  key: string
  value: any // eslint-disable-line @typescript-eslint/no-explicit-any
  source: string
  created_at: string
  updated_at: string
}

export interface LLMCall {
  id: number
  task_id: string | null
  role: string
  provider: string
  model: string
  purpose: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  ok: boolean
  error: string
  created_at: string
  prompt_preview?: string
  response_text?: string
}

export interface Commit {
  sha: string
  short: string
  message: string
  author: string
  date: string
  files: string[]
}

export interface SystemStatus {
  version: string
  llm: { provider: string; model: string; ok: boolean; detail: string }
  node: { ok: boolean }
  git: { ok: boolean }
  browser: { ok: boolean; detail: string }
  settings: Record<string, unknown>
}
