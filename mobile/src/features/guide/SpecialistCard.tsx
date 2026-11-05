import { router } from 'expo-router';
import { View } from 'react-native';
import { catTitle, Specialist } from '@/api/guide';
import { radius, useTheme } from '@/theme';
import { Icon, Img, Tap, Txt } from '@/ui';

/** Строка специалиста в списке контакт-гайда. */
export function SpecialistCard({ s }: { s: Specialist }) {
  const { c } = useTheme();
  const where = s.online && !s.city ? (s.premium ? 'Онлайн' : 'Онлайн по всей стране') : [s.city || s.province, s.online ? 'и онлайн' : ''].filter(Boolean).join(' ');
  return (
    <Tap onPress={() => router.push({ pathname: '/specialist/[id]', params: { id: String(s.id) } })} scaleTo={0.985}
      accessibilityLabel={`${s.name}, ${s.category}`}
      style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l, padding: 14,
        borderWidth: 1, borderColor: s.premium ? c.accent : c.line }}>
      {s.photo ? <Img source={s.photo} style={{ width: 48, height: 48, borderRadius: radius.m }} accessibilityIgnoresInvertColors /> : (
        <View style={{ width: 48, height: 48, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
          <Txt v="headline" tone="accent">{s.name.trim()[0]?.toUpperCase() || '·'}</Txt>
        </View>
      )}
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="overline" tone="accent" numberOfLines={1}>{catTitle(s.category)}</Txt>
        <Txt v="headline" numberOfLines={1}>{s.name}</Txt>
        {where || s.premium ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 2 }}>
            {s.premium ? <Recommended /> : null}
            {where ? <Txt v="footnote" numberOfLines={1} style={{ flexShrink: 1 }}>{where}</Txt> : null}
          </View>
        ) : null}
      </View>
      <Icon name="chevron" size={14} color={c.faint} />
    </Tap>
  );
}

/** Подпись платного размещения: показывается, пока не закончился оплаченный срок (сервер это проверяет). */
export function Recommended() {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, height: 20, borderRadius: 10, backgroundColor: c.accent }}>
      <Icon name="star" size={11} color={c.onAccent} />
      <Txt v="caption" color={c.onAccent} style={{ fontFamily: 'Onest_700Bold' }}>Рекомендуем</Txt>
    </View>
  );
}
