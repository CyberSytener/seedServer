/* ------------------------------------------------------------------ */
/* SagaCanvas - the 3-zone layout: Toolbox | Canvas | Inspector         */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useReactFlow,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { api } from '../../api/client';
import { useSagaStore } from '../../store/useSagaStore';
import { graphToBlueprint } from '../../utils/mapper';
import { CustomNode } from './CustomNode';
import { AnimatedEdge } from './AnimatedEdge';
import { Toolbox } from '../panels/Toolbox';
import { Inspector } from '../panels/Inspector';
import { StatusBar } from '../panels/StatusBar';
import { PerformanceHud } from '../panels/PerformanceHud';
import { useNavigateView } from '../../lib/useNavigateView';

/* Must be defined outside the component to avoid re-creation */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const nodeTypes: Record<string, any> = { sagaNode: CustomNode };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const edgeTypes: Record<string, any> = { animatedEdge: AnimatedEdge };

export function SagaCanvas() {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  const nodes = useSagaStore((s) => s.nodes);
  const edges = useSagaStore((s) => s.edges);
  const onNodesChange = useSagaStore((s) => s.onNodesChange);
  const onEdgesChange = useSagaStore((s) => s.onEdgesChange);
  const onConnect = useSagaStore((s) => s.onConnect);
  const selectNode = useSagaStore((s) => s.selectNode);
  const addNode = useSagaStore((s) => s.addNode);
  const blueprintName = useSagaStore((s) => s.blueprintName);
  const setSaveStatus = useSagaStore((s) => s.setSaveStatus);
  const setDirty = useSagaStore((s) => s.setDirty);
  const addToast = useSagaStore((s) => s.addToast);
  const dirty = useSagaStore((s) => s.dirty);
  const navigateView = useNavigateView();

  /* ---- Drag & drop from Toolbox ---- */
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const blockType = e.dataTransfer.getData('application/sagablock');
      if (!blockType) return;
      const position = screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });
      addNode(blockType, position);
    },
    [screenToFlowPosition, addNode],
  );

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => selectNode(node.id),
    [selectNode],
  );

  const onPaneClick = useCallback(() => selectNode(null), [selectNode]);

  /* ---- Auto-save blueprint on changes ---- */
  const saveTimerRef = useRef<number | null>(null);
  const skipInitialRef = useRef(true);

  useEffect(() => {
    if (!blueprintName || !dirty) return;
    if (skipInitialRef.current) {
      skipInitialRef.current = false;
      return;
    }

    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
    }

    setSaveStatus('saving');
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        const steps = graphToBlueprint(nodes, edges);
        await api.saveBlueprint({ name: blueprintName, version: 'v1', steps });
        setSaveStatus('saved', Date.now());
        setDirty(false);
      } catch (err) {
        console.error('Auto-save failed', err);
        setSaveStatus('error');
        addToast(
          'Auto-save failed',
          'error',
          err instanceof Error ? { message: err.message } : err,
        );
      }
    }, 700);

    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [nodes, edges, blueprintName, setSaveStatus, setDirty, addToast, dirty]);

  return (
    <div className="flex h-full">
      {/* Left */}
      <Toolbox />

      {/* Center */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 relative" ref={wrapperRef}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onDragOver={onDragOver}
            onDrop={onDrop}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
            defaultEdgeOptions={{ type: 'animatedEdge' }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="#27272a"
            />
            <Controls showInteractive={false} />
            <MiniMap
              nodeStrokeColor="#3f3f46"
              nodeColor="#18181b"
              maskColor="rgba(0,0,0,0.7)"
            />
          </ReactFlow>
          {!blueprintName && nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="pointer-events-auto w-full max-w-sm rounded-lg border border-zinc-800 bg-zinc-950/90 p-4 text-center shadow-xl">
                <div className="text-sm font-semibold text-zinc-100">
                  Open a demo flow
                </div>
                <p className="mt-1 text-[11px] text-zinc-500">
                  Start from Gallery to inspect the seeded workflow on the canvas.
                </p>
                <button
                  onClick={() => navigateView('gallery')}
                  className="mt-3 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500"
                >
                  Go to Gallery
                </button>
              </div>
            </div>
          )}
          <PerformanceHud />
        </div>

        {/* Bottom */}
        <StatusBar />
      </div>

      {/* Right */}
      <Inspector />
    </div>
  );
}
