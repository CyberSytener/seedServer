/* ------------------------------------------------------------------ */
/* PerformanceHud - floating execution metrics overlay                 */
/* ------------------------------------------------------------------ */
import { Clock, Coins, Shield, Activity } from 'lucide-react';
import { useSagaStore } from '../../store/useSagaStore';
import { cn } from '../../lib/utils';

export function PerformanceHud() {
  const performance = useSagaStore((s) => s.performance);
  const executionStatus = useSagaStore((s) => s.executionStatus);

  if (!performance) return null;

  return (
    <div className="absolute right-6 top-6 z-10">
      <div className="rounded-xl border border-zinc-800 bg-zinc-950/80 backdrop-blur px-4 py-3 shadow-xl">
        <div className="flex items-center gap-2 text-[10px] text-zinc-500 mb-2">
          <Activity
            className={cn(
              'w-3 h-3',
              executionStatus === 'running' && 'animate-spin text-blue-400',
              executionStatus === 'success' && 'text-emerald-400',
              executionStatus === 'error' && 'text-red-400',
            )}
          />
          <span className="uppercase tracking-widest">Performance HUD</span>
        </div>
        <div className="grid grid-cols-3 gap-3 text-[11px] text-zinc-400">
          <Metric icon={Clock} label={`${performance.duration_ms}ms`} />
          <Metric icon={Coins} label={`${performance.cost_estimate} credits`} />
          <Metric
            icon={Shield}
            label={`${(performance.reliability_score * 100).toFixed(0)}%`}
          />
        </div>
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
    <div className="flex items-center gap-1">
      <Icon className="w-3 h-3" />
      <span className="font-mono">{label}</span>
    </div>
  );
}
