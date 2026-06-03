/* ------------------------------------------------------------------ */
/* ModulesView - server module registry with run/validate/release       */
/* ------------------------------------------------------------------ */
import { useEffect, useMemo, useState } from 'react';
import {
  Search,
  RefreshCw,
  Eye,
  Play,
  FlaskConical,
  Upload,
  X,
  Clock3,
  Activity,
} from 'lucide-react';
import { api, type ConsoleModule, type ConsoleRun } from '../../api/client';
import { cn } from '../../lib/utils';
import { formatJson, waitForTerminalRun } from '../../lib/helpers';
import { useSagaStore } from '../../store/useSagaStore';

const DEMO_MODE = import.meta.env.DEV;
const DEMO_MODULE_ID = 'general_assistant';

export function ModulesView() {
  const addToast = useSagaStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  const [modules, setModules] = useState<ConsoleModule[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedModule, setSelectedModule] = useState<ConsoleModule | null>(null);
  const [loading, setLoading] = useState(false);

  const [inputJson, setInputJson] = useState(
    JSON.stringify({ user_request: 'Summarize the Seed Server portfolio demo readiness.' }, null, 2),
  );
  const [inputError, setInputError] = useState<string | null>(null);

  const [runLoading, setRunLoading] = useState<'stub' | 'real' | null>(null);
  const [runDetail, setRunDetail] = useState<ConsoleRun | null>(null);
  const [validationResult, setValidationResult] = useState<{
    ok: boolean;
    errors: string[];
  } | null>(null);
  const [validating, setValidating] = useState(false);
  const [releasing, setReleasing] = useState(false);

  const [modal, setModal] = useState<{ title: string; data: unknown } | null>(null);

  const filteredModules = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return modules;
    return modules.filter((m) => {
      const tags = Array.isArray(m.tags) ? m.tags.join(' ') : '';
      return (
        m.module_id.toLowerCase().includes(term) ||
        String(m.title || '').toLowerCase().includes(term) ||
        String(m.description || '').toLowerCase().includes(term) ||
        tags.toLowerCase().includes(term)
      );
    });
  }, [modules, search]);

  async function fetchModules() {
    setLoading(true);
    try {
      const response = await api.getModules();
      setModules(response.modules ?? []);
      if (!selectedId && response.modules?.length) {
        const preferred =
          response.modules.find((module) => module.module_id === DEMO_MODULE_ID) ??
          response.modules[0];
        setSelectedId(preferred.module_id);
      }
    } catch (err) {
      addToast(
        `Failed to load modules: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setLoading(false);
  }

  async function loadModule(moduleId: string) {
    try {
      const detail = await api.getModule(moduleId);
      setSelectedModule(detail);
      setRunDetail(null);
      setValidationResult(null);
    } catch (err) {
      addToast(
        `Failed to load module: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
  }

  useEffect(() => {
    fetchModules();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) return;
    loadModule(selectedId);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  function parseInput(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(inputJson || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Input must be a JSON object');
      }
      setInputError(null);
      return parsed as Record<string, unknown>;
    } catch (err) {
      setInputError(err instanceof Error ? err.message : 'Invalid JSON input');
      return null;
    }
  }

  async function runModule(mode: 'stub' | 'real') {
    if (!selectedModule) return;
    const input = parseInput();
    if (!input) return;

    setRunLoading(mode);
    try {
      const started = await api.runModule(selectedModule.module_id, mode, input);
      const detail = await waitForTerminalRun(started.run_id);
      setRunDetail(detail);
      addToast(
        detail.status === 'done'
          ? `${selectedModule.module_id}: run completed`
          : `${selectedModule.module_id}: run ${detail.status}`,
        detail.status === 'done' ? 'success' : 'info',
      );
    } catch (err) {
      addToast(
        `Run failed: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setRunLoading(null);
  }

  async function validateModule() {
    if (!selectedModule) return;
    const input = parseInput();
    if (!input) return;

    setValidating(true);
    try {
      const result = await api.validateModule(selectedModule.module_id, input);
      setValidationResult(result);
      addToast(
        result.ok ? 'Validation passed' : 'Validation failed',
        result.ok ? 'success' : 'error',
        result.ok ? undefined : result.errors,
      );
    } catch (err) {
      addToast(
        `Validation error: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setValidating(false);
  }

  async function releaseModule() {
    if (!selectedModule) return;
    setReleasing(true);
    try {
      const result = await api.releaseModule(selectedModule.module_id);
      addToast(`Released ${selectedModule.module_id}@${result.version}`, 'success');
      await fetchModules();
      await loadModule(selectedModule.module_id);
    } catch (err) {
      addToast(
        `Release failed: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setReleasing(false);
  }

  return (
    <div className="h-full flex bg-zinc-950">
      <aside className="w-80 border-r border-zinc-900/70 p-4 overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">Server Modules</h2>
            <p className="text-[10px] text-zinc-500">
              {modules.length} module{modules.length !== 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={fetchModules}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-zinc-900 text-zinc-400 hover:bg-zinc-800"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            Refresh
          </button>
        </div>

        <div className="relative mb-3">
          <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-zinc-600" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search modules"
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        <div className="space-y-2">
          {filteredModules.map((module) => (
            <button
              key={module.module_id}
              onClick={() => setSelectedId(module.module_id)}
              className={cn(
                'w-full text-left rounded-lg border px-3 py-2 transition-colors',
                module.module_id === selectedId
                  ? 'border-blue-500/60 bg-blue-500/10'
                  : 'border-zinc-800/70 bg-zinc-900/40 hover:bg-zinc-900/70',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-200 truncate">
                  {module.module_id}
                </span>
                <span className="text-[10px] text-zinc-500">{module.status}</span>
              </div>
              <div className="text-[10px] text-zinc-500 mt-1 line-clamp-2">
                {module.description}
              </div>
            </button>
          ))}
          {filteredModules.length === 0 && (
            <p className="text-[11px] text-zinc-600">No modules found.</p>
          )}
        </div>
      </aside>

      <section className="flex-1 p-6 overflow-y-auto">
        {!selectedModule ? (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
            Select a module to inspect and test.
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-zinc-100">
                  {selectedModule.module_id}
                </h3>
                <p className="text-[11px] text-zinc-500 mt-1">
                  {selectedModule.description || 'No description provided.'}
                </p>
              </div>
              <button
                onClick={() => setModal({ title: 'Module JSON', data: selectedModule })}
                className="text-[11px] px-2 py-1 rounded-md bg-zinc-900 text-zinc-300 hover:bg-zinc-800 flex items-center gap-1"
              >
                <Eye className="w-3 h-3" /> View JSON
              </button>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <InfoCard label="Status" value={selectedModule.status} />
              <InfoCard label="Version" value={String(selectedModule.version ?? 'n/a')} />
              <InfoCard label="Pipeline" value={String(selectedModule.pipeline ?? 'n/a')} />
              <InfoCard label="Task Type" value={String(selectedModule.task_type ?? 'n/a')} />
            </div>

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <h4 className="text-xs font-semibold text-zinc-300 mb-2">Test Input JSON</h4>
              <textarea
                value={inputJson}
                onChange={(e) => setInputJson(e.target.value)}
                rows={8}
                className="w-full px-2 py-2 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
              />
              {inputError && <div className="text-[10px] text-red-400 mt-1">{inputError}</div>}

              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={() => runModule('stub')}
                  disabled={runLoading !== null}
                  className="text-[11px] px-2.5 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 flex items-center gap-1"
                >
                  <Play className={cn('w-3 h-3', runLoading === 'stub' && 'animate-spin')} />
                  Run Stub
                </button>
                <button
                  onClick={() => runModule('real')}
                  disabled={runLoading !== null || DEMO_MODE}
                  title={DEMO_MODE ? 'Real provider runs are disabled in the local portfolio demo.' : undefined}
                  className="text-[11px] px-2.5 py-1 rounded-md bg-zinc-800 text-zinc-300 hover:bg-zinc-700 disabled:opacity-40 flex items-center gap-1"
                >
                  <Play className={cn('w-3 h-3', runLoading === 'real' && 'animate-spin')} />
                  Run Real
                </button>
                <button
                  onClick={validateModule}
                  disabled={validating}
                  className="text-[11px] px-2.5 py-1 rounded-md bg-zinc-800 text-zinc-200 hover:bg-zinc-700 disabled:opacity-40 flex items-center gap-1"
                >
                  <FlaskConical className={cn('w-3 h-3', validating && 'animate-spin')} />
                  Validate
                </button>
                <button
                  onClick={releaseModule}
                  disabled={releasing}
                  className="text-[11px] px-2.5 py-1 rounded-md bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-40 flex items-center gap-1"
                >
                  <Upload className={cn('w-3 h-3', releasing && 'animate-spin')} />
                  Release
                </button>
              </div>
            </section>

            {validationResult && (
              <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
                <h4 className="text-xs font-semibold text-zinc-300 mb-2">Validation Result</h4>
                <div
                  className={cn(
                    'text-[11px]',
                    validationResult.ok ? 'text-emerald-400' : 'text-red-400',
                  )}
                >
                  {validationResult.ok ? 'Passed' : 'Failed'}
                </div>
                {!validationResult.ok && (
                  <pre className="mt-2 text-[11px] text-zinc-300 overflow-auto max-h-44">
                    {formatJson(validationResult.errors)}
                  </pre>
                )}
              </section>
            )}

            {runDetail && (
              <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
                <h4 className="text-xs font-semibold text-zinc-300 mb-2">Latest Run</h4>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
                  <InfoCard icon={Activity} label="Status" value={runDetail.status} />
                  <InfoCard icon={Clock3} label="Mode" value={runDetail.mode} />
                  <InfoCard
                    label="Latency"
                    value={`${Number(runDetail.metrics?.latency_ms ?? 0)}ms`}
                  />
                  <InfoCard
                    label="Cost"
                    value={String(Number(runDetail.metrics?.cost_units ?? 0))}
                  />
                </div>
                <button
                  onClick={() =>
                    setModal({
                      title: `Run ${runDetail.run_id}`,
                      data: {
                        timeline: runDetail.timeline,
                        result: runDetail.result,
                        metrics: runDetail.metrics,
                      },
                    })
                  }
                  className="text-[11px] px-2 py-1 rounded-md bg-zinc-900 text-zinc-300 hover:bg-zinc-800 flex items-center gap-1"
                >
                  <Eye className="w-3 h-3" /> View Run JSON
                </button>
              </section>
            )}

            <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
              <h4 className="text-xs font-semibold text-zinc-300 mb-2">Contracts</h4>
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    setModal({
                      title: 'Input Schema',
                      data: selectedModule.input_schema ?? {},
                    })
                  }
                  className="text-[11px] px-2 py-1 rounded-md bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                >
                  Input Schema
                </button>
                <button
                  onClick={() =>
                    setModal({
                      title: 'Output Schema',
                      data: selectedModule.output_schema ?? {},
                    })
                  }
                  className="text-[11px] px-2 py-1 rounded-md bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                >
                  Output Schema
                </button>
              </div>
            </section>
          </div>
        )}
      </section>

      {modal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="w-[90vw] max-w-3xl bg-zinc-950 border border-zinc-800 rounded-xl shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
              <h4 className="text-sm font-semibold text-zinc-200">{modal.title}</h4>
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

function InfoCard({
  icon: Icon,
  label,
  value,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-center gap-2 text-[10px] text-zinc-500">
        {Icon ? <Icon className="w-3 h-3" /> : null}
        {label}
      </div>
      <div className="text-[12px] text-zinc-200 mt-1 break-all">{value}</div>
    </div>
  );
}
