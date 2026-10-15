import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api, ApiError, BOT, getToken } from './client';
import { queryClient } from './query';

export type Peer = { id: number; name: string; avatar?: string };
export type DmListing = { id: number; title: string; price: string; photo: string } | null;
export type DmMessage = { id: number; text: string; at: string; mine: boolean; read: boolean };
export type Conversation = {
  id: number; peer: Peer; listing: DmListing; unread: number;
  /** Можно ли писать (только друзьям); приходит при открытии диалога. */
  can_write?: boolean;
  last: { text: string; at: string; mine: boolean } | null;
};

export const useConversations = (enabled: boolean) => useQuery({
  queryKey: ['me', 'dm'], enabled, staleTime: 15_000,
  queryFn: () => api<{ items: Conversation[]; unread: number }>('/api/app/dm'),
});
export const useDialog = (id: number) => useQuery({
  queryKey: ['me', 'dm', id], enabled: id > 0, staleTime: 5_000,
  queryFn: () => api<{ conversation: Conversation; messages: DmMessage[] }>(`/api/app/dm/${id}`),
});
/** Диалог с продавцом по объявлению барахолки. */
export const startDialog = (itemId: number) => api<{ id: number }>('/api/app/dm/start', { item_id: itemId });
export const sendDm = (id: number, text: string) => api<{ message: DmMessage }>(`/api/app/dm/${id}`, { text }).then((d) => d.message);
export const markRead = (id: number) => api(`/api/app/dm/${id}/read`, {});
export const reportDialog = (id: number) => api(`/api/app/dm/${id}/report`, {});

// ---- Реальное время: одно WebSocket-соединение на приложение.
// Новые сообщения, «печатает…» и «прочитано» приходят сразу, без опроса сервера.

export type RoomMsg = { id: number; text: string; at: string; author: { id: number; name: string; city: string }; mine: boolean };
type Ev = { type: 'dm'; conv: number; message: DmMessage } | { type: 'typing'; conv: number } | { type: 'read'; conv: number; upto: number }
  | { type: 'room'; slug: string; message: RoomMsg }
  | { type: 'friend'; event: 'request' | 'accepted'; user: { id: number; name: string } }
  | { type: 'post'; event: 'like' | 'comment' | 'repost'; post: number; user: { id: number; name: string } }
  | { type: 'said'; ref: string; ok: boolean; message?: RoomMsg; error?: string; status?: number };
const waiting = new Map<string, (e: Extract<Ev, { type: 'said' }>) => void>();
const listeners = new Set<(e: Ev) => void>();
let ws: WebSocket | null = null;
let retry = 0;
let wanted = false;
const rooms = new Set<string>();

function connect() {
  const t = getToken();
  if (!wanted || !t || ws) return;
  const sock = new WebSocket(`${BOT.replace(/^http/, 'ws')}/api/app/ws?token=${encodeURIComponent(t)}`);
  ws = sock;
  sock.onopen = () => { retry = 0; rooms.forEach((r) => sock.send(JSON.stringify({ type: 'join', room: r }))); };
  sock.onmessage = (m) => {
    let e: Ev;
    try { e = JSON.parse(String(m.data)); } catch { return; }
    if (e.type === 'dm') {
      queryClient.setQueryData<{ conversation: Conversation; messages: DmMessage[] }>(['me', 'dm', e.conv], (cur) =>
        cur && !cur.messages.some((x) => x.id === e.message.id) ? { ...cur, messages: [...cur.messages, e.message] } : cur);
      queryClient.invalidateQueries({ queryKey: ['me', 'dm'], exact: true });
    }
    if (e.type === 'friend') {
      queryClient.invalidateQueries({ queryKey: ['me', 'friends'] });
      queryClient.invalidateQueries({ queryKey: ['me', 'user', e.user.id] });
    }
    if (e.type === 'post') queryClient.invalidateQueries({ queryKey: ['post', e.post] });
    if (e.type === 'said') { waiting.get(e.ref)?.(e); waiting.delete(e.ref); return; }
    if (e.type === 'read') {
      queryClient.setQueryData<{ conversation: Conversation; messages: DmMessage[] }>(['me', 'dm', e.conv], (cur) =>
        cur ? { ...cur, messages: cur.messages.map((x) => (x.mine && x.id <= e.upto ? { ...x, read: true } : x)) } : cur);
    }
    listeners.forEach((l) => l(e));
  };
  sock.onclose = () => {
    if (ws !== sock) return;            // закрыли старое соединение при смене аккаунта — новое уже открыто
    ws = null;
    if (!wanted) return;
    retry = Math.min(retry + 1, 6);
    setTimeout(connect, 500 * 2 ** retry);
  };
  sock.onerror = () => { try { sock.close(); } catch { /* уже закрыт */ } };
}

/** Держит соединение, пока пользователь вошёл. Сменился аккаунт — переподключаемся с новым токеном. */
export function useRealtime(userId: number) {
  useEffect(() => {
    wanted = userId > 0;
    if (ws) { const old = ws; ws = null; old.close(); }
    if (wanted) connect();
  }, [userId]);
}

export function onRealtime(fn: (e: Ev) => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
/** Подписка на новые сообщения городского/тематического чата, пока он открыт. */
export function joinRoom(slug: string) {
  rooms.add(slug);
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'join', room: slug }));
  return () => {
    rooms.delete(slug);
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'leave', room: slug }));
  };
}
export const realtimeConnected = () => !!ws && ws.readyState === 1;

let refN = 0;
/** Отправка в общий чат по WebSocket. null — соединения нет (тогда отправляем обычным запросом). */
export function sayInRoom(room: string, text: string): Promise<RoomMsg> | null {
  const sock = ws;
  if (!sock || sock.readyState !== 1) return null;
  const ref = `s${Date.now()}_${++refN}`;
  return new Promise<RoomMsg>((resolve, reject) => {
    const timer = setTimeout(() => { waiting.delete(ref); reject(new ApiError('Не отправилось. Проверьте интернет.', 0)); }, 8000);
    waiting.set(ref, (e) => {
      clearTimeout(timer);
      if (e.ok && e.message) resolve(e.message);
      else reject(new ApiError(e.error || 'Не отправилось', e.status || 400));
    });
    sock.send(JSON.stringify({ type: 'say', room, text, ref }));
  });
}

export function sendTyping(conv: number) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'typing', conv }));
}
