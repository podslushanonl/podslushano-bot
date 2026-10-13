import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api, BOT, getToken } from './client';
import { queryClient } from './query';

export type Peer = { id: number; name: string };
export type DmListing = { id: number; title: string; price: string; photo: string } | null;
export type DmMessage = { id: number; text: string; at: string; mine: boolean; read: boolean };
export type Conversation = {
  id: number; peer: Peer; listing: DmListing; unread: number;
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
export const startDialog = (listingId: number) => api<{ id: number }>('/api/app/dm/start', { listing_id: listingId });
export const sendDm = (id: number, text: string) => api<{ message: DmMessage }>(`/api/app/dm/${id}`, { text }).then((d) => d.message);
export const markRead = (id: number) => api(`/api/app/dm/${id}/read`, {});
export const reportDialog = (id: number) => api(`/api/app/dm/${id}/report`, {});

// ---- Реальное время: одно WebSocket-соединение на приложение.
// Новые сообщения, «печатает…» и «прочитано» приходят сразу, без опроса сервера.

export type RoomMsg = { id: number; text: string; at: string; author: { id: number; name: string; city: string }; mine: boolean };
type Ev = { type: 'dm'; conv: number; message: DmMessage } | { type: 'typing'; conv: number } | { type: 'read'; conv: number; upto: number }
  | { type: 'room'; slug: string; message: RoomMsg };
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
    if (e.type === 'read') {
      queryClient.setQueryData<{ conversation: Conversation; messages: DmMessage[] }>(['me', 'dm', e.conv], (cur) =>
        cur ? { ...cur, messages: cur.messages.map((x) => (x.mine && x.id <= e.upto ? { ...x, read: true } : x)) } : cur);
    }
    listeners.forEach((l) => l(e));
  };
  sock.onclose = () => {
    ws = null;
    if (!wanted) return;
    retry = Math.min(retry + 1, 6);
    setTimeout(connect, 500 * 2 ** retry);
  };
  sock.onerror = () => { try { sock.close(); } catch { /* уже закрыт */ } };
}

/** Держит соединение, пока пользователь вошёл. */
export function useRealtime(signedIn: boolean) {
  useEffect(() => {
    wanted = signedIn;
    if (signedIn) connect();
    else if (ws) { ws.close(); ws = null; }
  }, [signedIn]);
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

export function sendTyping(conv: number) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'typing', conv }));
}
