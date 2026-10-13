import { Image } from 'expo-image';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useState } from 'react';
import { FlatList, Linking, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ActionSheet, SheetAction } from '@/components/ActionSheet';
import { Button, Card, ErrorBox, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { EventItem, Job, News, TG_BOT, goUrl } from '@/lib/api';
import { ago, dayMonth, weekday } from '@/lib/format';
import { useAuth } from '@/lib/auth';
import { Msg, block, removeOwn, report, routeForError, timeLabel } from '@/lib/community';
import { useApp } from '@/lib/useApp';
import { usePosts } from '@/lib/usePosts';

type Row =
  | { t: 'news'; k: string; n: News }
  | { t: 'event'; k: string; e: EventItem }
  | { t: 'job'; k: string; j: Job }
  | { t: 'save'; k: string }
  | { t: 'post'; k: string; p: Msg };

const SAVE_UNTIL = '2026-12-31';

/** Лента: новости вперемешку с ближайшими событиями, вакансиями и «Сэкономить». */
function buildFeed(news: News[], events: EventItem[], jobs: Job[], posts: Msg[]): Row[] {
  const rows: Row[] = [];
  const today = new Date().toISOString().slice(0, 10);
  // Новости и посты сообщества — по времени, между ними события, вакансии и «Сэкономить»
  const main: ({ ts: number; row: Row })[] = [
    ...news.map((n) => ({ ts: Date.parse(`${n.date}T${n.time || '00:00'}:00`) || 0, row: { t: 'news', k: 'n' + n.id, n } as Row })),
    ...posts.map((p) => ({ ts: Date.parse(p.at) || 0, row: { t: 'post', k: 'p' + p.id, p } as Row })),
  ].sort((a, b) => b.ts - a.ts);
  let ei = 0, ji = 0;
  main.forEach(({ row }, i) => {
    rows.push(row);
    if (i === 1 && today <= SAVE_UNTIL) rows.push({ t: 'save', k: 'save' });
    if (i % 3 === 2 && events[ei]) { rows.push({ t: 'event', k: 'e' + events[ei].key, e: events[ei] }); ei++; }
    if (i % 7 === 6 && jobs[ji]) { rows.push({ t: 'job', k: 'j' + jobs[ji].id, j: jobs[ji] }); ji++; }
  });
  return rows;
}

const open = (url: string) => WebBrowser.openBrowserAsync(url).catch(() => Linking.openURL(url));

function NewsCard({ n }: { n: News }) {
  return (
    <Card onPress={() => open(n.link)} style={{ padding: 0, overflow: 'hidden' }}>
      {n.img ? <Image source={n.img} style={st.cover} contentFit="cover" transition={150} /> : null}
      <View style={{ padding: 16, gap: 6 }}>
        <Eyebrow color={C.muted}>{n.cat} · {ago(n.date, n.time)}</Eyebrow>
        <H>{n.h}</H>
        {n.lead ? <P muted lines={3}>{n.lead}</P> : null}
      </View>
    </Card>
  );
}

function EventCard({ e }: { e: EventItem }) {
  return (
    <Card onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} style={st.row}>
      {e.img ? <Image source={e.img} style={st.poster} contentFit="cover" /> : <View style={[st.poster, { backgroundColor: C.accentSoft }]} />}
      <View style={{ flex: 1, gap: 4 }}>
        <Eyebrow>Афиша · {weekday(e.date)}, {dayMonth(e.date)}</Eyebrow>
        <H size={16}>{e.h}</H>
        <P muted lines={2}>{[e.venue, e.city].filter(Boolean).join(', ')}</P>
      </View>
    </Card>
  );
}

function JobCard({ j }: { j: Job }) {
  return (
    <Card onPress={() => j.url && open(j.url)}>
      <Eyebrow color={C.info}>Работа · {j.city || 'Нидерланды'}</Eyebrow>
      <H size={16}>{j.title}</H>
      <P muted lines={2}>{[j.company, j.salary, j.lang].filter(Boolean).join(' · ')}</P>
    </Card>
  );
}

function PostCard({ p, onMenu }: { p: Msg; onMenu: () => void }) {
  return (
    <Card style={{ gap: 6 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <View style={st.ava}><Text style={st.avaT}>{p.author.name.slice(0, 1).toUpperCase()}</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={st.pName}>{p.author.name}</Text>
          <Text style={st.pMeta}>{[p.city, timeLabel(p.at)].filter(Boolean).join(' · ')}</Text>
        </View>
        <Pressable onPress={onMenu} hitSlop={12} accessibilityLabel="Действия"><Text style={st.more}>⋯</Text></Pressable>
      </View>
      <P>{p.text}</P>
    </Card>
  );
}

function SaveCard() {
  return (
    <Card style={{ backgroundColor: C.accentSoft, borderColor: '#FFD9C2' }}>
      <Eyebrow>Сэкономить · до 31 декабря</Eyebrow>
      <H>Не переплачивайте за медстраховку</H>
      <P>Базовый пакет у всех страховщиков одинаковый, разница только в цене. 6 вопросов, и вы будете знать, на что смотреть.</P>
      <View style={{ flexDirection: 'row', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
        <Button title="6 вопросов" onPress={() => Linking.openURL(`${TG_BOT}?start=save_zorg`)} />
        <Button title="Сравнить цены" soft onPress={() => open(goUrl('zorg_compare'))} />
      </View>
    </Card>
  );
}

export default function Feed() {
  const { data, error, refreshing, refresh } = useApp();
  const { user } = useAuth();
  const { posts, reload, setPosts } = usePosts();
  const [menu, setMenu] = useState<Msg | null>(null);
  const [note, setNote] = useState('');
  const insets = useSafeAreaInsets();
  const rows = useMemo(() => (data ? buildFeed(data.news, data.events, data.jobs, posts) : []), [data, posts]);
  const write = () => (user ? router.push('/new-post') : router.push('/login'));
  const fail = (e: any) => { if (!routeForError(e)) setNote(e?.message || 'Ошибка'); };
  const actions = (p: Msg): SheetAction[] => p.mine
    ? [{ title: 'Удалить пост', danger: true, onPress: () => removeOwn('post', p.id).then(reload).catch(fail) }]
    : [
        { title: 'Пожаловаться', danger: true, onPress: () => report('post', p.id).then(() => setNote('Спасибо, жалоба отправлена модераторам.')).catch(fail) },
        { title: `Скрыть посты: ${p.author.name}`, onPress: () => block(p.author.id).then(() => setPosts((c) => c.filter((x) => x.author.id !== p.author.id))).catch(fail) },
      ];

  if (!data) return error ? <ErrorBox onRetry={refresh} /> : <Loading />;
  return (
    <FlatList
      data={rows}
      keyExtractor={(r) => r.k}
      contentContainerStyle={{ padding: 16, paddingTop: insets.top + 12, gap: 14 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { refresh(); reload(); }} tintColor={C.accent} />}
      ListHeaderComponent={
        <View style={{ marginBottom: 4, gap: 12 }}>
          <View>
            <Text style={st.logo}>podslushano</Text>
            <P muted>Жизнь в Нидерландах по-русски</P>
          </View>
          <Pressable onPress={write} style={st.compose}>
            <Text style={st.composeT}>{user ? `${user.name || 'Вы'}, что нового?` : 'Войдите, чтобы написать пост'}</Text>
            <Text style={st.composeBtn}>Написать</Text>
          </Pressable>
          {note ? <Text style={st.note} onPress={() => setNote('')}>{note}</Text> : null}
        </View>
      }
      renderItem={({ item }) =>
        item.t === 'news' ? <NewsCard n={item.n} /> : item.t === 'event' ? <EventCard e={item.e} /> :
        item.t === 'job' ? <JobCard j={item.j} /> : item.t === 'post' ? <PostCard p={item.p} onMenu={() => (user ? setMenu(item.p) : router.push('/login'))} /> : <SaveCard />}
      ListFooterComponent={<ActionSheet visible={!!menu} actions={menu ? actions(menu) : []} onClose={() => setMenu(null)} />}
    />
  );
}

const st = StyleSheet.create({
  logo: { fontSize: 30, fontWeight: '900', letterSpacing: -1, color: C.ink },
  cover: { width: '100%', aspectRatio: 16 / 9, backgroundColor: C.line },
  row: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  poster: { width: 76, height: 96, borderRadius: 14 },
  compose: { flexDirection: 'row', alignItems: 'center', backgroundColor: C.card, borderRadius: 999, borderWidth: 1, borderColor: C.line, paddingLeft: 16, paddingRight: 6, paddingVertical: 6 },
  composeT: { flex: 1, color: C.muted, fontSize: 15 },
  composeBtn: { backgroundColor: C.accent, color: '#fff', fontWeight: '700', borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, overflow: 'hidden' },
  note: { backgroundColor: C.accentSoft, color: C.ink, padding: 10, borderRadius: 12 },
  ava: { width: 38, height: 38, borderRadius: 19, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  avaT: { color: C.accent, fontWeight: '800', fontSize: 16 },
  pName: { fontSize: 15, fontWeight: '700', color: C.ink },
  pMeta: { fontSize: 12.5, color: C.muted },
  more: { fontSize: 22, color: C.muted, paddingHorizontal: 4 },
});
