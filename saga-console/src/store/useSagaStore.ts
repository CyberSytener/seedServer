/* ------------------------------------------------------------------ */
/* Zustand store — single source of truth for the Saga Console         */
/* ------------------------------------------------------------------ */
import { create } from 'zustand';
import {
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type Connection,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from '@xyflow/react';
import type {
  BlockMeta,
  BlueprintListItem,
  SagaRunDetail,
  SagaRunSummary,
  TraceEntry,
  PerformanceMetrics,
  SagaNodeData,
} from '../types';
import { getBlockUI } from '../utils/mapper';

let _nodeCounter = 0;

function loadAuthToken(): string {
  try {
    return localStorage.getItem('sagaAuthToken') ?? '';
  } catch {
    return '';
  }
}

function persistAuthToken(token: string) {
  try {
    if (token) {
      localStorage.setItem('sagaAuthToken', token);
    } else {
      localStorage.removeItem('sagaAuthToken');
    }
  } catch {
    // ignore storage failures
  }
}

interface SagaStore {
  /* ---- View ---- */
  view: 'canvas' | 'gallery' | 'runs' | 'modules' | 'providers';
  setView: (v: 'canvas' | 'gallery' | 'runs' | 'modules' | 'providers') => void;

  /* ---- Blueprint identity ---- */
  blueprintName: string;
  setBlueprintName: (n: string) => void;

  /* ---- Canvas (React Flow) ---- */
  nodes: Node<SagaNodeData>[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (c: Connection) => void;
  setNodes: (n: Node<SagaNodeData>[]) => void;
  setEdges: (e: Edge[]) => void;
  addNode: (blockType: string, pos: { x: number; y: number }) => void;
  removeNode: (id: string) => void;

  /* ---- Selection ---- */
  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;
  updateNodeParams: (nodeId: string, key: string, value: unknown) => void;
  setNodeParamEnabled: (nodeId: string, key: string, enabled: boolean) => void;
  toggleNodeDisabled: (nodeId: string) => void;

  /* ---- Registry ---- */
  blocks: BlockMeta[];
  setBlocks: (b: BlockMeta[]) => void;

  /* ---- Execution ---- */
  executionStatus: 'idle' | 'running' | 'success' | 'error';
  trace: TraceEntry[];
  performance: PerformanceMetrics | null;
  aiSummary: string | null;
  executionMode: 'DRY_RUN' | 'LIVE';
  setExecutionMode: (mode: 'DRY_RUN' | 'LIVE') => void;
  runInputJson: string;
  setRunInputJson: (value: string) => void;
  setRunning: () => void;
  setExecutionResult: (
    status: string,
    trace: TraceEntry[],
    perf: PerformanceMetrics,
    summary?: string,
  ) => void;
  resetExecution: () => void;

  /* ---- Model tier ---- */
  modelTier: string;
  setModelTier: (t: string) => void;

  /* ---- Auth ---- */
  authToken: string;
  setAuthToken: (t: string) => void;

  /* ---- Developer mode ---- */
  developerMode: boolean;
  setDeveloperMode: (v: boolean) => void;

  /* ---- Auto-save ---- */
  saveStatus: 'idle' | 'saving' | 'saved' | 'error';
  lastSavedAt: number | null;
  setSaveStatus: (status: SagaStore['saveStatus'], ts?: number | null) => void;
  dirty: boolean;
  setDirty: (value: boolean) => void;

  /* ---- Toasts ---- */
  toasts: Array<{
    id: string;
    message: string;
    tone: 'info' | 'success' | 'error';
    details?: unknown;
  }>;
  addToast: (
    message: string,
    tone?: 'info' | 'success' | 'error',
    details?: unknown,
  ) => void;
  removeToast: (id: string) => void;

  /* ---- Gallery list ---- */
  blueprintsList: BlueprintListItem[];
  setBlueprintsList: (l: BlueprintListItem[]) => void;

  /* ---- Run history ---- */
  runs: SagaRunSummary[];
  selectedRun: SagaRunDetail | null;
  runsFilterBlueprint: string | null;
  setRuns: (r: SagaRunSummary[]) => void;
  setSelectedRun: (r: SagaRunDetail | null) => void;
  setRunsFilterBlueprint: (name: string | null) => void;

  /* ---- Modules ---- */
  selectedModuleName: string | null;
  setSelectedModuleName: (name: string | null) => void;
}

export const useSagaStore = create<SagaStore>((set, get) => ({
  // ===== View =====
  view: 'gallery',
  setView: (view) => set({ view }),

  // ===== Blueprint =====
  blueprintName: '',
  setBlueprintName: (blueprintName) => set({ blueprintName }),

  // ===== Canvas =====
  nodes: [],
  edges: [],

  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes) as Node<SagaNodeData>[],
      dirty: true,
    });
  },

  onEdgesChange: (changes) => {
    set((state) => {
      const removed = changes
        .filter((c) => c.type === 'remove')
        .map((c) => state.edges.find((e) => e.id === c.id))
        .filter((e): e is Edge => Boolean(e));

      const nextEdges = applyEdgeChanges(changes, state.edges);

      if (removed.length === 0) {
        return { edges: nextEdges, dirty: true };
      }

      const nextNodes = state.nodes.map((node) => {
        const impacted = removed.filter((e) => e.target === node.id);
        if (impacted.length === 0) return node;

        const updatedInputs = { ...(node.data.stepInputs as Record<string, unknown>) };

        for (const edge of impacted) {
          const inputKey = edge.targetHandle?.replace('input-', '') ?? '';
          const outputKey = edge.sourceHandle?.replace('output-', '') ?? '';
          if (!inputKey || !edge.source || !outputKey) continue;

          const entry = updatedInputs[inputKey];
          if (!entry || typeof entry !== 'object') continue;

          const entryObj = entry as Record<string, unknown>;
          const from = entryObj.from;
          if (from !== `${edge.source}.${outputKey}`) continue;

          const { from: _removed, ...rest } = entryObj;
          if (Object.keys(rest).length > 0) {
            updatedInputs[inputKey] = rest;
          } else {
            delete updatedInputs[inputKey];
          }
        }

        return {
          ...node,
          data: {
            ...node.data,
            stepInputs: updatedInputs,
          },
        };
      });

      return { edges: nextEdges, nodes: nextNodes, dirty: true };
    });
  },

  onConnect: (connection) => {
    set((state) => {
      const newEdges = addEdge(
        { ...connection, type: 'animatedEdge' },
        state.edges,
      );

      // Keep stepInputs in sync with the new edge
      const inputKey = connection.targetHandle?.replace('input-', '') ?? '';
      const outputKey = connection.sourceHandle?.replace('output-', '') ?? '';

      if (connection.target && connection.source && inputKey && outputKey) {
        const newNodes = state.nodes.map((n) => {
          if (n.id === connection.target) {
            return {
              ...n,
              data: {
                ...n.data,
                stepInputs: {
                  ...(n.data.stepInputs as Record<string, unknown>),
                  [inputKey]: { from: `${connection.source}.${outputKey}` },
                },
              },
            };
          }
          return n;
        });
        return { edges: newEdges, nodes: newNodes, dirty: true };
      }

      return { edges: newEdges, dirty: true };
    });
  },

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  addNode: (blockType, position) => {
    const { blocks } = get();
    const meta = blocks.find((b) => b.name === blockType);
    if (!meta) return;

    _nodeCounter++;
    const stepId = `${blockType}_${_nodeCounter}`;
    const ui = getBlockUI(blockType);

    // Pre-populate context-root refs so the node is immediately wirable
    const defaultInputs: Record<string, unknown> = {};
    for (const key of meta.inputKeys) {
      if (['user_id', 'persona', 'scan_id'].includes(key)) {
        defaultInputs[key] = { from: key };
      }
    }

    const newNode: Node<SagaNodeData> = {
      id: stepId,
      type: 'sagaNode',
      position,
      data: {
        blockType,
        stepId,
        label: stepId,
        icon: ui.icon,
        color: ui.color,
        category: meta.category,
        description: meta.description,
        handleInputs: meta.inputKeys,
        handleOutputs: meta.outputKeys,
        stepInputs: defaultInputs,
        params: {},
        paramToggles: {},
        status: 'idle',
        shape: ui.shape ?? 'default',
        disabled: false,
      },
    };

    set({ nodes: [...get().nodes, newNode], dirty: true });
  },

  removeNode: (nodeId) => {
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== nodeId),
      edges: state.edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId,
      ),
      selectedNodeId:
        state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      dirty: true,
    }));
  },

  // ===== Selection =====
  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id }),

  updateNodeParams: (nodeId, key, value) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              data: {
                ...n.data,
                params: { ...(n.data.params as Record<string, unknown>), [key]: value },
                paramToggles: {
                  ...(n.data.paramToggles as Record<string, boolean>),
                  [key]: (n.data.paramToggles as Record<string, boolean>)?.[key] ?? true,
                },
              },
            }
          : n,
      ),
      dirty: true,
    }));
  },

  setNodeParamEnabled: (nodeId, key, enabled) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              data: {
                ...n.data,
                paramToggles: {
                  ...(n.data.paramToggles as Record<string, boolean>),
                  [key]: enabled,
                },
              },
            }
          : n,
      ),
      dirty: true,
    }));
  },

  toggleNodeDisabled: (nodeId) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, disabled: !n.data.disabled } }
          : n,
      ),
      dirty: true,
    }));
  },

  // ===== Registry =====
  blocks: [],
  setBlocks: (blocks) => set({ blocks }),

  // ===== Execution =====
  executionStatus: 'idle',
  trace: [],
  performance: null,
  aiSummary: null,
  executionMode: 'DRY_RUN',
  setExecutionMode: (executionMode) => set({ executionMode }),
  runInputJson: JSON.stringify(
    {
      user_id: '00000000-0000-0000-0000-000000000000',
      persona: { keywords: ['test'], title: 'Test' },
    },
    null,
    2,
  ),
  setRunInputJson: (runInputJson) => set({ runInputJson }),

  setRunning: () => {
    set((state) => ({
      executionStatus: 'running' as const,
      trace: [],
      performance: null,
      aiSummary: null,
      nodes: state.nodes.map((n) => ({
        ...n,
        data: {
          ...n.data,
          status: 'running' as const,
          executionTime: undefined,
          traceStatus: undefined,
          traceError: undefined,
          traceOutputKeys: undefined,
        },
      })),
      edges: state.edges.map((e) => ({
        ...e,
        data: { ...(e.data ?? {}), animated: true, status: undefined },
      })),
    }));
  },

  setExecutionResult: (status, trace, perf, summary) => {
    const ok = status === 'succeeded';
    const traceMap = new Map(trace.map((t) => [t.step, t]));

    set((state) => ({
      executionStatus: ok ? ('success' as const) : ('error' as const),
      trace,
      performance: perf,
      aiSummary: summary ?? null,
      nodes: state.nodes.map((n) => {
        const entry = traceMap.get(n.data.stepId);
        const failed = entry?.status === 'failed';
        return {
          ...n,
          data: {
            ...n.data,
            status: entry
              ? failed
                ? ('error' as const)
                : ('success' as const)
              : ok
                ? ('idle' as const)
                : ('error' as const),
            executionTime: entry?.elapsed_sec,
            traceStatus: entry?.status,
            traceError: entry?.error,
            traceOutputKeys: entry?.output_keys,
          },
        };
      }),
      edges: state.edges.map((e) => ({
        ...e,
        data: {
          ...(e.data ?? {}),
          animated: false,
          status: (() => {
            const target = state.nodes.find((n) => n.id === e.target);
            const entry = target ? traceMap.get(target.data.stepId) : undefined;
            if (entry?.status === 'failed') return 'error';
            if (entry) return 'success';
            return ok ? undefined : 'error';
          })(),
        },
      })),
    }));
  },

  resetExecution: () => {
    set((state) => ({
      executionStatus: 'idle' as const,
      trace: [],
      performance: null,
      aiSummary: null,
      nodes: state.nodes.map((n) => ({
        ...n,
        data: {
          ...n.data,
          status: 'idle' as const,
          executionTime: undefined,
          traceStatus: undefined,
          traceError: undefined,
          traceOutputKeys: undefined,
        },
      })),
      edges: state.edges.map((e) => ({
        ...e,
        data: { ...(e.data ?? {}), animated: false, status: undefined },
      })),
    }));
  },

  // ===== Model tier =====
  modelTier: 'cheap',
  setModelTier: (modelTier) => set({ modelTier }),

  // ===== Auth =====
  authToken: loadAuthToken(),
  setAuthToken: (authToken) => {
    persistAuthToken(authToken);
    set({ authToken });
  },

  // ===== Developer mode =====
  developerMode: false,
  setDeveloperMode: (developerMode) => set({ developerMode }),

  // ===== Auto-save =====
  saveStatus: 'idle',
  lastSavedAt: null,
  setSaveStatus: (saveStatus, lastSavedAt = null) =>
    set({ saveStatus, lastSavedAt }),
  dirty: false,
  setDirty: (dirty) => set({ dirty }),

  // ===== Toasts =====
  toasts: [],
  addToast: (message, tone = 'info', details) => {
    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    set((state) => ({
      toasts: [...state.toasts, { id, message, tone, details }],
    }));
  },
  removeToast: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),

  // ===== Gallery =====
  blueprintsList: [],
  setBlueprintsList: (blueprintsList) => set({ blueprintsList }),

  // ===== Run history =====
  runs: [],
  selectedRun: null,
  runsFilterBlueprint: null,
  setRuns: (runs) => set({ runs }),
  setSelectedRun: (selectedRun) => set({ selectedRun }),
  setRunsFilterBlueprint: (runsFilterBlueprint) => set({ runsFilterBlueprint }),

  // ===== Modules =====
  selectedModuleName: null,
  setSelectedModuleName: (selectedModuleName) => set({ selectedModuleName }),
}));
