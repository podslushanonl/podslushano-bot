import { InfiniteData, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api, BOT } from './client';
import { queryClient } from './query';

export type PostAuthor = { id: number; name: string; city: string; avatar?: string };
export type Share = { kind: 'news' | 'event'; key: string; title: string; url: string; img: string };
export type RepostOf = { id: number; deleted: true } | { id: number; deleted?: false; text: string; at: string; city: string; author: PostAuthor; photos: string[] };
export type Post = {
  id: number; text: string; at: string; city: string; country: string; author: PostAuthor; mine: boolean;
  photos: string[]; likes: number; liked: boolean; comments: number; reposts: number; repost: RepostOf | null;
  /** Я уже сделал репост (для репоста — его оригинала). */
  reposted: boolean; share: Share | null;
};
export type Comment = { id: number; text: string; at: string; author: PostAuthor; mine: boolean };
/** all — все; friends — друзья и я; near — моя страна (можно сузить до города). */
export type Scope = 'all' | 'friends' | 'near';
type Page = { posts: Post[]; more: boolean };

export const MAX_POST_PHOTOS = 4;
export const postPhoto = (path: string) => BOT + path;

/** Для «Рядом» страна передаётся явно и входит в ключ кэша: после смены страны лента обновится сама. */
export const useFeed = (scope: Scope, opts: { city?: string; country?: string; enabled?: boolean } = {}) => useInfiniteQuery({
  queryKey: ['feed', scope, scope === 'near' ? opts.country || '' : '', opts.city || ''], enabled: opts.enabled ?? true, staleTime: 20_000,
  initialPageParam: 0,
  queryFn: ({ pageParam }) => api<Page>(`/api/app/posts?scope=${scope}`
    + (scope === 'near' && opts.country ? `&country=${encodeURIComponent(opts.country)}` : '')
    + (opts.city ? `&city=${encodeURIComponent(opts.city)}` : '') + (pageParam ? `&before=${pageParam}` : '')),
  getNextPageParam: (last: Page) => (last.more && last.posts.length ? last.posts[last.posts.length - 1].id : undefined),
});
export const feedPosts = (d?: InfiniteData<Page>) => (d?.pages || []).flatMap((p) => p.posts);

/** Стена пользователя: его посты и репосты. */
export const useWall = (userId: number, enabled = true) => useInfiniteQuery({
  queryKey: ['feed', 'wall', userId], enabled: enabled && userId > 0, staleTime: 20_000, initialPageParam: 0,
  queryFn: ({ pageParam }) => api<Page>(`/api/app/user/${userId}/posts${pageParam ? `?before=${pageParam}` : ''}`),
  getNextPageParam: (last: Page) => (last.more && last.posts.length ? last.posts[last.posts.length - 1].id : undefined),
});

export const usePost = (id: number) => useQuery({
  queryKey: ['post', id], enabled: id > 0, staleTime: 10_000,
  queryFn: () => api<{ post: Post; comments: Comment[] }>(`/api/app/posts/${id}`),
});

/** Пост изменился (лайк, комментарий): правим его во всех загруженных лентах, профилях и на экране поста. */
export function patchPost(id: number, fn: (p: Post) => Post) {
  queryClient.setQueriesData<InfiniteData<Page>>({ queryKey: ['feed'] }, (d) => d && {
    ...d, pages: d.pages.map((pg) => ({ ...pg, posts: pg.posts.map((p) => (p.id === id ? fn(p) : p)) })),
  });
  queryClient.setQueryData<{ post: Post; comments: Comment[] }>(['post', id], (d) => d && { ...d, post: fn(d.post) });
  queryClient.setQueriesData<any>({ queryKey: ['me', 'user'] }, (d: any) => d?.posts && {
    ...d, posts: d.posts.map((p: Post) => (p.id === id ? fn(p) : p)),
  });
}

export const feedChanged = () => {
  queryClient.invalidateQueries({ queryKey: ['feed'] });
  queryClient.invalidateQueries({ queryKey: ['me', 'user'] });
};

export const createPost = (body: { text: string; photos?: string[]; repost_of?: number }) =>
  api<{ post: Post }>('/api/app/posts', body).then((d) => d.post);

export async function toggleLike(p: Post) {
  const on = !p.liked;
  patchPost(p.id, (x) => ({ ...x, liked: on, likes: Math.max(0, x.likes + (on ? 1 : -1)) }));
  try {
    const d = await api<{ likes: number; liked: boolean }>(`/api/app/posts/${p.id}/like`, { on });
    patchPost(p.id, (x) => ({ ...x, liked: d.liked, likes: d.likes }));
  } catch (e) {
    patchPost(p.id, (x) => ({ ...x, liked: p.liked, likes: p.likes }));
    throw e;
  }
}

/** Репост в один тап на свою стену (on=false — убрать свой репост). */
export async function setRepost(p: Post, on: boolean) {
  const target = p.repost && !p.repost.deleted ? p.repost.id : p.id;
  const d = await api<{ reposts: number; reposted: boolean; original: number }>(`/api/app/posts/${target}/repost`, { on });
  const apply = (x: Post) => ((x.id === d.original || (x.repost && x.repost.id === d.original))
    ? { ...x, reposted: d.reposted, reposts: x.id === d.original ? d.reposts : x.reposts } : x);
  queryClient.setQueriesData<InfiniteData<Page>>({ queryKey: ['feed'] }, (q) => q && {
    ...q, pages: q.pages.map((pg) => ({ ...pg, posts: pg.posts.map(apply) })),
  });
  patchPost(d.original, (x) => ({ ...x, reposted: d.reposted, reposts: d.reposts }));
  feedChanged();
  return d.reposted;
}

export async function addComment(postId: number, text: string) {
  const d = await api<{ comment: Comment }>(`/api/app/posts/${postId}/comments`, { text });
  queryClient.setQueryData<{ post: Post; comments: Comment[] }>(['post', postId], (cur) => cur && {
    ...cur, comments: [...cur.comments, d.comment],
  });
  patchPost(postId, (x) => ({ ...x, comments: x.comments + 1 }));
  return d.comment;
}
