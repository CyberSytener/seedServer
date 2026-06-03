/* ------------------------------------------------------------------ */
/* App - root component with header + URL routing                       */
/* ------------------------------------------------------------------ */
import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ReactFlowProvider } from '@xyflow/react';
import {
  Workflow,
  LayoutGrid,
  Zap,
  Sparkles,
  KeyRound,
  Clock3,
  Boxes,
  SlidersHorizontal,
} from 'lucide-react';
import { cn } from './lib/utils';
import { useNavigateView } from './lib/useNavigateView';
import { api } from './api/client';
import { enrichBlockMeta } from './utils/mapper';
import { useSagaStore } from './store/useSagaStore';
import { SagaCanvas } from './components/canvas/SagaCanvas';
import { GalleryView } from './components/gallery/GalleryView';
import { RunsView } from './components/runs/RunsView';
import { ModulesView } from './components/modules/ModulesView';
import { ProviderProfilesView } from './components/providers/ProviderProfilesView';
import { Login } from './components/auth/Login';
import { ToastHost } from './components/toast/ToastHost';

type ViewKey = 'canvas' | 'gallery' | 'runs' | 'modules' | 'providers';
const DEMO_MODE = import.meta.env.DEV;

const PATH_TO_VIEW: Record<string, ViewKey> = {
  canvas: 'canvas',
  gallery: 'gallery',
  runs: 'runs',
  modules: 'modules',
  providers: 'providers',
};

export default function App() {
  const location = useLocation();
  const navigateView = useNavigateView();

  const view = useSagaStore((s) => s.view);
  const setView = useSagaStore((s) => s.setView);
  const setBlocks = useSagaStore((s) => s.setBlocks);
  const blueprintName = useSagaStore((s) => s.blueprintName);
  const authToken = useSagaStore((s) => s.authToken);
  const setAuthToken = useSagaStore((s) => s.setAuthToken);
  const addToast = useSagaStore((s) => s.addToast);

  /* Sync URL -> store view on location change */
  useEffect(() => {
    const segment = location.pathname.split('/').filter(Boolean)[0] ?? 'gallery';
    const mapped = PATH_TO_VIEW[segment];
    if (mapped && mapped !== view) {
      setView(mapped);
    }
  }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Fetch registry on mount; attempt token refresh if session expired */
  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    (async () => {
      try {
        await api.me();
      } catch {
        // Session might be expired - try refresh
        try {
          const refreshed = await api.refreshToken();
          if (!cancelled && refreshed.accessToken) {
            setAuthToken(refreshed.accessToken);
            return; // useEffect will re-run with new token
          }
        } catch {
          // refresh failed - will force re-login below if registry also fails
        }
      }
      try {
        const schema = await api.getRegistrySchema();
        if (!cancelled) {
          setBlocks(enrichBlockMeta(schema));
        }
      } catch (err) {
        console.error('Registry bootstrap failed', err);
        if (!cancelled) {
          addToast('Session expired or registry unavailable', 'error');
          setAuthToken('');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authToken, setAuthToken, setBlocks]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!authToken) {
    return <Login onSuccess={setAuthToken} />;
  }

  return (
    <ReactFlowProvider>
      <div className="h-screen w-screen flex flex-col bg-background overflow-hidden">
        {/* ---- Top bar ---- */}
        <header className="h-12 border-b border-border flex items-center px-4 gap-4 shrink-0">
          {/* Brand */}
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-blue-400" />
            <span className="font-semibold text-sm tracking-tight">
              Saga Console
            </span>
          </div>

          {/* Nav tabs */}
          <div className="flex items-center gap-1 ml-4 bg-secondary/50 rounded-lg p-0.5">
            <NavTab
              active={view === 'canvas'}
              onClick={() => navigateView('canvas')}
              icon={Workflow}
              label="Canvas"
            />
            <NavTab
              active={view === 'gallery'}
              onClick={() => navigateView('gallery')}
              icon={LayoutGrid}
              label="Gallery"
            />
            <NavTab
              active={view === 'runs'}
              onClick={() => navigateView('runs')}
              icon={Clock3}
              label="Runs"
            />
            <NavTab
              active={view === 'modules'}
              onClick={() => navigateView('modules')}
              icon={Boxes}
              label="Modules"
            />
            <NavTab
              active={view === 'providers'}
              onClick={() => navigateView('providers')}
              icon={SlidersHorizontal}
              label="Providers"
            />
          </div>

          {/* Active blueprint indicator */}
          {view === 'canvas' && blueprintName && (
            <div className="flex items-center gap-2 ml-4 text-xs text-zinc-400">
              <Zap className="w-3 h-3" />
              <span className="font-mono">{blueprintName}</span>
            </div>
          )}

          <div className="flex-1" />

          <div className="hidden md:flex items-center gap-2">
            {DEMO_MODE && (
              <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                Stub demo
              </span>
            )}
            <KeyRound className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-[11px] text-zinc-400">Admin session</span>
            <button
              onClick={async () => {
                try { await api.logout(); } catch { /* ignore */ }
                setAuthToken('');
              }}
              className="px-2 py-1 rounded-md text-[11px] bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200"
            >
              Logout
            </button>
          </div>

          <span className="text-[10px] font-mono text-zinc-600">v0.5.0</span>
        </header>

        {/* ---- Main content (URL-routed) ---- */}
        <div className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/gallery" element={<GalleryView />} />
            <Route path="/canvas" element={<SagaCanvas />} />
            <Route path="/runs" element={<RunsView />} />
            <Route path="/modules" element={<ModulesView />} />
            <Route path="/providers" element={<ProviderProfilesView />} />
            <Route path="*" element={<Navigate to="/gallery" replace />} />
          </Routes>
        </div>
        <ToastHost />
      </div>
    </ReactFlowProvider>
  );
}

/* ---- Tiny nav-tab helper ---- */
function NavTab({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors',
        active
          ? 'bg-zinc-700 text-white'
          : 'text-zinc-400 hover:text-zinc-200',
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
    </button>
  );
}
