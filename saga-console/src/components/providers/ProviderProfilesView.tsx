import { useEffect, useMemo, useState } from 'react';
import {
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Search,
  Shield,
  KeyRound,
  DollarSign,
} from 'lucide-react';
import { api, type ProviderProfile } from '../../api/client';
import { cn } from '../../lib/utils';
import { useSagaStore } from '../../store/useSagaStore';

type DraftProfile = {
  id: string;
  enabled: boolean;
  requires_scope: string;
  daily_budget_units: string;
  per_run_cap_units: string;
  allowed_models_text: string;
  timeout_caps_text: string;
  retry_caps_text: string;
  redaction_policy_text: string;
};

function profileToDraft(profile: ProviderProfile): DraftProfile {
  return {
    id: String(profile.id || ''),
    enabled: Boolean(profile.enabled),
    requires_scope: String(profile.requires_scope || 'providers:use:real'),
    daily_budget_units: String(Number(profile.daily_budget_units ?? 0)),
    per_run_cap_units: String(Number(profile.per_run_cap_units ?? 0)),
    allowed_models_text: Array.isArray(profile.allowed_models)
      ? profile.allowed_models.join(', ')
      : '',
    timeout_caps_text: JSON.stringify(profile.timeout_caps ?? {}, null, 2),
    retry_caps_text: JSON.stringify(profile.retry_caps ?? {}, null, 2),
    redaction_policy_text: JSON.stringify(profile.redaction_policy ?? {}, null, 2),
  };
}

function emptyDraft(): DraftProfile {
  return {
    id: '',
    enabled: true,
    requires_scope: 'providers:use:real',
    daily_budget_units: '0',
    per_run_cap_units: '0',
    allowed_models_text: '',
    timeout_caps_text: '{}',
    retry_caps_text: '{}',
    redaction_policy_text: '{"store_raw_response":false}',
  };
}

function parseObjectJson(raw: string, field: string): Record<string, unknown> {
  const value = String(raw || '').trim();
  if (!value) return {};
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${field} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

function parseNonNegativeFloat(raw: string, field: string): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${field} must be a non-negative number`);
  }
  return parsed;
}

export function ProviderProfilesView() {
  const addToast = useSagaStore((s) => s.addToast);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [search, setSearch] = useState('');

  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [draft, setDraft] = useState<DraftProfile>(emptyDraft());

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return profiles;
    return profiles.filter((profile) => {
      const models = Array.isArray(profile.allowed_models)
        ? profile.allowed_models.join(' ').toLowerCase()
        : '';
      return (
        String(profile.id || '').toLowerCase().includes(term) ||
        String(profile.requires_scope || '').toLowerCase().includes(term) ||
        models.includes(term)
      );
    });
  }, [profiles, search]);

  async function loadProfiles() {
    setLoading(true);
    try {
      const response = await api.getProviderProfiles();
      const nextProfiles = Array.isArray(response.profiles) ? response.profiles : [];
      nextProfiles.sort((a, b) => a.id.localeCompare(b.id));
      setProfiles(nextProfiles);

      if (!isNew) {
        const preferredId = selectedId && nextProfiles.some((item) => item.id === selectedId)
          ? selectedId
          : nextProfiles[0]?.id ?? null;
        setSelectedId(preferredId);
        if (preferredId) {
          const detail = await api.getProviderProfile(preferredId);
          setDraft(profileToDraft(detail.profile));
        } else {
          setDraft(emptyDraft());
        }
      }
    } catch (err) {
      addToast(
        `Failed to load provider profiles: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setLoading(false);
  }

  async function loadProfile(profileId: string) {
    try {
      const detail = await api.getProviderProfile(profileId);
      setDraft(profileToDraft(detail.profile));
    } catch (err) {
      addToast(
        `Failed to load profile: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
  }

  useEffect(() => {
    loadProfiles();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId || isNew) return;
    loadProfile(selectedId);
  }, [selectedId, isNew]); // eslint-disable-line react-hooks/exhaustive-deps

  function startCreate() {
    setIsNew(true);
    setSelectedId(null);
    setDraft(emptyDraft());
  }

  function startSelect(profileId: string) {
    setIsNew(false);
    setSelectedId(profileId);
  }

  async function saveProfile() {
    const profileId = String(draft.id || '').trim();
    if (!profileId) {
      addToast('Profile ID is required', 'error');
      return;
    }

    let timeoutCaps: Record<string, unknown>;
    let retryCaps: Record<string, unknown>;
    let redactionPolicy: Record<string, unknown>;
    let dailyBudgetUnits: number;
    let perRunCapUnits: number;

    try {
      timeoutCaps = parseObjectJson(draft.timeout_caps_text, 'timeout_caps');
      retryCaps = parseObjectJson(draft.retry_caps_text, 'retry_caps');
      redactionPolicy = parseObjectJson(draft.redaction_policy_text, 'redaction_policy');
      dailyBudgetUnits = parseNonNegativeFloat(draft.daily_budget_units, 'daily_budget_units');
      perRunCapUnits = parseNonNegativeFloat(draft.per_run_cap_units, 'per_run_cap_units');
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Invalid profile payload', 'error');
      return;
    }

    const allowedModels = String(draft.allowed_models_text || '')
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0);

    setSaving(true);
    try {
      const response = await api.upsertProviderProfile(profileId, {
        enabled: draft.enabled,
        requires_scope: String(draft.requires_scope || '').trim() || 'providers:use:real',
        daily_budget_units: dailyBudgetUnits,
        per_run_cap_units: perRunCapUnits,
        allowed_models: allowedModels,
        timeout_caps: timeoutCaps,
        retry_caps: retryCaps,
        redaction_policy: redactionPolicy,
      });
      addToast(
        `${response.operation === 'created' ? 'Created' : 'Updated'} profile ${profileId}`,
        'success',
      );
      setIsNew(false);
      setSelectedId(profileId);
      await loadProfiles();
    } catch (err) {
      addToast(
        `Save failed: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setSaving(false);
  }

  async function deleteProfile() {
    const profileId = String(selectedId || '').trim();
    if (!profileId) return;
    if (profileId === 'default_real') {
      addToast('default_real profile cannot be deleted', 'error');
      return;
    }

    if (!window.confirm(`Delete provider profile "${profileId}"?`)) {
      return;
    }

    setDeleting(true);
    try {
      await api.deleteProviderProfile(profileId);
      addToast(`Deleted profile ${profileId}`, 'success');
      setSelectedId(null);
      setDraft(emptyDraft());
      await loadProfiles();
    } catch (err) {
      addToast(
        `Delete failed: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    }
    setDeleting(false);
  }

  return (
    <div className="h-full flex bg-zinc-950">
      <aside className="w-80 border-r border-zinc-900/70 p-4 overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-200">Provider Profiles</h2>
            <p className="text-[10px] text-zinc-500">
              {profiles.length} profile{profiles.length !== 1 ? 's' : ''}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={startCreate}
              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-emerald-700/80 text-zinc-100 hover:bg-emerald-600"
            >
              <Plus className="w-3 h-3" />
              New
            </button>
            <button
              onClick={loadProfiles}
              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-zinc-900 text-zinc-400 hover:bg-zinc-800"
            >
              <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
              Refresh
            </button>
          </div>
        </div>

        <div className="relative mb-3">
          <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-zinc-600" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search profiles"
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        <div className="space-y-2">
          {filtered.map((profile) => (
            <button
              key={profile.id}
              onClick={() => startSelect(profile.id)}
              className={cn(
                'w-full text-left rounded-lg border px-3 py-2 transition-colors',
                !isNew && profile.id === selectedId
                  ? 'border-blue-500/60 bg-blue-500/10'
                  : 'border-zinc-800/70 bg-zinc-900/40 hover:bg-zinc-900/70',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-200 truncate">
                  {profile.id}
                </span>
                <span
                  className={cn(
                    'text-[10px]',
                    profile.enabled ? 'text-emerald-400' : 'text-zinc-500',
                  )}
                >
                  {profile.enabled ? 'enabled' : 'disabled'}
                </span>
              </div>
              <div className="text-[10px] text-zinc-500 mt-1 truncate">
                {profile.requires_scope}
              </div>
            </button>
          ))}
          {filtered.length === 0 && (
            <p className="text-[11px] text-zinc-600">No provider profiles found.</p>
          )}
        </div>
      </aside>

      <section className="flex-1 p-6 overflow-y-auto">
        <div className="space-y-4 max-w-4xl">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-lg font-semibold text-zinc-100">
                {isNew ? 'Create Provider Profile' : draft.id || 'Provider Profile'}
              </h3>
              <p className="text-[11px] text-zinc-500 mt-1">
                Configure access scope, model allowlist, and budget caps for real LLM runs.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!isNew && selectedId && (
                <button
                  onClick={deleteProfile}
                  disabled={deleting || selectedId === 'default_real'}
                  className="text-[11px] px-2.5 py-1 rounded-md bg-red-700/70 text-zinc-100 hover:bg-red-600 disabled:opacity-40 flex items-center gap-1"
                >
                  <Trash2 className={cn('w-3 h-3', deleting && 'animate-spin')} />
                  Delete
                </button>
              )}
              <button
                onClick={saveProfile}
                disabled={saving}
                className="text-[11px] px-2.5 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 flex items-center gap-1"
              >
                <Save className={cn('w-3 h-3', saving && 'animate-spin')} />
                Save
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <FieldCard icon={Shield} label="Profile ID">
              <input
                value={draft.id}
                onChange={(e) => setDraft((prev) => ({ ...prev, id: e.target.value }))}
                disabled={!isNew}
                placeholder="e.g. openai_default"
                className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 focus:outline-none focus:border-blue-500/50 disabled:opacity-60"
              />
            </FieldCard>

            <FieldCard icon={KeyRound} label="Required Scope">
              <input
                value={draft.requires_scope}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, requires_scope: e.target.value }))
                }
                placeholder="providers:use:real"
                className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 focus:outline-none focus:border-blue-500/50"
              />
            </FieldCard>

            <FieldCard icon={DollarSign} label="Daily Budget Units">
              <input
                value={draft.daily_budget_units}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, daily_budget_units: e.target.value }))
                }
                inputMode="decimal"
                className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 focus:outline-none focus:border-blue-500/50"
              />
            </FieldCard>

            <FieldCard icon={DollarSign} label="Per-run Cap Units">
              <input
                value={draft.per_run_cap_units}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, per_run_cap_units: e.target.value }))
                }
                inputMode="decimal"
                className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 focus:outline-none focus:border-blue-500/50"
              />
            </FieldCard>
          </div>

          <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
            <label className="text-[11px] text-zinc-300 block mb-1">Allowed Models (comma-separated)</label>
            <input
              value={draft.allowed_models_text}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, allowed_models_text: e.target.value }))
              }
              placeholder="gpt-4.1-mini, gemini-2.0-flash"
              className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 focus:outline-none focus:border-blue-500/50"
            />

            <label className="text-[11px] text-zinc-300 block mt-3 mb-1">Enabled</label>
            <button
              onClick={() => setDraft((prev) => ({ ...prev, enabled: !prev.enabled }))}
              className={cn(
                'text-[11px] px-2.5 py-1 rounded-md border',
                draft.enabled
                  ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300'
                  : 'border-zinc-700 bg-zinc-900 text-zinc-400',
              )}
            >
              {draft.enabled ? 'Enabled' : 'Disabled'}
            </button>
          </section>

          <JsonSection
            label="timeout_caps (JSON object)"
            value={draft.timeout_caps_text}
            onChange={(value) => setDraft((prev) => ({ ...prev, timeout_caps_text: value }))}
          />
          <JsonSection
            label="retry_caps (JSON object)"
            value={draft.retry_caps_text}
            onChange={(value) => setDraft((prev) => ({ ...prev, retry_caps_text: value }))}
          />
          <JsonSection
            label="redaction_policy (JSON object)"
            value={draft.redaction_policy_text}
            onChange={(value) =>
              setDraft((prev) => ({ ...prev, redaction_policy_text: value }))
            }
          />
        </div>
      </section>
    </div>
  );
}

function FieldCard({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className="w-3 h-3 text-zinc-500" />
        <label className="text-[11px] text-zinc-300">{label}</label>
      </div>
      {children}
    </section>
  );
}

function JsonSection({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <label className="text-[11px] text-zinc-300 block mb-1">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={5}
        className="w-full px-2 py-2 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300 font-mono focus:outline-none focus:border-blue-500/50"
      />
    </section>
  );
}
