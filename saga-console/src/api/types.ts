/* ------------------------------------------------------------------ */
/* API types — console runtime data models                             */
/* ------------------------------------------------------------------ */

export type ConsoleModule = {
  module_id: string;
  title: string;
  description: string;
  status: string;
  version?: string;
  tags?: string[];
  pipeline?: string;
  task_type?: string;
  runtime?: Record<string, unknown>;
  capabilities?: string[];
  cost_policy?: Record<string, unknown>;
  ui?: Record<string, unknown>;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
};

export type ConsoleFlow = {
  flow_id: string;
  status: string;
  owner_id: string;
  version: string;
  created_at?: string;
  updated_at?: string;
  nodes?: Array<{
    node_id: string;
    module_id: string;
    config?: Record<string, unknown>;
  }>;
  edges?: Array<{
    from: string;
    to: string;
    mapping?: Record<string, unknown>;
  }>;
  contract_validation?: FlowContractValidation;
  raw_blueprint?: {
    name?: string;
    version?: string;
    steps?: Array<{
      id: string;
      block: string;
      inputs: Record<string, unknown>;
      params?: Record<string, unknown>;
    }>;
  };
};

export type ContractIssue = {
  code: string;
  path: string;
  message: string;
};

export type FlowContractValidation = {
  ok: boolean;
  checked_nodes: number;
  checked_edges: number;
  sources: Record<string, string>;
  issues: ContractIssue[];
  errors: string[];
};

export type ConsoleRun = {
  run_id: string;
  target_type: 'module' | 'flow';
  target_id: string;
  status: 'running' | 'done' | 'failed' | 'stopped';
  raw_status: string;
  mode: 'stub' | 'real';
  created_at: string;
  updated_at: string;
  provider_profile?: string;
  timeline?: Array<{
    node_id: string;
    module_id: string;
    elapsed_sec?: number;
    status?: string;
    error?: string;
    meta?: Record<string, unknown>;
  }>;
  result?: Record<string, unknown>;
  metrics?: {
    latency_ms?: number;
    cost_units?: number;
    retries?: number;
    tokens?: number;
  };
};

export type ProviderProfile = {
  id: string;
  enabled: boolean;
  allowed_models: string[];
  daily_budget_units: number;
  per_run_cap_units: number;
  requires_scope: string;
  timeout_caps?: Record<string, unknown>;
  retry_caps?: Record<string, unknown>;
  redaction_policy?: Record<string, unknown>;
};

export type AuthLoginResponse = {
  accessToken: string;
  tokenType?: string;
  user?: {
    userId?: string;
    id?: string;
    name?: string;
    email?: string;
  };
};

export type MeResponse = {
  user_id: string;
  is_admin: boolean;
  email?: string | null;
};
