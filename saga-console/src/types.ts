/* ------------------------------------------------------------------ */
/* Shared types for the Saga Console frontend                          */
/* ------------------------------------------------------------------ */

// --- Registry / Block metadata ---

export interface BlockMeta {
  name: string;
  description: string;
  category: string;
  icon: string;
  color: string;
  inputKeys: string[];
  outputKeys: string[];
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
}

// --- Blueprint structures ---

export interface BlueprintStep {
  id: string;
  block: string;
  inputs: Record<string, unknown>;
  params?: Record<string, unknown>;
}

export interface Blueprint {
  name: string;
  version: string;
  steps: BlueprintStep[];
}

export interface BlueprintListItem {
  name: string;
  owner_id: string;
  status: 'DRAFT' | 'SANDBOXED' | 'ACTIVE' | 'ARCHIVED';
  created_at: string;
  contract_ok?: boolean;
  contract_issue_count?: number;
}

export interface BlueprintInfoResponse {
  name: string;
  owner_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  data: Blueprint;
}

// --- Execution ---

export interface TraceEntry {
  step: string;
  block: string;
  elapsed_sec: number;
  dry_run: boolean;
  output_keys: string[];
  status?: 'succeeded' | 'failed';
  error?: string;
}

export interface PerformanceMetrics {
  duration_ms: number;
  cost_estimate: number;
  reliability_score: number;
}

export interface ExecutionResult {
  blueprint: string;
  run_id?: string;
  status: string;
  execution_mode: string;
  scan_id?: string;
  scored_count: number;
  job_count: number;
  source_counts: Record<string, number>;
  execution_trace: TraceEntry[];
  performance: PerformanceMetrics;
  ai_summary?: string;
}

// --- Run history ---

export interface SagaRunSummary {
  run_id: string;
  blueprint_name: string;
  owner_id: string;
  status: string;
  execution_mode: string;
  created_at: string;
}

export interface SagaRunDetail extends SagaRunSummary {
  request_payload: Record<string, unknown>;
  result: Record<string, unknown>;
  execution_trace: TraceEntry[];
  performance: Record<string, unknown>;
  ai_summary?: string;
  updated_at: string;
}

export interface ModuleStat {
  block: string;
  run_count: number;
  step_count: number;
  avg_elapsed_sec: number;
  last_seen?: string | null;
}

// --- Draft ---

export interface DraftResult {
  ok: boolean;
  blueprint: Record<string, unknown>;
  blueprint_id?: string;
  status: string;
  model?: {
    model_tier: string;
    model_name: string;
    model_label: string;
    credit_cost: number;
  };
  validation_errors: string[];
  safety: {
    passed: boolean;
    reason: string;
    warnings: string[];
  };
  dry_run?: {
    status: string;
    execution_mode: string;
    job_count: number;
    scored_count: number;
    execution_trace: TraceEntry[];
  };
  ai_summary?: string;
}

// --- React Flow node data ---

export type NodeStatus = 'idle' | 'running' | 'success' | 'error';

export type NodeShape = 'default' | 'diamond' | 'hexagon' | 'stadium' | 'circle';

export interface SagaNodeData {
  blockType: string;
  stepId: string;
  label: string;
  icon: string;
  color: string;
  category?: string;
  description: string;
  handleInputs: string[];
  handleOutputs: string[];
  stepInputs: Record<string, unknown>;
  params: Record<string, unknown>;
  paramToggles?: Record<string, boolean>;
  status: NodeStatus;
  executionTime?: number;
  traceStatus?: 'succeeded' | 'failed' | 'skipped';
  traceError?: string;
  traceOutputKeys?: string[];
  /** Visual shape hint for the canvas renderer */
  shape?: NodeShape;
  /** When true, node is skipped during execution */
  disabled?: boolean;
  [key: string]: unknown; // required by React Flow
}
