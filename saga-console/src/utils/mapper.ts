/* ------------------------------------------------------------------ */
/* Bi-directional mapper: Blueprint JSON <-> React Flow graph          */
/* ------------------------------------------------------------------ */
import type { Node, Edge } from '@xyflow/react';
import type { BlockMeta, BlueprintStep, NodeShape, SagaNodeData } from '../types';

/* ------------------------------------------------------------------ */
/* Block UI defaults (icon, colour, category, shape)                   */
/* ------------------------------------------------------------------ */
interface BlockUIEntry {
  icon: string;
  color: string;
  category: string;
  shape?: NodeShape;
}

const BLOCK_UI: Record<string, BlockUIEntry> = {
  // ── Domain blocks ──────────────────────────────────────
  market_scanner:     { icon: 'Search',       color: '#3b82f6', category: 'Scanners' },
  job_scorer:         { icon: 'BarChart3',    color: '#8b5cf6', category: 'Scorers' },
  notification_block: { icon: 'Bell',         color: '#f59e0b', category: 'Actions' },
  sub_saga:           { icon: 'GitBranch',    color: '#10b981', category: 'Orchestration' },

  // ── NeoEats blocks ─────────────────────────────────────
  'neoeats.inventory.get':       { icon: 'Database',     color: '#16a34a', category: 'NeoEats' },
  'neoeats.inventory.normalize': { icon: 'Sliders',      color: '#0d9488', category: 'NeoEats' },
  'neoeats.input.normalize':     { icon: 'Filter',       color: '#0d9488', category: 'NeoEats' },
  'neoeats.recipe.generate':     { icon: 'Sparkles',     color: '#f59e0b', category: 'NeoEats' },
  'neoeats.recipe.compile_strict': { icon: 'ClipboardCheck', color: '#059669', category: 'NeoEats' },
  'neoeats.recipe.validate':     { icon: 'ShieldCheck',  color: '#22c55e', category: 'NeoEats' },

  // ── Triggers ───────────────────────────────────────────
  manual_trigger:     { icon: 'Play',         color: '#22c55e', category: 'Triggers', shape: 'stadium' },
  webhook_trigger:    { icon: 'Webhook',      color: '#06b6d4', category: 'Triggers', shape: 'stadium' },
  cron_trigger:       { icon: 'Clock',        color: '#8b5cf6', category: 'Triggers', shape: 'stadium' },

  // ── Control Flow ───────────────────────────────────────
  if_block:           { icon: 'GitFork',      color: '#f97316', category: 'Control Flow', shape: 'diamond' },
  switch_block:       { icon: 'Route',        color: '#e11d48', category: 'Control Flow', shape: 'diamond' },
  loop_block:         { icon: 'Repeat',       color: '#a855f7', category: 'Control Flow', shape: 'hexagon' },
  merge_block:        { icon: 'Merge',        color: '#14b8a6', category: 'Control Flow', shape: 'hexagon' },

  // ── Data Transform ─────────────────────────────────────
  set_block:          { icon: 'PenLine',      color: '#64748b', category: 'Transform' },
  filter_block:       { icon: 'Filter',       color: '#0ea5e9', category: 'Transform' },
  wait_block:         { icon: 'Timer',        color: '#78716c', category: 'Transform' },
  noop_block:         { icon: 'Minus',        color: '#525252', category: 'Transform' },
};

const FALLBACK_UI: BlockUIEntry = { icon: 'Box', color: '#6b7280', category: 'Other' };

export function getBlockUI(blockType: string) {
  return BLOCK_UI[blockType] ?? FALLBACK_UI;
}

/* ------------------------------------------------------------------ */
/* Registry schema -> enriched BlockMeta[]                             */
/* ------------------------------------------------------------------ */
function schemaKeys(schema: Record<string, unknown> | undefined): string[] {
  if (!schema) return [];
  const props = (schema as Record<string, unknown>).properties;
  if (props && typeof props === 'object') return Object.keys(props as object);
  return [];
}

export function enrichBlockMeta(
  schema: { blocks: Array<Record<string, unknown>> | Record<string, unknown> },
): BlockMeta[] {
  const blocks = schema.blocks ?? [];
  const items = Array.isArray(blocks)
    ? blocks
    : Object.entries(blocks as Record<string, unknown>).map(([name, value]) => ({
        name,
        ...(value as Record<string, unknown>),
      }));

  return items.map((rawItem) => {
    const item = rawItem as Record<string, unknown>;
    const name = String(item['name'] ?? '');
    const ui = getBlockUI(name);
    const inputSchema = (item['input_schema'] ?? item['inputs'] ?? {}) as Record<string, unknown>;
    const outputSchema = (item['output_schema'] ?? item['outputs'] ?? {}) as Record<string, unknown>;
    return {
      name,
      description: String(item['description'] ?? ''),
      category: ui.category,
      icon: ui.icon,
      color: ui.color,
      inputKeys: schemaKeys(inputSchema),
      outputKeys: schemaKeys(outputSchema),
      inputSchema,
      outputSchema,
    };
  });
}

/* ------------------------------------------------------------------ */
/* Blueprint steps  ->  React Flow nodes + edges                       */
/* ------------------------------------------------------------------ */
const NODE_GAP_Y = 180;
const NODE_START_X = 350;
const NODE_START_Y = 60;

export function blueprintToGraph(
  steps: BlueprintStep[],
  blocksMeta: BlockMeta[],
): { nodes: Node<SagaNodeData>[]; edges: Edge[] } {
  const metaMap = new Map(blocksMeta.map((b) => [b.name, b]));
  const nodes: Node<SagaNodeData>[] = [];
  const edges: Edge[] = [];

  steps.forEach((step, index) => {
    const meta = metaMap.get(step.block);
    const ui = getBlockUI(step.block);

    nodes.push({
      id: step.id,
      type: 'sagaNode',
      position: { x: NODE_START_X, y: NODE_START_Y + index * NODE_GAP_Y },
      data: {
        blockType: step.block,
        stepId: step.id,
        label: step.id,
        icon: ui.icon,
        color: ui.color,
        category: meta?.category ?? ui.category,
        description: meta?.description ?? step.block,
        handleInputs: meta?.inputKeys ?? [],
        handleOutputs: meta?.outputKeys ?? [],
        stepInputs: step.inputs ?? {},
        params: (step.params ?? {}) as Record<string, unknown>,
        paramToggles: Object.keys(step.params ?? {}).reduce(
          (acc, key) => {
            acc[key] = true;
            return acc;
          },
          {} as Record<string, boolean>,
        ),
        status: 'idle',
        shape: ui.shape ?? 'default',
        disabled: false,
      },
    });

    // Parse `{ "from": "step_id.key" }` refs to create edges
    if (step.inputs) {
      for (const [inputKey, inputValue] of Object.entries(step.inputs)) {
        const ref = extractFromRef(inputValue);
        if (ref) {
          const [srcStepId, srcKey] = ref;
          edges.push({
            id: `e-${srcStepId}-${step.id}-${srcKey}-${inputKey}`,
            source: srcStepId,
            target: step.id,
            sourceHandle: `output-${srcKey}`,
            targetHandle: `input-${inputKey}`,
            type: 'animatedEdge',
          });
        }
      }
    }
  });

  return { nodes, edges };
}

/* Extract ["step_id", "key"] from a `{ from: "step_id.key" }` ref */
function extractFromRef(value: unknown): [string, string] | null {
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;
  const from = obj.from;
  if (typeof from !== 'string') return null;
  const dot = from.indexOf('.');
  if (dot === -1) return null;
  const stepId = from.substring(0, dot);
  const key = from.substring(dot + 1);
  // Skip context-root refs (these aren't step-to-step edges)
  const CONTEXT_ROOTS = new Set(['payload', 'request', 'user_id', 'persona', 'scan_id']);
  if (CONTEXT_ROOTS.has(stepId)) return null;
  return [stepId, key];
}

/* ------------------------------------------------------------------ */
/* React Flow nodes + edges  ->  Blueprint steps                       */
/* ------------------------------------------------------------------ */
export function graphToBlueprint(
  nodes: Node<SagaNodeData>[],
  edges: Edge[],
): BlueprintStep[] {
  const sorted = [...nodes].sort((a, b) => a.position.y - b.position.y);

  return sorted.map((node) => {
    const d = node.data;

    // Start from the stored stepInputs (preserves context refs + defaults)
    const inputs: Record<string, unknown> = { ...(d.stepInputs as Record<string, unknown>) };

    // Overlay connections from edges
    const incoming = edges.filter((e) => e.target === node.id);
    for (const edge of incoming) {
      const inputKey = edge.targetHandle?.replace('input-', '');
      const outputKey = edge.sourceHandle?.replace('output-', '');
      if (inputKey && edge.source && outputKey) {
        inputs[inputKey] = { from: `${edge.source}.${outputKey}` };
      }
    }

    const step: BlueprintStep = { id: d.stepId, block: d.blockType, inputs };
    const params = d.params as Record<string, unknown>;
    const toggles = (d.paramToggles ?? {}) as Record<string, boolean>;
    const enabledParams = Object.entries(params).reduce(
      (acc, [key, value]) => {
        if (toggles[key] === false) return acc;
        acc[key] = value;
        return acc;
      },
      {} as Record<string, unknown>,
    );
    if (Object.keys(enabledParams).length > 0) step.params = enabledParams;
    return step;
  });
}
