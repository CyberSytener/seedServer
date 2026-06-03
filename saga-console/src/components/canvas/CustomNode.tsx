/* ------------------------------------------------------------------ */
/* CustomNode — the saga block rendered on the React Flow canvas       */
/* ------------------------------------------------------------------ */
import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import {
  Search,
  BarChart3,
  Bell,
  GitBranch,
  Box,
  Play,
  Webhook,
  Clock,
  GitFork,
  Route,
  Repeat,
  Merge,
  PenLine,
  Filter,
  Timer,
  Minus,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { SagaNodeData } from '../../types';
import { useSagaStore } from '../../store/useSagaStore';

const ICONS: Record<string, LucideIcon> = {
  Search,
  BarChart3,
  Bell,
  GitBranch,
  Box,
  Play,
  Webhook,
  Clock,
  GitFork,
  Route,
  Repeat,
  Merge,
  PenLine,
  Filter,
  Timer,
  Minus,
};

const HEADER_H = 56;
const ROW_H = 22;
const BODY_PAD = 12;

/* Shape-specific wrapper classes */
const SHAPE_CLASSES: Record<string, string> = {
  default: 'rounded-xl',
  diamond: 'rounded-xl rotate-0', // Visual diamond accent via border
  hexagon: 'rounded-2xl',
  stadium: 'rounded-full',
  circle: 'rounded-full',
};

const SHAPE_ACCENT: Record<string, string> = {
  diamond: 'border-l-4',
  hexagon: 'border-l-4',
  stadium: '',
  default: '',
  circle: '',
};

interface CustomNodeProps {
  data: SagaNodeData;
  selected?: boolean;
}

function CustomNodeInner({ data, selected }: CustomNodeProps) {
  const Icon = ICONS[data.icon] ?? Box;
  const maxRows = Math.max(data.handleInputs.length, data.handleOutputs.length, 1);
  const developerMode = useSagaStore((s) => s.developerMode);
  const setNodeParamEnabled = useSagaStore((s) => s.setNodeParamEnabled);
  const toggleNodeDisabled = useSagaStore((s) => s.toggleNodeDisabled);

  const paramToggles = (data.paramToggles ?? {}) as Record<string, boolean>;
  const params = data.params as Record<string, unknown>;
  const paramKeys = Object.keys(params ?? {});
  const shape = data.shape ?? 'default';
  const isDisabled = data.disabled === true;

  const borderClass: Record<string, string> = {
    idle: 'border-zinc-700/50',
    running: 'border-blue-500 shadow-blue-500/25 shadow-lg node-running',
    success: 'border-emerald-500 shadow-emerald-500/15 shadow-lg',
    error: 'border-red-500 shadow-red-500/15 shadow-lg',
  };

  function handleTop(index: number) {
    return HEADER_H + BODY_PAD + index * ROW_H + ROW_H / 2;
  }

  return (
    <div
      className={cn(
        'bg-zinc-900/95 backdrop-blur-sm border-2 w-[260px] shadow-2xl',
        'transition-all duration-300',
        SHAPE_CLASSES[shape],
        SHAPE_ACCENT[shape],
        borderClass[data.status] ?? borderClass.idle,
        selected && 'ring-2 ring-blue-400/40',
        isDisabled && 'opacity-40 grayscale',
      )}
      style={shape === 'diamond' || shape === 'hexagon' ? { borderLeftColor: data.color } : undefined}
    >
      {/* ---- Disabled overlay badge ---- */}
      {isDisabled && (
        <div className="absolute -top-2 -right-2 z-10 bg-zinc-800 border border-zinc-600 rounded-full px-1.5 py-0.5 text-[9px] text-zinc-400 uppercase tracking-wider">
          off
        </div>
      )}

      {/* ---- Input handles ---- */}
      {data.handleInputs.map((key, i) => (
        <Handle
          key={`in-${key}`}
          type="target"
          position={Position.Left}
          id={`input-${key}`}
          style={{ top: handleTop(i) }}
          className="!w-3 !h-3 !rounded-full !bg-zinc-600 !border-2 !border-zinc-500 hover:!bg-blue-400 hover:!border-blue-400 !transition-colors"
        />
      ))}

      {/* ---- Output handles ---- */}
      {data.handleOutputs.map((key, i) => (
        <Handle
          key={`out-${key}`}
          type="source"
          position={Position.Right}
          id={`output-${key}`}
          style={{ top: handleTop(i) }}
          className="!w-3 !h-3 !rounded-full !bg-zinc-600 !border-2 !border-zinc-500 hover:!bg-emerald-400 hover:!border-emerald-400 !transition-colors"
        />
      ))}

      {/* ---- Header ---- */}
      <div
        className={cn(
          'px-3 py-2.5 flex items-center gap-2.5',
          shape === 'stadium' ? 'rounded-full' : 'rounded-t-[10px]',
        )}
        style={{ backgroundColor: data.color + '18' }}
      >
        <div
          className={cn(
            'w-8 h-8 flex items-center justify-center shrink-0 shadow-md',
            shape === 'diamond' ? 'rounded-md rotate-45' : 'rounded-lg',
          )}
          style={{ backgroundColor: data.color }}
        >
          <Icon className={cn('w-4 h-4 text-white', shape === 'diamond' && '-rotate-45')} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider leading-none mb-0.5">
            {data.blockType}
          </p>
          <p className="text-sm font-semibold text-zinc-100 truncate leading-tight">
            {data.stepId}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {data.executionTime != null && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
              {data.executionTime}s
            </span>
          )}
          {/* Disable toggle button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleNodeDisabled(data.stepId);
            }}
            className={cn(
              'w-5 h-5 rounded flex items-center justify-center transition-colors',
              isDisabled
                ? 'bg-zinc-700 text-zinc-500'
                : 'bg-zinc-800/60 text-zinc-400 hover:bg-zinc-700',
            )}
            title={isDisabled ? 'Enable node' : 'Disable node'}
          >
            <span className="text-[9px] font-bold">{isDisabled ? '⏸' : '▶'}</span>
          </button>
        </div>
      </div>

      {/* ---- Metadata ---- */}
      <div className="px-3 pt-2 text-[10px] text-zinc-500 flex items-center justify-between">
        <span className="uppercase tracking-widest">
          {data.category ?? 'Module'}
        </span>
        <span className="text-zinc-600">
          {data.handleInputs.length} in / {data.handleOutputs.length} out
        </span>
      </div>
      {data.traceStatus && (
        <div className="px-3 pt-1 flex items-center justify-between text-[10px]">
          <span
            className={cn(
              'uppercase tracking-widest',
              data.traceStatus === 'failed'
                ? 'text-red-400'
                : data.traceStatus === 'skipped'
                  ? 'text-zinc-500'
                  : 'text-emerald-400',
            )}
          >
            {data.traceStatus}
          </span>
          <span className="text-zinc-600">
            {data.traceOutputKeys?.length
              ? `${data.traceOutputKeys.length} keys`
              : 'no outputs'}
          </span>
        </div>
      )}
      {data.traceStatus === 'failed' && data.traceError && (
        <div className="px-3 pt-1 text-[10px] text-red-400 line-clamp-2">
          {data.traceError}
        </div>
      )}
      {data.description && (
        <div className="px-3 pt-1 text-[10px] text-zinc-600 line-clamp-2">
          {data.description}
        </div>
      )}
      {developerMode && (
        <div className="px-3 pt-1">
          <a
            href={`/v1/sagas/registry/schema`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-[10px] text-blue-400 hover:text-blue-300"
          >
            View {data.blockType} in registry
          </a>
        </div>
      )}

      {/* ---- Handle labels ---- */}
      <div className="px-3 py-3">
        {Array.from({ length: maxRows }).map((_, i) => (
          <div
            key={i}
            className="flex items-center justify-between"
            style={{ height: ROW_H }}
          >
            <span className="text-[11px] font-mono text-zinc-500 pl-2">
              {data.handleInputs[i] ?? ''}
            </span>
            <span className="text-[11px] font-mono text-zinc-500 pr-2">
              {data.handleOutputs[i] ?? ''}
            </span>
          </div>
        ))}
      </div>

      {/* ---- Params toggles ---- */}
      {paramKeys.length > 0 && (
        <div className="px-3 pb-3">
          <div className="text-[9px] text-zinc-600 uppercase tracking-widest mb-2">
            Params
          </div>
          <div className="space-y-1">
            {paramKeys.map((key) => {
              const enabled = paramToggles[key] !== false;
              return (
                <div
                  key={key}
                  className="flex items-center justify-between text-[10px]"
                >
                  <span
                    className={cn(
                      'font-mono',
                      enabled ? 'text-zinc-400' : 'text-zinc-600 line-through',
                    )}
                  >
                    {key}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setNodeParamEnabled(data.stepId, key, !enabled);
                    }}
                    className={cn(
                      'w-8 h-4 rounded-full border transition-colors relative',
                      enabled
                        ? 'bg-emerald-500/20 border-emerald-500/40'
                        : 'bg-zinc-800/60 border-zinc-700',
                    )}
                  >
                    <span
                      className={cn(
                        'absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full transition-all',
                        enabled
                          ? 'right-0.5 bg-emerald-400'
                          : 'left-0.5 bg-zinc-600',
                      )}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export const CustomNode = memo(CustomNodeInner);
