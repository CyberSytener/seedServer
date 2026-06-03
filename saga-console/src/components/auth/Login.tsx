/* ------------------------------------------------------------------ */
/* Login - minimalist gatekeeper                                        */
/* ------------------------------------------------------------------ */
import { useState } from 'react';
import { Lock, ShieldCheck } from 'lucide-react';
import { api } from '../../api/client';

const DEV_MODE = import.meta.env.DEV;
const ADMIN_USER = 'L0g1n';
const ADMIN_PASS = 'P@SSW0RD';
// Format required by backend: test_<user_id>|<role>|<scopes>
const ADMIN_TOKEN = 'test_devuser|developer|runs:read,runs:write,modules:read,modules:write,flows:read,flows:write,catalog:read,blueprints:write,providers:read,providers:use:real';

export function Login({ onSuccess }: { onSuccess: (token: string) => void }) {
  const [username, setUsername] = useState(DEV_MODE ? ADMIN_USER : '');
  const [password, setPassword] = useState(DEV_MODE ? ADMIN_PASS : '');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await api.login(username, password);
      const token = String(response.accessToken || '').trim();
      if (!token) {
        throw new Error('Empty access token');
      }
      onSuccess(token);
      return;
    } catch (err) {
      if (DEV_MODE && username === ADMIN_USER && password === ADMIN_PASS) {
        onSuccess(ADMIN_TOKEN);
        setError(null);
        return;
      }
      setError(err instanceof Error ? err.message : 'Invalid credentials');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-screen bg-zinc-950 flex items-center justify-center px-6">
      <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900/60 shadow-2xl p-6">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-9 h-9 rounded-xl bg-blue-500/20 flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Saga Console</h1>
            <p className="text-[11px] text-zinc-500">Admin Access Required</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
              Username
            </label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full mt-1.5 px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-sm text-zinc-300 focus:outline-none focus:border-blue-500/60"
              placeholder="Enter admin user"
            />
          </div>
          <div>
            <label className="text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full mt-1.5 px-3 py-2 rounded-lg bg-zinc-950 border border-zinc-800 text-sm text-zinc-300 focus:outline-none focus:border-blue-500/60"
              placeholder="Enter password"
            />
          </div>

          {error && <p className="text-[11px] text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors flex items-center justify-center gap-2"
          >
            <Lock className="w-4 h-4" />
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="text-[10px] text-zinc-600 mt-4">
          Uses server `/api/v1/auth/login`.{DEV_MODE ? ' Local demo fallback is enabled.' : ''}
        </p>
      </div>
    </div>
  );
}
