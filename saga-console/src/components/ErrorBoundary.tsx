import { Component, type ReactNode } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="min-h-screen w-screen bg-zinc-950 flex items-center justify-center px-6">
        <div className="w-full max-w-lg rounded-2xl border border-zinc-800 bg-zinc-900/60 shadow-2xl p-8 text-center">
          <div className="mx-auto w-12 h-12 rounded-xl bg-red-500/20 flex items-center justify-center mb-4">
            <AlertTriangle className="w-6 h-6 text-red-400" />
          </div>
          <h1 className="text-xl font-semibold text-zinc-100 mb-2">
            Something went wrong
          </h1>
          <p className="text-sm text-zinc-400 mb-6">
            The application encountered an unexpected error. You can try
            reloading or resetting the current view.
          </p>
          {import.meta.env.DEV && this.state.error && (
            <pre className="mb-6 max-h-40 overflow-auto rounded-lg bg-zinc-950 border border-zinc-800 p-3 text-left text-xs text-red-400 font-mono">
              {this.state.error.message}
            </pre>
          )}
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={this.handleReset}
              className="px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 text-sm hover:bg-zinc-700 transition-colors flex items-center gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-500 transition-colors"
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
