import { FlashList, FlashListRef } from '@shopify/flash-list';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { createElement, ReactNode, useRef, useState } from 'react';
import { Platform, Share, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { saveCover, useAuth } from '@/api/auth';
import { BOT, mediaUrl } from '@/api/client';
import { routeForError } from '@/api/community';
import { feedPosts, Post, useWall } from '@/api/feed';
import { Listing, shrinkForWeb, useUserListings } from '@/api/market';
import { Clip, useUserClips } from '@/api/pulse';
import { acceptFriend, addFriend, blockPerson, removeFriend, startChat, unblockPerson, useProfile } from '@/api/social';
import { FeedPost } from '@/features/feed/FeedItems';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { Tile } from '@/features/market/Tile';
import { plural } from '@/lib/format';
import { presenceLabel } from '@/lib/presence';
import { HAIRLINE, useTheme } from '@/theme';
import { ActionSheet, BackButton, Button, Empty, handle, Icon, IconButton, IconName, Img, Skeleton, TAB_SPACE, Tap, TopBar, Txt, useRefresh,
  useScrollY, useToast, UserAvatar, VerifiedBadge } from '@/ui';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const since = (d: string) => { const [y, m] = (d || '').split('-').map(Number); return y && m ? `с ${MONTHS[m - 1]} ${y}` : ''; };
type Tab = 'posts' | 'pulse' | 'market';
// Строки списка: пост целиком, ряд из трёх видео или ряд из двух объявлений — всё в одном FlashList
type Row = { k: 'post'; id: string; p: Post } | { k: 'clips'; id: string; items: Clip[] } | { k: 'items'; id: string; items: Listing[] };
const rows = <T,>(list: T[], n: number) => Array.from({ length: Math.ceil(list.length / n) }, (_, i) => list.slice(i * n, i * n + n));
const AVATAR = 104;

function Stat({ n, label, onPress }: { n: number; label: string; onPress?: () => void }) {
  const body = (
    <>
      <Txt v="title3" style={{ fontFamily: 'Onest_700Bold', fontVariant: ['tabular-nums'] }}>{n}</Txt>
      <Txt v="footnote" tone="muted">{label}</Txt>
    </>
  );
  const box = { alignItems: 'center', gap: 1, minWidth: 76 } as const;
  if (!onPress) return <View style={box} accessibilityLabel={`${n} ${label}`}>{body}</View>;
  return <Tap onPress={onPress} scaleTo={0.95} style={box} accessibilityLabel={`${n} ${label}`}>{body}</Tap>;
}

/** Вкладки профиля с иконками и подчёркиванием (как в VK и Instagram). */
function Tabs({ value, onChange }: { value: Tab; onChange: (v: Tab) => void }) {
  const { c } = useTheme();
  const items: [Tab, IconName, string][] = [['posts', 'grid', 'Публикации'], ['pulse', 'pulse', 'Pulse'], ['market', 'market', 'Барахолка']];
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: 'row', borderBottomWidth: HAIRLINE, borderBottomColor: c.line, backgroundColor: c.bg }}>
      {items.map(([k, icon, title]) => {
        const on = value === k;
        return (
          <Tap key={k} onPress={() => onChange(k)} scaleTo={0.97} haptic="select" accessibilityRole="tab" accessibilityLabel={title} accessibilityState={{ selected: on }}
            style={{ flex: 1, alignItems: 'center', paddingVertical: 12, borderBottomWidth: 2, borderBottomColor: on ? c.ink : 'transparent', marginBottom: -HAIRLINE }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Icon name={icon} size={17} color={on ? c.ink : c.faint} />
              <Txt v="subhead" color={on ? c.ink : c.faint} style={{ fontFamily: 'Onest_700Bold' }}>{title}</Txt>
            </View>
          </Tap>
        );
      })}
    </View>
  );
}

/** Плитка видео без плеера: в браузере — первый кадр (грузятся только метаданные, по мере прокрутки),
 *  в приложении — тёмная карточка с подписью. Плеер создаётся лишь когда видео открыли. */
function ClipTile({ clip, onPress, width }: { clip: Clip; onPress: () => void; width: number }) {
  return (
    <Tap onPress={onPress} scaleTo={0.97} accessibilityLabel={clip.text || 'Видео'} style={{ width, aspectRatio: 9 / 16, backgroundColor: '#1C1C1E', overflow: 'hidden' }}>
      {Platform.OS === 'web' ? createElement('video', {
        src: `${mediaUrl(clip.url)}#t=0.1`, preload: 'metadata', muted: true, playsInline: true, loading: 'lazy',
        style: { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', pointerEvents: 'none' },
      }) : (
        <View style={{ flex: 1, padding: 8, justifyContent: 'center', alignItems: 'center' }}>
          <Icon name="play" size={26} color="rgba(255,255,255,0.85)" />
          {clip.text ? <Txt v="caption" color="rgba(255,255,255,0.75)" numberOfLines={3} center style={{ marginTop: 6 }}>{clip.text}</Txt> : null}
        </View>
      )}
      <View pointerEvents="none" style={{ position: 'absolute', left: 6, bottom: 6, flexDirection: 'row', alignItems: 'center', gap: 3 }}>
        <Icon name="heartFill" filled size={13} color="#FFFFFF" />
        <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_700Bold', textShadowColor: 'rgba(0,0,0,0.6)', textShadowRadius: 3 }}>{clip.likes}</Txt>
      </View>
    </Tap>
  );
}

/** Закрытый аккаунт, мы не друзья: вместо публикаций — заглушка. */
function Locked() {
  const { c } = useTheme();
  return (
    <View style={{ alignItems: 'center', gap: 12, paddingVertical: 40, paddingHorizontal: 24 }}>
      <View style={{ width: 72, height: 72, borderRadius: 36, borderWidth: 1.5, borderColor: c.ink, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name="lock" thin size={32} color={c.ink} />
      </View>
      <Txt v="title3" center>Это закрытый аккаунт</Txt>
      <Txt v="callout" tone="muted" center>Добавьтесь в друзья, чтобы увидеть публикации</Txt>
    </View>
  );
}

/** Профиль в стиле VK / Instagram: обложка во всю ширину, круглый аватар поверх, имя с галочкой, вкладки
 *  «Публикации / Pulse / Барахолка». Одинаков для моего профиля и чужого (у чужого — дружба и сообщения). */
export function ProfileView({ userId, own }: { userId: number; own?: boolean }) {
  const { c, dark } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { y, onScroll } = useScrollY();
  const list = useRef<FlashListRef<Row>>(null);
  const toast = useToast();
  const { user: me } = useAuth();
  const q = useProfile(userId, !!me);
  const locked = !!q.data?.locked;
  const [tab, setTab] = useState<Tab>('posts');
  const wall = useWall(userId, !!me && !locked);
  const clips = useUserClips(userId, !!me && !locked && tab === 'pulse');
  const items = useUserListings(userId, !!me && tab === 'market');
  const refresh = useRefresh(list, () => Promise.all([q.refetch(), wall.refetch(), clips.refetch(), items.refetch()]), () => y.get() < 4);
  const posts = feedPosts(wall.data);
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const { openMenu, sheet } = usePostMenu();
  const p = q.data;
  const u = own && me ? { ...p?.user, ...me, id: me.id, since: p?.user.since || '' } : p?.user;
  const coverH = Math.round(Math.min(width, 640) / 2.6) + insets.top;
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast(ok); } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };
  const write = () => run(async () => {
    const d = await startChat(userId);
    router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
  });
  const changeCover = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.8, base64: true });
    const a = r.canceled ? null : r.assets?.[0];
    if (!a) return;
    run(async () => saveCover(a.base64 ? `data:image/jpeg;base64,${a.base64}` : await shrinkForWeb(a.uri)), 'Обложка обновлена');
  };

  let actions: ReactNode = null;
  if (own) {
    actions = (
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Button title="Редактировать" kind="secondary" size="s" icon="edit" style={{ flex: 1 }} onPress={() => router.push('/profile-edit')} />
        <Button title="Опубликовать" kind="accent" size="s" icon="plus" style={{ flex: 1 }} onPress={() => router.push('/new-post')} />
      </View>
    );
  } else if (p) {
    const rel = p.relation;
    actions = rel === 'friends' ? (
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Button title="Написать" kind="accent" size="s" icon="bubble" loading={busy} style={{ flex: 1 }} onPress={write} />
        <Button title="В друзьях" kind="secondary" size="s" icon="check" style={{ flex: 1 }} onPress={() => setMenu(true)} />
      </View>
    ) : rel === 'incoming' ? (
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Button title="Принять заявку" kind="accent" size="s" icon="check" loading={busy} style={{ flex: 1 }} onPress={() => run(() => acceptFriend(userId), 'Теперь вы друзья')} />
        <Button title="Отклонить" kind="secondary" size="s" style={{ flex: 1 }} onPress={() => run(() => removeFriend(userId))} />
      </View>
    ) : rel === 'outgoing' ? (
      <Button title="Заявка отправлена" kind="secondary" size="s" icon="check" loading={busy} onPress={() => run(() => removeFriend(userId), 'Заявка отменена')} />
    ) : rel === 'blocked' ? (
      <Button title="Разблокировать" kind="secondary" size="s" loading={busy} onPress={() => run(() => unblockPerson(userId), 'Пользователь разблокирован')} />
    ) : rel === 'unavailable' ? (
      <Txt v="callout" tone="muted" center>Пользователь ограничил общение с вами.</Txt>
    ) : (
      <Button title="Добавить в друзья" kind="accent" size="s" icon="plus" loading={busy} onPress={() => run(() => addFriend(userId), 'Заявка отправлена')} />
    );
  }

  const presence = !own ? presenceLabel(p?.presence) : '';
  const place = [u?.city, u?.country].filter(Boolean).join(', ');
  const header = u ? (
    <View>
      {/* Обложка во всю ширину; без своей — фирменный градиент */}
      <View style={{ height: coverH, backgroundColor: c.bgSunken, overflow: 'hidden' }}>
        {u.cover ? <Img source={mediaUrl(u.cover)} contentFit="cover" style={{ width: '100%', height: '100%' }} />
          : <View style={{ flex: 1, [Platform.OS === 'web' ? 'backgroundImage' : 'experimental_backgroundImage']:
              dark ? 'linear-gradient(135deg, #2A1408 0%, #6B2A0B 55%, #FF6A1A 100%)' : 'linear-gradient(135deg, #FFE1CC 0%, #FFB27A 50%, #FF6A1A 100%)' } as any} />}
        {own ? (
          <Tap onPress={changeCover} scaleTo={0.9} accessibilityLabel={u.cover ? 'Сменить обложку' : 'Добавить обложку'}
            style={{ position: 'absolute', right: 14, bottom: 26, flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, height: 32,
              borderRadius: 16, backgroundColor: 'rgba(0,0,0,0.45)' }}>
            <Icon name="camera2" size={15} color="#FFFFFF" />
            <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_600SemiBold' }}>{u.cover ? 'Обложка' : 'Добавить обложку'}</Txt>
          </Tap>
        ) : null}
      </View>

      {/* Карточка поверх обложки с аватаром по центру */}
      <View style={{ marginTop: -20, paddingHorizontal: 16, paddingBottom: 16, backgroundColor: c.bg,
        borderTopLeftRadius: 24, borderTopRightRadius: 24, alignItems: 'center', gap: 4 }}>
        {/* Тонкая рамка цвета фона отделяет аватар от обложки (в тёмной теме — тёмная, в светлой — белая) */}
        <View style={{ marginTop: -AVATAR / 2 - 3, borderWidth: 3, borderColor: c.bg, borderRadius: AVATAR, backgroundColor: c.bg }}>
          <UserAvatar u={{ ...u, id: userId, name: u.name || '·' }} size={AVATAR} />
          {!own && p?.presence?.online ? (
            <View style={{ position: 'absolute', right: 6, bottom: 6, width: 18, height: 18, borderRadius: 9, backgroundColor: '#34C759', borderWidth: 3, borderColor: c.bg }} />
          ) : null}
        </View>
        {/* Настоящее имя — заголовок только здесь, в профиле; везде остальное — @username */}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 6, maxWidth: '92%' }}>
          <Txt v="title2" numberOfLines={1} style={{ flexShrink: 1, fontFamily: 'Onest_700Bold' }}>{u.name || (own ? 'Без имени' : '')}</Txt>
          {u.verified ? <VerifiedBadge size={21} /> : null}
          {(own ? me?.is_private : p?.private) ? <Icon name="lock" size={16} color={c.muted} /> : null}
        </View>
        {u.username ? <Txt v="subhead" tone="muted" selectable>@{u.username}</Txt> : null}
        {u.bio ? <Txt v="callout" tone="ink" center style={{ paddingHorizontal: 12 }}>{u.bio}</Txt>
          : own ? <Tap onPress={() => router.push('/profile-edit')}><Txt v="callout" tone="accent">Добавить статус</Txt></Tap> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center', gap: 10, marginTop: 2 }}>
          {place ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Icon name="location" size={13} color={c.muted} />
              <Txt v="footnote" tone="muted">{place}</Txt>
            </View>
          ) : null}
          {presence ? <Txt v="footnote" color={p?.presence?.online ? c.accentText : c.faint}>{presence}</Txt> : null}
        </View>
        {since(u.since || '') ? <Txt v="caption" color={c.faint}>В podslushano {since(u.since || '')}</Txt> : null}

        <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 4, marginTop: 10, marginBottom: 12 }}>
          <Stat n={p?.posts ?? posts.length} label={plural(p?.posts ?? posts.length, ['публикация', 'публикации', 'публикаций'])} onPress={() => setTab('posts')} />
          <View style={{ width: 1, backgroundColor: c.line, marginVertical: 6 }} />
          <Stat n={p?.friends ?? 0} label={plural(p?.friends ?? 0, ['друг', 'друга', 'друзей'])} onPress={own ? () => router.push('/friends') : undefined} />
        </View>
        <View style={{ alignSelf: 'stretch' }}>{actions}</View>
      </View>
    </View>
  ) : null;

  const tileW = Math.floor((Math.min(width, 640) - 4) / 3);
  const clipList = clips.data || [];
  const itemList = items.data || [];
  const data: Row[] = !u || locked ? []
    : tab === 'posts' ? posts.map((x) => ({ k: 'post' as const, id: `p${x.id}`, p: x }))
    : tab === 'pulse' ? rows(clipList, 3).map((r) => ({ k: 'clips' as const, id: `c${r[0].id}`, items: r }))
    : rows(itemList, 2).map((r) => ({ k: 'items' as const, id: `i${r[0].id}`, items: r }));
  const loading = tab === 'posts' ? wall.isLoading : tab === 'pulse' ? clips.isLoading : items.isLoading;
  let empty: ReactNode = null;
  if (!me) {
    empty = (
      <View style={{ paddingTop: insets.top + 64, paddingHorizontal: 16 }}>
        <Empty icon="person" title="Профили видны участникам" text="Войдите, чтобы смотреть профили, добавлять в друзья и писать."
          action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
      </View>
    );
  } else if (!u) {
    empty = q.isLoading ? (
      <View style={{ gap: 14 }}><Skeleton h={coverH} r={0} /><View style={{ alignItems: 'center', gap: 12 }}><Skeleton w={104} h={104} r={52} /><Skeleton w="50%" h={24} /></View></View>
    ) : <View style={{ paddingTop: insets.top + 64, paddingHorizontal: 16 }}><Empty icon="person" title="Профиль не найден" text={(q.error as any)?.message} /></View>;
  } else if (locked) empty = <Locked />;
  else if (loading) {
    empty = tab === 'posts'
      ? <View style={{ gap: 18, padding: 16 }}>{[0, 1].map((i) => <View key={i} style={{ gap: 10 }}><Skeleton w="60%" /><Skeleton h={300} r={0} /></View>)}</View>
      : <View style={{ padding: tab === 'pulse' ? 0 : 16 }}><Skeleton h={220} r={tab === 'pulse' ? 0 : 16} /></View>;
  } else if (tab === 'posts') {
    empty = (
      <Empty icon="text" title={own ? 'Здесь будут ваши публикации' : 'Пока нет публикаций'}
        text={own ? 'Расскажите, что нового, поделитесь фото или сделайте репост интересного из ленты.' : undefined}
        action={own ? <Button title="Написать первый пост" kind="primary" onPress={() => router.push('/new-post')} /> : undefined} />
    );
  } else if (tab === 'pulse') {
    empty = (
      <Empty icon="pulse" title={own ? 'Ваши видео появятся здесь' : 'Пока нет видео'}
        action={own ? <Button title="Загрузить в Pulse" kind="secondary" icon="plus" onPress={() => router.push('/pulse')} /> : undefined} />
    );
  } else {
    empty = (
      <Empty icon="market" title={own ? 'У вас нет объявлений' : 'Нет объявлений'}
        action={own ? <Button title="Подать объявление" kind="secondary" icon="plus" onPress={() => router.push('/market/new')} /> : undefined} />
    );
  }
  const renderRow = ({ item }: { item: Row }) => {
    if (item.k === 'post') return <FeedPost p={item.p} onMenu={() => openMenu(item.p)} />;
    if (item.k === 'clips') {
      return (
        <View style={{ flexDirection: 'row', gap: 2, paddingBottom: 2 }}>
          {item.items.map((cl) => <ClipTile key={cl.id} clip={cl} width={tileW}
            onPress={() => router.push({ pathname: '/clips/[uid]', params: { uid: String(userId), start: String(cl.id) } })} />)}
        </View>
      );
    }
    return (
      <View style={{ flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingBottom: 14 }}>
        {item.items.map((l) => <View key={l.id} style={{ flex: 1 }}><Tile l={l} /></View>)}
        {item.items.length === 1 ? <View style={{ flex: 1 }} /> : null}
      </View>
    );
  };
  const more = () => {
    if (tab === 'posts' && wall.hasNextPage && !wall.isFetchingNextPage) wall.fetchNextPage();
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <FlashList
        ref={list}
        data={data}
        extraData={tab}
        keyExtractor={(r) => r.id}
        getItemType={(r) => r.k}
        renderItem={renderRow}
        onScroll={onScroll}
        scrollEventThrottle={16}
        contentInsetAdjustmentBehavior="never"
        refreshControl={refresh.control}
        contentContainerStyle={{ paddingBottom: (own ? TAB_SPACE : 40) + insets.bottom }}
        ListHeaderComponent={u && me ? (
          <View>
            {header}
            {!locked ? <Tabs value={tab} onChange={setTab} /> : null}
            {tab === 'pulse' && !locked ? <View style={{ height: 2 }} /> : <View style={{ height: tab === 'market' ? 14 : 4 }} />}
          </View>
        ) : null}
        ListEmptyComponent={empty}
        onEndReachedThreshold={0.6}
        onEndReached={more}
      />
      <TopBar y={y} title={u?.username ? `@${u.username}` : u?.name} left={own ? undefined : <BackButton />}
        right={own ? <IconButton icon="settings" label="Настройки" onPress={() => router.push('/settings')} />
          : p && p.relation !== 'blocked' ? <IconButton icon="more" label="Действия" onPress={() => setMenu(true)} /> : null} />
      {refresh.indicator}
      {sheet}
      {p && !own ? (
        <ActionSheet visible={menu} onClose={() => setMenu(false)} actions={[
          { title: 'Поделиться профилем', icon: 'share' as const, onPress: () => {
            const url = `${BOT}/app/user/${userId}`;
            const nav = (globalThis as any).navigator;
            if (Platform.OS !== 'web') Share.share({ message: url }).catch(() => {});
            else if (nav?.clipboard) nav.clipboard.writeText(url).then(() => toast('Ссылка скопирована')).catch(() => {});
          } },
          ...(p.relation === 'friends' ? [{ title: 'Удалить из друзей', icon: 'people' as const, onPress: () => run(() => removeFriend(userId), 'Удалён из друзей') }] : []),
          { title: `Заблокировать: ${handle(p.user)}`, icon: 'block' as const, danger: true, onPress: () => run(() => blockPerson(userId), 'Пользователь заблокирован') },
        ]} />
      ) : null}
    </View>
  );
}
