/* ------------------------------------------------------------------ */
/* Shared utility helpers                                              */
/* ------------------------------------------------------------------ */
import { api, type ConsoleRun } from '../api/client';

/** Safely serialize any value to a pretty-printed JSON string. */
export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? '');
  }
}

/** Poll a run until it reaches a terminal state (or max attempts). */
export async function waitForTerminalRun(
  runId: string,
  attempts = 80,
  intervalMs = 500,
): Promise<ConsoleRun> {
  let detail = await api.getRunRaw(runId);
  for (let i = 0; i < attempts; i += 1) {
    if (detail.status !== 'running') return detail;
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    detail = await api.getRunRaw(runId);
  }
  return detail;
}
