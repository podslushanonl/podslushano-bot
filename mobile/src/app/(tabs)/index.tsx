import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { feedPosts, useFeed } from '@/api/feed';
import { useContent } from '@/api/content';
import { queryClient } from '@/api/query';
import { CitySheet } from '@/features/common/CitySheet';
import { itemId, statsOf, useItemStats } from '@/api/items';
import { JobCard, SaveCard } from '@/features/feed/cards';
import { FeedEvent, FeedList, FeedNews, FeedPost } from '@/features/feed/FeedItems';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { NowCard } from '@/features/home/NowCard';
import { PermissionsSheet } from '@/features/home/PermissionsSheet';
import { StoriesRow } from '@/features/stories/StoriesRow';
import { locateMe } from '@/lib/location';
import { useCity, useCountry } from '@/lib/useCity';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Avatar, Button, Empty, Glass, Icon, IconButton, IconName, Skeleton, TabScreen, Tap, Txt, useToast } from '@/ui';

const SERVICES: { title: string; icon: IconName; href: '/afisha' | '/trains' | '/jobs' | '/save'; accent?: boolean }[] = [
  { title: 'Афиша', icon: 'ticket', href: '/afisha' },
  { title: 'Поезда', icon: 'train', href: '/trains' },
  { title: 'Работа', icon: 'briefcase', href: '/jobs' },
  { title: 'Сэкономить', icon: 'tag', href: '/save', accent: true },
];

const SAVE_UNTIL = '2026-12-31';
type Feed = 'all' | 'near';

function greeting(name?: string) {
  const h = Number(new Date().toLocaleString('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Europe/Amsterdam' }));
  const part = h < 5 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер';
  return name ? `${part},\n${name}` : part;
}

/** Вкладки ленты «Все» и «Рядом» — с подчёркиванием, как в Instagram и VK; прилипают к верху при прокрутке. */
function FeedTabs({ value, onChange }: { value: Feed; onChange: (v: Feed) => void }) {
  const { c } = useTheme();
  const items: [Feed, IconName, string][] = [['all', 'globe', 'Все'], ['near', 'location', 'Рядом']];
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: 'row', marginHorizontal: -20, borderBottomWidth: HAIRLINE, borderBottomColor: c.line }}>
      {items.map(([k, icon, title]) => {
        const on = value === k;
        return (
          <Tap key={k} onPress={() => onChange(k)} scaleTo={0.97} haptic="select" accessibilityRole="tab" accessibilityLabel={title}
            accessibilityState={{ selected: on }}
            style={{ flex: 1, alignItems: 'center', paddingVertical: 12, borderBottomWidth: 2, borderBottomColor: on ? c.ink : 'transparent', marginBottom: -HAIRLINE }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Icon name={icon} size={16} color={on ? c.ink : c.faint} />
              <Txt v="subhead" color={on ? c.ink : c.faint} style={{ fontFamily: 'Onest_700Bold' }}>{title}</Txt>
            </View>
          </Tap>
        );
      })}
    </View>
  );
}

type Row = { k: string; ts: number; el: 'news' | 'post' | 'event' | 'job' | 'save'; data?: any };

export default function Home() {
  const { c } = useTheme();
  const { user } = useAuth();
  const toast = useToast();
  const [city, setCity] = useCity();
  const country = useCountry();
  const [picker, setPicker] = useState(false);
  const [feed, setFeed] = useState<Feed>('all');
  const [locating, setLocating] = useState(false);
  const content = useContent();
  // «Все» — посты всех трёх стран вперемешку с новостями и афишей; «Рядом» — посты в радиусе 50 км (или из моего города)
  const posts = useFeed(feed, feed === 'near' ? { country, city: user ? undefined : city || undefined } : {});
  const { openMenu, sheet } = usePostMenu();

  const rows = useMemo<Row[]>(() => {
    const ps = feedPosts(posts.data);
    const seen = new Set<number>();
    const uniq = ps.filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)));   // пост с галочкой бывает и наверху, и на своём месте
    const postRows: Row[] = uniq.map((p) => ({ k: 'p' + p.id, ts: Date.parse(p.at) || 0, el: 'post' as const, data: p }));
    if (feed === 'near') return postRows;
    const news = content.data?.news || [];
    const main: Row[] = [
      ...news.map((n) => ({ k: 'n' + n.id, ts: Date.parse(`${n.date}T${n.time || '00:00'}:00`) || 0, el: 'news' as const, data: n })),
      ...postRows,
    ].sort((a, b) => b.ts - a.ts);
    const events = (content.data?.events || []).filter((e) => e.date >= new Date().toISOString().slice(0, 10));
    const jobs = content.data?.jobs || [];
    const out: Row[] = [];
    let ei = 0, ji = 0;
    main.forEach((r, i) => {
      out.push(r);
      if (i === 1 && new Date().toISOString().slice(0, 10) <= SAVE_UNTIL) out.push({ k: 'save', ts: 0, el: 'save' });
      if (i % 3 === 2 && events[ei]) { out.push({ k: 'e' + events[ei].key, ts: 0, el: 'event', data: events[ei] }); ei++; }
      if (i % 7 === 6 && jobs[ji]) { out.push({ k: 'j' + jobs[ji].id, ts: 0, el: 'job', data: jobs[ji] }); ji++; }
    });
    return out;
  }, [content.data, posts.data, feed]);
  // Посты с галочкой поднимаются наверх первой страницы «Все» — не сортируем их вниз по дате
  const sorted = useMemo(() => {
    if (feed !== 'all') return rows;
    const ps = feedPosts(posts.data).slice(0, 3).filter((p) => p.author.verified).map((p) => 'p' + p.id);
    const top = rows.filter((r) => ps.includes(r.k));
    return [...top, ...rows.filter((r) => !ps.includes(r.k))];
  }, [rows, feed, posts.data]);
  // Счётчики лайков, комментариев и репостов для новостей и событий в ленте — одним запросом
  const itemIds = useMemo(() => rows.filter((r) => r.el === 'news' || r.el === 'event')
    .map((r) => itemId(r.el === 'news' ? 'news' : 'event', r.el === 'news' ? r.data.id : r.data.key)).slice(0, 60), [rows]);
  const stats = useItemStats(itemIds);
  const [tabsY, setTabsY] = useState<number | undefined>();
  const tabs = <FeedTabs value={feed} onChange={setFeed} />;

  const gps = async () => {
    if (!user) { router.push('/login'); return; }
    setLocating(true);
    try { const p = await locateMe(); toast(`Ваше место: ${p.name}`); } catch (e: any) { toast(e?.message || 'Не получилось определить место', 'error'); }
    finally { setLocating(false); }
  };

  const composer = (
    <Tap onPress={() => router.push(user ? '/new-post' : '/login')} scaleTo={0.98} haptic="light"
      accessibilityRole="button" accessibilityLabel={user ? 'Новая публикация' : 'Войти, чтобы написать пост'}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.bgSunken, borderRadius: radius.pill,
        paddingVertical: 6, paddingLeft: 6, paddingRight: 16 }}>
      {user ? <Avatar name={user.name} id={user.id} uri={user.avatar} size={38} /> : <Avatar name="" size={38} />}
      <Txt v="callout" tone="muted" style={{ flex: 1 }} numberOfLines={1}>{user ? `${user.name || 'Вы'}, что нового?` : 'Войдите, чтобы написать пост'}</Txt>
      <Icon name="camera" thin size={22} color={c.muted} />
    </Tap>
  );

  // «Рядом»: где я и радиус; без GPS — предложение определить место
  const nearHead = (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: radius.l, backgroundColor: c.bgElevated,
      borderWidth: HAIRLINE, borderColor: c.line }}>
      <View style={{ width: 42, height: 42, borderRadius: 21, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name="location" size={20} color={c.onAccent} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="bodyStrong" numberOfLines={1}>{city || 'Место не выбрано'}</Txt>
        <Txt v="footnote" tone="muted" numberOfLines={2}>
          {user?.located ? 'Посты соседей в радиусе 50 км' : city ? `Посты из ${city}. Включите GPS — будет радиус 50 км` : 'Определите место, чтобы видеть соседей'}
        </Txt>
      </View>
      <Button title={user?.located ? 'Обновить' : 'GPS'} kind={user?.located ? 'secondary' : 'accent'} size="s" full={false} icon="location"
        loading={locating} onPress={gps} />
    </View>
  );

  return (
    <>
      <TabScreen
        title={greeting(user?.name)}
        collapsing pinned={tabs} pinAt={tabsY}
        onRefresh={() => Promise.all([content.refetch(), posts.refetch(), stats.refetch(),
          queryClient.invalidateQueries({ queryKey: ['weather'] }), queryClient.invalidateQueries({ queryKey: ['ns'] })])}
        above={
          <Tap onPress={() => setPicker(true)} scaleTo={0.95} style={{ alignSelf: 'flex-start', marginBottom: 6 }} accessibilityLabel={`Место: ${city || 'не выбрано'}. Изменить`}>
            <Glass radius={radius.pill} interactive style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, height: 38 }}>
              <Icon name="location" size={15} />
              <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{city || 'Выбрать место'}</Txt>
              <Icon name="down" size={12} color={c.muted} />
            </Glass>
          </Tap>
        }
        right={<IconButton icon="edit" label="Написать пост" onPress={() => router.push(user ? '/new-post' : '/login')} />}>

        <StoriesRow />

        <View onLayout={(e) => setTabsY(e.nativeEvent.layout.y)}>{tabs}</View>

        {feed === 'all' ? (
          <>
            <NowCard city={city} />
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              {SERVICES.map((s) => (
                <Tap key={s.href} onPress={() => router.push(s.href)} scaleTo={0.92} style={{ alignItems: 'center', gap: 8, width: '23%' }} accessibilityLabel={s.title}>
                  <View style={{ width: 64, height: 64, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
                    backgroundColor: s.accent ? c.accent : c.bgElevated, borderWidth: s.accent ? 0 : HAIRLINE, borderColor: c.line }}>
                    <Icon name={s.icon} size={26} color={s.accent ? c.onAccent : c.ink} />
                  </View>
                  <Txt v="footnote" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{s.title}</Txt>
                </Tap>
              ))}
            </View>
          </>
        ) : nearHead}

        {composer}

        {feed === 'near' && !posts.isLoading && !rows.length ? (
          <Empty icon="location" title="Рядом пока тихо"
            text={city ? `Станьте первым, кто напишет${user?.located ? ' в радиусе 50 км' : ` из ${city}`}.` : 'Определите своё место — и здесь появятся посты соседей.'}
            action={<Button title="Написать пост" kind="secondary" onPress={() => router.push(user ? '/new-post' : '/login')} />} />
        ) : (feed === 'all' ? !content.data && content.isLoading : posts.isLoading) ? (
          <View style={{ gap: 14 }}>{[0, 1].map((i) => <View key={i} style={{ gap: 10 }}><Skeleton h={190} r={28} /><Skeleton w="70%" /><Skeleton w="45%" h={12} /></View>)}</View>
        ) : sorted.length ? (
          <FeedList>
            {sorted.map((r) => {
              if (r.el === 'news') return <FeedNews key={r.k} n={r.data} stats={statsOf(stats.data, itemId('news', r.data.id))} />;
              if (r.el === 'post') return <FeedPost key={r.k} p={r.data} onMenu={() => openMenu(r.data)} />;
              if (r.el === 'event') return <FeedEvent key={r.k} e={r.data} stats={statsOf(stats.data, itemId('event', r.data.key))} />;
              if (r.el === 'job') return <View key={r.k} style={{ paddingHorizontal: 20, paddingVertical: 8 }}><JobCard j={r.data} /></View>;
              return <View key={r.k} style={{ paddingHorizontal: 20, paddingVertical: 8 }}><SaveCard /></View>;
            })}
            {posts.hasNextPage ? (
              <View style={{ paddingHorizontal: 20 }}>
                <Button title="Показать ещё" kind="secondary" loading={posts.isFetchingNextPage} onPress={() => posts.fetchNextPage()} />
              </View>
            ) : null}
          </FeedList>
        ) : (
          <Txt v="callout" tone="muted" center>{content.isError ? 'Не получилось загрузить ленту. Потяните вниз, чтобы обновить.' : 'Пока пусто.'}</Txt>
        )}
      </TabScreen>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
      <PermissionsSheet />
      {sheet}
    </>
  );
}
