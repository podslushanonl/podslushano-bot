import { router } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from './client';
import { sayInRoom } from './dm';

export type Author = { id: number; name: string; city: string; verified?: boolean };
export type Msg = { id: number; text: string; at: string; author: Author; mine: boolean; city?: string };
export type Room = { slug: string; title: string; kind: 'city' | 'topic'; country: string; today: number };

export const useRooms = () => useQuery({ queryKey: ['rooms'], queryFn: () => api<{ rooms: Room[] }>('/api/app/rooms').then((d) => d.rooms), staleTime: 30_000 });
export const fetchMessages = (slug: string, after?: number) =>
  api<{ room: { title: string }; messages: Msg[] }>(`/api/app/rooms/${slug}/messages${after ? `?after=${after}` : ''}`);
/** Сообщение в общий чат: по живому соединению (WebSocket), без него — обычным запросом. */
export const sendMessage = async (slug: string, text: string): Promise<Msg> =>
  (await sayInRoom(slug, text)) ?? api<{ message: Msg }>(`/api/app/rooms/${slug}/messages`, { text }).then((d) => d.message);
export const acceptRules = () => api('/api/app/rules', {});
export type ContentKind = 'msg' | 'post' | 'comment' | 'icomment' | 'clip' | 'pcomment';
export const report = (kind: ContentKind, id: number) => api('/api/app/report', { kind, id });
export const block = (userId: number) => api('/api/app/block', { user_id: userId });
export const removeOwn = (kind: ContentKind, id: number) => api('/api/app/delete', { kind, id });

/** Ошибка доступа → куда отправить человека: войти, указать имя, принять правила. true — обработано. */
export function routeForError(e: unknown): boolean {
  if (!(e instanceof ApiError)) return false;
  if (e.status === 401) { router.push('/login'); return true; }
  if (e.status === 409) { router.push('/profile-edit'); return true; }
  if (e.status === 428) { router.push('/rules'); return true; }
  return false;
}
