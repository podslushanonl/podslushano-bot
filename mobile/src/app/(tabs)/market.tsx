import { FlashList } from '@shopify/flash-list';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { RefreshControl, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { Listing, useMarket, useMarketMeta } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { Tile } from '@/features/market/Tile';
import { useCity, useCountry } from '@/lib/useCity';
import { radius, type as T, useTheme } from '@/theme';
import { Button, ChipRow, Empty, Glass, Icon, IconButton, LargeTitle, Skeleton, TAB_SPACE, Tap, TopBar, Txt, useScrollY } from '@/ui';

export default function Market() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const [myCity] = useCity();
  const country = useCountry();
  const [cat, setCat] = useState('');
  const [city, setCity] = useState('');
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [picker, setPicker] = useState(false);
  const { y, onScroll } = useScrollY();
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 350); return () => clearTimeout(t); }, [q]);

  const meta = useMarketMeta();
  const market = useMarket({ cat, city, q: debounced });
  const items = useMemo<Listing[]>(() => market.data?.pages.flatMap((p) => p.items) || [], [market.data]);
  const cats = [{ key: '', title: 'Все' }, ...(meta.data?.categories || []).map((x) => ({ key: x.key, title: x.title }))];
  const add = () => router.push(user ? '/market/new' : '/login');

  const header = (
    <View style={{ gap: 14, paddingBottom: 16 }}>
      <LargeTitle title="Барахолка" right={user ? <Button title="Мои" kind="secondary" size="s" full={false} onPress={() => router.push('/market/my')} /> : undefined} />
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, height: 50, borderRadius: radius.l, paddingHorizontal: 14,
          backgroundColor: c.bgElevated, borderWidth: 1, borderColor: c.line }}>
          <Icon name="search" size={19} color={c.muted} />
          <TextInput value={q} onChangeText={setQ} placeholder="Коляска, велосипед, диван" placeholderTextColor={c.faint} returnKeyType="search"
            accessibilityLabel="Поиск по объявлениям" style={[T.callout, { flex: 1, color: c.ink, outlineStyle: 'none' } as any]} />
          {q ? <IconButton icon="close" label="Очистить поиск" kind="plain" size={32} onPress={() => setQ('')} /> : null}
        </View>
        <Tap onPress={() => setPicker(true)} scaleTo={0.94} accessibilityLabel={city ? `Город: ${city}` : 'Выбрать город'}
          style={{ height: 50, paddingHorizontal: 14, borderRadius: radius.l, backgroundColor: city ? c.inverse : c.bgElevated, borderWidth: city ? 0 : 1, borderColor: c.line,
            flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Icon name="location" size={17} color={city ? c.onInverse : c.ink} />
          <Txt v="subhead" color={city ? c.onInverse : c.ink} style={{ fontFamily: 'Onest_600SemiBold' }}>{city || 'Все'}</Txt>
        </Tap>
      </View>
      <ChipRow items={cats} value={cat} onChange={setCat} />
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <FlashList
        data={items}
        numColumns={2}
        keyExtractor={(l) => String(l.id)}
        onScroll={onScroll}
        scrollEventThrottle={16}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingTop: insets.top + 64, paddingHorizontal: 14, paddingBottom: TAB_SPACE + insets.bottom + 70 }}
        ListHeaderComponent={<View style={{ paddingHorizontal: 6 }}>{header}</View>}
        renderItem={({ item }) => <View style={{ paddingHorizontal: 6, paddingBottom: 18 }}><Tile l={item} /></View>}
        ListEmptyComponent={market.isLoading ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, paddingHorizontal: 6 }}>
            {[0, 1, 2, 3].map((i) => <View key={i} style={{ width: '47.5%', gap: 8 }}><Skeleton h={200} r={28} /><Skeleton w="80%" /><Skeleton w="50%" h={12} /></View>)}
          </View>
        ) : (
          <Empty icon="market" title={debounced || cat || city ? 'Ничего не нашлось' : 'Пока нет объявлений'}
            text={debounced || cat || city ? 'Попробуйте другой запрос, категорию или город.' : 'Станьте первым — подать объявление бесплатно.'}
            action={<Button title="Подать объявление" kind="primary" icon="plus" onPress={add} />} />
        )}
        onEndReachedThreshold={0.5}
        onEndReached={() => { if (market.hasNextPage && !market.isFetchingNextPage) market.fetchNextPage(); }}
        refreshControl={<RefreshControl refreshing={market.isRefetching && !market.isFetchingNextPage} onRefresh={() => market.refetch()} tintColor={c.accent} />}
      />
      <TopBar y={y} title="Барахолка" />
      <View pointerEvents="box-none" style={{ position: 'absolute', right: 18, bottom: TAB_SPACE + insets.bottom - 6 }}>
        <Tap onPress={add} scaleTo={0.92} haptic="medium" accessibilityLabel="Подать объявление">
          <Glass radius={radius.pill} tint={c.accent} interactive style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 20, height: 54,
            backgroundColor: c.accent } as any}>
            <Icon name="plus" size={20} color={c.onAccent} />
            <Txt v="bodyStrong" color={c.onAccent} style={{ fontFamily: 'Onest_700Bold' }}>Подать</Txt>
          </Glass>
        </Tap>
      </View>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} extra={[myCity]} allLabel="Все города" />
    </View>
  );
}
