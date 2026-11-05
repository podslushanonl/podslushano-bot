import { router } from 'expo-router';
import { View } from 'react-native';
import { catTitle, Specialist } from '@/api/guide';
import { radius, useTheme } from '@/theme';
import { Icon, Tap, Txt } from '@/ui';

/** Строка специалиста в списке контакт-гайда. */
export function SpecialistCard({ s }: { s: Specialist }) {
  const { c } = useTheme();
  const where = s.online && !s.city ? 'Онлайн по всей стране' : [s.city, s.online ? 'и онлайн' : ''].filter(Boolean).join(' ');
  return (
    <Tap onPress={() => router.push({ pathname: '/specialist/[id]', params: { id: String(s.id) } })} scaleTo={0.985}
      accessibilityLabel={`${s.name}, ${s.category}`}
      style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l, padding: 14,
        borderWidth: 1, borderColor: s.premium ? c.accent : c.line }}>
      <View style={{ width: 48, height: 48, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
        <Txt v="headline" tone="accent">{s.name.trim()[0]?.toUpperCase() || '·'}</Txt>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="overline" tone="accent" numberOfLines={1}>{catTitle(s.category)}</Txt>
        <Txt v="headline" numberOfLines={1}>{s.name}</Txt>
        {where ? <Txt v="footnote" numberOfLines={1}>{where}</Txt> : null}
      </View>
      <Icon name="chevron" size={14} color={c.faint} />
    </Tap>
  );
}
