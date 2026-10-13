import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, SectionList, StyleSheet, Text, View } from 'react-native';
import { ErrorBox, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { Room, rooms } from '@/lib/community';

export default function Chats() {
  const [list, setList] = useState<Room[] | null>(null);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setList(await rooms()); setError(false); } catch { setError(true); }
  }, []);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);

  if (!list) return error ? <ErrorBox onRetry={load} /> : <Loading />;
  const sections = [
    { title: 'Города', data: list.filter((r) => r.kind === 'city') },
    { title: 'Темы', data: list.filter((r) => r.kind === 'topic') },
  ];
  return (
    <SectionList
      sections={sections}
      keyExtractor={(r) => r.slug}
      contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      stickySectionHeadersEnabled={false}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={C.accent} />}
      ListHeaderComponent={<P muted>Общайтесь с русскоязычными в своём городе и по темам. Будьте вежливы: у нас есть модерация.</P>}
      renderSectionHeader={({ section }) => <Text style={s.sec}>{section.title}</Text>}
      renderItem={({ item, index, section }) => (
        <Pressable onPress={() => router.push({ pathname: '/chat/[slug]', params: { slug: item.slug, title: item.title } })}
          style={({ pressed }) => [s.row, index === 0 && s.first, index === section.data.length - 1 && s.last, pressed && { opacity: 0.7 }]}>
          <View style={[s.dot, { backgroundColor: item.kind === 'city' ? C.accent : C.info }]}>
            <Text style={s.dotT}>{item.title.slice(0, 1)}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.t}>{item.title}</Text>
            <Text style={s.d}>{item.today ? `${item.today} сообщ. за сутки` : 'Начните разговор'}</Text>
          </View>
          <Text style={s.chev}>›</Text>
        </Pressable>
      )}
    />
  );
}

const s = StyleSheet.create({
  sec: { fontSize: 13, fontWeight: '700', color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8, marginTop: 18, marginBottom: 8, marginLeft: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: C.card, paddingHorizontal: 14, paddingVertical: 12, borderColor: C.line, borderLeftWidth: 1, borderRightWidth: 1, borderBottomWidth: 1 },
  first: { borderTopWidth: 1, borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  last: { borderBottomLeftRadius: 20, borderBottomRightRadius: 20 },
  dot: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  dotT: { color: '#fff', fontWeight: '800', fontSize: 17 },
  t: { fontSize: 16, fontWeight: '700', color: C.ink },
  d: { fontSize: 13, color: C.muted, marginTop: 2 },
  chev: { fontSize: 24, color: C.muted },
});
