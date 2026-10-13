import { Image } from 'expo-image';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo } from 'react';
import { FlatList, Linking, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button, Card, ErrorBox, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { EventItem, Job, News, TG_BOT, goUrl } from '@/lib/api';
import { ago, dayMonth, weekday } from '@/lib/format';
import { useApp } from '@/lib/useApp';

type Row =
  | { t: 'news'; k: string; n: News }
  | { t: 'event'; k: string; e: EventItem }
  | { t: 'job'; k: string; j: Job }
  | { t: 'save'; k: string };

const SAVE_UNTIL = '2026-12-31';

/** Лента: новости вперемешку с ближайшими событиями, вакансиями и «Сэкономить». */
function buildFeed(news: News[], events: EventItem[], jobs: Job[]): Row[] {
  const rows: Row[] = [];
  const today = new Date().toISOString().slice(0, 10);
  let ei = 0, ji = 0;
  news.forEach((n, i) => {
    rows.push({ t: 'news', k: 'n' + n.id, n });
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
  const insets = useSafeAreaInsets();
  const rows = useMemo(() => (data ? buildFeed(data.news, data.events, data.jobs) : []), [data]);

  if (!data) return error ? <ErrorBox onRetry={refresh} /> : <Loading />;
  return (
    <FlatList
      data={rows}
      keyExtractor={(r) => r.k}
      contentContainerStyle={{ padding: 16, paddingTop: insets.top + 12, gap: 14 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={C.accent} />}
      ListHeaderComponent={
        <View style={{ marginBottom: 4 }}>
          <Text style={st.logo}>podslushano</Text>
          <P muted>Жизнь в Нидерландах по-русски</P>
        </View>
      }
      renderItem={({ item }) =>
        item.t === 'news' ? <NewsCard n={item.n} /> : item.t === 'event' ? <EventCard e={item.e} /> :
        item.t === 'job' ? <JobCard j={item.j} /> : <SaveCard />}
    />
  );
}

const st = StyleSheet.create({
  logo: { fontSize: 30, fontWeight: '900', letterSpacing: -1, color: C.ink },
  cover: { width: '100%', aspectRatio: 16 / 9, backgroundColor: C.line },
  row: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  poster: { width: 76, height: 96, borderRadius: 14 },
});
