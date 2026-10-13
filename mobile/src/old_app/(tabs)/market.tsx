import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { MarketIcon } from '@/components/MarketIcon';
import { ErrorBox, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { useAuth } from '@/lib/auth';
import { ago } from '@/lib/format';
import { Category, Listing, browse, onMarketChanged, photoUrl } from '@/lib/market';

function Chip({ title, on, onPress }: { title: string; on: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipT, on && { color: '#fff' }]}>{title}</Text>
    </Pressable>
  );
}

function Tile({ l }: { l: Listing }) {
  return (
    <Pressable onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(l.id) } })}
      style={({ pressed }) => [s.tile, pressed && { opacity: 0.9, transform: [{ scale: 0.985 }] }]}>
      {l.photo ? <Image source={{ uri: photoUrl(l) }} style={s.photo} contentFit="cover" transition={150} />
        : <View style={[s.photo, s.noPhoto]}><MarketIcon name={l.cat} color={C.accent} size={34} /></View>}
      <View style={{ padding: 10, gap: 3 }}>
        {l.price ? <Text style={s.price} numberOfLines={1}>{l.price}</Text> : null}
        <Text style={s.title} numberOfLines={2}>{l.title}</Text>
        <Text style={s.meta} numberOfLines={1}>{[l.city, ago(l.at.slice(0, 10))].filter(Boolean).join(' · ')}</Text>
      </View>
    </Pressable>
  );
}

export default function Market() {
  const { user } = useAuth();
  const [cat, setCat] = useState('');
  const [city, setCity] = useState('');
  const [q, setQ] = useState('');
  const [items, setItems] = useState<Listing[] | null>(null);
  const [cats, setCats] = useState<Category[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const req = useRef(0);

  const load = useCallback(async (offset = 0) => {
    const id = ++req.current;
    try {
      const d = await browse({ cat, city, q: q.trim(), offset });
      if (id !== req.current) return; // пришёл ответ на старый фильтр
      setItems((cur) => (offset ? [...(cur || []), ...d.items] : d.items));
      setMore(d.more); setCats(d.categories); setCities(d.cities); setError(false);
    } catch { if (id === req.current) setError(true); }
  }, [cat, city, q]);

  useEffect(() => { const t = setTimeout(() => load(0), q ? 350 : 0); return () => clearTimeout(t); }, [load, q]);
  useEffect(() => onMarketChanged(() => load(0)), [load]);

  const cityList = [...new Set([...(user?.city ? [user.city] : []), ...cities])];
  const header = (
    <View style={{ gap: 10, marginBottom: 6 }}>
      <TextInput value={q} onChangeText={setQ} placeholder="Поиск: коляска, велосипед, диван…" placeholderTextColor={C.muted}
        returnKeyType="search" style={s.search} />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.row}>
        <Chip title="Все" on={!cat} onPress={() => setCat('')} />
        {cats.map((c) => <Chip key={c.key} title={c.title} on={cat === c.key} onPress={() => setCat(cat === c.key ? '' : c.key)} />)}
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.row}>
        <Chip title="Все города" on={!city} onPress={() => setCity('')} />
        {cityList.map((c) => <Chip key={c} title={c} on={city === c} onPress={() => setCity(city === c ? '' : c)} />)}
      </ScrollView>
      <View style={[s.row, { justifyContent: 'space-between' }]}>
        <Pressable onPress={() => router.push(user ? '/market/new' : '/login')} style={s.add}>
          <Text style={s.addT}>+ Подать объявление</Text>
        </Pressable>
        {user ? <Pressable onPress={() => router.push('/market/my')} style={s.mine}><Text style={s.mineT}>Мои объявления</Text></Pressable> : null}
      </View>
    </View>
  );

  if (!items) return error ? <ErrorBox onRetry={() => load(0)} /> : <Loading />;
  return (
    <FlatList
      data={items}
      keyExtractor={(l) => String(l.id)}
      numColumns={2}
      columnWrapperStyle={{ gap: 12 }}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 40 }}
      ListHeaderComponent={header}
      keyboardShouldPersistTaps="handled"
      renderItem={({ item }) => <Tile l={item} />}
      ListEmptyComponent={<View style={{ paddingVertical: 30 }}><P muted>Пока ничего не нашлось. Попробуйте другой город или категорию — или подайте своё объявление.</P></View>}
      onEndReachedThreshold={0.4}
      onEndReached={() => { if (more) { setMore(false); load(items.length); } }}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={C.accent}
        onRefresh={async () => { setRefreshing(true); await load(0); setRefreshing(false); }} />}
    />
  );
}

const s = StyleSheet.create({
  search: { backgroundColor: C.card, borderRadius: 999, borderWidth: 1, borderColor: C.line, paddingHorizontal: 16, paddingVertical: 11, fontSize: 16, color: C.ink },
  row: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  chipOn: { backgroundColor: C.ink, borderColor: C.ink },
  chipT: { fontSize: 14, fontWeight: '600', color: C.ink },
  add: { backgroundColor: C.accent, borderRadius: 999, paddingHorizontal: 16, paddingVertical: 10 },
  addT: { color: '#fff', fontWeight: '700', fontSize: 15 },
  mine: { paddingHorizontal: 8, paddingVertical: 10 },
  mineT: { color: C.accent, fontWeight: '700', fontSize: 15 },
  tile: { flex: 1, maxWidth: '48.5%', backgroundColor: C.card, borderRadius: 18, overflow: 'hidden', borderWidth: 1, borderColor: C.line },
  photo: { width: '100%', aspectRatio: 1, backgroundColor: C.bg },
  noPhoto: { alignItems: 'center', justifyContent: 'center', backgroundColor: C.accentSoft },
  price: { fontSize: 16, fontWeight: '800', color: C.ink },
  title: { fontSize: 14, color: C.text, lineHeight: 18 },
  meta: { fontSize: 12, color: C.muted },
});
