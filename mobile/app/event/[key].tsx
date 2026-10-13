import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button, Card, ErrorBox, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { SITE } from '@/lib/api';
import { dayMonth, weekday } from '@/lib/format';
import { toggleFavorite, useAuth } from '@/lib/auth';
import { useApp } from '@/lib/useApp';

export default function EventScreen() {
  const { key } = useLocalSearchParams<{ key: string }>();
  // При открытии по ссылке (podslushano://event/...) данных ещё нет: грузим, а не говорим «не найдено»
  const { data, error, refresh } = useApp();
  const { user, favorites } = useAuth();
  if (!data) return error ? <ErrorBox onRetry={refresh} /> : <Loading />;
  const e = data.events.find((x) => x.key === String(key));
  if (!e) return <View style={{ padding: 24 }}><P muted>Событие не найдено.</P></View>;
  const when = `${weekday(e.date)}, ${dayMonth(e.date)}${e.end && e.end !== e.date ? ` — ${dayMonth(e.end)}` : ''}${e.time ? ` · ${e.time}` : ''}`;
  const ticket = e.tickets?.[0]?.[2] || e.url;
  const fav = favorites.some((f) => f.key === e.key);
  const heart = () => (user ? toggleFavorite(e.key, e.h, !fav).catch(() => {}) : router.push('/login'));
  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
      <Stack.Screen options={{ title: e.h, headerRight: () => (
        <Pressable onPress={heart} hitSlop={12} accessibilityLabel={fav ? 'Убрать из избранного' : 'В избранное'}>
          <Text style={{ fontSize: 24, color: fav ? C.accent : C.muted }}>{fav ? '♥' : '♡'}</Text>
        </Pressable>
      ) }} />
      {e.img ? <Image source={e.img} style={st.img} contentFit="cover" /> : null}
      <View style={{ padding: 16, gap: 12 }}>
        <Eyebrow>{e.cat || 'событие'}</Eyebrow>
        <H size={26}>{e.h}</H>
        {e.s ? <P>{e.s}</P> : null}
        <Card>
          <Row k="Когда" v={when} />
          {e.venue ? <Row k="Где" v={[e.venue, e.addr || e.city].filter(Boolean).join(', ')} /> : null}
          {e.price ? <Row k="Цена" v={e.price} /> : null}
        </Card>
        {(e.p || []).map((t, i) => <P key={i}>{t}</P>)}
        {ticket ? <Button title="Билеты" onPress={() => WebBrowser.openBrowserAsync(ticket)} /> : null}
        <Button title="Открыть на сайте" soft onPress={() => WebBrowser.openBrowserAsync(`${SITE}/events/${e.key}/`)} />
      </View>
    </ScrollView>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <View style={st.row}>
      <P muted>{k}</P>
      <View style={{ flex: 1 }}><P>{v}</P></View>
    </View>
  );
}

const st = StyleSheet.create({
  img: { width: '100%', aspectRatio: 4 / 5, maxHeight: 520, backgroundColor: C.line },
  row: { flexDirection: 'row', gap: 12, paddingVertical: 4 },
});
