import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useMemo } from 'react';
import { RefreshControl, SectionList, StyleSheet, Text, View } from 'react-native';
import { Card, ErrorBox, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { EventItem } from '@/lib/api';
import { dayMonth, monthTitle, weekday } from '@/lib/format';
import { useApp } from '@/lib/useApp';

export default function Afisha() {
  const { data, error, refreshing, refresh } = useApp();
  const sections = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    (data?.events || []).forEach((e) => {
      const k = e.date.slice(0, 7);
      m.set(k, [...(m.get(k) || []), e]);
    });
    return [...m.entries()].map(([k, list]) => ({ title: monthTitle(k + '-01'), data: list }));
  }, [data]);

  if (!data) return error ? <ErrorBox onRetry={refresh} /> : <Loading />;
  return (
    <SectionList
      sections={sections}
      keyExtractor={(e) => e.key}
      contentContainerStyle={{ padding: 16, gap: 12 }}
      stickySectionHeadersEnabled={false}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={C.accent} />}
      ListEmptyComponent={<P muted>Ближайших событий пока нет.</P>}
      renderSectionHeader={({ section }) => <Text style={st.month}>{section.title}</Text>}
      renderItem={({ item: e }) => (
        <Card onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} style={st.row}>
          {e.img ? <Image source={e.img} style={st.poster} contentFit="cover" /> : <View style={[st.poster, { backgroundColor: C.accentSoft }]} />}
          <View style={{ flex: 1, gap: 4 }}>
            <Eyebrow>{weekday(e.date)}, {dayMonth(e.date)}{e.time ? ` · ${e.time}` : ''}</Eyebrow>
            <H size={16}>{e.h}</H>
            {e.s ? <P muted lines={2}>{e.s}</P> : null}
            <P muted lines={1}>{[e.venue, e.city].filter(Boolean).join(', ')}</P>
          </View>
        </Card>
      )}
    />
  );
}

const st = StyleSheet.create({
  month: { fontSize: 22, fontWeight: '800', color: C.ink, marginTop: 10, marginBottom: 2, letterSpacing: -0.4 },
  row: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  poster: { width: 84, height: 108, borderRadius: 14 },
});
