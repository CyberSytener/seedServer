/* ------------------------------------------------------------------ */
/* RunsView - run history + process details                             */
/* ------------------------------------------------------------------ */
import { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw,
  FileText,
  Clock3,
  User,
  Activity,
  Eye,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import { cn } from '../../lib/utils';
import { useNavigateView } from '../../lib/useNavigateView';
import { formatJson } from '../../lib/helpers';
import { useSagaStore } from '../../store/useSagaStore';
import { blueprintToGraph } from '../../utils/mapper';
import type { SagaRunDetail, SagaRunSummary } from '../../types';

export function RunsView() {
  const runs = useSagaStore((s) => s.runs);
  const setRuns = useSagaStore((s) => s.setRuns);
  const selectedRun = useSagaStore((s) => s.selectedRun);
  const setSelectedRun = useSagaStore((s) => s.setSelectedRun);
  const runsFilterBlueprint = useSagaStore((s) => s.runsFilterBlueprint);
  const setRunsFilterBlueprint = useSagaStore((s) => s.setRunsFilterBlueprint);
  const navigateView = useNavigateView();
  const setBlueprintName = useSagaStore((s) => s.setBlueprintName);
  const setNodes = useSagaStore((s) => s.setNodes);
  const setEdges = useSagaStore((s) => s.setEdges);
  const resetExecution = useSagaStore((s) => s.resetExecution);
  const blocks = useSagaStore((s) => s.blocks);
  const setDirty = useSagaStore((s) => s.setDirty);
  const addToast = useSagaStore((s) => s.addToast);

  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [modal, setModal] = useState<{ title: string; data: unknown } | null>(
    null,
  );

  async function fetchRuns() {
    setLoading(true);
    try {
      const res = await api.getRuns({ blueprint: runsFilterBlueprint ?? undefined });
      const nextRuns = res.runs ?? [];
      setRuns(nextRuns);
      if (
        nextRuns.length > 0 &&
        (!selectedRun || !nextRuns.some((run) => run.run_id === selectedRun.run_id))
      ) {
        await openRun(nextRuns[0].run_id);
      }
    } catch (err) {
      console.error('Failed to fetch runs', err);
      addToast('Failed to load runs', 'error');
    }
    setLoading(false);
  }

  useEffect(() => {
    fetchRuns();
  }, [runsFilterBlueprint]); // eslint-disable-line react-hooks/exhaustive-deps

  async function openRun(runId: string) {
    setDetailLoading(true);
    try {
      const run = await api.getRun(runId);
      setSelectedRun(run);
    } catch (err) {
      console.error('Failed to fetch run', err);
      addToast('Failed to load run details', 'error');
    }
    setDetailLoading(false);
  }

  async function openBlueprint(name: string) {
    try {
      const bp = await api.getBlueprint(name);
      const steps = bp.data?.steps ?? [];
      const { nodes, edges } = blueprintToGraph(steps, blocks);
      setBlueprintName(name);
      setNodes(nodes);
      setEdges(edges);
      resetExecution();
      setDirty(false);
      navigateView('canvas');
    } catch (err) {
      console.error('Failed to open blueprint', err);
      addToast('Failed to open blueprint', 'error');
    }
  }

  const selectedPerformance = useMemo(() => {
    const perf = selectedRun?.performance ?? {};
    return Object.entries(perf as Record<string, unknown>);
  }, [selectedRun]);

  return (
    <div className="h-full flex bg-zinc-950">
      {/* Left list */}
      <aside className="w-80 border-r border-zinc-900/70 p-4 overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">Run History</h2>
            <p className="text-[10px] text-zinc-500">
              {runs.length} run{runs.length !== 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={fetchRuns}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-zinc-900 text-zinc-400 hover:bg-zinc-800"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            Refresh
          </button>
        </div>

        {runsFilterBlueprint && (
          <div className="mb-3 flex items-center justify-between rounded-md bg-zinc-900/70 px-2 py-1">
            <span className="text-[10px] text-zinc-400">
              Filter: {runsFilterBlueprint}
            </span>
            <button
              onClick={() => setRunsFilterBlueprint(null)}
              className="text-[10px] text-zinc-500 hover:text-zinc-300"
            >
              Clear
            </button>
          </div>
        )}

        <div className="space-y-2">
          {loading && runs.length === 0 && (
            [1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 rounded-lg bg-zinc-900/50 animate-pulse" />
            ))
          )}
          {runs.map((run) => (
            <RunRow
              key={run.run_id}
              run={run}
              active={run.run_id === selectedRun?.run_id}
              onClick={() => openRun(run.run_id)}
            />
          ))}
          {runs.length === 0 && !loading && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              <p className="text-[11px] text-zinc-500">No runs yet.</p>
              <button
                onClick={() => navigateView('gallery')}
                className="mt-2 rounded-md bg-zinc-800 px-2 py-1 text-[10px] font-medium text-zinc-300 hover:bg-zinc-700"
              >
                Open Gallery
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Right detail */}
      <section className="flex-1 p-6 overflow-y-auto">
        {!selectedRun ? (
          <div className="h-full flex items-center justify-center">
            <div className="max-w-sm text-center">
              <div className="text-sm font-semibold text-zinc-300">
                No run selected
              </div>
              <p className="mt-1 text-[11px] text-zinc-600">
                Sandbox the demo flow from Gallery, then inspect the execution timeline here.
              </p>
              <button
                onClick={() => navigateView('gallery')}
                className="mt-3 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500"
              >
                Go to Gallery
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-zinc-100">
                  {selectedRun.blueprint_name}
                </h3>
                <p className="text-[11px] text-zinc-500 mt-1">
                  Run ID: {selectedRun.run_id}
                </p>
              </div>
              <button
                onClick={() => openBlueprint(selectedRun.blueprint_name)}
                className="text-[11px] px-2 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-500"
              >
                Open Blueprint
              </button>
            </div>

            {detailLoading && (
              <p className="text-[11px] text-zinc-500">Loading run...</p>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <InfoCard icon={Activity} label="Status" value={selectedRun.status} />
              <InfoCard
                icon={Clock3}
                label="Mode"
                value={selectedRun.execution_mode}
              />
              <InfoCard icon={User} label="Owner" value={selectedRun.owner_id} />
              <InfoCard
                icon={FileText}
                label="Created"
                value={new Date(selectedRun.created_at).toLocaleString()}
              />
            </div>

            {selectedRun.ai_summary && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
                <h4 className="text-xs font-semibold text-zinc-300 mb-2">
                  AI Summary
                </h4>
                <p className="text-[12px] text-zinc-400 whitespace-pre-wrap">
                  {selectedRun.ai_summary}
                </p>
              </div>
            )}

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-zinc-300">
                  Performance
                </h4>
                <button
                  onClick={() =>
                    setModal({ title: 'Performance JSON', data: selectedRun.performance })
                  }
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Eye className="w-3 h-3" /> View JSON
                </button>
              </div>
              {selectedPerformance.length === 0 ? (
                <p className="text-[11px] text-zinc-600">No metrics.</p>
              ) : (
                <div className="grid grid-cols-2 gap-2 text-[11px] text-zinc-400">
                  {selectedPerformance.map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-zinc-600">{key}</span>
                      <span className="text-zinc-300">
                        {typeof value === 'number' ? value : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-zinc-300">
                  Execution Trace
                </h4>
                <button
                  onClick={() =>
                    setModal({
                      title: 'Execution Trace JSON',
                      data: selectedRun.execution_trace,
                    })
                  }
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Eye className="w-3 h-3" /> View JSON
                </button>
              </div>
              {selectedRun.execution_trace?.length ? (
                <div className="space-y-2">
                  {selectedRun.execution_trace.map((entry, idx) => (
                    <div
                      key={`${entry.step ?? 'step'}-${idx}`}
                      className="rounded-md bg-zinc-950/60 border border-zinc-800/60 px-3 py-2"
                    >
                      <div className="flex items-center justify-between text-[11px] text-zinc-400">
                        <span>{entry.step ?? 'step'}</span>
                        <span>{entry.elapsed_sec ?? 0}s</span>
                      </div>
                      <div className="text-[11px] text-zinc-500 mt-1">
                        {entry.block ?? 'block'}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-zinc-600">No trace entries.</p>
              )}
            </section>

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-zinc-300">
                  Request Payload
                </h4>
                <button
                  onClick={() =>
                    setModal({
                      title: 'Request Payload JSON',
                      data: selectedRun.request_payload,
                    })
                  }
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Eye className="w-3 h-3" /> View JSON
                </button>
              </div>
              <pre className="text-[11px] text-zinc-400 bg-zinc-950/60 border border-zinc-800/60 rounded-md p-3 overflow-auto max-h-56">
                {formatJson(selectedRun.request_payload)}
              </pre>
            </section>

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-zinc-300">Result</h4>
                <button
                  onClick={() =>
                    setModal({ title: 'Result JSON', data: selectedRun.result })
                  }
                  className="text-[10px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1"
                >
                  <Eye className="w-3 h-3" /> View JSON
                </button>
              </div>
              <pre className="text-[11px] text-zinc-400 bg-zinc-950/60 border border-zinc-800/60 rounded-md p-3 overflow-auto max-h-56">
                {formatJson(selectedRun.result)}
              </pre>
            </section>
          </div>
        )}
      </section>

      {modal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="w-[90vw] max-w-3xl bg-zinc-950 border border-zinc-800 rounded-xl shadow-xl">
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
              {formatJson(modal.data)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function RunRow({
  run,
  active,
  onClick,
}: {
  run: SagaRunSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left rounded-lg border px-3 py-2 transition-colors',
        active
          ? 'border-blue-500/60 bg-blue-500/10'
          : 'border-zinc-800/70 bg-zinc-900/40 hover:bg-zinc-900/70',
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-zinc-200 truncate">
          {run.blueprint_name}
        </span>
        <span className="text-[10px] text-zinc-500">
          {new Date(run.created_at).toLocaleDateString()}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-zinc-500">
        <span>{run.status}</span>
        <span>/</span>
        <span>{run.execution_mode}</span>
      </div>
    </button>
  );
}

function InfoCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-center gap-2 text-[10px] text-zinc-500">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="text-[12px] text-zinc-200 mt-1 break-all">{value}</div>
    </div>
  );
}
