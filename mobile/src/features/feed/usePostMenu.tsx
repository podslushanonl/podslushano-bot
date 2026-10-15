import { router } from 'expo-router';
import { useState } from 'react';
import { useAuth } from '@/api/auth';
import { removeOwn, report, routeForError } from '@/api/community';
import { feedChanged, Post } from '@/api/feed';
import { blockPerson } from '@/api/social';
import { ActionSheet, handle, SheetAction, useToast } from '@/ui';

/** Меню «⋯» у поста: своё — удалить; чужое — пожаловаться или заблокировать автора. */
export function usePostMenu(onDeleted?: (p: Post) => void) {
  const { user } = useAuth();
  const toast = useToast();
  const [menu, setMenu] = useState<Post | null>(null);
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); };
  const actions = (p: Post): SheetAction[] => p.mine
    ? [{ title: 'Удалить пост', icon: 'trash', danger: true, onPress: () => removeOwn('post', p.id).then(() => { feedChanged(); onDeleted?.(p); toast('Пост удалён'); }).catch(fail) }]
    : [
        { title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => report('post', p.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) },
        { title: `Заблокировать: ${handle(p.author)}`, icon: 'block', onPress: () => blockPerson(p.author.id).then(() => { feedChanged(); toast('Посты этого автора скрыты'); }).catch(fail) },
      ];
  return {
    openMenu: (p: Post) => (user ? setMenu(p) : router.push('/login')),
    sheet: <ActionSheet visible={!!menu} actions={menu ? actions(menu) : []} onClose={() => setMenu(null)} />,
  };
}
