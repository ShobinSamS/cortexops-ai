import { create } from 'zustand';
export interface User { id: string; email: string; name: string; role: string; workspace_id: string }
interface Auth { token: string | null; user: User | null; set: (token: string | null, user: User | null) => void }
export const useAuth = create<Auth>((set) => ({ token: null, user: null, set: (token, user) => set({ token, user }) }));
let refreshing: Promise<boolean> | null = null;
export async function refreshSession() {
  if (!refreshing) refreshing = fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' }).then(async res => {
    if (!res.ok) { useAuth.getState().set(null, null); return false; }
    const data = await res.json(); useAuth.getState().set(data.access_token, data.user); return true;
  }).catch(() => false).finally(() => { refreshing = null; });
  return refreshing;
}
export async function api<T = any>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(options.headers);
  if (useAuth.getState().token) headers.set('Authorization', `Bearer ${useAuth.getState().token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const res = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'include' });
  if (res.status === 401 && !retried && !path.startsWith('/auth/')) {
    if (await refreshSession()) return api<T>(path, options, true);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  }
  return res.status === 204 ? undefined as T : res.json();
}
export async function download(path: string, filename: string) {
  let res = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${useAuth.getState().token}` } });
  if (res.status === 401 && await refreshSession()) res = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${useAuth.getState().token}` } });
  if (!res.ok) throw new Error('Export failed');
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
}
export interface Investigation { id: string; title: string; question: string; status: string; selected_sources: string[]; created_at: string; started_at?: string; completed_at?: string; plan: { objective?: string; hypotheses?: string[]; steps?: string[] }; error?: string }
export interface Evidence { id: string; source: string; title: string; content: string; reference: Record<string, any>; score?: number }
