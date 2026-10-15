import { useQuery } from '@tanstack/react-query';
import type { Person } from './social';
import { api, upload } from './client';
import { queryClient } from './query';

import type { PostAuthor } from './feed';

/** Пост на наклейке истории-репоста; null — пост удалён или больше недоступен. */
export type StoryPost = { id: number; text: string; author: PostAuthor; photo: string; ratio: number; at: string } | null;
export type StoryItem = {
  id: number; url: string; kind: 'photo' | 'video' | 'post'; at: string; my_reaction: string;
  caption: string; bg: string; post?: StoryPost;
};
export type StoryGroup = { user: Person; items: StoryItem[]; mine: boolean };

export const useStories = (enabled: boolean) => useQuery({
  queryKey: ['me', 'stories'], enabled, staleTime: 60_000,
  queryFn: () => api<{ groups: StoryGroup[]; reactions: string[] }>('/api/app/stories'),
});

export async function addStory(file: { uri: string; name: string; type: string }, caption = '') {
  await upload('/api/app/stories', file, { caption });
  queryClient.invalidateQueries({ queryKey: ['me', 'stories'] });
}

/** Репост поста в свою историю: наклейка на градиенте bg (ключ из STORY_BG). */
export async function sharePostToStory(postId: number, bg: string, caption = '') {
  await api('/api/app/stories/share', { post_id: postId, bg, caption });
  queryClient.invalidateQueries({ queryKey: ['me', 'stories'] });
}

/** Фоны историй-репостов (ключи — как на сервере, utils/stories.BACKGROUNDS). */
export const STORY_BG: Record<string, [string, string, string]> = {
  sunset: ['#FF3D6E', '#FF7A1A', '#FFC93C'],
  ocean: ['#0F4C81', '#1E88E5', '#5ED6E8'],
  forest: ['#0B3D2E', '#1E7F55', '#8BD17C'],
  night: ['#0B0D1A', '#2A1F5C', '#6A3FB5'],
  peach: ['#FF9A8B', '#FF6A88', '#FF99AC'],
  grape: ['#4A00E0', '#8E2DE2', '#D16BA5'],
};
export const storyGradient = (bg: string) => {
  const [a, b, c] = STORY_BG[bg] || STORY_BG.sunset;
  return `linear-gradient(160deg, ${a} 0%, ${b} 55%, ${c} 100%)`;
};

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
