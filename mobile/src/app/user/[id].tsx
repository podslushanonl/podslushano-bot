import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { acceptFriend, addFriend, blockPerson, Relation, removeFriend, startChat, unblockPerson, useProfile } from '@/api/social';
import { PostCard } from '@/features/feed/cards';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { ActionSheet, Avatar, Button, Empty, IconButton, PageScreen, Skeleton, Txt, useToast } from '@/ui';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const since = (d: string) => { const [y, m] = d.split('-').map(Number); return y && m ? `с ${MONTHS[m - 1]} ${y}` : ''; };
const friendsWord = (n: number) => (n % 10 === 1 && n % 100 !== 11 ? 'друг' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'друга' : 'друзей');

export default function UserProfile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const uid = Number(id);
  const toast = useToast();
  const { user: me, ready } = useAuth();
  const q = useProfile(uid, !!me);
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const { openMenu, sheet: postSheet } = usePostMenu();
  const p = q.data;

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast(ok); } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };
  const write = () => run(async () => {
    const d = await startChat(uid);
    router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
  });

  if (ready && !me) {
    return (
      <PageScreen title="Профиль">
        <Empty icon="person" title="Профили видны участникам" text="Войдите, чтобы смотреть профили, добавлять в друзья и писать."
          action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
      </PageScreen>
    );
  }

  // Главная кнопка: «Написать» — только друзьям; остальным вместо неё — «Добавить в друзья»
  const actions: Record<Relation, React.ReactNode> = {
    self: <Button title="Изменить профиль" kind="secondary" icon="edit" onPress={() => router.push('/profile-edit')} />,
    friends: <Button title="Написать сообщение" kind="primary" icon="bubble" loading={busy} onPress={write} />,
    none: <Button title="Добавить в друзья" kind="accent" icon="plus" loading={busy} onPress={() => run(() => addFriend(uid), 'Заявка отправлена')} />,
    outgoing: <Button title="Заявка отправлена · отменить" kind="secondary" icon="check" loading={busy} onPress={() => run(() => removeFriend(uid), 'Заявка отменена')} />,
    incoming: (
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Button title="Принять заявку" kind="accent" icon="check" loading={busy} style={{ flex: 1 }} onPress={() => run(() => acceptFriend(uid), 'Теперь вы друзья')} />
        <Button title="Отклонить" kind="secondary" full={false} onPress={() => run(() => removeFriend(uid))} />
      </View>
    ),
    blocked: <Button title="Разблокировать" kind="secondary" icon="block" loading={busy} onPress={() => run(() => unblockPerson(uid), 'Пользователь разблокирован')} />,
    unavailable: <Txt v="callout" tone="muted" center>Пользователь ограничил общение с вами.</Txt>,
  };

  return (
    <PageScreen title={p?.user.name || 'Профиль'} refreshing={q.isRefetching} onRefresh={() => q.refetch()}
      right={p && !['self', 'blocked'].includes(p.relation) ? <IconButton icon="more" label="Действия" onPress={() => setMenu(true)} /> : null}>
      {q.isLoading || !ready ? (
        <View style={{ alignItems: 'center', gap: 12 }}><Skeleton w={96} h={96} r={48} /><Skeleton w="50%" h={24} /><Skeleton h={54} r={27} /></View>
      ) : !p ? (
        <Empty icon="person" title="Профиль не найден" text={(q.error as any)?.message} />
      ) : (
        <>
          <View style={{ alignItems: 'center', gap: 8 }}>
            <Avatar name={p.user.name} id={p.user.id} size={96} />
            <Txt v="title1" center>{p.user.name}</Txt>
            <Txt v="subhead" tone="muted" center>{[p.user.city, p.user.country].filter(Boolean).join(', ')}</Txt>
            <Txt v="footnote" center>{[`${p.friends} ${friendsWord(p.friends)}`, since(p.user.since) && `в podslushano ${since(p.user.since)}`].filter(Boolean).join(' · ')}</Txt>
          </View>
          {actions[p.relation]}
          {p.relation === 'incoming' ? <Txt v="footnote" center>{p.user.name} хочет добавить вас в друзья. Друзья могут писать друг другу в личные сообщения.</Txt> : null}
          {['none', 'outgoing'].includes(p.relation) ? <Txt v="footnote" center>Личные сообщения доступны друзьям. В общих чатах можно общаться со всеми.</Txt> : null}
          {p.posts.length ? (
            <View style={{ gap: 10 }}>
              <Txt v="overline" style={{ marginLeft: 6 }}>Посты</Txt>
              {p.posts.map((x) => <PostCard key={x.id} p={x} onMenu={() => openMenu(x)} />)}
            </View>
          ) : null}
          {postSheet}
          <ActionSheet visible={menu} onClose={() => setMenu(false)} actions={[
            ...(p.relation === 'friends' ? [{ title: 'Удалить из друзей', icon: 'people' as const, onPress: () => run(() => removeFriend(uid), 'Удалён из друзей') }] : []),
            { title: `Заблокировать: ${p.user.name}`, icon: 'block', danger: true, onPress: () => run(() => blockPerson(uid), 'Пользователь заблокирован') },
          ]} />
        </>
      )}
    </PageScreen>
  );
}
