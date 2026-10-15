import { useQuery } from '@tanstack/react-query';
import type { Person } from './social';
import { api, upload } from './client';
import { queryClient } from './query';

export type StoryItem = { id: number; url: string; kind: 'photo' | 'video'; at: string; my_reaction: string };
export type StoryGroup = { user: Person; items: StoryItem[]; mine: boolean };

export const useStories = (enabled: boolean) => useQuery({
  queryKey: ['me', 'stories'], enabled, staleTime: 60_000,
  queryFn: () => api<{ groups: StoryGroup[]; reactions: string[] }>('/api/app/stories'),
});

export async function addStory(file: { uri: string; name: string; type: string }) {
  await upload('/api/app/stories', file);
  queryClient.invalidateQueries({ queryKey: ['me', 'stories'] });
}

export async function reactStory(id: number, emoji: string) {
  await api(`/api/app/stories/${id}/react`, { emoji });
  queryClient.setQueryData<{ groups: StoryGroup[]; reactions: string[] }>(['me', 'stories'], (d) => d && {
    ...d, groups: d.groups.map((g) => ({ ...g, items: g.items.map((s) => (s.id === id ? { ...s, my_reaction: emoji } : s)) })),
  });
}

export async function deleteStory(id: number) {
  await api(`/api/app/stories/${id}/delete`, {});
  queryClient.invalidateQueries({ queryKey: ['me', 'stories'] });
}
