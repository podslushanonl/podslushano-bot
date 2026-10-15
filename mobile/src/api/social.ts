import { useQuery } from '@tanstack/react-query';
import type { Presence } from '@/lib/presence';
import { api } from './client';
import { queryClient } from './query';

/** Отношение ко мне: self — это я; incoming — он позвал меня; blocked — я заблокировал; unavailable — меня заблокировали. */
export type Relation = 'self' | 'none' | 'outgoing' | 'incoming' | 'friends' | 'blocked' | 'unavailable';
export type Person = { id: number; name: string; city: string; country: string; avatar: string; bio: string; relation?: Relation; verified?: boolean; cover?: string };
export type Profile = {
  user: Person & { since: string }; relation: Relation; friends: number; posts: number; can_message: boolean;
  /** private — аккаунт закрыт; locked — мне его публикации не видны (мы не друзья). */
  private?: boolean; locked?: boolean;
  presence?: Presence;
};
export type FriendLists = { friends: Person[]; incoming: Person[]; outgoing: Person[]; blocked: Person[] };

export const useProfile = (id: number, enabled = true) => useQuery({
  queryKey: ['me', 'user', id], enabled: enabled && id > 0, staleTime: 15_000,
  queryFn: () => api<Profile>(`/api/app/user/${id}`),
});
export const useFriends = (enabled: boolean) => useQuery({
  queryKey: ['me', 'friends'], enabled, staleTime: 15_000,
  queryFn: () => api<FriendLists>('/api/app/friends'),
});
export const useSearchPeople = (q: string, country: string) => useQuery({
  queryKey: ['me', 'people', q, country], enabled: q.trim().length >= 2, staleTime: 30_000,
  queryFn: () => api<{ users: Person[] }>(`/api/app/users?q=${encodeURIComponent(q.trim())}${country ? `&country=${encodeURIComponent(country)}` : ''}`).then((d) => d.users),
});

/** Действие с человеком → новое отношение; списки друзей и профиль обновляются. */
async function act(path: string, userId: number): Promise<Relation> {
  const d = await api<{ relation: Relation }>(`/api/app/friends/${path}`, { user_id: userId });
  friendsChanged(userId);
  return d.relation;
}
export function friendsChanged(userId?: number) {
  queryClient.invalidateQueries({ queryKey: ['me', 'friends'] });
  queryClient.invalidateQueries({ queryKey: ['me', 'people'] });
  if (userId) queryClient.invalidateQueries({ queryKey: ['me', 'user', userId] });
}
export const addFriend = (id: number) => act('request', id);
export const acceptFriend = (id: number) => act('accept', id);
export const removeFriend = (id: number) => act('remove', id);
export const blockPerson = (id: number) => act('block', id);
export const unblockPerson = (id: number) => act('unblock', id);
/** Личный диалог с другом (сервер откажет с 403, если вы не друзья). */
export const startChat = (userId: number) => api<{ id: number }>('/api/app/dm/start', { user_id: userId });
