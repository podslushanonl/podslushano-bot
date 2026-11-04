import { router } from 'expo-router';
import { View } from 'react-native';
import { kindOf, Place } from '@/api/places';
import { radius, useTheme } from '@/theme';
import { Icon, Img, Tap, Txt } from '@/ui';

/** Строка места в списке: фото, тип, название, город. */
export function PlaceCard({ p }: { p: Place }) {
  const { c } = useTheme();
  const k = kindOf(p.kinds[0]);
  return (
    <Tap onPress={() => router.push({ pathname: '/place/[id]', params: { id: p.id } })} scaleTo={0.985}
      accessibilityLabel={`${k.one}: ${p.name}${p.town ? `, ${p.town}` : ''}`}
      style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l, padding: 12,
        borderWidth: 1, borderColor: c.line }}>
      {p.img ? <Img source={p.img} style={{ width: 76, height: 76, borderRadius: radius.m }} />
        : (
          <View style={{ width: 76, height: 76, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name={k.icon} size={26} color={c.accentText} />
          </View>
        )}
      <View style={{ flex: 1, gap: 3 }}>
        <Txt v="overline" tone="accent" numberOfLines={1}>{k.one}</Txt>
        <Txt v="headline" numberOfLines={2}>{p.name}</Txt>
        {p.town ? <Txt v="footnote" numberOfLines={1}>{p.town}</Txt> : null}
      </View>
      <Icon name="chevron" size={14} color={c.faint} />
    </Tap>
  );
}
