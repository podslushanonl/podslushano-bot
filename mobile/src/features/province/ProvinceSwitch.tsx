import { router } from 'expo-router';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Icon, IconButton, Tap, Txt } from '@/ui';

/** Переключатель места жительства в шапке раздела: «Oss ⌄» (или провинция, если город не указан). */
export function ProvinceSwitch() {
  const { c } = useTheme();
  const { province, home } = useProvince();
  const label = home?.name || province?.name;
  return (
    <Tap onPress={() => router.push('/province')} accessibilityRole="button"
      accessibilityLabel={`Место жительства: ${label || 'не выбрано'}. Сменить`}
      style={{ alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 6, height: 34, paddingLeft: 10, paddingRight: 12,
        borderRadius: radius.pill, backgroundColor: c.accentSoft }}>
      <Icon name="location" size={16} color={c.accentText} />
      <Txt v="subhead" tone="accent" numberOfLines={1} style={{ fontWeight: '600', flexShrink: 1 }}>{label || 'Где вы живёте?'}</Txt>
      <Icon name="down" size={12} color={c.accentText} />
    </Tap>
  );
}

/** Правая часть шапки: поиск. Профиль теперь отдельная вкладка нижнего меню. */
export function HeaderActions() {
  return <IconButton icon="search" kind="surface" size={40} label="Поиск" onPress={() => router.push('/search')} />;
}
