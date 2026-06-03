/* ------------------------------------------------------------------ */
/* ToastHost — lightweight feedback toasts                            */
/* ------------------------------------------------------------------ */
import { useEffect, useMemo, useState } from 'react';
import { CheckCircle, XCircle, Info } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useSagaStore } from '../../store/useSagaStore';

export function ToastHost() {
  const toasts = useSagaStore((s) => s.toasts);
  const removeToast = useSagaStore((s) => s.removeToast);
  const [details, setDetails] = useState<{ title: string; data: unknown } | null>(
    null,
  );

  return (
    <>
      <div className="fixed right-4 top-16 z-50 space-y-2">
        {toasts.map((toast) => (
          <ToastItem
            key={toast.id}
            id={toast.id}
            message={toast.message}
            tone={toast.tone}
            details={toast.details}
            onDismiss={removeToast}
            onDetails={(data) => setDetails({ title: toast.message, data })}
          />
        ))}
      </div>

      {details && (
        <div className="fixed inset-0 z-40">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setDetails(null)}
          />
          <div className="absolute right-0 top-0 h-full w-full max-w-lg bg-zinc-950/95 border-l border-zinc-800 shadow-2xl">
            <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-widest">
                  Toast Details
                </div>
                <div className="text-sm text-zinc-200 mt-1">
                  {details.title}
                </div>
              </div>
              <button
                onClick={() => setDetails(null)}
                className="text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                Close
              </button>
            </div>
            <pre className="p-4 text-[11px] text-zinc-300 overflow-auto h-[calc(100%-56px)]">
              {formatDetails(details.data)}
            </pre>
          </div>
        </div>
      )}
    </>
  );
}

function ToastItem({
  id,
  message,
  tone,
  details,
  onDismiss,
  onDetails,
}: {
  id: string;
  message: string;
  tone: 'info' | 'success' | 'error';
  details?: unknown;
  onDismiss: (id: string) => void;
  onDetails: (data: unknown) => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), 3200);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  const Icon = tone === 'success' ? CheckCircle : tone === 'error' ? XCircle : Info;

  return (
    <div
      className={cn(
        'min-w-[220px] max-w-[320px] rounded-lg border px-3 py-2 shadow-xl',
        'bg-zinc-950/90 backdrop-blur text-[11px] text-zinc-300',
        tone === 'success' && 'border-emerald-500/30',
        tone === 'error' && 'border-red-500/30',
        tone === 'info' && 'border-zinc-800',
      )}
    >
      <div className="flex items-center gap-2">
        <Icon
          className={cn(
            'w-3.5 h-3.5',
            tone === 'success' && 'text-emerald-400',
            tone === 'error' && 'text-red-400',
            tone === 'info' && 'text-blue-400',
          )}
        />
        <span className="flex-1">{message}</span>
        {details !== undefined && (
          <button
            onClick={() => onDetails(details)}
            className="text-[10px] text-blue-400 hover:text-blue-300"
          >
            Details
          </button>
        )}
      </div>
    </div>
  );
}

function formatDetails(value: unknown): string {
  try {
    if (typeof value === 'string') return value;
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? '');
  }
}
