/* ------------------------------------------------------------------ */
/* Inspector - right sidebar: node properties, params editor, model     */
/* ------------------------------------------------------------------ */
import {
  Settings2,
  ExternalLink,
  Trash2,
  Search,
  BarChart3,
  Bell,
  GitBranch,
  Box,
  Eye,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSagaStore } from '../../store/useSagaStore';
import type { BlockMeta, SagaNodeData } from '../../types';
import { getBlockUI } from '../../utils/mapper';

const ICONS: Record<string, LucideIcon> = {
  Search,
  BarChart3,
  Bell,
  GitBranch,
  Box,
};

export function Inspector() {
  const selectedNodeId = useSagaStore((s) => s.selectedNodeId);
  const nodes = useSagaStore((s) => s.nodes);
  const blocks = useSagaStore((s) => s.blocks);
  const updateNodeParams = useSagaStore((s) => s.updateNodeParams);
  const setNodes = useSagaStore((s) => s.setNodes);
  const setEdges = useSagaStore((s) => s.setEdges);
  const removeNode = useSagaStore((s) => s.removeNode);
  const selectNode = useSagaStore((s) => s.selectNode);
  const modelTier = useSagaStore((s) => s.modelTier);
  const setModelTier = useSagaStore((s) => s.setModelTier);
  const developerMode = useSagaStore((s) => s.developerMode);
  const setDeveloperMode = useSagaStore((s) => s.setDeveloperMode);
  const setDirty = useSagaStore((s) => s.setDirty);
  const [modal, setModal] = useState<{ title: string; data: unknown } | null>(
    null,
  );
  const [rawJson, setRawJson] = useState('');
  const [rawError, setRawError] = useState<string | null>(null);

  const selected = nodes.find((n) => n.id === selectedNodeId);
  const data = selected?.data as SagaNodeData | undefined;
  const meta = blocks.find((b) => b.name === data?.blockType) as
    | BlockMeta
    | undefined;
  const params = (data?.params as Record<string, unknown>) ?? {};
  const isNotification = data?.blockType === 'notification_block';
  const recipientInfo = (params.recipient_info as Record<string, unknown>) ?? {};

  useEffect(() => {
    if (!data) {
      setRawJson('');
      setRawError(null);
      return;
    }
    const payload = {
      id: data.stepId,
      block: data.blockType,
      inputs: data.stepInputs ?? {},
      params: data.params ?? {},
    };
    setRawJson(JSON.stringify(payload, null, 2));
    setRawError(null);
  }, [data]);

  function setRecipientField(key: string, value: unknown) {
    if (!selectedNodeId) return;
    updateNodeParams(selectedNodeId, 'recipient_info', {
      ...recipientInfo,
      [key]: value,
    });
  }

  function applyRawJson() {
    if (!selected || !selectedNodeId) return;
    try {
      const parsed = JSON.parse(rawJson || '{}') as Record<string, unknown>;
      const nextId = String(parsed.id ?? selected.id);
      const nextBlock = String(parsed.block ?? data?.blockType ?? '');
      if (!nextId || !nextBlock) {
        throw new Error('Step id and block are required');
      }
      const nextInputs =
        (parsed.inputs as Record<string, unknown>) ??
        (data?.stepInputs as Record<string, unknown>) ??
        {};
      const nextParams =
        (parsed.params as Record<string, unknown>) ??
        (data?.params as Record<string, unknown>) ??
        {};

      const meta = blocks.find((b) => b.name === nextBlock);
      const ui = getBlockUI(nextBlock);
      const oldId = selected.id;

      const nextParamToggles = { ...(data?.paramToggles as Record<string, boolean>) };
      for (const key of Object.keys(nextParams)) {
        if (nextParamToggles[key] === undefined) {
          nextParamToggles[key] = true;
        }
      }

      const updatedNodes = nodes.map((node) => {
        if (node.id !== oldId) {
          const stepInputs = { ...(node.data.stepInputs as Record<string, unknown>) };
          for (const [key, value] of Object.entries(stepInputs)) {
            if (!value || typeof value !== 'object') continue;
            const entry = value as Record<string, unknown>;
            if (typeof entry.from !== 'string') continue;
            if (entry.from.startsWith(`${oldId}.`)) {
              stepInputs[key] = {
                ...entry,
                from: `${nextId}.${entry.from.slice(oldId.length + 1)}`,
              };
            }
          }
          return { ...node, data: { ...node.data, stepInputs } };
        }

        return {
          ...node,
          id: nextId,
          data: {
            ...node.data,
            stepId: nextId,
            label: nextId,
            blockType: nextBlock,
            icon: meta?.icon ?? ui.icon,
            color: meta?.color ?? ui.color,
            category: meta?.category ?? ui.category,
            description: meta?.description ?? nextBlock,
            handleInputs: meta?.inputKeys ?? [],
            handleOutputs: meta?.outputKeys ?? [],
            stepInputs: nextInputs,
            params: nextParams,
            paramToggles: nextParamToggles,
          },
        };
      });

      const contextRoots = new Set(['payload', 'request', 'user_id', 'persona', 'scan_id']);
      const existingEdges = useSagaStore.getState().edges;

      const updatedEdges = existingEdges
        .map((edge) => {
          if (edge.source !== oldId && edge.target !== oldId) return edge;
          const source = edge.source === oldId ? nextId : edge.source;
          const target = edge.target === oldId ? nextId : edge.target;
          return {
            ...edge,
            source,
            target,
            id: `e-${source}-${target}-${edge.sourceHandle ?? 'out'}-${edge.targetHandle ?? 'in'}`,
          };
        })
        .filter((edge) => edge.target !== nextId);

      for (const [inputKey, value] of Object.entries(nextInputs)) {
        if (!value || typeof value !== 'object') continue;
        const entry = value as Record<string, unknown>;
        if (typeof entry.from !== 'string') continue;
        const dot = entry.from.indexOf('.');
        if (dot === -1) continue;
        const sourceStep = entry.from.slice(0, dot);
        const sourceKey = entry.from.slice(dot + 1);
        if (!sourceStep || !sourceKey || contextRoots.has(sourceStep)) continue;
        updatedEdges.push({
          id: `e-${sourceStep}-${nextId}-${sourceKey}-${inputKey}`,
          source: sourceStep,
          target: nextId,
          sourceHandle: `output-${sourceKey}`,
          targetHandle: `input-${inputKey}`,
          type: 'animatedEdge',
        });
      }

      setNodes(updatedNodes);
      setEdges(updatedEdges);
      selectNode(nextId);
      setDirty(true);
      setRawError(null);
    } catch (err) {
      setRawError(err instanceof Error ? err.message : 'Invalid JSON');
    }
  }

  return (
    <aside className="w-64 border-l border-border bg-zinc-950/60 flex flex-col overflow-hidden shrink-0">
      {/* Header */}
      <div className="px-3 py-3 border-b border-border flex items-center gap-2">
        <Settings2 className="w-3.5 h-3.5 text-zinc-500" />
        <h2 className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest">
          Inspector
        </h2>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {!data ? (
          <div className="px-4 py-12 text-center">
            <Settings2 className="w-6 h-6 text-zinc-800 mx-auto mb-2" />
            <p className="text-xs text-zinc-600">Select a node to inspect</p>
          </div>
        ) : (
          <div className="p-3 space-y-4">
            {/* Identity */}
            <Section label="Block Type">
              <div className="flex items-center gap-2 mt-1">
                {(() => {
                  const Icon = ICONS[data.icon] ?? Box;
                  return (
                    <Icon
                      className="w-4 h-4"
                      style={{ color: data.color }}
                    />
                  );
                })()}
                <span className="text-sm font-mono text-zinc-300">
                  {data.blockType}
                </span>
              </div>
            </Section>

            <Section label="Step ID">
              <p className="text-sm font-mono text-zinc-300 mt-0.5">
                {data.stepId}
              </p>
            </Section>

            {data.description && (
              <Section label="Description">
                <p className="text-xs text-zinc-500 mt-0.5 leading-relaxed">
                  {data.description}
                </p>
              </Section>
            )}

            {meta && (
              <Section label="Module Metadata">
                <div className="mt-1 space-y-2">
                  <div className="text-[11px] text-zinc-500">
                    Category:{' '}
                    <span className="text-zinc-300">{meta.category}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-[11px] text-zinc-400">
                    <div>
                      <div className="text-[10px] text-zinc-600 uppercase tracking-widest">
                        Inputs
                      </div>
                      <div className="mt-1 space-y-1">
                        {meta.inputKeys.length ? (
                          meta.inputKeys.map((key) => (
                            <div key={key} className="font-mono text-zinc-300">
                              {key}
                            </div>
                          ))
                        ) : (
                          <div className="text-zinc-600">None</div>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-zinc-600 uppercase tracking-widest">
                        Outputs
                      </div>
                      <div className="mt-1 space-y-1">
                        {meta.outputKeys.length ? (
                          meta.outputKeys.map((key) => (
                            <div key={key} className="font-mono text-zinc-300">
                              {key}
                            </div>
                          ))
                        ) : (
                          <div className="text-zinc-600">None</div>
                        )}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() =>
                      setModal({
                        title: 'Module JSON',
                        data: {
                          name: meta.name,
                          description: meta.description,
                          inputs: meta.inputSchema,
                          outputs: meta.outputSchema,
                          category: meta.category,
                        },
                      })
                    }
                    className="text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                  >
                    <Eye className="w-3 h-3" /> View JSON
                  </button>
                </div>
              </Section>
            )}

            {/* Inputs (read-only) */}
            {data.handleInputs.length > 0 && (
              <Section label="Inputs">
                <div className="mt-1 space-y-1">
                  {data.handleInputs.map((key) => {
                    const val = (
                      data.stepInputs as Record<string, Record<string, unknown>>
                    )?.[key];
                    const display = val?.from
                      ? `<- ${val.from}`
                      : val?.default !== undefined
                        ? `default: ${JSON.stringify(val.default)}`
                        : '-';
                    return (
                      <div
                        key={key}
                        className="flex items-center justify-between text-[11px]"
                      >
                        <span className="font-mono text-zinc-500">{key}</span>
                        <span
                          className="font-mono text-zinc-600 truncate max-w-[120px]"
                          title={String(display)}
                        >
                          {display}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Section>
            )}

            {/* Params (editable) */}
            <Section label="Parameters">
              <div className="mt-1.5 space-y-2">
                {Object.entries(data.params as Record<string, unknown>).map(
                  ([key, value]) => (
                    <div key={key}>
                      <label className="text-[10px] text-zinc-500 font-mono">
                        {key}
                      </label>
                      <input
                        type={typeof value === 'number' ? 'number' : 'text'}
                        value={String(value ?? '')}
                        onChange={(e) => {
                          const v =
                            typeof value === 'number'
                              ? Number(e.target.value)
                              : typeof value === 'boolean'
                                ? e.target.value === 'true'
                                : e.target.value;
                          updateNodeParams(selectedNodeId!, key, v);
                        }}
                        className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                      />
                    </div>
                  ),
                )}
                {Object.keys(data.params as object).length === 0 && (
                  <p className="text-[10px] text-zinc-700 italic">
                    No parameters
                  </p>
                )}
              </div>
            </Section>

            {isNotification && (
              <Section label="Notification">
                <div className="mt-1.5 space-y-2">
                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      channel
                    </label>
                    <input
                      type="text"
                      value={String(params.channel ?? '')}
                      onChange={(e) =>
                        updateNodeParams(
                          selectedNodeId!,
                          'channel',
                          e.target.value,
                        )
                      }
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                      placeholder="webhook | email | slack | telegram"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      webhook_url
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.webhook_url ?? '')}
                      onChange={(e) => setRecipientField('webhook_url', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      slack_webhook_url
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.slack_webhook_url ?? '')}
                      onChange={(e) => setRecipientField('slack_webhook_url', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      telegram_bot_token
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.telegram_bot_token ?? '')}
                      onChange={(e) => setRecipientField('telegram_bot_token', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      telegram_chat_id
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.telegram_chat_id ?? '')}
                      onChange={(e) => setRecipientField('telegram_chat_id', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      email_to
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.email_to ?? '')}
                      onChange={(e) => setRecipientField('email_to', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      email_from
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.email_from ?? '')}
                      onChange={(e) => setRecipientField('email_from', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      smtp_host
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.smtp_host ?? '')}
                      onChange={(e) => setRecipientField('smtp_host', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      smtp_port
                    </label>
                    <input
                      type="number"
                      value={String(recipientInfo.smtp_port ?? '')}
                      onChange={(e) => setRecipientField('smtp_port', Number(e.target.value))}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      smtp_user
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.smtp_user ?? '')}
                      onChange={(e) => setRecipientField('smtp_user', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      smtp_pass
                    </label>
                    <input
                      type="password"
                      value={String(recipientInfo.smtp_pass ?? '')}
                      onChange={(e) => setRecipientField('smtp_pass', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-zinc-500 font-mono">
                      subject
                    </label>
                    <input
                      type="text"
                      value={String(recipientInfo.subject ?? '')}
                      onChange={(e) => setRecipientField('subject', e.target.value)}
                      className="w-full mt-0.5 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                    />
                  </div>
                </div>
              </Section>
            )}

            {/* Raw JSON editor */}
            <Section label="Raw Step JSON">
              <div className="mt-1.5 space-y-2">
                <textarea
                  value={rawJson}
                  onChange={(e) => setRawJson(e.target.value)}
                  rows={10}
                  className="w-full px-2 py-2 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
                />
                {rawError && (
                  <div className="text-[10px] text-red-400">{rawError}</div>
                )}
                <button
                  onClick={applyRawJson}
                  className="px-2 py-1 rounded-md text-[10px] bg-blue-600 text-white hover:bg-blue-500"
                >
                  Apply JSON
                </button>
              </div>
            </Section>

            {/* Source link */}
            {developerMode && (
              <div className="border-t border-border pt-3">
                <a
                  href={`/v1/sagas/registry/schema`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-[11px] text-blue-400 hover:text-blue-300 transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  View Registry Entry
                </a>
              </div>
            )}

            {/* Delete */}
            <button
              onClick={() => {
                removeNode(selectedNodeId!);
                selectNode(null);
              }}
              className="flex items-center gap-1.5 text-[11px] text-red-400/60 hover:text-red-400 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              Remove Node
            </button>
          </div>
        )}
      </div>

      {/* Model Tier - always visible at bottom */}
      <div className="px-3 py-3 border-t border-border shrink-0">
        <label className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest">
          Model Tier
        </label>
        <select
          value={modelTier}
          onChange={(e) => setModelTier(e.target.value)}
          className="w-full mt-1.5 px-2 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 focus:outline-none focus:border-blue-500/50 appearance-none cursor-pointer"
        >
          <option value="cheap">Eco - Flash-Lite (1 credit)</option>
          <option value="balanced">Balanced - Flash (3 credits)</option>
          <option value="powerful">Pro - Gemini Pro (10 credits)</option>
        </select>
      </div>

      <div className="px-3 py-3 border-t border-border shrink-0">
        <label className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest">
          Developer Mode
        </label>
        <button
          onClick={() => setDeveloperMode(!developerMode)}
          className={
            developerMode
              ? 'mt-1.5 w-full px-2 py-1.5 rounded bg-emerald-500/20 text-emerald-300 text-[11px]'
              : 'mt-1.5 w-full px-2 py-1.5 rounded bg-zinc-900 text-zinc-400 text-[11px]'
          }
        >
          {developerMode ? 'Enabled' : 'Disabled'}
        </button>
      </div>

      {modal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="w-[90vw] max-w-2xl bg-zinc-950 border border-zinc-800 rounded-xl shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
              <h4 className="text-sm font-semibold text-zinc-200">
                {modal.title}
              </h4>
              <button
                onClick={() => setModal(null)}
                className="text-zinc-500 hover:text-zinc-300"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <pre className="p-4 text-[11px] text-zinc-300 overflow-auto max-h-[70vh]">
              {JSON.stringify(modal.data, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </aside>
  );
}

/* ---- Tiny helper ---- */
function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest">
        {label}
      </label>
      {children}
    </div>
  );
}
