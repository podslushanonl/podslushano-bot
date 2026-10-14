import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { feedPosts, Scope, useFeed } from '@/api/feed';
import { useContent } from '@/api/content';
import { queryClient } from '@/api/query';
import { CitySheet } from '@/features/common/CitySheet';
import { EventCard, JobCard, NewsCard, PostCard, SaveCard } from '@/features/feed/cards';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { NowCard } from '@/features/home/NowCard';
import { useCity, useCountry } from '@/lib/useCity';
import { radius, useTheme } from '@/theme';
import { Avatar, Button, Chip, Empty, Glass, Icon, IconButton, IconName, Segmented, Skeleton, TabScreen, Tap, Txt } from '@/ui';

const SERVICES: { title: string; icon: IconName; href: '/afisha' | '/trains' | '/jobs' | '/save'; accent?: boolean }[] = [
  { title: 'Афиша', icon: 'ticket', href: '/afisha' },
  { title: 'Поезда', icon: 'train', href: '/trains' },
  { title: 'Работа', icon: 'briefcase', href: '/jobs' },
  { title: 'Сэкономить', icon: 'tag', href: '/save', accent: true },
];

const SAVE_UNTIL = '2026-12-31';

function greeting(name?: string) {
  const h = Number(new Date().toLocaleString('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Europe/Amsterdam' }));
  const part = h < 5 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер';
  return name ? `${part},\n${name}` : part;
}

type Row = { k: string; ts: number; el: 'news' | 'post' | 'event' | 'job' | 'save'; data?: any };

export default function Home() {
  const { c } = useTheme();
  const { user } = useAuth();
  const [city, setCity] = useCity();
  const country = useCountry();
  const [picker, setPicker] = useState(false);
  const [filter, setFilter] = useState<'all' | 'friends' | 'near' | 'news'>('all');
  const [onlyCity, setOnlyCity] = useState(false);
  const content = useContent();
  // «Всё» — все посты вперемешку с новостями; «Друзья» и «Рядом» — только посты людей
  const scope: Scope = filter === 'friends' ? 'friends' : filter === 'near' ? 'near' : 'all';
  const posts = useFeed(scope, { city: filter === 'near' && onlyCity ? city : undefined, enabled: filter !== 'news' && (filter !== 'friends' || !!user) });
  const { openMenu, sheet } = usePostMenu();

  const rows = useMemo<Row[]>(() => {
    const news = content.data?.news || [];
    const ps = filter === 'news' ? [] : feedPosts(posts.data);
    const main: Row[] = [
      ...(filter === 'all' || filter === 'news' ? news.map((n) => ({ k: 'n' + n.id, ts: Date.parse(`${n.date}T${n.time || '00:00'}:00`) || 0, el: 'news' as const, data: n })) : []),
      ...ps.map((p) => ({ k: 'p' + p.id, ts: Date.parse(p.at) || 0, el: 'post' as const, data: p })),
    ].sort((a, b) => b.ts - a.ts);
    if (filter !== 'all') return main;
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
  }, [content.data, posts.data, filter]);

  let newsIdx = 0;

  return (
    <>
      <TabScreen
        title={greeting(user?.name)}
        refreshing={content.isRefetching || posts.isRefetching}
        onRefresh={() => { content.refetch(); posts.refetch(); queryClient.invalidateQueries({ queryKey: ['weather'] }); queryClient.invalidateQueries({ queryKey: ['ns'] }); }}
        above={
          <Tap onPress={() => setPicker(true)} scaleTo={0.95} style={{ alignSelf: 'flex-start', marginBottom: 6 }} accessibilityLabel={`Город: ${city}. Изменить`}>
            <Glass radius={radius.pill} interactive style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, height: 38 }}>
              <Icon name="location" size={15} />
              <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{city}</Txt>
              <Icon name="down" size={12} color={c.muted} />
            </Glass>
          </Tap>
        }
        right={<IconButton icon="edit" label="Написать пост" onPress={() => router.push(user ? '/new-post' : '/login')} />}>

        <NowCard city={city} />

        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          {SERVICES.map((s) => (
            <Tap key={s.href} onPress={() => router.push(s.href)} scaleTo={0.92} style={{ alignItems: 'center', gap: 8, width: '23%' }} accessibilityLabel={s.title}>
              <View style={{ width: 64, height: 64, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
                backgroundColor: s.accent ? c.accent : c.bgElevated, borderWidth: s.accent ? 0 : 1, borderColor: c.line }}>
                <Icon name={s.icon} size={26} color={s.accent ? c.onAccent : c.ink} />
              </View>
              <Txt v="footnote" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{s.title}</Txt>
            </Tap>
          ))}
        </View>

        <Tap onPress={() => router.push(user ? '/new-post' : '/login')} scaleTo={0.98}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.bgElevated, borderRadius: radius.pill, padding: 6, paddingRight: 8, borderWidth: 1, borderColor: c.line }}>
          {user ? <Avatar name={user.name} id={user.id} size={40} /> : <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: c.bgSunken, alignItems: 'center', justifyContent: 'center' }}><Icon name="person" size={20} color={c.muted} /></View>}
          <Txt v="callout" tone="muted" style={{ flex: 1 }}>{user ? `${user.name || 'Вы'}, что нового?` : 'Войдите, чтобы написать пост'}</Txt>
          <View style={{ backgroundColor: c.inverse, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 9 }}>
            <Txt v="subhead" color={c.onInverse} style={{ fontFamily: 'Onest_700Bold' }}>Написать</Txt>
          </View>
        </Tap>

        <View style={{ gap: 14 }}>
          <Txt v="title2">Лента</Txt>
          <Segmented value={filter} onChange={setFilter}
            items={[{ key: 'all', title: 'Всё' }, { key: 'friends', title: 'Друзья' }, { key: 'near', title: 'Рядом' }, { key: 'news', title: 'Новости' }]} />
          {filter === 'near' ? (
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Chip title={country} icon="globe" on={!onlyCity} onPress={() => setOnlyCity(false)} />
              <Chip title={city} icon="location" on={onlyCity} onPress={() => setOnlyCity(true)} />
            </View>
          ) : null}
        </View>

        {filter === 'friends' && !user ? (
          <Empty icon="people" title="Лента друзей" text="Войдите, добавьте друзей — и здесь будут их посты."
            action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
        ) : filter === 'friends' && !posts.isLoading && !rows.length ? (
          <Empty icon="people" title="Пока тихо" text="Здесь посты ваших друзей. Найдите знакомых и добавьте в друзья."
            action={<Button title="Найти друзей" kind="secondary" onPress={() => router.push('/friends')} />} />
        ) : filter === 'near' && !posts.isLoading && !rows.length ? (
          <Empty icon="location" title="Рядом пока тихо" text={`Станьте первым, кто напишет из ${onlyCity ? city : 'вашей страны'}.`}
            action={<Button title="Написать пост" kind="secondary" onPress={() => router.push(user ? '/new-post' : '/login')} />} />
        ) : (filter === 'all' || filter === 'news') && !content.data && content.isLoading ? (
          <View style={{ gap: 14 }}>{[0, 1].map((i) => <View key={i} style={{ gap: 10 }}><Skeleton h={190} r={28} /><Skeleton w="70%" /><Skeleton w="45%" h={12} /></View>)}</View>
        ) : rows.length ? (
          <View style={{ gap: 14 }}>
            {rows.map((r) => {
              if (r.el === 'news') return <NewsCard key={r.k} n={r.data} big={newsIdx++ % 4 === 0} />;
              if (r.el === 'post') return <PostCard key={r.k} p={r.data} onMenu={() => openMenu(r.data)} />;
              if (r.el === 'event') return <EventCard key={r.k} e={r.data} />;
              if (r.el === 'job') return <JobCard key={r.k} j={r.data} />;
              return <SaveCard key={r.k} />;
            })}
            {filter !== 'news' && posts.hasNextPage ? (
              <Button title="Показать ещё" kind="secondary" loading={posts.isFetchingNextPage} onPress={() => posts.fetchNextPage()} />
            ) : null}
          </View>
        ) : (
          <Txt v="callout" tone="muted" center>{content.isError ? 'Не получилось загрузить ленту. Потяните вниз, чтобы обновить.' : 'Пока пусто.'}</Txt>
        )}
      </TabScreen>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
      {sheet}
    </>
  );
}
