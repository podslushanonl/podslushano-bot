import { router } from 'expo-router';
import { View } from 'react-native';
import { CAT_ICON, Listing, photoUrl } from '@/api/market';
import { ago } from '@/lib/format';
import { radius, useTheme } from '@/theme';
import { Glass, Icon, Img, Tap, Txt } from '@/ui';

/** Карточка объявления в сетке: крупное фото, цена на стекле поверх фото. */
export function Tile({ l }: { l: Listing }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(l.id) } })} scaleTo={0.97}
      style={{ gap: 8 }} accessibilityLabel={`${l.title}${l.price ? `, ${l.price}` : ''}`}>
      <View style={{ borderRadius: radius.xl, overflow: 'hidden', aspectRatio: 0.82, backgroundColor: c.placeholder }}>
        {l.photo ? <Img source={photoUrl(l)} style={{ width: '100%', height: '100%' }} recyclingKey={String(l.id)} />
          : <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: c.accentSoft }}>
              <Icon name={CAT_ICON[l.cat] || 'box'} size={34} color={c.accentText} />
            </View>}
        {l.price ? (
          <View style={{ position: 'absolute', left: 8, bottom: 8, maxWidth: '86%' }}>
            <Glass radius={radius.pill} strong style={{ paddingHorizontal: 11, paddingVertical: 6 }}>
              <Txt v="price" numberOfLines={1} style={{ fontSize: 14, lineHeight: 18 }}>{l.price}</Txt>
            </Glass>
          </View>
        ) : null}
      </View>
      <View style={{ gap: 2, paddingHorizontal: 2 }}>
        <Txt v="subhead" tone="ink" numberOfLines={2} style={{ fontFamily: 'Onest_600SemiBold' }}>{l.title}</Txt>
        <Txt v="caption" numberOfLines={1}>{[l.city, ago(l.at.slice(0, 10))].filter(Boolean).join(' · ')}</Txt>
      </View>
    </Tap>
  );
}
