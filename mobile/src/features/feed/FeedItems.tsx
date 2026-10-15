import { router } from 'expo-router';
import { ReactNode, useEffect, useRef, useState } from 'react';
import { DimensionValue, Pressable, ScrollView, View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withSpring, withTiming } from 'react-native-reanimated';
import { toggleFavorite, useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { EventItem, News } from '@/api/content';
import { Post, postPhoto, RepostOf, setRepost, Share, toggleLike } from '@/api/feed';
import { ItemKind, ItemRef, ItemStats, shareItem, toggleItemLike } from '@/api/items';
import { ago, dayMonth, plural, relTime, weekday } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { HAIRLINE, useTheme } from '@/theme';
import { ActionSheet, BrandAvatar, handle, Icon, IconButton, IconName, Img, PhotoViewer, SheetAction, Tap, Txt, useToast, UserAvatar, VerifiedBadge } from '@/ui';
import { ShareSheet } from './ShareSheet';

// Лента как в Instagram: пост без карточки и рамок, фото от края до края экрана; сверху — аватар и @username,
// под фото — сердце, комментарии, «поделиться» и справа закладка; ниже — «N лайков», подпись и время.

const PAD = 14;               // отступ текста от краёв экрана
const LIKE_RED = '#FF3040';   // сердце после лайка
const nowMs = () => Date.now();

/** Лента постов. inset — горизонтальный отступ экрана: посты его «съедают» и встают от края до края. */
export function FeedList({ children, inset = 20 }: { children: ReactNode; inset?: number }) {
  return <View style={{ marginHorizontal: -inset, gap: 6 }}>{children}</View>;
}

/** Сердце: контур; при лайке плавно заливается красным и «подпрыгивает». */
function Heart({ on, size = 26 }: { on: boolean; size?: number }) {
  const { c } = useTheme();
  const p = useSharedValue(on ? 1 : 0);
  const k = useSharedValue(1);
  useEffect(() => {
    p.set(withTiming(on ? 1 : 0, { duration: 220 }));
    if (on) k.set(withSequence(withTiming(1.25, { duration: 110 }), withSpring(1, { damping: 9, stiffness: 260 })));
  }, [on, p, k]);
  const outline = useAnimatedStyle(() => ({ opacity: 1 - p.get() }));
  const fill = useAnimatedStyle(() => ({ opacity: p.get(), transform: [{ scale: k.get() }] }));
  return (
    <View style={{ width: size, height: size }}>
      <Animated.View style={[{ position: 'absolute' }, outline]}><Icon name="heart" size={size} color={c.ink} /></Animated.View>
      <Animated.View style={[{ position: 'absolute' }, fill]}><Icon name="heartFill" filled size={size} color={LIKE_RED} /></Animated.View>
    </View>
  );
}

function RowBtn({ label, onPress, children, selected }: { label: string; onPress: () => void; children: ReactNode; selected?: boolean }) {
  return (
    <Tap onPress={onPress} haptic="light" scaleTo={0.86} accessibilityLabel={label} accessibilityState={{ selected: !!selected }} hitSlop={8}
      style={{ marginRight: 16, paddingVertical: 2 }}>
      {children}
    </Tap>
  );
}

/** Точки карусели фото — по центру ряда действий, как в Instagram. */
function Dots({ n, at }: { n: number; at: number }) {
  const { c } = useTheme();
  if (n < 2) return null;
  return (
    <View pointerEvents="none" style={{ position: 'absolute', left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', gap: 4 }}>
      {Array.from({ length: n }, (_, i) => (
        <View key={i} style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: i === at ? c.accent : c.line }} />
      ))}
    </View>
  );
}

/** Ряд действий: слева сердце, комментарий, самолётик; справа закладка. */
export function ActionRow({ liked, onLike, onComment, onShare, onRepost, reposted, saved, onSave, dots }: {
  liked: boolean; onLike: () => void; onComment: () => void; onShare?: () => void; onRepost?: () => void; reposted?: boolean;
  saved?: boolean; onSave?: () => void; dots?: ReactNode;
}) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: PAD, height: 44 }}>
      {dots}
      <RowBtn label={liked ? 'Убрать лайк' : 'Нравится'} onPress={onLike} selected={liked}><Heart on={liked} /></RowBtn>
      <RowBtn label="Комментарии" onPress={onComment}><Icon name="bubble" size={25} color={c.ink} /></RowBtn>
      {onRepost ? (
        <RowBtn label={reposted ? 'Вы сделали репост' : 'Репост'} onPress={onRepost} selected={reposted}>
          <Icon name="repost" size={25} color={reposted ? c.success : c.ink} />
        </RowBtn>
      ) : null}
      {onShare ? <RowBtn label="Поделиться" onPress={onShare}><Icon name="paperplane" size={24} color={c.ink} /></RowBtn> : null}
      <View style={{ flex: 1 }} />
      {onSave ? (
        <Tap onPress={onSave} haptic="light" scaleTo={0.86} hitSlop={8} accessibilityLabel={saved ? 'Убрать из закладок' : 'В закладки'}
          accessibilityState={{ selected: !!saved }}>
          <Icon name={saved ? 'bookmarkFill' : 'bookmark'} filled={saved} size={25} color={c.ink} />
        </Tap>
      ) : null}
    </View>
  );
}

/** «30 лайков» жирным под рядом действий. */
function Likes({ n, extra }: { n: number; extra?: string }) {
  if (!n && !extra) return null;
  return (
    <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold', paddingHorizontal: PAD }}>
      {n ? `${n} ${plural(n, ['лайк', 'лайка', 'лайков'])}` : ''}{n && extra ? ' · ' : ''}{extra || ''}
    </Txt>
  );
}

/** Ряд действий + счётчик (экран новости или события). */
export function ActionBar({ likes, liked, comments, reposts, reposted, onLike, onComment, onRepost, onShare }: {
  likes: number; liked: boolean; comments: number; reposts: number; reposted: boolean;
  onLike: () => void; onComment: () => void; onRepost?: () => void; onShare?: () => void;
}) {
  const extra = [comments ? `${comments} ${plural(comments, ['комментарий', 'комментария', 'комментариев'])}` : '',
    reposts ? `${reposts} ${plural(reposts, ['репост', 'репоста', 'репостов'])}` : ''].filter(Boolean).join(' · ');
  return (
    <View style={{ marginHorizontal: -PAD, gap: 2 }}>
      <ActionRow liked={liked} onLike={onLike} onComment={onComment} onShare={onShare} onRepost={onRepost} reposted={reposted} />
      <Likes n={likes} extra={extra} />
    </View>
  );
}

function useFail() {
  const toast = useToast();
  return (e: any) => { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); };
}

/** Стандартные пропорции медиа (ширина/высота): квадрат, вертикаль 4:5 (1080×1350), горизонталь 16:9. */
export const MEDIA_RATIOS = { square: 1, portrait: 4 / 5, landscape: 16 / 9 } as const;
const snapRatio = (r?: number) => {
  const all = Object.values(MEDIA_RATIOS);
  return all.reduce((best, x) => (Math.abs(x - (r || 1)) < Math.abs(best - (r || 1)) ? x : best), all[0]);
};

/** Фото поста от края до края: строго 4:5, 1:1 или 16:9 (по первому фото), без полей — cover.
 *  Несколько фото — карусель со свайпом и счётчиком «1/3». Касание — фото на весь экран, двойное — лайк. */
function PostMedia({ paths, ratio, onLike, onPage }: { paths: string[]; ratio?: number; onLike?: () => void; onPage?: (i: number) => void }) {
  const { c } = useTheme();
  const [w, setW] = useState(0);
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const heart = useSharedValue(0);
  const last = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const pop = useAnimatedStyle(() => ({ opacity: heart.get(), transform: [{ scale: 0.5 + heart.get() * 0.6 }] }));
  if (!paths.length) return null;
  const urls = paths.map(postPhoto);
  const tap = (i: number) => {
    const now = nowMs();
    if (onLike && now - last.current < 280) {
      last.current = 0;
      if (timer.current) clearTimeout(timer.current);
      heart.set(withSequence(withSpring(1, { damping: 9, stiffness: 260 }), withTiming(1, { duration: 350 }), withTiming(0, { duration: 200 })));
      onLike();
      return;
    }
    last.current = now;
    timer.current = setTimeout(() => setOpen(i), onLike ? 280 : 0);
  };
  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ width: '100%', aspectRatio: snapRatio(ratio), backgroundColor: c.bgSunken }}>
      {w ? (
        <ScrollView horizontal pagingEnabled scrollEnabled={urls.length > 1} showsHorizontalScrollIndicator={false} scrollEventThrottle={32}
          disableIntervalMomentum decelerationRate="fast"
          onScroll={(e) => { const i = Math.round(e.nativeEvent.contentOffset.x / w); if (i !== page) { setPage(i); onPage?.(i); } }}>
          {urls.map((u, i) => (
            <Pressable key={u} onPress={() => tap(i)} accessibilityLabel={`Фото ${i + 1} из ${urls.length}`} style={{ width: w, height: '100%' }}>
              <Img source={u} contentFit="cover" style={{ width: '100%', height: '100%' }} />
            </Pressable>
          ))}
        </ScrollView>
      ) : null}
      {urls.length > 1 ? (
        <View pointerEvents="none" style={{ position: 'absolute', top: 12, right: 12, paddingHorizontal: 9, height: 24, borderRadius: 12,
          backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'center' }}>
          <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_600SemiBold' }}>{page + 1}/{urls.length}</Txt>
        </View>
      ) : null}
      <Animated.View pointerEvents="none" style={[{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, alignItems: 'center', justifyContent: 'center' }, pop]}>
        <Icon name="heartFill" filled size={96} color="#FFFFFF" />
      </Animated.View>
      <PhotoViewer urls={urls} index={open} onClose={() => setOpen(null)} />
    </View>
  );
}

/** Фото поста в превью (репост, черновик): те же пропорции, скруглённая сетка. */
export function PostPhotos({ paths, ratio }: { paths: string[]; ratio?: number }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!paths.length) return null;
  const urls = paths.map(postPhoto);
  const half = '49.5%' as DimensionValue;
  return (
    <>
      <View style={{ borderRadius: 10, overflow: 'hidden', flexDirection: 'row', flexWrap: 'wrap', gap: 3 }}>
        {urls.map((u, i) => (
          <Tap key={u} onPress={() => setOpen(i)} scaleTo={0.985} haptic={false} accessibilityLabel={`Открыть фото ${i + 1} из ${urls.length}`}
            style={{ width: urls.length === 1 ? '100%' : half, aspectRatio: urls.length === 1 ? snapRatio(ratio) : 1 }}>
            <Img source={u} contentFit="cover" style={{ width: '100%', height: '100%' }} />
          </Tap>
        ))}
      </View>
      <PhotoViewer urls={urls} index={open} onClose={() => setOpen(null)} />
    </>
  );
}

const openShare = (s: Share) => (s.kind === 'event'
  ? router.push({ pathname: '/event/[key]', params: { key: s.key } })
  : s.url ? openUrl(s.url) : undefined);

/** Превью новости или события, которыми поделились. */
function SharePreview({ s }: { s: Share }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => openShare(s)} scaleTo={0.99} style={{ flexDirection: 'row', gap: 12, alignItems: 'center', borderRadius: 12,
      borderWidth: HAIRLINE, borderColor: c.line, padding: 10, marginHorizontal: PAD }}>
      {s.img ? <Img source={s.img} style={{ width: 60, height: 60, borderRadius: 8 }} /> : (
        <View style={{ width: 60, height: 60, borderRadius: 8, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
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
  const box = { borderRadius: 14, borderWidth: HAIRLINE, borderColor: c.line, padding: 12, marginHorizontal: PAD } as const;
  if (r.deleted) return <View style={box}><Txt v="callout" tone="muted">Пост удалён или недоступен</Txt></View>;
  return (
    <Tap onPress={() => onOpen(r.id)} scaleTo={0.99} style={{ ...box, gap: 8 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <UserAvatar u={r.author} size={24} />
        <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }} numberOfLines={1}>{handle(r.author)}</Txt>
        {r.author.verified ? <VerifiedBadge size={13} /> : null}
        <Txt v="caption" tone="muted">{relTime(r.at)}</Txt>
      </View>
      {r.text ? <Txt v="callout" tone="ink" numberOfLines={6}>{r.text}</Txt> : null}
      <PostPhotos paths={r.photos} ratio={r.ratio} />
    </Tap>
  );
}

/** Шапка: аватар, @username с галочкой, ниже — город/подпись; справа «⋯». */
function Head({ avatar, title, sub, verified, onPress, onMenu }: {
  avatar: ReactNode; title: string; sub?: string; verified?: boolean; onPress?: () => void; onMenu?: () => void;
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingLeft: PAD, paddingRight: 4, height: 56 }}>
      <Tap onPress={onPress} disabled={!onPress} scaleTo={0.97} style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10 }}
        accessibilityLabel={title}>
        {avatar}
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Txt v="subhead" tone="ink" numberOfLines={1} style={{ flexShrink: 1, fontFamily: 'Onest_700Bold', fontSize: 14.5 }}>{title}</Txt>
            {verified ? <VerifiedBadge size={14} /> : null}
          </View>
          {sub ? <Txt v="caption" tone="muted" numberOfLines={1}>{sub}</Txt> : null}
        </View>
      </Tap>
      {onMenu ? <IconButton icon="more" label="Действия" onPress={onMenu} kind="plain" size={36} /> : null}
    </View>
  );
}

/** Обрезка длинной подписи: до ~125 символов и трёх строк, по границе слова. null — обрезать не нужно. */
function cut(t: string, n = 125) {
  const lines = t.split('\n');
  if (t.length <= n && lines.length <= 3) return null;
  let s = lines.slice(0, 3).join('\n').slice(0, n);
  const sp = s.lastIndexOf(' ');
  if (sp > n * 0.6) s = s.slice(0, sp);
  return s.trimEnd();
}

/** Подпись: @username жирным, текст и «… ещё». */
function Caption({ who, text, full, big }: { who?: string; text: string; full?: boolean; big?: boolean }) {
  const [more, setMore] = useState(false);
  const short = full || more ? null : cut(text, big ? 280 : 125);
  return (
    <Txt v={big ? 'body' : 'subhead'} tone="ink" selectable={full} style={{ paddingHorizontal: PAD, lineHeight: big ? 23 : 20 }}
      onPress={short ? () => setMore(true) : undefined}>
      {who ? <Txt v={big ? 'body' : 'subhead'} tone="ink" style={{ fontFamily: 'Onest_700Bold' }}>{who} </Txt> : null}
      {short ?? text}
      {short ? <Txt v={big ? 'body' : 'subhead'} tone="muted">… ещё</Txt> : null}
    </Txt>
  );
}

function Meta({ children }: { children: ReactNode }) {
  return <Txt v="caption" tone="muted" style={{ paddingHorizontal: PAD }}>{children}</Txt>;
}

/** Пост пользователя в ленте, на стене и на экране поста. */
export function FeedPost({ p, onMenu, full }: { p: Post; onMenu: () => void; full?: boolean }) {
  const { user, favorites } = useAuth();
  const toast = useToast();
  const fail = useFail();
  const [share, setShare] = useState(false);
  const [page, setPage] = useState(0);
  const open = (id: number) => router.push({ pathname: '/post/[id]', params: { id: String(id) } });
  const needLogin = () => { router.push('/login'); };
  const like = () => (user ? toggleLike(p).catch(fail) : needLogin());
  const likeOnce = () => { if (!p.liked) like(); };
  const original = p.repost && !p.repost.deleted ? p.repost : null;
  const target = original ? original.id : p.id;
  const saved = favorites.some((f) => f.kind === 'post' && f.key === String(p.id));
  const save = () => (user ? toggleFavorite(String(p.id), (p.text || 'Публикация').slice(0, 120), !saved, 'post')
    .then(() => toast(saved ? 'Убрано из закладок' : 'Сохранено в закладки')).catch(fail) : needLogin());
  const repost = (on: boolean) => setRepost(p, on).then(() => toast(on ? 'Репост в вашем профиле' : 'Репост убран')).catch(fail);
  const sub = [p.repost ? 'репост' : p.share ? 'поделился' : '', p.city || p.author.city].filter(Boolean).join(' · ');
  const media = p.photos.length > 0;
  const who = handle(p.author);
  return (
    <View style={{ paddingBottom: 14 }}>
      <Head avatar={<UserAvatar u={p.author} size={36} />} title={who} sub={sub} verified={p.author.verified}
        onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(p.author.id) } })} onMenu={onMenu} />
      {/* Пост без фото — текст сразу под шапкой, крупнее (как в Threads) */}
      {!media && p.text ? <View style={{ paddingBottom: 6 }}><Caption text={p.text} full={full} big /></View> : null}
      {media ? <PostMedia paths={p.photos} ratio={p.ratio} onLike={likeOnce} onPage={setPage} /> : null}
      {p.repost || p.share ? (
        <View style={{ paddingTop: media ? 10 : 2 }}>
          {p.repost ? <RepostBox r={p.repost} onOpen={open} /> : null}
          {p.share ? <SharePreview s={p.share} /> : null}
        </View>
      ) : null}
      <ActionRow liked={p.liked} onLike={like} onComment={() => open(p.id)} onShare={() => setShare(true)}
        saved={saved} onSave={save} dots={<Dots n={p.photos.length} at={page} />} />
      <View style={{ gap: 5 }}>
        <Likes n={p.likes} extra={!original && p.reposts ? `${p.reposts} ${plural(p.reposts, ['репост', 'репоста', 'репостов'])}` : ''} />
        {media && p.text ? <Caption who={who} text={p.text} full={full} /> : null}
        {p.comments && !full ? (
          <Tap onPress={() => open(p.id)} scaleTo={0.99} haptic={false} style={{ alignSelf: 'flex-start' }}>
            <Txt v="subhead" tone="muted" style={{ paddingHorizontal: PAD }}>
              {p.comments === 1 ? 'Смотреть 1 комментарий' : `Смотреть все комментарии (${p.comments})`}
            </Txt>
          </Tap>
        ) : null}
        <Meta>{relTime(p.at)}</Meta>
      </View>
      <ShareSheet visible={share} onClose={() => setShare(false)} postId={target} reposted={p.reposted}
        canRepost={!p.mine || !!original} onRepost={repost} />
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
  const like = () => (user ? toggleItemLike(it.kind, it.key, s).catch(fail) : router.push('/login'));
  const row = (extra?: { saved: boolean; onSave: () => void }) => (
    <ActionRow liked={s.liked} onLike={like} onComment={comments} onShare={() => (user ? setSheet(true) : router.push('/login'))}
      saved={extra?.saved} onSave={extra?.onSave} />
  );
  const counts = (
    <View style={{ gap: 5 }}>
      <Likes n={s.likes} extra={s.shares ? `${s.shares} ${plural(s.shares, ['репост', 'репоста', 'репостов'])}` : ''} />
    </View>
  );
  const more = s.comments ? (
    <Tap onPress={comments} scaleTo={0.99} haptic={false} style={{ alignSelf: 'flex-start' }}>
      <Txt v="subhead" tone="muted" style={{ paddingHorizontal: PAD }}>
        {s.comments === 1 ? 'Смотреть 1 комментарий' : `Смотреть все комментарии (${s.comments})`}
      </Txt>
    </Tap>
  ) : null;
  return { row, counts, more, sheet: <ActionSheet visible={sheet} onClose={() => setSheet(false)} actions={actions} /> };
}

function Badge({ icon }: { icon: IconName }) {
  const { c } = useTheme();
  return (
    <View style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: c.inverse, alignItems: 'center', justifyContent: 'center' }}>
      <Icon name={icon} size={17} color={c.accent} />
    </View>
  );
}

export const newsRef = (n: News): ItemRef => ({ kind: 'news', key: n.id, title: n.h, url: n.link, img: n.img || '' });
export const eventRef = (e: EventItem): ItemRef => ({ kind: 'event', key: e.key, title: e.h, url: e.url || '', img: e.img || '' });

/** Новость от сообщества: официальная аватарка бренда и галочка, фото 16:9 от края до края. */
export function FeedNews({ n, stats }: { n: News; stats: ItemStats }) {
  const { row, counts, more, sheet } = useItemActions(newsRef(n), stats);
  return (
    <View style={{ paddingBottom: 14 }}>
      <Head avatar={<BrandAvatar size={36} />} verified title="podslushano.nl" sub={n.cat || 'Новости'} />
      <Tap onPress={() => openUrl(n.link)} scaleTo={0.995} haptic={false} accessibilityRole="link">
        {n.img ? <Img source={n.img} contentFit="cover" style={{ width: '100%', aspectRatio: MEDIA_RATIOS.landscape }} /> : null}
      </Tap>
      {row()}
      <View style={{ gap: 5 }}>
        {counts}
        <Tap onPress={() => openUrl(n.link)} scaleTo={0.995} haptic={false} accessibilityRole="link" style={{ gap: 4 }}>
          <Txt v="headline" style={{ fontSize: 17, lineHeight: 23, paddingHorizontal: PAD }}>{n.h}</Txt>
          {n.lead ? <Caption text={n.lead} /> : null}
        </Tap>
        {more}
        <Meta>{ago(n.date, n.time)}</Meta>
      </View>
      {sheet}
    </View>
  );
}

export function FeedEvent({ e, stats }: { e: EventItem; stats: ItemStats }) {
  const { c } = useTheme();
  const { user, favorites } = useAuth();
  const toast = useToast();
  const { row, counts, more, sheet } = useItemActions(eventRef(e), stats);
  const saved = favorites.some((f) => f.kind === 'event' && f.key === e.key);
  const save = () => (user ? toggleFavorite(e.key, e.h, !saved).then(() => toast(saved ? 'Убрано из избранного' : 'Сохранено в избранное'))
    .catch(() => toast('Не получилось', 'error')) : router.push('/login'));
  const go = () => router.push({ pathname: '/event/[key]', params: { key: e.key } });
  return (
    <View style={{ paddingBottom: 14 }}>
      <Head avatar={<Badge icon="ticket" />} title="Афиша" sub={`${weekday(e.date)}, ${dayMonth(e.date)}${e.time ? ` · ${e.time}` : ''}`} onPress={go} />
      {e.img ? (
        <Tap onPress={go} scaleTo={0.995} haptic={false}>
          <Img source={e.img} contentFit="cover" style={{ width: '100%', aspectRatio: MEDIA_RATIOS.landscape }} />
        </Tap>
      ) : null}
      {row({ saved, onSave: save })}
      <View style={{ gap: 5 }}>
        {counts}
        <Tap onPress={go} scaleTo={0.995} haptic={false} style={{ gap: 4, paddingHorizontal: PAD }}>
          <Txt v="headline" style={{ fontSize: 17, lineHeight: 23 }}>{e.h}</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Icon name="location" size={14} color={c.muted} />
            <Txt v="footnote" numberOfLines={1} style={{ flex: 1 }}>{[e.venue, e.city].filter(Boolean).join(', ') || 'Нидерланды'}{e.price ? ` · ${e.price}` : ''}</Txt>
          </View>
        </Tap>
        {more}
      </View>
      {sheet}
    </View>
  );
}

export type { ItemKind };
