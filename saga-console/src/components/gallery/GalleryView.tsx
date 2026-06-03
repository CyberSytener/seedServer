/* ------------------------------------------------------------------ */
/* GalleryView - grid of blueprint cards + AI Draft prompt              */
/* ------------------------------------------------------------------ */
import { useEffect, useState } from 'react';
import {
  Plus,
  RefreshCw,
  Zap,
  Archive,
  Clock,
  User,
  FileText,
  Sparkles,
  Loader2,
  CheckCircle,
  ShieldCheck,
  Clock3,
  ArrowRight,
  PlayCircle,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useNavigateView } from '../../lib/useNavigateView';
import { api } from '../../api/client';
import { blueprintToGraph } from '../../utils/mapper';
import { useSagaStore } from '../../store/useSagaStore';
import type { BlueprintListItem } from '../../types';

const DEMO_BLUEPRINT_NAME = 'market_scan_default';

const STATUS_BADGE: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  DRAFT: { bg: 'bg-zinc-700/30', text: 'text-zinc-400', label: 'Draft' },
  SANDBOXED: {
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    label: 'Sandboxed',
  },
  ACTIVE: {
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    label: 'Active',
  },
  ARCHIVED: {
    bg: 'bg-zinc-800/50',
    text: 'text-zinc-600',
    label: 'Archived',
  },
};

export function GalleryView() {
  const blueprintsList = useSagaStore((s) => s.blueprintsList);
  const setBlueprintsList = useSagaStore((s) => s.setBlueprintsList);
  const navigateView = useNavigateView();
  const setBlueprintName = useSagaStore((s) => s.setBlueprintName);
  const setNodes = useSagaStore((s) => s.setNodes);
  const setEdges = useSagaStore((s) => s.setEdges);
  const resetExecution = useSagaStore((s) => s.resetExecution);
  const blocks = useSagaStore((s) => s.blocks);
  const modelTier = useSagaStore((s) => s.modelTier);
  const setRunsFilterBlueprint = useSagaStore((s) => s.setRunsFilterBlueprint);
  const setDirty = useSagaStore((s) => s.setDirty);
  const addToast = useSagaStore((s) => s.addToast);

  const [loading, setLoading] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [draftResult, setDraftResult] = useState<string | null>(null);
  const [sandboxing, setSandboxing] = useState<string | null>(null);
  const [sandboxMessage, setSandboxMessage] = useState<string | null>(null);
  const demoBlueprint = blueprintsList.find((bp) => bp.name === DEMO_BLUEPRINT_NAME);

  /* ---- Fetch blueprint list ---- */
  async function fetchBlueprints() {
    setLoading(true);
    try {
      const res = await api.getBlueprints();
      setBlueprintsList(res.blueprints);
    } catch (err) {
      console.error('Failed to fetch blueprints', err);
      addToast('Failed to load blueprints', 'error');
    }
    setLoading(false);
  }

  useEffect(() => {
    fetchBlueprints();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- Open a blueprint in the canvas ---- */
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

  /* ---- Seed gallery ---- */
  async function seedGallery() {
    try {
      await api.seedGallery();
      await fetchBlueprints();
      addToast('Demo gallery is ready', 'success');
    } catch (err) {
      console.error('Seed gallery failed', err);
      addToast(`Seed failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
  }

  /* ---- AI Draft ---- */
  async function handleDraft() {
    if (!draftPrompt.trim()) return;
    setDrafting(true);
    setDraftResult(null);
    try {
      const result = await api.draftBlueprint(draftPrompt, modelTier);
      if (result.ok && result.blueprint_id) {
        const dryStatus = result.dry_run?.status;
        const dryError = (result.dry_run as { error?: string } | undefined)?.error;
        const extra =
          dryStatus === 'failed' && dryError
            ? ` - dry-run failed: ${dryError}`
            : '';
        setDraftResult(
          `"${result.blueprint.name ?? result.blueprint_id}" created (${result.status})${extra}`,
        );
        setDraftPrompt('');
        fetchBlueprints();
        // Auto-open in canvas
        const steps = (result.blueprint.steps ?? []) as Array<{
          id: string;
          block: string;
          inputs: Record<string, unknown>;
          params?: Record<string, unknown>;
        }>;
        const { nodes, edges } = blueprintToGraph(steps, blocks);
        setBlueprintName(result.blueprint_id);
        setNodes(nodes);
        setEdges(edges);
        resetExecution();
        navigateView('canvas');
      } else {
        setDraftResult(
          `Draft failed: ${result.validation_errors.join(', ') || result.safety?.reason || 'unknown'}`,
        );
      }
    } catch (err) {
      setDraftResult(
        `Error: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    setDrafting(false);
  }

  /* ---- Approve a blueprint (SANDBOXED -> ACTIVE) ---- */
  async function handleApprove(
    e: React.MouseEvent,
    bp: BlueprintListItem,
  ) {
    e.stopPropagation();
    try {
      await api.approveBlueprint(bp.name);
      fetchBlueprints();
    } catch (err) {
      console.error('Approve failed', err);
      addToast('Approve failed', 'error');
    }
  }

  async function sandboxBlueprintByName(name: string) {
    setSandboxing(name);
    setSandboxMessage(null);
    try {
      const result = await api.sandboxBlueprint(name);
      const ok = result.dry_run?.status === 'succeeded' || result.status === 'SANDBOXED';
      setSandboxMessage(ok ? `Dry-run OK for ${name}` : `Dry-run failed for ${name}`);
      addToast(
        ok ? `Sandboxed ${name}` : `Sandbox failed for ${name}`,
        ok ? 'success' : 'error',
        ok ? undefined : result.dry_run ?? result,
      );
      await fetchBlueprints();
    } catch (err) {
      addToast(
        `Sandbox error: ${err instanceof Error ? err.message : String(err)}`,
        'error',
        err instanceof Error ? { message: err.message } : err,
      );
      setSandboxMessage(
        `Dry-run error: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    setSandboxing(null);
  }

  async function handleSandbox(
    e: React.MouseEvent,
    bp: BlueprintListItem,
  ) {
    e.stopPropagation();
    await sandboxBlueprintByName(bp.name);
  }

  return (
    <div className="h-full overflow-y-auto bg-zinc-950">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">
              Blueprint Gallery
            </h1>
            <p className="text-xs text-zinc-500 mt-0.5">
              {blueprintsList.length} blueprint
              {blueprintsList.length !== 1 ? 's' : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={seedGallery}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <Plus className="w-3 h-3" />
              Seed Gallery
            </button>
            <button
              onClick={fetchBlueprints}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <RefreshCw
                className={cn('w-3 h-3', loading && 'animate-spin')}
              />
              Refresh
            </button>
          </div>
        </div>

        <section className="mb-6 rounded-lg border border-blue-500/20 bg-blue-950/20 px-4 py-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <PlayCircle className="w-4 h-4 text-blue-300" />
                <span className="text-xs font-semibold text-blue-100">
                  Portfolio Demo
                </span>
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 text-[10px] font-medium',
                    demoBlueprint
                      ? 'bg-emerald-500/10 text-emerald-300'
                      : 'bg-amber-500/10 text-amber-300',
                  )}
                >
                  {demoBlueprint ? demoBlueprint.status : 'Not seeded'}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-zinc-400">
                {demoBlueprint
                  ? `${DEMO_BLUEPRINT_NAME} is ready for canvas inspection, sandboxing, and run review.`
                  : 'Seed the demo flow to start the reviewer path.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {!demoBlueprint ? (
                <button
                  onClick={seedGallery}
                  className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500"
                >
                  <Plus className="w-3 h-3" />
                  Seed Demo
                </button>
              ) : (
                <>
                  <button
                    onClick={() => openBlueprint(DEMO_BLUEPRINT_NAME)}
                    className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500"
                  >
                    Open Canvas
                    <ArrowRight className="w-3 h-3" />
                  </button>
                  <button
                    onClick={() => sandboxBlueprintByName(DEMO_BLUEPRINT_NAME)}
                    disabled={sandboxing === DEMO_BLUEPRINT_NAME}
                    className="flex items-center gap-1.5 rounded-md bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
                  >
                    {sandboxing === DEMO_BLUEPRINT_NAME ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <CheckCircle className="w-3 h-3" />
                    )}
                    Sandbox
                  </button>
                  <button
                    onClick={() => {
                      setRunsFilterBlueprint(DEMO_BLUEPRINT_NAME);
                      navigateView('runs');
                    }}
                    className="flex items-center gap-1.5 rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-zinc-700"
                  >
                    <Clock3 className="w-3 h-3" />
                    Runs
                  </button>
                </>
              )}
            </div>
          </div>
        </section>

        {/* AI Draft section */}
        <div className="mb-8 p-4 rounded-xl bg-zinc-900/50 border border-zinc-800/50">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-amber-400" />
            <span className="text-xs font-semibold text-zinc-300">
              AI Draft
            </span>
            <span className="text-[10px] text-zinc-600">
              Describe a workflow in plain English
            </span>
          </div>
          <div className="flex gap-2">
            <input
              value={draftPrompt}
              onChange={(e) => setDraftPrompt(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDraft()}
              placeholder="e.g. Scan the job market, score results, and notify the user with top 5 matches..."
              className="flex-1 px-3 py-2 rounded-lg bg-zinc-900 border border-zinc-700/50 text-sm text-zinc-300 placeholder:text-zinc-700 focus:outline-none focus:border-blue-500/50"
            />
            <button
              onClick={handleDraft}
              disabled={drafting || !draftPrompt.trim()}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {drafting ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Zap className="w-3 h-3" />
              )}
              Draft
            </button>
          </div>
          {draftResult && (
            <p className="mt-2 text-[11px] text-zinc-500">{draftResult}</p>
          )}
        </div>

        {/* Loading skeleton */}
        {loading && blueprintsList.length === 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div
                key={i}
                className="h-32 rounded-xl bg-zinc-900/50 border border-zinc-800/50 animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Blueprint grid */}
        {(!loading || blueprintsList.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {blueprintsList.map((bp) => {
            const badge = STATUS_BADGE[bp.status] ?? STATUS_BADGE.DRAFT;
            return (
              <button
                key={bp.name}
                onClick={() => openBlueprint(bp.name)}
                className="text-left p-4 rounded-xl bg-zinc-900/50 border border-zinc-800/50 hover:border-zinc-700 hover:bg-zinc-900/80 transition-all group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="w-4 h-4 text-zinc-600 shrink-0" />
                    <h3 className="text-sm font-semibold text-zinc-200 truncate">
                      {bp.name}
                    </h3>
                  </div>
                  <span
                    className={cn(
                      'text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0',
                      badge.bg,
                      badge.text,
                    )}
                  >
                    {badge.label}
                  </span>
                </div>

                <div className="flex items-center gap-3 text-[10px] text-zinc-600">
                  <span className="flex items-center gap-1">
                    <User className="w-3 h-3" />
                    {bp.owner_id}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {new Date(bp.created_at).toLocaleDateString()}
                  </span>
                </div>

                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setRunsFilterBlueprint(bp.name);
                      navigateView('runs');
                    }}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
                  >
                    <Clock3 className="w-3 h-3" />
                    Runs
                  </button>
                </div>

                {bp.status === 'DRAFT' && (
                  <button
                    onClick={(e) => handleSandbox(e, bp)}
                    className="mt-3 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors"
                  >
                    {sandboxing === bp.name ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <CheckCircle className="w-3 h-3" />
                    )}
                    Sandbox (Dry-run)
                  </button>
                )}

                {/* Approve button for SANDBOXED blueprints */}
                {bp.status === 'SANDBOXED' && (
                  <button
                    onClick={(e) => handleApprove(e, bp)}
                    className="mt-3 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors"
                  >
                    <ShieldCheck className="w-3 h-3" />
                    Approve
                  </button>
                )}
              </button>
            );
          })}
        </div>
        )}

        {sandboxMessage && (
          <div className="mt-4 text-[11px] text-zinc-500">{sandboxMessage}</div>
        )}

        {/* Empty state */}
        {blueprintsList.length === 0 && !loading && (
          <div className="text-center py-16">
            <Archive className="w-8 h-8 text-zinc-700 mx-auto mb-3" />
            <p className="text-sm text-zinc-600">No blueprints yet</p>
            <p className="text-xs text-zinc-700 mt-1">
              Seed the gallery or draft a new saga
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
