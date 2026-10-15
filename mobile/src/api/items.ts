import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import type { Comment, Post } from './feed';
import { feedChanged } from './feed';
import { queryClient } from './query';

/** Новость или событие ленты, к которым можно ставить лайки, комментировать и делиться. */
export type ItemKind = 'news' | 'event';
export type ItemRef = { kind: ItemKind; key: string; title: string; url: string; img: string };
export type ItemStats = { likes: number; liked: boolean; comments: number; shares: number; shared: boolean };
export const itemId = (kind: ItemKind, key: string) => `${kind}:${key}`;
const EMPTY: ItemStats = { likes: 0, liked: false, comments: 0, shares: 0, shared: false };

/** Счётчики для видимых новостей и событий — одним запросом. */
export const useItemStats = (ids: string[]) => useQuery({
  queryKey: ['items', 'stats', ids.join(',')], enabled: ids.length > 0, staleTime: 20_000,
  queryFn: () => api<{ stats: Record<string, ItemStats> }>(`/api/app/items/stats?keys=${encodeURIComponent(ids.join(','))}`).then((d) => d.stats),
});
export const statsOf = (all: Record<string, ItemStats> | undefined, id: string) => all?.[id] || EMPTY;

function patch(id: string, fn: (s: ItemStats) => ItemStats) {
  queryClient.setQueriesData<Record<string, ItemStats>>({ queryKey: ['items', 'stats'] }, (cur) => (cur && cur[id] ? { ...cur, [id]: fn(cur[id]) } : cur));
}

export async function toggleItemLike(kind: ItemKind, key: string, s: ItemStats) {
  const id = itemId(kind, key);
  const on = !s.liked;
  patch(id, (x) => ({ ...x, liked: on, likes: Math.max(0, x.likes + (on ? 1 : -1)) }));
  try {
    const d = await api<{ likes: number; liked: boolean }>(`/api/app/items/${kind}/${encodeURIComponent(key)}/like`, { on });
    patch(id, (x) => ({ ...x, likes: d.likes, liked: d.liked }));
  } catch (e) { patch(id, () => s); throw e; }
}

export const useItemComments = (kind: ItemKind, key: string) => useQuery({
  queryKey: ['items', 'comments', kind, key], staleTime: 10_000,
  queryFn: () => api<{ comments: Comment[] }>(`/api/app/items/${kind}/${encodeURIComponent(key)}/comments`).then((d) => d.comments),
});

export async function addItemComment(kind: ItemKind, key: string, text: string) {
  const d = await api<{ comment: Comment }>(`/api/app/items/${kind}/${encodeURIComponent(key)}/comments`, { text });
  queryClient.setQueryData<Comment[]>(['items', 'comments', kind, key], (cur) => [...(cur || []), d.comment]);
  patch(itemId(kind, key), (x) => ({ ...x, comments: x.comments + 1 }));
  return d.comment;
}

/** «Поделиться в профиле»: пост-ссылка на новость или событие на моей стене. */
export async function shareItem(it: ItemRef, text = '') {
  const d = await api<{ post: Post }>(`/api/app/items/${it.kind}/${encodeURIComponent(it.key)}/share`,
    { title: it.title, url: it.url, img: it.img, text });
  patch(itemId(it.kind, it.key), (x) => ({ ...x, shared: true, shares: x.shares + 1 }));
  feedChanged();
  return d.post;
}
