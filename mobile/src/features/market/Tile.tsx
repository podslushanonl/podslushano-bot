import { router } from 'expo-router';
import { View } from 'react-native';
import { CAT_ICON, Listing, photoUrl } from '@/api/market';
import { ago } from '@/lib/format';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Icon, Img, Tap, Txt } from '@/ui';

/** Карточка объявления в сетке из двух колонок (как в Vinted): крупное фото, цена, название, город. */
export function Tile({ l }: { l: Listing }) {
  const { c, shadow } = useTheme();
  const free = l.price_value === 0;
  return (
    <Tap onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(l.id) } })} scaleTo={0.97}
      accessibilityLabel={`${l.title}, ${l.price}, ${l.city}`}
      style={[{ borderRadius: radius.l, backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line, overflow: 'hidden' }, shadow]}>
      <View style={{ aspectRatio: 0.86, backgroundColor: c.placeholder }}>
        {l.photo ? <Img source={photoUrl(l)} style={{ width: '100%', height: '100%' }} recyclingKey={String(l.id)} />
          : <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: c.bgSunken }}>
              <Icon name={CAT_ICON[l.cat] || 'box'} thin size={40} color={c.faint} />
            </View>}
        {free ? (
          <View style={{ position: 'absolute', left: 8, top: 8, backgroundColor: c.accent, borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 4 }}>
            <Txt v="caption" color={c.onAccent} style={{ fontFamily: 'Onest_700Bold' }}>Даром</Txt>
          </View>
        ) : null}
      </View>
      <View style={{ padding: 10, paddingTop: 9, gap: 3 }}>
        <Txt v="headline" numberOfLines={1} style={{ fontFamily: 'Onest_700Bold' }}>{l.price}</Txt>
        <Txt v="subhead" tone="text" numberOfLines={2} style={{ minHeight: 40 }}>{l.title}</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3, marginTop: 2 }}>
          <Icon name="location" thin size={13} color={c.faint} />
          <Txt v="caption" color={c.faint} numberOfLines={1} style={{ flex: 1 }}>{[l.city, ago(l.at.slice(0, 10))].filter(Boolean).join(' · ')}</Txt>
        </View>
      </View>
    </Tap>
  );
}
