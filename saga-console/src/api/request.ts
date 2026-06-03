/* ------------------------------------------------------------------ */
/* API request core — shared fetch wrapper with auth                   */
/* ------------------------------------------------------------------ */
const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

function toRequestUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

function getAuthToken(): string | null {
  try {
    return localStorage.getItem('sagaAuthToken');
  } catch {
    return null;
  }
}

export type RequestOptions = {
  includeAuth?: boolean;
};

export async function request<T>(
  path: string,
  init?: RequestInit,
  options?: RequestOptions,
): Promise<T> {
  const token = getAuthToken();
  const includeAuth = options?.includeAuth ?? true;
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (includeAuth && token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const res = await fetch(toRequestUrl(path), {
    ...init,
    headers,
  });
  const text = await res.text();
  if (!res.ok) {
    let body: { detail?: unknown } = { detail: res.statusText };
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { detail: text };
      }
    }
    throw new Error(
      typeof body?.detail === 'string'
        ? body.detail
        : JSON.stringify(body?.detail ?? body),
    );
  }
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}
