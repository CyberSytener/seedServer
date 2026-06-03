/* ------------------------------------------------------------------ */
/* Toolbox - left sidebar: draggable block palette                      */
/* ------------------------------------------------------------------ */
import {
  Search,
  BarChart3,
  Bell,
  GitBranch,
  Box,
  GripVertical,
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
  Database,
  Sliders,
  Sparkles,
  ClipboardCheck,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useSagaStore } from '../../store/useSagaStore';
import type { BlockMeta } from '../../types';

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
  Database,
  Sliders,
  Sparkles,
  ClipboardCheck,
  ShieldCheck,
};

function groupByCategory(
  blocks: BlockMeta[],
): Record<string, BlockMeta[]> {
  const groups: Record<string, BlockMeta[]> = {};
  for (const b of blocks) {
    const cat = b.category || 'Other';
    (groups[cat] ??= []).push(b);
  }
  return groups;
}

/** Display categories in a logical order: triggers first, then control
 *  flow, then transforms, then domain blocks, then everything else. */
const CATEGORY_ORDER = [
  'Triggers',
  'Control Flow',
  'Transform',
  'NeoEats',
  'Scanners',
  'Scorers',
  'Actions',
  'Orchestration',
  'Other',
];

function sortedCategoryEntries(
  groups: Record<string, BlockMeta[]>,
): [string, BlockMeta[]][] {
  const entries = Object.entries(groups);
  return entries.sort(([a], [b]) => {
    const ai = CATEGORY_ORDER.indexOf(a);
    const bi = CATEGORY_ORDER.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

export function Toolbox() {
  const blocks = useSagaStore((s) => s.blocks);
  const groups = groupByCategory(blocks);

  function onDragStart(e: React.DragEvent, blockType: string) {
    e.dataTransfer.setData('application/sagablock', blockType);
    e.dataTransfer.effectAllowed = 'move';
  }

  return (
    <aside className="w-56 border-r border-border bg-zinc-950/60 flex flex-col overflow-hidden shrink-0">
      {/* Header */}
      <div className="px-3 py-3 border-b border-border">
        <h2 className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest">
          Blocks
        </h2>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4">
        {sortedCategoryEntries(groups).map(([category, items]) => (
          <div key={category}>
            <p className="text-[10px] font-bold text-zinc-600 uppercase tracking-widest px-1 mb-1.5">
              {category}
            </p>
            <div className="space-y-1">
              {items.map((block) => {
                const Icon = ICONS[block.icon] ?? Box;
                return (
                  <div
                    key={block.name}
                    draggable
                    onDragStart={(e) => onDragStart(e, block.name)}
                    className={cn(
                      'flex items-center gap-2.5 px-2 py-2 rounded-lg cursor-grab',
                      'bg-zinc-900/40 border border-zinc-800/40',
                      'hover:bg-zinc-800/60 hover:border-zinc-700/60',
                      'active:cursor-grabbing transition-colors group',
                    )}
                  >
                    <div
                      className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                      style={{ backgroundColor: block.color + '20' }}
                    >
                      <Icon
                        className="w-3.5 h-3.5"
                        style={{ color: block.color }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-zinc-300 truncate">
                        {block.name.replace(/_/g, ' ')}
                      </p>
                      <p className="text-[10px] text-zinc-600 truncate">
                        {block.description}
                      </p>
                    </div>
                    <GripVertical className="w-3 h-3 text-zinc-700 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {blocks.length === 0 && (
          <p className="text-[10px] text-zinc-700 px-2 py-4 text-center">
            Loading blocks...
          </p>
        )}
      </div>
    </aside>
  );
}
