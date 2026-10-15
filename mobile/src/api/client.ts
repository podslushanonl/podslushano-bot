import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export const SITE = 'https://www.podslushano.nl';
// Сервер бота; для проверки на тестовом сервере можно задать EXPO_PUBLIC_BOT_URL при сборке
export const BOT = process.env.EXPO_PUBLIC_BOT_URL || 'https://worker-production-ad76.up.railway.app';
export const TG_BOT = 'https://t.me/podslushano_nl_bot';

export class ApiError extends Error {
  /** data — весь ответ сервера (нужен, когда в ошибке есть подробности, например taken при привязке). */
  constructor(msg: string, public status: number, public data?: any) { super(msg); }
}

// Токен входа: в защищённом хранилище телефона, в браузере — в localStorage
const KEY = 'pn_token';
export const tokenStore = {
  get: () => (Platform.OS === 'web' ? AsyncStorage.getItem(KEY) : SecureStore.getItemAsync(KEY)),
  set: (v: string) => (Platform.OS === 'web' ? AsyncStorage.setItem(KEY, v) : SecureStore.setItemAsync(KEY, v)),
  del: () => (Platform.OS === 'web' ? AsyncStorage.removeItem(KEY) : SecureStore.deleteItemAsync(KEY)),
};

// Имя устройства для списка «Активные сессии»; браузер сервер узнаёт по User-Agent
const CLIENT: Record<string, string> = Platform.OS === 'web' ? {} : { 'X-Client': `${Platform.OS === 'ios' ? 'iPhone' : 'Android'} · приложение` };

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;
export const setToken = (t: string | null) => { token = t; };
export const getToken = () => token;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

/** Запрос к API бота. Ошибки сервера приходят как ApiError с понятным текстом. */
export async function api<T = any>(path: string, body?: object, method?: string): Promise<T> {
  let r: Response;
  try {
    r = await fetch(BOT + path, {
      method: method || (body ? 'POST' : 'GET'),
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...CLIENT, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Нет соединения. Проверьте интернет.', 0);
  }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && token) onUnauthorized?.();
  if (!r.ok || d.ok === false) throw new ApiError(d.error || 'Что-то пошло не так. Попробуйте ещё раз.', r.status, d);
  return d as T;
}

export async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new ApiError(`HTTP ${r.status}`, r.status);
  return r.json() as Promise<T>;
}

export const goUrl = (key: string) => `${BOT}/go/${key}?s=app`;

/** Загрузка файла (фото или видео) формой multipart: видео не кодируем в base64, чтобы не раздувать запрос. */
export async function upload<T = any>(path: string, file: { uri: string; name: string; type: string }, fields: Record<string, string> = {}): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  if (Platform.OS === 'web') form.append('file', await (await fetch(file.uri)).blob(), file.name);
  else form.append('file', file as any);
  let r: Response;
  try {
    r = await fetch(BOT + path, { method: 'POST', body: form,
      headers: { Accept: 'application/json', ...CLIENT, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  } catch {
    throw new ApiError('Нет соединения. Проверьте интернет.', 0);
  }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && token) onUnauthorized?.();
  if (!r.ok || d.ok === false) throw new ApiError(d.error || 'Не загрузилось. Попробуйте ещё раз.', r.status, d);
  return d as T;
}

/** Полный адрес файла с сервера (/media/…). */
export const mediaUrl = (path: string) => (path.startsWith('/') ? BOT + path : path);
