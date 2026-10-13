import { useCallback, useEffect, useState } from 'react';
import { Msg, posts } from './community';

// Посты сообщества для ленты; после публикации лента обновляется сама
const listeners = new Set<() => void>();
export const notifyPostsChanged = () => listeners.forEach((l) => l());

export function usePosts() {
  const [list, setList] = useState<Msg[]>([]);
  const load = useCallback(() => { posts().then(setList).catch(() => {}); }, []);
  useEffect(() => {
    const t = setTimeout(load, 0);
    listeners.add(load);
    return () => { clearTimeout(t); listeners.delete(load); };
  }, [load]);
  return { posts: list, reload: load, setPosts: setList };
}
