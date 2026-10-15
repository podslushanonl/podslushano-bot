import { router } from 'expo-router';
import { ReactNode, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { feedPosts, Post, postPhoto, useWall } from '@/api/feed';
import { acceptFriend, addFriend, blockPerson, removeFriend, startChat, unblockPerson, useProfile } from '@/api/social';
import { FeedDivider, FeedPost } from '@/features/feed/FeedItems';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { useTheme } from '@/theme';
import { ActionSheet, Avatar, BackButton, Button, Empty, Icon, IconButton, Img, Skeleton, TAB_SPACE, Tap, TopBar, Txt, useScrollY, useToast } from '@/ui';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const since = (d: string) => { const [y, m] = (d || '').split('-').map(Number); return y && m ? `с ${MONTHS[m - 1]} ${y}` : ''; };
const plural = (n: number, [one, few, many]: [string, string, string]) =>
  n % 10 === 1 && n % 100 !== 11 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;

function Stat({ n, label, onPress }: { n: number; label: string; onPress?: () => void }) {
  return (
    <Tap onPress={onPress} disabled={!onPress} scaleTo={0.95} style={{ alignItems: 'flex-start', gap: 1 }} accessibilityLabel={`${n} ${label}`}>
      <Txt v="title3" style={{ fontVariant: ['tabular-nums'] }}>{n}</Txt>
      <Txt v="footnote">{label}</Txt>
    </Tap>
  );
}

function Tabs({ value, onChange }: { value: 'posts' | 'photos'; onChange: (v: 'posts' | 'photos') => void }) {
  const { c } = useTheme();
  const tab = (k: 'posts' | 'photos', icon: 'text' | 'grid', title: string) => (
    <Tap key={k} onPress={() => onChange(k)} scaleTo={0.97} accessibilityRole="tab" accessibilityState={{ selected: value === k }}
      style={{ flex: 1, alignItems: 'center', paddingVertical: 12, gap: 6, borderBottomWidth: 2, borderBottomColor: value === k ? c.ink : 'transparent' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Icon name={icon} size={17} color={value === k ? c.ink : c.faint} />
        <Txt v="subhead" color={value === k ? c.ink : c.faint} style={{ fontFamily: 'Onest_700Bold' }}>{title}</Txt>
      </View>
    </Tap>
  );
  return (
    <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.line, marginHorizontal: -20, paddingHorizontal: 20 }}>
      {tab('posts', 'text', 'Публикации')}{tab('photos', 'grid', 'Фото')}
    </View>
  );
}

/** Сетка фото из публикаций человека — как вкладка «Фото» в соцсетях. */
function PhotoGrid({ posts }: { posts: Post[] }) {
  const items = posts.flatMap((p) => p.photos.map((ph) => ({ p, ph })));
  if (!items.length) return <Empty icon="photo" title="Пока без фото" text="Фото из публикаций появятся здесь." />;
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 2, marginHorizontal: -20 }}>
      {items.map(({ p, ph }) => (
        <Tap key={ph} onPress={() => router.push({ pathname: '/post/[id]', params: { id: String(p.id) } })} scaleTo={0.97} style={{ width: '33.1%', aspectRatio: 1 }}>
          <Img source={postPhoto(ph)} style={{ width: '100%', height: '100%' }} />
        </Tap>
      ))}
    </View>
  );
}

/** Страница человека в стиле соцсети: шапка с фото и счётчиками, действия, вкладки «Публикации / Фото». */
export function ProfileView({ userId, own }: { userId: number; own?: boolean }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { y, onScroll } = useScrollY();
  const toast = useToast();
  const { user: me } = useAuth();
  const q = useProfile(userId, !!me);
  const wall = useWall(userId, !!me);
  const posts = feedPosts(wall.data);
  const [tab, setTab] = useState<'posts' | 'photos'>('posts');
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const { openMenu, sheet } = usePostMenu();
  const p = q.data;
  const u = own && me ? { ...p?.user, ...me, id: me.id, since: p?.user.since || '' } : p?.user;
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast(ok); } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };
  const write = () => run(async () => {
    const d = await startChat(userId);
    router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
  });

  let actions: ReactNode = null;
  if (own) {
    actions = (
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Button title="Редактировать" kind="secondary" size="s" icon="edit" style={{ flex: 1 }} onPress={() => router.push('/profile-edit')} />
        <Button title="Новый пост" kind="primary" size="s" icon="plus" style={{ flex: 1 }} onPress={() => router.push('/new-post')} />
      </View>
    );
  } else if (p) {
    const rel = p.relation;
    actions = rel === 'friends' ? (
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Button title="Написать" kind="primary" size="s" icon="bubble" loading={busy} style={{ flex: 1 }} onPress={write} />
        <Button title="В друзьях" kind="secondary" size="s" icon="check" style={{ flex: 1 }} onPress={() => setMenu(true)} />
      </View>
    ) : rel === 'incoming' ? (
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Button title="Принять заявку" kind="accent" size="s" icon="check" loading={busy} style={{ flex: 1 }} onPress={() => run(() => acceptFriend(userId), 'Теперь вы друзья')} />
        <Button title="Отклонить" kind="secondary" size="s" style={{ flex: 1 }} onPress={() => run(() => removeFriend(userId))} />
      </View>
    ) : rel === 'outgoing' ? (
      <Button title="Заявка отправлена" kind="secondary" size="s" icon="check" loading={busy} onPress={() => run(() => removeFriend(userId), 'Заявка отменена')} />
    ) : rel === 'blocked' ? (
      <Button title="Разблокировать" kind="secondary" size="s" loading={busy} onPress={() => run(() => unblockPerson(userId), 'Пользователь разблокирован')} />
    ) : rel === 'unavailable' ? (
      <Txt v="callout" tone="muted">Пользователь ограничил общение с вами.</Txt>
    ) : (
      <Button title="Добавить в друзья" kind="accent" size="s" icon="plus" loading={busy} onPress={() => run(() => addFriend(userId), 'Заявка отправлена')} />
    );
  }

  const header = (
    <View style={{ gap: 16 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 18 }}>
        <View style={{ padding: 3, borderRadius: 60, borderWidth: 2, borderColor: c.accent }}>
          <Avatar name={u?.name || '·'} id={userId} uri={u?.avatar} size={92} />
        </View>
        <View style={{ flex: 1, flexDirection: 'row', justifyContent: 'space-around' }}>
          <Stat n={p?.posts ?? posts.length} label={plural(p?.posts ?? posts.length, ['публикация', 'публикации', 'публикаций'])} onPress={() => setTab('posts')} />
          <Stat n={p?.friends ?? 0} label={plural(p?.friends ?? 0, ['друг', 'друга', 'друзей'])} onPress={own ? () => router.push('/friends') : undefined} />
        </View>
      </View>
      <View style={{ gap: 4 }}>
        <Txt v="title2">{u?.name || (own ? 'Без имени' : '')}</Txt>
        {u?.city || u?.country ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
            <Icon name="location" size={14} color={c.muted} />
            <Txt v="subhead" tone="muted">{[u?.city, u?.country].filter(Boolean).join(', ')}</Txt>
          </View>
        ) : null}
        {u?.bio ? <Txt v="callout" tone="ink" style={{ marginTop: 4 }}>{u.bio}</Txt>
          : own ? <Tap onPress={() => router.push('/profile-edit')}><Txt v="callout" tone="accent">Добавить статус</Txt></Tap> : null}
        {since(u?.since || '') ? <Txt v="footnote" color={c.faint} style={{ marginTop: 2 }}>В podslushano {since(u?.since || '')}</Txt> : null}
      </View>
      {actions}
    </View>
  );

  const more = wall.hasNextPage
    ? <Button title="Показать ещё" kind="secondary" size="s" loading={wall.isFetchingNextPage} onPress={() => wall.fetchNextPage()} /> : null;
  const body = !me ? null : wall.isLoading ? (
    <View style={{ gap: 18, paddingTop: 16 }}>{[0, 1].map((i) => <View key={i} style={{ gap: 10 }}><Skeleton w="60%" /><Skeleton h={120} r={16} /></View>)}</View>
  ) : tab === 'photos' ? (
    <View style={{ paddingTop: 2, gap: 12 }}>
      <PhotoGrid posts={posts} />
      {more}
    </View>
  ) : posts.length ? (
    <View>
      {posts.map((x, i) => (
        <View key={x.id}>
          {i ? <FeedDivider /> : null}
          <FeedPost p={x} onMenu={() => openMenu(x)} />
        </View>
      ))}
      {more}
    </View>
  ) : (
    <Empty icon="text" title={own ? 'Здесь будут ваши публикации' : 'Пока нет публикаций'}
      text={own ? 'Расскажите, что нового, поделитесь фото или сделайте репост интересного из ленты.' : undefined}
      action={own ? <Button title="Написать первый пост" kind="primary" onPress={() => router.push('/new-post')} /> : undefined} />
  );

  return (
    <View style={{ flex: 1, backgroundColor: c.bgElevated }}>
      <ScrollView onScroll={onScroll} scrollEventThrottle={16} contentInsetAdjustmentBehavior="never"
        refreshControl={<RefreshControl refreshing={q.isRefetching || wall.isRefetching} onRefresh={() => { q.refetch(); wall.refetch(); }} tintColor={c.accent} />}
        contentContainerStyle={{ paddingTop: insets.top + 64, paddingHorizontal: 20, paddingBottom: (own ? TAB_SPACE : 40) + insets.bottom, gap: 20 }}>
        {!me ? (
          <Empty icon="person" title="Профили видны участникам" text="Войдите, чтобы смотреть профили, добавлять в друзья и писать."
            action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
        ) : q.isLoading && !u ? (
          <View style={{ gap: 14 }}><Skeleton w={98} h={98} r={49} /><Skeleton w="50%" h={24} /><Skeleton h={40} r={20} /></View>
        ) : !u ? (
          <Empty icon="person" title="Профиль не найден" text={(q.error as any)?.message} />
        ) : (
          <>
            {header}
            <Tabs value={tab} onChange={setTab} />
            {body}
          </>
        )}
      </ScrollView>
      <TopBar y={y} title={u?.name} left={own ? undefined : <BackButton />}
        right={own ? <IconButton icon="settings" label="Настройки" onPress={() => router.push('/settings')} />
          : p && !['blocked'].includes(p.relation) ? <IconButton icon="more" label="Действия" onPress={() => setMenu(true)} /> : null} />
      {sheet}
      {p && !own ? (
        <ActionSheet visible={menu} onClose={() => setMenu(false)} actions={[
          ...(p.relation === 'friends' ? [{ title: 'Удалить из друзей', icon: 'people' as const, onPress: () => run(() => removeFriend(userId), 'Удалён из друзей') }] : []),
          { title: `Заблокировать: ${p.user.name}`, icon: 'block' as const, danger: true, onPress: () => run(() => blockPerson(userId), 'Пользователь заблокирован') },
        ]} />
      ) : null}
    </View>
  );
}
