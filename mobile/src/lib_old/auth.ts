import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { useEffect, useState } from 'react';
import { Platform } from 'react-native';
import { BOT } from './api';

// Аккаунт приложения: токен хранится в защищённом хранилище телефона (в браузере — в localStorage)
export type User = { id: number; name: string; city: string; email: string; telegram: boolean };
export type Favorite = { kind: string; key: string; title: string };
type State = { token: string | null; user: User | null; favorites: Favorite[]; ready: boolean };

const KEY = 'pn_token';
let state: State = { token: null, user: null, favorites: [], ready: false };
const listeners = new Set<(s: State) => void>();
const set = (patch: Partial<State>) => { state = { ...state, ...patch }; listeners.forEach((l) => l(state)); };

const store = {
  get: () => (Platform.OS === 'web' ? AsyncStorage.getItem(KEY) : SecureStore.getItemAsync(KEY)),
  set: (v: string) => (Platform.OS === 'web' ? AsyncStorage.setItem(KEY, v) : SecureStore.setItemAsync(KEY, v)),
  del: () => (Platform.OS === 'web' ? AsyncStorage.removeItem(KEY) : SecureStore.deleteItemAsync(KEY)),
};

export class ApiError extends Error { constructor(msg: string, public status: number) { super(msg); } }

export async function call<T = any>(path: string, body?: object, method?: string): Promise<T> {
  const r = await fetch(BOT + path, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json', ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && state.token) { await logout(); }
  if (!r.ok || d.ok === false) throw new ApiError(d.error || 'Что-то пошло не так. Попробуйте ещё раз.', r.status);
  return d as T;
}

async function refreshMe() {
  const d = await call<{ user: User; favorites: Favorite[] }>('/api/app/me');
  set({ user: d.user, favorites: d.favorites });
}

let started = false;
async function init() {
  if (started) return; started = true;
  try {
    const t = await store.get();
    if (t) { set({ token: t }); await refreshMe().catch(() => {}); }
  } finally { set({ ready: true }); }
}

async function signedIn(d: { token: string; user: User }) {
  await store.set(d.token);
  set({ token: d.token, user: d.user });
  await refreshMe().catch(() => {});
}

export const requestCode = (email: string) => call('/api/app/auth/email', { email });
export const verifyCode = async (email: string, code: string) => signedIn(await call('/api/app/auth/verify', { email, code }));
export const startTelegram = () => call<{ nonce: string; url: string }>('/api/app/auth/tg', {});
/** true — вход подтверждён в боте, false — ещё ждём */
export async function pollTelegram(nonce: string) {
  const d = await call<any>(`/api/app/auth/tg?nonce=${encodeURIComponent(nonce)}`);
  if (d.pending) return false;
  await signedIn(d);
  return true;
}
export async function saveProfile(p: { name?: string; city?: string }) {
  const d = await call<{ user: User; favorites: Favorite[] }>('/api/app/me', p);
  set({ user: d.user, favorites: d.favorites });
}
export async function toggleFavorite(key: string, title: string, on: boolean) {
  const before = state.favorites;
  set({ favorites: on ? [{ kind: 'event', key, title }, ...before] : before.filter((f) => f.key !== key) });
  try { await call('/api/app/favorites', { kind: 'event', key, title, on }); } catch (e) { set({ favorites: before }); throw e; }
}
export async function logout() {
  await store.del().catch(() => {});
  set({ token: null, user: null, favorites: [] });
}

export function useAuth() {
  const [s, setS] = useState(state);
  useEffect(() => { listeners.add(setS); init(); return () => { listeners.delete(setS); }; }, []);
  return s;
}
