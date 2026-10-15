import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api, upload } from './client';
import type { Comment, PostAuthor } from './feed';
import { queryClient } from './query';

export type Clip = {
  id: number; url: string; text: string; at: string; author: PostAuthor; mine: boolean;
  likes: number; liked: boolean; saved: boolean; comments: number;
};
type Page = { clips: Clip[]; more: boolean };

// Ключ начинается с 'me': при выходе или смене аккаунта лента сбрасывается (лайки, закладки и видео закрытых друзей — личные)
export const PULSE_KEY = ['me', 'pulse'] as const;
export const usePulse = () => useInfiniteQuery({
  queryKey: PULSE_KEY, initialPageParam: 0, staleTime: 60_000,
  queryFn: ({ pageParam }) => api<Page>(`/api/app/pulse${pageParam ? `?before=${pageParam}` : ''}`),
  getNextPageParam: (last) => (last.more && last.clips.length ? last.clips[last.clips.length - 1].id : undefined),
});
/** Видео одного человека — вкладка Pulse в профиле. */
export const useUserClips = (userId: number, enabled = true) => useQuery({
  queryKey: ['me', 'pulse-user', userId], enabled: enabled && userId > 0, staleTime: 30_000,
  queryFn: () => api<{ clips: Clip[] }>(`/api/app/user/${userId}/pulse`).then((d) => d.clips),
});
export const useSavedClips = (enabled: boolean) => useQuery({
  queryKey: ['me', 'pulse-saved'], enabled, queryFn: () => api<{ clips: Clip[] }>('/api/app/pulse/saved').then((d) => d.clips),
});
export const useClipComments = (id: number) => useQuery({
  queryKey: ['pulse-comments', id], enabled: id > 0,
  queryFn: () => api<{ comments: Comment[] }>(`/api/app/pulse/${id}/comments`).then((d) => d.comments),
});

/** Меняет видео во всех кэшах — общая лента, видео в профилях, закладки (лайк, закладка, число комментариев):
 *  экран обновляется сразу, где бы ни было открыто видео. */
export function patchClip(id: number, fn: (c: Clip) => Clip) {
  const map = (list: Clip[]) => list.map((c) => (c.id === id ? fn(c) : c));
  queryClient.setQueryData<{ pages: Page[]; pageParams: unknown[] }>(PULSE_KEY, (d) =>
    d && { ...d, pages: d.pages.map((p) => ({ ...p, clips: map(p.clips) })) });
  queryClient.setQueriesData<Clip[]>({ queryKey: ['me', 'pulse-user'] }, (d) => d && map(d));
  queryClient.setQueriesData<Clip[]>({ queryKey: ['me', 'pulse-saved'] }, (d) => d && map(d));
}

/** После удаления или жалобы видео перечитываем везде, где оно могло быть. */
export function refreshClips() {
  for (const k of [PULSE_KEY, ['me', 'pulse-user'], ['me', 'pulse-saved']]) queryClient.invalidateQueries({ queryKey: k });
}

export async function toggleClip(c: Clip, what: 'like' | 'save') {
  const on = what === 'like' ? !c.liked : !c.saved;
  patchClip(c.id, (x) => (what === 'like' ? { ...x, liked: on, likes: x.likes + (on ? 1 : -1) } : { ...x, saved: on }));
  try {
    await api(`/api/app/pulse/${c.id}/${what}`, { on });
    if (what === 'save') queryClient.invalidateQueries({ queryKey: ['me', 'pulse-saved'] });
  } catch (e) {
    patchClip(c.id, () => c);
    throw e;
  }
}

export async function addClipComment(id: number, text: string) {
  const d = await api<{ comment: Comment }>(`/api/app/pulse/${id}/comments`, { text });
  queryClient.setQueryData<Comment[]>(['pulse-comments', id], (cur) => [...(cur || []), d.comment]);
  patchClip(id, (x) => ({ ...x, comments: x.comments + 1 }));
}

export async function uploadClip(file: { uri: string; name: string; type: string }, text: string) {
  const d = await upload<{ clip: Clip }>('/api/app/pulse', file, { text });
  queryClient.invalidateQueries({ queryKey: PULSE_KEY, exact: true });
  return d.clip;
}
