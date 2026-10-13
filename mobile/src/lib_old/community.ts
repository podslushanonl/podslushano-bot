import { router } from 'expo-router';
import { ApiError, call } from './auth';

export type Author = { id: number; name: string; city: string };
export type Msg = { id: number; text: string; at: string; author: Author; mine: boolean; city?: string };
export type Room = { slug: string; title: string; kind: 'city' | 'topic'; today: number };

export const rooms = () => call<{ rooms: Room[] }>('/api/app/rooms').then((d) => d.rooms);
export const messages = (slug: string, after?: number) =>
  call<{ room: { title: string }; messages: Msg[] }>(`/api/app/rooms/${slug}/messages${after ? `?after=${after}` : ''}`);
export const sendMessage = (slug: string, text: string) => call<{ message: Msg }>(`/api/app/rooms/${slug}/messages`, { text }).then((d) => d.message);
export const posts = () => call<{ posts: Msg[] }>('/api/app/posts').then((d) => d.posts);
export const sendPost = (text: string) => call<{ post: Msg }>('/api/app/posts', { text }).then((d) => d.post);
export const acceptRules = () => call('/api/app/rules', {});
export const report = (kind: 'msg' | 'post', id: number) => call('/api/app/report', { kind, id });
export const block = (userId: number) => call('/api/app/block', { user_id: userId });
export const removeOwn = (kind: 'msg' | 'post', id: number) => call('/api/app/delete', { kind, id });

/** Ошибка при отправке → куда отправить человека: войти, имя в профиле, правила. true — обработано переходом. */
export function routeForError(e: unknown): boolean {
  if (!(e instanceof ApiError)) return false;
  if (e.status === 401) { router.push('/login'); return true; }
  if (e.status === 409) { router.push('/profile'); return true; }
  if (e.status === 428) { router.push('/rules'); return true; }
  return false;
}

export function timeLabel(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const hm = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Amsterdam' });
  if (d.toDateString() === now.toDateString()) return hm;
  return `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: 'Europe/Amsterdam' })}, ${hm}`;
}
