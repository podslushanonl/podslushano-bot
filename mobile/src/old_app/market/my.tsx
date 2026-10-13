import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { MarketIcon } from '@/components/MarketIcon';
import { Button, ErrorBox, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { routeForError } from '@/lib/community';
import { Listing, myListings, onMarketChanged, photoUrl } from '@/lib/market';

const STATUS_COLOR: Record<string, string> = { approved: C.ok, pending: C.info, awaiting_payment: C.accent, rejected: C.warn };

export default function MyListings() {
  const [items, setItems] = useState<Listing[] | null>(null);
  const [max, setMax] = useState(5);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { const d = await myListings(); setItems(d.items); setMax(d.max); setError(false); }
    catch (e) { if (!routeForError(e)) setError(true); }
  }, []);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  useEffect(() => onMarketChanged(load), [load]);

  if (!items) return error ? <ErrorBox onRetry={load} /> : <Loading />;
  return (
    <FlatList
      data={items}
      keyExtractor={(l) => String(l.id)}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: 40 }}
      ListHeaderComponent={<View style={{ gap: 12, marginBottom: 4 }}>
        <P muted>{`Одновременно можно держать до ${max} активных объявлений. Публикация — на 30 дней после проверки.`}</P>
        <Button title="+ Подать объявление" onPress={() => router.push('/market/new')} />
      </View>}
      ListEmptyComponent={<P muted>Здесь появятся ваши объявления.</P>}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={C.accent}
        onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      renderItem={({ item: l }) => (
        <Pressable onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(l.id) } })}
          style={({ pressed }) => [s.row, pressed && { opacity: 0.8 }]}>
          {l.photo ? <Image source={{ uri: photoUrl(l) }} style={s.thumb} contentFit="cover" />
            : <View style={[s.thumb, s.noPhoto]}><MarketIcon name={l.cat} color={C.accent} /></View>}
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={s.title} numberOfLines={2}>{l.title}</Text>
            <Text style={[s.status, { color: STATUS_COLOR[l.status || ''] || C.muted }]}>{l.status_title}</Text>
          </View>
          <Text style={s.chev}>›</Text>
        </Pressable>
      )}
    />
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: C.card, borderRadius: 18, borderWidth: 1, borderColor: C.line, padding: 10 },
  thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: C.line },
  noPhoto: { alignItems: 'center', justifyContent: 'center', backgroundColor: C.accentSoft },
  title: { fontSize: 15, fontWeight: '700', color: C.ink },
  status: { fontSize: 13, fontWeight: '700' },
  chev: { fontSize: 24, color: C.muted },
});
