/* ------------------------------------------------------------------ */
/* StatusBar - bottom bar with Test Run button, metrics, AI summary     */
/* ------------------------------------------------------------------ */
import { Activity, Clock, Coins, Shield, Sparkles, Save, Braces } from 'lucide-react';
import { useEffect } from 'react';
import { cn } from '../../lib/utils';
import { api } from '../../api/client';
import { useSagaStore } from '../../store/useSagaStore';
import { graphToBlueprint } from '../../utils/mapper';

const DEMO_MODE = import.meta.env.DEV;

export function StatusBar() {
  const executionStatus = useSagaStore((s) => s.executionStatus);
  const performance = useSagaStore((s) => s.performance);
  const aiSummary = useSagaStore((s) => s.aiSummary);
  const blueprintName = useSagaStore((s) => s.blueprintName);
  const setRunning = useSagaStore((s) => s.setRunning);
  const setExecutionResult = useSagaStore((s) => s.setExecutionResult);
  const executionMode = useSagaStore((s) => s.executionMode);
  const setExecutionMode = useSagaStore((s) => s.setExecutionMode);
  const saveStatus = useSagaStore((s) => s.saveStatus);
  const lastSavedAt = useSagaStore((s) => s.lastSavedAt);
  const dirty = useSagaStore((s) => s.dirty);
  const setSaveStatus = useSagaStore((s) => s.setSaveStatus);
  const setDirty = useSagaStore((s) => s.setDirty);
  const nodes = useSagaStore((s) => s.nodes);
  const edges = useSagaStore((s) => s.edges);
  const addToast = useSagaStore((s) => s.addToast);
  const runInputJson = useSagaStore((s) => s.runInputJson);
  const setRunInputJson = useSagaStore((s) => s.setRunInputJson);

  async function handleRun() {
    if (executionStatus === 'running' || !blueprintName) return;
    if (executionMode === 'LIVE') {
      const ok = window.confirm(
        `Run LIVE saga "${blueprintName}"? This will persist results and trigger real actions.`,
      );
      if (!ok) return;
    }
    let parsedInput: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(runInputJson || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Run input must be a JSON object');
      }
      parsedInput = parsed as Record<string, unknown>;
    } catch (err) {
      addToast(
        `Run input JSON error: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
      return;
    }
    setRunning();
    try {
      const result = await api.executeSaga(
        blueprintName,
        parsedInput,
        executionMode,
      );
      setExecutionResult(
        result.status,
        result.execution_trace,
        result.performance,
        result.ai_summary,
      );
      addToast(
        result.status === 'succeeded' ? 'Run completed' : 'Run failed',
        result.status === 'succeeded' ? 'success' : 'error',
        result.status === 'succeeded' ? undefined : result,
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionResult(
        'error',
        [],
        { duration_ms: 0, cost_estimate: 0, reliability_score: 0 },
        msg,
      );
      addToast(`Run error: ${msg}`, 'error', { message: msg });
    }
  }

  function handleEditRunInput() {
    const next = window.prompt('Run input JSON', runInputJson);
    if (next == null) return;
    setRunInputJson(next);
  }

  async function handleSaveNow() {
    if (!blueprintName) return;
    setSaveStatus('saving');
    try {
      const steps = graphToBlueprint(nodes, edges);
      await api.saveBlueprint({ name: blueprintName, version: 'v1', steps });
      setSaveStatus('saved', Date.now());
      setDirty(false);
      addToast('Blueprint saved', 'success');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveStatus('error');
      addToast(`Save failed: ${msg}`, 'error');
    }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        handleSaveNow();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  const dotColor: Record<string, string> = {
    idle: 'bg-zinc-600',
    running: 'bg-blue-400',
    success: 'bg-emerald-400',
    error: 'bg-red-400',
  };

  const textColor: Record<string, string> = {
    idle: 'text-zinc-600',
    running: 'text-blue-400',
    success: 'text-emerald-400',
    error: 'text-red-400',
  };

  return (
    <div className="h-10 border-t border-border bg-zinc-950/80 flex items-center px-4 gap-6 shrink-0">
      {/* Run */}
      <button
        onClick={handleRun}
        disabled={executionStatus === 'running' || !blueprintName}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all',
          executionStatus === 'running'
            ? 'bg-blue-500/20 text-blue-400 cursor-wait'
            : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-30 disabled:cursor-not-allowed',
        )}
      >
        <Activity
          className={cn(
            'w-3 h-3',
            executionStatus === 'running' && 'animate-spin',
          )}
        />
        {executionStatus === 'running' ? 'Running...' : 'Run'}
      </button>

      <select
        value={executionMode}
        onChange={(e) => setExecutionMode(e.target.value as 'DRY_RUN' | 'LIVE')}
        className="px-2 py-1 rounded-md text-[11px] bg-zinc-900 border border-zinc-800 text-zinc-400 focus:outline-none focus:border-blue-500/50"
      >
        <option value="DRY_RUN">Dry Run</option>
        <option value="LIVE" disabled={DEMO_MODE}>Live</option>
      </select>

      <button
        onClick={handleSaveNow}
        disabled={!blueprintName || saveStatus === 'saving'}
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] border transition-colors',
          dirty
            ? 'border-amber-500/40 text-amber-300 bg-amber-500/10 hover:bg-amber-500/20'
            : 'border-zinc-800 text-zinc-400 bg-zinc-900 hover:bg-zinc-800',
        )}
      >
        <Save className="w-3 h-3" />
        Save Now
      </button>

      <button
        onClick={handleEditRunInput}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] border border-zinc-800 text-zinc-400 bg-zinc-900 hover:bg-zinc-800"
      >
        <Braces className="w-3 h-3" />
        Input JSON
      </button>

      {dirty && (
        <span className="text-[10px] text-amber-400">Unsaved changes</span>
      )}

      {/* Status dot */}
      <div className="flex items-center gap-1.5">
        <div
          className={cn(
            'w-1.5 h-1.5 rounded-full',
            dotColor[executionStatus] ?? dotColor.idle,
          )}
        />
        <span
          className={cn(
            'text-[11px] font-mono',
            textColor[executionStatus] ?? textColor.idle,
          )}
        >
          {executionStatus.toUpperCase()}
        </span>
      </div>

      {/* Performance metrics */}
      {performance && (
        <>
          <Metric icon={Clock} label={`${performance.duration_ms}ms`} />
          <Metric icon={Coins} label={`${performance.cost_estimate} credits`} />
          <Metric
            icon={Shield}
            label={`${(performance.reliability_score * 100).toFixed(0)}%`}
          />
        </>
      )}

      {/* AI Summary */}
      {aiSummary && (
        <div className="flex-1 flex items-center gap-1.5 min-w-0">
          <Sparkles className="w-3 h-3 text-amber-400 shrink-0" />
          <span className="text-[10px] text-zinc-500 truncate">
            {aiSummary}
          </span>
        </div>
      )}

      {/* Save status */}
      <div className="text-[10px] text-zinc-500 ml-auto">
        {saveStatus === 'saving' && 'Saving...'}
        {saveStatus === 'saved' &&
          `Saved ${lastSavedAt ? new Date(lastSavedAt).toLocaleTimeString() : ''}`}
        {saveStatus === 'error' && 'Save failed'}
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1 text-[11px] font-mono text-zinc-500">
      <Icon className="w-3 h-3" />
      <span>{label}</span>
    </div>
  );
}
