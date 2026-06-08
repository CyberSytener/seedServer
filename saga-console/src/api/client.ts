/* ------------------------------------------------------------------ */
/* API client - Console facade first, legacy shims second              */
/* ------------------------------------------------------------------ */
import { request } from './request';
import type {
  ConsoleModule,
  ConsoleFlow,
  ConsoleRun,
  FlowContractValidation,
  ProviderProfile,
  AuthLoginResponse,
  MeResponse,
} from './types';
import type {
  BlueprintInfoResponse,
  BlueprintListItem,
  DraftResult,
  ExecutionResult,
  ModuleStat,
  SagaRunDetail,
  SagaRunSummary,
  TraceEntry,
} from '../types';

/* Re-export types for consumer convenience */
export type { ConsoleModule, ConsoleFlow, ConsoleRun, ProviderProfile } from './types';

function toLegacyBlueprintStatus(status: string): BlueprintListItem['status'] {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'released' || normalized === 'active') return 'ACTIVE';
  if (normalized === 'sandboxed') return 'SANDBOXED';
  if (normalized === 'deprecated' || normalized === 'archived') return 'ARCHIVED';
  return 'DRAFT';
}

function toLegacyExecutionMode(mode: string): string {
  return mode === 'stub' ? 'DRY_RUN' : 'LIVE';
}

function timelineToLegacyTrace(
  timeline: NonNullable<ConsoleRun['timeline']>,
  mode: string,
): TraceEntry[] {
  return timeline.map((item) => {
    const meta = (item.meta ?? {}) as Record<string, unknown>;
    const outputKeys = meta.output_keys;
    return {
      step: item.node_id,
      block: item.module_id,
      elapsed_sec: Number(item.elapsed_sec ?? 0),
      dry_run: mode === 'stub',
      output_keys: Array.isArray(outputKeys)
        ? outputKeys.map((key) => String(key))
        : [],
      status: item.status === 'failed' ? 'failed' : 'succeeded',
      error: item.error ? String(item.error) : undefined,
    };
  });
}

function statusToLegacySagaStatus(status: ConsoleRun['status']): string {
  if (status === 'done') return 'succeeded';
  if (status === 'failed') return 'failed';
  if (status === 'stopped') return 'stopped';
  return 'running';
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForRunTerminal(
  runId: string,
  attempts = 80,
  intervalMs = 500,
): Promise<ConsoleRun> {
  let latest = await api.getRunRaw(runId);
  for (let idx = 0; idx < attempts; idx += 1) {
    if (latest.status !== 'running') {
      return latest;
    }
    await delay(intervalMs);
    latest = await api.getRunRaw(runId);
  }
  return latest;
}

function flowToBlueprintSteps(flow: ConsoleFlow): Array<{
  id: string;
  block: string;
  inputs: Record<string, unknown>;
  params?: Record<string, unknown>;
}> {
  const rawSteps = flow.raw_blueprint?.steps;
  if (Array.isArray(rawSteps) && rawSteps.length > 0) {
    return rawSteps;
  }

  const nodes = Array.isArray(flow.nodes) ? flow.nodes : [];
  const edges = Array.isArray(flow.edges) ? flow.edges : [];
  const incoming = new Map<string, Array<{ from: string; mapping?: Record<string, unknown> }>>();
  for (const edge of edges) {
    if (!edge?.to || !edge?.from) continue;
    const bucket = incoming.get(edge.to) ?? [];
    bucket.push({ from: edge.from, mapping: edge.mapping });
    incoming.set(edge.to, bucket);
  }

  return nodes.map((node) => {
    const config = (node.config ?? {}) as Record<string, unknown>;
    const inputs = (
      typeof config.inputs === 'object' && config.inputs
        ? { ...(config.inputs as Record<string, unknown>) }
        : {}
    ) as Record<string, unknown>;
    const params = (
      typeof config.params === 'object' && config.params
        ? (config.params as Record<string, unknown>)
        : Object.fromEntries(
            Object.entries(config).filter(
              ([key]) =>
                !['inputs', 'params', 'retry', 'timeout', 'budget_slice'].includes(key),
            ),
          )
    ) as Record<string, unknown>;

    for (const edge of incoming.get(node.node_id) ?? []) {
      const mapping = edge.mapping;
      if (mapping && typeof mapping === 'object' && Object.keys(mapping).length > 0) {
        for (const [targetKey, sourceKey] of Object.entries(mapping)) {
          const sourcePath = String(sourceKey || '').trim();
          inputs[targetKey] = { from: sourcePath ? `${edge.from}.${sourcePath}` : edge.from };
        }
      } else {
        inputs[edge.from] = { from: edge.from };
      }
    }

    const step = {
      id: node.node_id,
      block: node.module_id,
      inputs,
    } as {
      id: string;
      block: string;
      inputs: Record<string, unknown>;
      params?: Record<string, unknown>;
    };
    if (Object.keys(params).length > 0) {
      step.params = params;
    }
    return step;
  });
}

const DEFAULT_GALLERY_FLOWS: Array<{
  name: string;
  steps: Array<{
    id: string;
    block: string;
    inputs: Record<string, unknown>;
    params?: Record<string, unknown>;
  }>;
}> = [
  {
    name: 'market_scan_default',
    steps: [
      {
        id: 'market_scanner_1',
        block: 'market_scanner',
        inputs: {
          user_id: { from: 'user_id' },
          persona: { from: 'persona' },
        },
      },
      {
        id: 'job_scorer_1',
        block: 'job_scorer',
        inputs: {
          user_id: { from: 'user_id' },
          persona: { from: 'persona' },
          jobs: { from: 'market_scanner_1.jobs' },
          scan_id: { from: 'market_scanner_1.scan_id' },
        },
      },
      {
        id: 'notification_1',
        block: 'notification_block',
        inputs: {
          items: { from: 'job_scorer_1.scored_jobs' },
        },
        params: { channel: 'webhook', top_n: 3 },
      },
    ],
  },
];

export const api = {
  login: (username: string, password: string) =>
    request<AuthLoginResponse>(
      '/api/v1/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      },
      { includeAuth: false },
    ),

  me: () => request<MeResponse>('/v1/me'),

  refreshToken: () =>
    request<AuthLoginResponse>('/api/v1/auth/refresh', { method: 'POST' }),

  logout: () =>
    request<{ ok: boolean; user_id: string }>('/api/v1/auth/logout', {
      method: 'POST',
    }),

  /* ---- Console facade: modules ---- */
  getModules: () => request<{ modules: ConsoleModule[] }>('/v1/modules'),

  getModule: (moduleId: string) =>
    request<ConsoleModule>(`/v1/modules/${encodeURIComponent(moduleId)}`),

  runModule: (
    moduleId: string,
    mode: 'stub' | 'real',
    input: Record<string, unknown>,
  ) =>
    request<ConsoleRun>('/v1/runs', {
      method: 'POST',
      body: JSON.stringify({
        target: { type: 'module', id: moduleId },
        mode,
        input,
      }),
    }),

  releaseModule: (moduleId: string, version?: string, notes?: string) =>
    request<{ release_id: string; version: string }>(
      `/v1/modules/${encodeURIComponent(moduleId)}/release`,
      {
        method: 'POST',
        body: JSON.stringify({ version, notes }),
      },
    ),

  validateModule: (
    moduleId: string,
    sampleInput: Record<string, unknown>,
  ) =>
    request<{ ok: boolean; errors: string[] }>(
      `/v1/modules/${encodeURIComponent(moduleId)}/validate`,
      {
        method: 'POST',
        body: JSON.stringify({ sample_input: sampleInput }),
      },
    ),

  /* ---- Console facade: flows ---- */
  getFlows: () => request<{ flows: ConsoleFlow[] }>('/v1/flows'),

  getFlowRaw: (flowId: string) =>
    request<ConsoleFlow>(`/v1/flows/${encodeURIComponent(flowId)}`),

  compileFlow: (payload: {
    flow_id: string;
    version?: string;
    blueprint?: { steps: unknown[] };
    graph?: Record<string, unknown>;
    assertions?: Record<string, unknown>;
    entrypoint_schema?: Record<string, unknown>;
    observability?: Record<string, unknown>;
    save?: boolean;
  }) =>
    request<{
      flow_id: string;
      version: string;
      compiled_mode_payload_ref: Record<string, unknown>;
      contract_validation: FlowContractValidation;
    }>('/v1/flows/compile', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  releaseFlow: (flowId: string, version?: string, notes?: string) =>
    request<{ release_id: string; version: string }>(
      `/v1/flows/${encodeURIComponent(flowId)}/release`,
      {
        method: 'POST',
        body: JSON.stringify({ version, notes }),
      },
    ),

  validateFlow: (flowId: string) =>
    request<{
      ok: boolean;
      errors: string[];
      checks: {
        graph_contract: { ok: boolean; errors: string[] };
        contract_compatibility: FlowContractValidation;
      };
    }>(
      `/v1/flows/${encodeURIComponent(flowId)}/validate`,
      {
        method: 'POST',
      },
    ),

  sandboxFlow: (flowId: string) =>
    request<{ name: string; status: string; dry_run: Record<string, unknown> }>(
      `/v1/flows/${encodeURIComponent(flowId)}/sandbox`,
      { method: 'POST' },
    ),

  /* ---- Console facade: runs ---- */
  createRun: (payload: {
    target: { type: 'module' | 'flow'; id: string };
    mode: 'stub' | 'real';
    input: Record<string, unknown>;
    provider_profile?: string;
    budget?: Record<string, unknown>;
    control?: Record<string, unknown>;
  }) =>
    request<ConsoleRun>('/v1/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getRunRaw: (runId: string) =>
    request<ConsoleRun>(`/v1/runs/${encodeURIComponent(runId)}`),

  getRunsRaw: (params?: {
    targetType?: 'module' | 'flow';
    targetId?: string;
    status?: 'running' | 'done' | 'failed' | 'stopped';
    limit?: number;
    blueprint?: string;
  }) => {
    const search = new URLSearchParams();
    if (params?.targetType) search.set('target_type', params.targetType);
    if (params?.targetId) search.set('target_id', params.targetId);
    if (params?.status) search.set('status', params.status);
    if (params?.limit) search.set('limit', String(params.limit));
    if (params?.blueprint) search.set('blueprint_name', params.blueprint);
    const suffix = search.toString() ? `?${search.toString()}` : '';
    return request<{ runs: ConsoleRun[] }>(`/v1/runs${suffix}`);
  },

  getRunArtifacts: (runId: string) =>
    request<{ run_id: string; artifacts: Array<Record<string, unknown>> }>(
      `/v1/runs/${encodeURIComponent(runId)}/artifacts`,
    ),

  cancelRun: (runId: string) =>
    request<{ run_id: string; cancelled: boolean }>(
      `/v1/runs/${encodeURIComponent(runId)}/cancel`,
      { method: 'POST' },
    ),

  /* ---- Console facade: provider profiles ---- */
  getProviderProfiles: () =>
    request<{ profiles: ProviderProfile[] }>('/v1/provider-profiles'),

  getProviderProfile: (profileId: string) =>
    request<{ profile: ProviderProfile }>(
      `/v1/provider-profiles/${encodeURIComponent(profileId)}`,
    ),

  upsertProviderProfile: (
    profileId: string,
    payload: Partial<ProviderProfile>,
  ) =>
    request<{ ok: boolean; operation: 'created' | 'updated'; profile: ProviderProfile }>(
      `/v1/provider-profiles/${encodeURIComponent(profileId)}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      },
    ),

  deleteProviderProfile: (profileId: string) =>
    request<{ ok: boolean; deleted: boolean; profile_id: string }>(
      `/v1/provider-profiles/${encodeURIComponent(profileId)}`,
      { method: 'DELETE' },
    ),

  /* ---- Legacy-compatible wrappers used by current UI ---- */
  getRegistrySchema: async () => {
    try {
      const direct = await request<{ blocks: Record<string, unknown> }>(
        '/registry/schema',
        { method: 'GET' },
        { includeAuth: false },
      );
      if (direct && typeof direct.blocks === 'object') {
        return direct;
      }
    } catch {
      // fallback to authenticated endpoints below
    }
    try {
      const legacy = await request<{ blocks: Record<string, unknown> }>(
        '/v1/sagas/registry/schema',
        { method: 'GET' },
      );
      if (legacy && typeof legacy.blocks === 'object') {
        return legacy;
      }
    } catch {
      // fallback to /v1/modules mapping
    }
    const response = await api.getModules();
    return {
      blocks: response.modules.reduce(
        (acc, module) => {
          acc[module.module_id] = {
            description: module.description,
            input_schema: module.input_schema ?? {},
            output_schema: module.output_schema ?? {},
          };
          return acc;
        },
        {} as Record<string, unknown>,
      ),
    };
  },

  getBlueprints: async (): Promise<{ blueprints: BlueprintListItem[] }> => {
    const response = await api.getFlows();
    const blueprints = response.flows.map((flow) => ({
      name: flow.flow_id,
      owner_id: flow.owner_id ?? 'system',
      status: toLegacyBlueprintStatus(flow.status),
      created_at: flow.created_at ?? flow.updated_at ?? new Date().toISOString(),
      contract_ok: flow.contract_validation?.ok,
      contract_issue_count: flow.contract_validation?.issues.length ?? 0,
    }));
    return { blueprints };
  },

  getBlueprint: async (name: string): Promise<BlueprintInfoResponse> => {
    const flow = await api.getFlowRaw(name);
    const steps = flowToBlueprintSteps(flow);
    return {
      name: flow.flow_id,
      owner_id: flow.owner_id ?? 'system',
      status: flow.status,
      created_at: flow.created_at ?? new Date().toISOString(),
      updated_at: flow.updated_at ?? flow.created_at ?? new Date().toISOString(),
      data: {
        name: flow.flow_id,
        version: flow.version ?? 'v1',
        steps,
      },
    };
  },

  saveBlueprint: (blueprint: { name: string; version: string; steps: unknown[] }) =>
    api.compileFlow({
      flow_id: blueprint.name,
      version: blueprint.version,
      blueprint: { steps: blueprint.steps },
      save: true,
    }),

  executeSaga: async (
    name: string,
    payload: unknown,
    mode = 'LIVE',
  ): Promise<ExecutionResult> => {
    const run = await api.createRun({
      target: { type: 'flow', id: name },
      mode: mode === 'LIVE' ? 'real' : 'stub',
      input: (payload as Record<string, unknown>) ?? {},
    });
    const detail = await waitForRunTerminal(run.run_id);
    const timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
    const trace = timelineToLegacyTrace(timeline, detail.mode);
    return {
      blueprint: name,
      run_id: run.run_id,
      status: statusToLegacySagaStatus(detail.status),
      execution_mode: toLegacyExecutionMode(detail.mode),
      scan_id: undefined,
      scored_count: 0,
      job_count: 0,
      source_counts: {},
      execution_trace: trace,
      performance: {
        duration_ms: Number(detail.metrics?.latency_ms ?? 0),
        cost_estimate: Number(detail.metrics?.cost_units ?? 0),
        reliability_score: detail.status === 'failed' ? 0 : 1,
      },
      ai_summary: detail.result?.stop_reason
        ? `stop_reason: ${String(detail.result.stop_reason)}`
        : undefined,
    };
  },

  getRuns: async (params?: {
    blueprint?: string;
    ownerId?: string;
    limit?: number;
  }): Promise<{ runs: SagaRunSummary[] }> => {
    const response = await api.getRunsRaw({
      blueprint: params?.blueprint,
      limit: params?.limit,
    });
    const runs = response.runs.map((run) => ({
      run_id: run.run_id,
      target_type: run.target_type,
      blueprint_name: run.target_id,
      owner_id: 'system',
      status: run.status,
      execution_mode: toLegacyExecutionMode(run.mode),
      created_at: run.created_at,
    }));
    return { runs };
  },

  getRun: async (runId: string): Promise<SagaRunDetail> => {
    const detail = await api.getRunRaw(runId);
    const timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
    return {
      run_id: detail.run_id,
      target_type: detail.target_type,
      blueprint_name: detail.target_id,
      owner_id: 'system',
      status: detail.status,
      execution_mode: toLegacyExecutionMode(detail.mode),
      created_at: detail.created_at,
      request_payload: {},
      result: detail.result ?? {},
      execution_trace: timelineToLegacyTrace(timeline, detail.mode),
      performance: {
        duration_ms: Number(detail.metrics?.latency_ms ?? 0),
        cost_estimate: Number(detail.metrics?.cost_units ?? 0),
        retries: Number(detail.metrics?.retries ?? 0),
        tokens: Number(detail.metrics?.tokens ?? 0),
      },
      ai_summary: detail.result?.stop_reason
        ? `stop_reason: ${String(detail.result.stop_reason)}`
        : undefined,
      updated_at: detail.updated_at,
    };
  },

  getModuleStats: (params?: { blueprint?: string; ownerId?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.blueprint) search.set('blueprint_name', params.blueprint);
    if (params?.limit) search.set('limit', String(params.limit));
    const suffix = search.toString() ? `?${search.toString()}` : '';
    return request<{ total_runs: number; modules: ModuleStat[] }>(
      `/v1/runs/module-stats${suffix}`,
    );
  },

  /* ---- Legacy extras (kept for optional UI actions) ---- */
  seedGallery: async () => {
    const seeded: string[] = [];
    for (const item of DEFAULT_GALLERY_FLOWS) {
      try {
        await api.compileFlow({
          flow_id: item.name,
          version: 'v1',
          blueprint: { steps: item.steps },
          save: true,
        });
        seeded.push(item.name);
      } catch {
        // fallback to legacy endpoint below
      }
    }
    if (seeded.length > 0) {
      return { seeded };
    }
    return request<{ seeded: string[] }>('/v1/sagas/blueprints/gallery/seed', {
      method: 'POST',
    });
  },

  draftBlueprint: (
    prompt: string,
    modelTier?: string,
    ownerId?: string,
    intent?: string,
  ) =>
    request<DraftResult>('/v1/sagas/architect/draft', {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        model_tier: modelTier,
        owner_id: ownerId,
        intent,
      }),
    }),

  deployBlueprint: (blueprint: unknown, ownerId?: string) =>
    request<{ blueprint_id: string; status: string }>('/v1/sagas/blueprints/deploy', {
      method: 'POST',
      body: JSON.stringify({ blueprint, owner_id: ownerId }),
    }),

  approveBlueprint: async (name: string) => {
    try {
      const released = await api.releaseFlow(name);
      return {
        name,
        status: 'ACTIVE',
        message: `released ${released.version}`,
      };
    } catch {
      return request<{ name: string; status: string; message: string }>(
        `/v1/sagas/blueprints/${encodeURIComponent(name)}/approve`,
        { method: 'POST' },
      );
    }
  },

  sandboxBlueprint: async (name: string) => {
    try {
      const sandboxed = await api.sandboxFlow(name);
      return {
        name,
        status: toLegacyBlueprintStatus(sandboxed.status),
        dry_run: sandboxed.dry_run,
      };
    } catch {
      try {
        const started = await api.createRun({
          target: { type: 'flow', id: name },
          mode: 'stub',
          input: {
            user_id: '00000000-0000-0000-0000-000000000000',
            persona: { keywords: ['sandbox'], title: 'Sandbox' },
          },
        });
        const detail = await api.getRunRaw(started.run_id);
        const passed =
          detail.status === 'done' &&
          String((detail.result as Record<string, unknown> | undefined)?.stop_reason ?? '') !==
            'node_failed';
        return {
          name,
          status: passed ? 'SANDBOXED' : 'DRAFT',
          dry_run: {
            status: passed ? 'succeeded' : 'failed',
            run_id: started.run_id,
            result: detail.result ?? {},
          },
        };
      } catch {
        return request<{ name: string; status: string; dry_run: Record<string, unknown> }>(
          `/v1/sagas/blueprints/${encodeURIComponent(name)}/sandbox`,
          { method: 'POST' },
        );
      }
    }
  },

  archiveBlueprint: (name: string) =>
    request<{ name: string; status: string }>(
      `/v1/sagas/blueprints/${encodeURIComponent(name)}/archive`,
      { method: 'POST' },
    ),
};
