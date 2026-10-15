import { useSyncExternalStore } from 'react';
import { api, ApiError, setToken, setUnauthorizedHandler, tokenStore } from './client';
import { queryClient } from './query';

export type User = { id: number; name: string; city: string; country: string; email: string; phone: string; telegram: boolean; bio: string; avatar: string };
export type Favorite = { kind: string; key: string; title: string };
type State = { ready: boolean; user: User | null; favorites: Favorite[] };

let state: State = { ready: false, user: null, favorites: [] };
const subs = new Set<() => void>();
const set = (p: Partial<State>) => { state = { ...state, ...p }; subs.forEach((f) => f()); };

export function useAuth() {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => state, () => state);
}
export const authState = () => state;

async function refreshMe() {
  const d = await api<{ user: User; favorites: Favorite[] }>('/api/app/me');
  set({ user: d.user, favorites: d.favorites });
}

let started = false;
/** Восстанавливает вход при запуске приложения. */
export async function bootAuth() {
  if (started) return;
  started = true;
  setUnauthorizedHandler(() => { logout(); });
  try {
    const t = await tokenStore.get();
    if (t) {
      setToken(t);
      await refreshMe().catch((e) => { if (e instanceof ApiError && e.status === 401) return logout(); });
    }
  } finally { set({ ready: true }); }
}

async function signedIn(d: { token: string; user: User }) {
  await tokenStore.set(d.token);
  setToken(d.token);
  set({ user: d.user });
  await refreshMe().catch(() => {});
  queryClient.invalidateQueries();
}

/** Куда слать код: номер (cc — код страны из флага) или почта. */
export type LoginTarget = { phone: string; cc: string } | { email: string };
export type CodeSent = { kind: 'phone' | 'email'; to: string; ttl: number };

/** Какими способами сейчас можно войти (вход по номеру включается на сервере). */
export const authMethods = () => api<{ phone: boolean; email: boolean; telegram: boolean }>('/api/app/auth/methods');
export const requestCode = (t: LoginTarget) => api<CodeSent>('/api/app/auth/start', t);
/** to — номер или почта из ответа requestCode (уже приведённые сервером к одному виду). */
export const verifyCode = async (sent: CodeSent, code: string) =>
  signedIn(await api('/api/app/auth/check', { [sent.kind]: sent.to, code }));
export const startTelegram = () => api<{ nonce: string; url: string }>('/api/app/auth/tg', {});
/** true — вход подтверждён в боте, false — ещё ждём. */
export async function pollTelegram(nonce: string) {
  const d = await api<any>(`/api/app/auth/tg?nonce=${encodeURIComponent(nonce)}`);
  if (d.pending) return false;
  await signedIn(d);
  return true;
}

export async function saveProfile(p: { name?: string; city?: string; country?: string; bio?: string }) {
  const d = await api<{ user: User; favorites: Favorite[] }>('/api/app/me', p);
  set({ user: d.user, favorites: d.favorites });
}

/** Новое фото профиля (data:…) или '' — убрать. crop — рамка, выбранная человеком (доли картинки). */
export async function saveAvatar(photo: string, crop?: { x: number; y: number; w: number; h: number }) {
  const d = await api<{ user: User }>('/api/app/me/avatar', crop ? { photo, crop } : { photo });
  set({ user: d.user });
  queryClient.invalidateQueries({ queryKey: ['me', 'user', d.user.id] });
}

export async function toggleFavorite(key: string, title: string, on: boolean, kind = 'event') {
  const before = state.favorites;
  set({ favorites: on ? [{ kind, key, title }, ...before] : before.filter((f) => !(f.key === key && f.kind === kind)) });
  try { await api('/api/app/favorites', { kind, key, title, on }); } catch (e) { set({ favorites: before }); throw e; }
}

export async function logout() {
  await tokenStore.del().catch(() => {});
  setToken(null);
  set({ user: null, favorites: [] });
  queryClient.removeQueries({ predicate: (q) => String(q.queryKey[0]).startsWith('me') });
}
