import { router } from 'expo-router';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Avatar, Icon, IconButton, Tap, Txt } from '@/ui';

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
      <Txt v="subhead" tone="accent" numberOfLines={1} style={{ fontFamily: 'Onest_600SemiBold', flexShrink: 1 }}>{label || 'Где вы живёте?'}</Txt>
      <Icon name="down" size={12} color={c.accentText} />
    </Tap>
  );
}

/** Правая часть шапки: поиск по провинции и профиль (аватар, если вошли). */
export function HeaderActions() {
  const { user } = useAuth();
  return (
    <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
      <IconButton icon="search" kind="surface" size={40} label="Поиск" onPress={() => router.push('/search')} />
      {user ? (
        <Tap onPress={() => router.push('/profile')} accessibilityLabel="Профиль" scaleTo={0.92} style={{ borderRadius: 20 }}>
          <Avatar name={user.name || 'Я'} id={user.id} uri={user.avatar} size={40} />
        </Tap>
      ) : <IconButton icon="person" kind="surface" size={40} label="Профиль и вход" onPress={() => router.push('/profile')} />}
    </View>
  );
}
