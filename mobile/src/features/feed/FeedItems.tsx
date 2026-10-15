import { router } from 'expo-router';
import { ReactNode, useEffect, useState } from 'react';
import { View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withSpring, withTiming } from 'react-native-reanimated';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { EventItem, News } from '@/api/content';
import { Post, postPhoto, RepostOf, setRepost, Share, toggleLike } from '@/api/feed';
import { ItemKind, ItemRef, ItemStats, shareItem, toggleItemLike } from '@/api/items';
import { ago, dayMonth, weekday } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Avatar, Icon, IconButton, IconName, Img, SheetAction, Tap, Txt, useToast } from '@/ui';
import { timeLabel } from './cards';

// Лента в стиле соцсети: элементы без «коробок», разделены тонкой линией; контент выровнен под именем,
// внизу у каждого — один и тот же ряд действий: нравится, комментарии, репост.

const GUTTER = 56;   // аватар 44 + отступ 12: текст и фото начинаются под именем

/** Тонкая линия между элементами ленты. */
export function FeedDivider() {
  const { c } = useTheme();
  return <View style={{ height: 1, backgroundColor: c.line, marginLeft: GUTTER }} />;
}

/** Подложка ленты: белый лист на всю ширину экрана. */
export function FeedSheet({ children }: { children: ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={{ marginHorizontal: -20, backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
      borderTopWidth: 1, borderColor: c.line, paddingHorizontal: 20, paddingTop: 6 }}>
      {children}
    </View>
  );
}

function ActionBtn({ icon, n, active, color, label, onPress, children }: {
  icon?: IconName; n?: number; active?: boolean; color?: string; label: string; onPress: () => void; children?: ReactNode;
}) {
  const { c } = useTheme();
  const tint = active ? color || c.accentText : c.muted;
  return (
    <Tap onPress={onPress} haptic="light" scaleTo={0.9} accessibilityLabel={label} accessibilityState={{ selected: !!active }}
      hitSlop={10} style={{ flexDirection: 'row', alignItems: 'center', gap: 6, minWidth: 60, paddingVertical: 6 }}>
      {children ?? (icon ? <Icon name={icon} thin size={22} color={tint} /> : null)}
      <Txt v="subhead" color={tint} style={{ fontFamily: 'Onest_500Medium', fontVariant: ['tabular-nums'] }}>{n ? n : ''}</Txt>
    </Tap>
  );
}

/** Сердце: тонкий контур; при лайке плавно заливается фирменным цветом и чуть «подпрыгивает». */
function Heart({ on, color }: { on: boolean; color: string }) {
  const { c } = useTheme();
  const p = useSharedValue(on ? 1 : 0);
  const k = useSharedValue(1);
  useEffect(() => {
    p.value = withTiming(on ? 1 : 0, { duration: 220 });
    if (on) k.value = withSequence(withTiming(1.22, { duration: 110 }), withSpring(1, { damping: 9, stiffness: 260 }));
  }, [on, p, k]);
  const outline = useAnimatedStyle(() => ({ opacity: 1 - p.value }));
  const fill = useAnimatedStyle(() => ({ opacity: p.value, transform: [{ scale: k.value }] }));
  return (
    <View style={{ width: 22, height: 22 }}>
      <Animated.View style={[{ position: 'absolute' }, outline]}><Icon name="heart" thin size={22} color={c.muted} /></Animated.View>
      <Animated.View style={[{ position: 'absolute' }, fill]}><Icon name="heartFill" filled size={22} color={color} /></Animated.View>
    </View>
  );
}

/** Ряд действий под элементом ленты. */
export function ActionBar({ likes, liked, comments, reposts, reposted, onLike, onComment, onRepost }: {
  likes: number; liked: boolean; comments: number; reposts: number; reposted: boolean;
  onLike: () => void; onComment: () => void; onRepost?: () => void;
}) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 22, marginTop: 6 }}>
      <ActionBtn n={likes} active={liked} color={c.accent} label={liked ? 'Убрать лайк' : 'Нравится'} onPress={onLike}>
        <Heart on={liked} color={c.accent} />
      </ActionBtn>
      <ActionBtn icon="bubble" n={comments} label="Комментарии" onPress={onComment} />
      {onRepost ? <ActionBtn icon="repost" n={reposts} active={reposted} color={c.success} label={reposted ? 'Вы сделали репост' : 'Репост'} onPress={onRepost} /> : null}
    </View>
  );
}

function useFail() {
  const toast = useToast();
  return (e: any) => { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); };
}

/** Фото поста: одно — во всю ширину, два — рядом, три-четыре — сеткой. */
export function PostPhotos({ paths, onPress }: { paths: string[]; onPress?: () => void }) {
  if (!paths.length) return null;
  const urls = paths.map(postPhoto);
  const tile = (u: string, style: object) => <Img key={u} source={u} style={[{ borderRadius: 14 }, style]} />;
  return (
    <Tap onPress={onPress} disabled={!onPress} scaleTo={0.99} accessibilityLabel={`Фото: ${urls.length}`}>
      {urls.length === 1 ? tile(urls[0], { width: '100%', aspectRatio: 4 / 3 }) : (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4 }}>
          {urls.map((u) => tile(u, { width: '49.3%', aspectRatio: urls.length === 2 ? 3 / 4 : 1 }))}
        </View>
      )}
    </Tap>
  );
}

const openShare = (s: Share) => (s.kind === 'event'
  ? router.push({ pathname: '/event/[key]', params: { key: s.key } })
  : s.url ? openUrl(s.url) : undefined);

/** Превью новости или события, которыми поделились в профиле. */
function SharePreview({ s }: { s: Share }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => openShare(s)} scaleTo={0.99} style={{ flexDirection: 'row', gap: 12, alignItems: 'center', borderRadius: radius.l,
      borderWidth: 1, borderColor: c.line, padding: 10 }}>
      {s.img ? <Img source={s.img} style={{ width: 64, height: 64, borderRadius: 12 }} /> : (
        <View style={{ width: 64, height: 64, borderRadius: 12, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={s.kind === 'event' ? 'ticket' : 'newspaper'} color={c.accentText} />
        </View>
      )}
      <View style={{ flex: 1, gap: 3 }}>
        <Txt v="caption" tone="accent" style={{ fontFamily: 'Onest_700Bold' }}>{s.kind === 'event' ? 'Событие' : 'Новость'}</Txt>
        <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }} numberOfLines={3}>{s.title}</Txt>
      </View>
    </Tap>
  );
}

function RepostBox({ r, onOpen }: { r: RepostOf; onOpen: (id: number) => void }) {
  const { c } = useTheme();
  if (r.deleted) {
    return <View style={{ borderRadius: radius.l, borderWidth: 1, borderColor: c.line, padding: 14 }}><Txt v="callout" tone="muted">Пост удалён или недоступен</Txt></View>;
  }
  return (
    <Tap onPress={() => onOpen(r.id)} scaleTo={0.99} style={{ borderRadius: radius.l, borderWidth: 1, borderColor: c.line, padding: 12, gap: 8 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Avatar name={r.author.name} id={r.author.id} uri={r.author.avatar} size={24} />
        <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }} numberOfLines={1}>{r.author.name}</Txt>
        <Txt v="caption">{timeLabel(r.at)}</Txt>
      </View>
      {r.text ? <Txt v="callout" tone="ink" numberOfLines={8}>{r.text}</Txt> : null}
      <PostPhotos paths={r.photos} />
    </Tap>
  );
}

/** Шапка элемента ленты: аватар, имя, подпись, «⋯». */
function Head({ avatar, title, sub, onPress, onMenu }: { avatar: ReactNode; title: string; sub: string; onPress?: () => void; onMenu?: () => void }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <Tap onPress={onPress} disabled={!onPress} scaleTo={0.97} style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 }}
        accessibilityLabel={title}>
        {avatar}
        <View style={{ flex: 1 }}>
          <Txt v="bodyStrong" numberOfLines={1}>{title}</Txt>
          <Txt v="footnote" numberOfLines={1}>{sub}</Txt>
        </View>
      </Tap>
      {onMenu ? <IconButton icon="more" label="Действия" onPress={onMenu} kind="plain" size={34} /> : null}
    </View>
  );
}

/** Пост пользователя в ленте, на стене и на экране поста. */
export function FeedPost({ p, onMenu, full }: { p: Post; onMenu: () => void; full?: boolean }) {
  const { user } = useAuth();
  const toast = useToast();
  const fail = useFail();
  const [sheet, setSheet] = useState(false);
  const open = (id: number) => router.push({ pathname: '/post/[id]', params: { id: String(id) } });
  const needLogin = () => { router.push('/login'); };
  const like = () => (user ? toggleLike(p).catch(fail) : needLogin());
  const original = p.repost && !p.repost.deleted ? p.repost : null;
  const canRepost = !p.mine || !!original;
  const repostActions: SheetAction[] = p.reposted
    ? [{ title: 'Отменить репост', icon: 'repost', danger: true, onPress: () => setRepost(p, false).then(() => toast('Репост убран')).catch(fail) }]
    : [
        { title: 'Репост в мой профиль', icon: 'repost', onPress: () => setRepost(p, true).then(() => toast('Репост в вашем профиле')).catch(fail) },
        { title: 'Репост с комментарием', icon: 'edit', onPress: () => router.push({ pathname: '/new-post', params: { repost: String(original ? original.id : p.id) } }) },
      ];
  const sub = [p.repost ? 'репост' : p.share ? 'поделился' : '', p.city || p.author.city, timeLabel(p.at)].filter(Boolean).join(' · ');
  return (
    <View style={{ paddingVertical: 16, gap: 10 }}>
      <Head avatar={<Avatar name={p.author.name} id={p.author.id} uri={p.author.avatar} size={44} />} title={p.author.name} sub={sub}
        onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(p.author.id) } })} onMenu={onMenu} />
      <View style={{ marginLeft: GUTTER, gap: 10 }}>
        {p.text ? (
          <Tap onPress={() => open(p.id)} disabled={full} scaleTo={0.995}>
            <Txt v="body" tone="ink" numberOfLines={full ? undefined : 12} selectable={full}>{p.text}</Txt>
          </Tap>
        ) : null}
        <PostPhotos paths={p.photos} onPress={full ? undefined : () => open(p.id)} />
        {p.repost ? <RepostBox r={p.repost} onOpen={open} /> : null}
        {p.share ? <SharePreview s={p.share} /> : null}
        <ActionBar likes={p.likes} liked={p.liked} comments={p.comments} reposts={original ? 0 : p.reposts} reposted={p.reposted}
          onLike={like} onComment={() => open(p.id)} onRepost={canRepost ? () => (user ? setSheet(true) : needLogin()) : undefined} />
      </View>
      <ActionSheet visible={sheet} onClose={() => setSheet(false)} actions={repostActions} />
    </View>
  );
}

/** Новость и событие: лайк, комментарии, «поделиться в профиле». */
function useItemActions(it: ItemRef, s: ItemStats) {
  const { user } = useAuth();
  const toast = useToast();
  const fail = useFail();
  const [sheet, setSheet] = useState(false);
  const comments = () => router.push({ pathname: '/item/[kind]/[key]', params: { kind: it.kind, key: it.key, title: it.title, url: it.url, img: it.img } });
  const actions: SheetAction[] = s.shared
    ? [{ title: 'Уже в вашем профиле', icon: 'check', onPress: () => {} }]
    : [
        { title: 'Поделиться в моём профиле', icon: 'repost', onPress: () => shareItem(it).then(() => toast('Теперь это в вашем профиле')).catch(fail) },
        { title: 'Поделиться с комментарием', icon: 'edit', onPress: () => router.push({ pathname: '/new-post', params: { share: JSON.stringify(it) } }) },
      ];
  const bar = (
    <ActionBar likes={s.likes} liked={s.liked} comments={s.comments} reposts={s.shares} reposted={s.shared}
      onLike={() => (user ? toggleItemLike(it.kind, it.key, s).catch(fail) : router.push('/login'))}
      onComment={comments} onRepost={() => (user ? setSheet(true) : router.push('/login'))} />
  );
  return { bar, comments, sheet: <ActionSheet visible={sheet} onClose={() => setSheet(false)} actions={actions} /> };
}

function Badge({ icon }: { icon: IconName }) {
  const { c } = useTheme();
  return (
    <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: c.inverse, alignItems: 'center', justifyContent: 'center' }}>
      <Icon name={icon} size={20} color={c.accent} />
    </View>
  );
}

export const newsRef = (n: News): ItemRef => ({ kind: 'news', key: n.id, title: n.h, url: n.link, img: n.img || '' });
export const eventRef = (e: EventItem): ItemRef => ({ kind: 'event', key: e.key, title: e.h, url: e.url || '', img: e.img || '' });

export function FeedNews({ n, stats }: { n: News; stats: ItemStats }) {
  const { bar, sheet } = useItemActions(newsRef(n), stats);
  return (
    <View style={{ paddingVertical: 16, gap: 10 }}>
      <Head avatar={<Badge icon="newspaper" />} title="podslushano.nl" sub={`${n.cat || 'Новости'} · ${ago(n.date, n.time)}`} />
      <View style={{ marginLeft: GUTTER, gap: 10 }}>
        <Tap onPress={() => openUrl(n.link)} scaleTo={0.995} style={{ gap: 10 }} accessibilityRole="link">
          <Txt v="headline" style={{ fontSize: 18, lineHeight: 24 }}>{n.h}</Txt>
          {n.lead ? <Txt v="callout" tone="muted" numberOfLines={3}>{n.lead}</Txt> : null}
          {n.img ? <Img source={n.img} style={{ width: '100%', aspectRatio: 16 / 10, borderRadius: 14 }} /> : null}
        </Tap>
        {bar}
      </View>
      {sheet}
    </View>
  );
}

export function FeedEvent({ e, stats }: { e: EventItem; stats: ItemStats }) {
  const { c } = useTheme();
  const { bar, sheet } = useItemActions(eventRef(e), stats);
  return (
    <View style={{ paddingVertical: 16, gap: 10 }}>
      <Head avatar={<Badge icon="ticket" />} title="Афиша" sub={`${weekday(e.date)}, ${dayMonth(e.date)}${e.time ? ` · ${e.time}` : ''}`} />
      <View style={{ marginLeft: GUTTER, gap: 10 }}>
        <Tap onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} scaleTo={0.995} style={{ gap: 8 }}>
          <Txt v="headline" style={{ fontSize: 18, lineHeight: 24 }}>{e.h}</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Icon name="location" size={14} color={c.muted} />
            <Txt v="footnote" numberOfLines={1} style={{ flex: 1 }}>{[e.venue, e.city].filter(Boolean).join(', ') || 'Нидерланды'}{e.price ? ` · ${e.price}` : ''}</Txt>
          </View>
          {e.img ? <Img source={e.img} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 14 }} /> : null}
        </Tap>
        {bar}
      </View>
      {sheet}
    </View>
  );
}

export type { ItemKind };
