import { router } from 'expo-router';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Avatar, Icon, IconButton, Tap, Txt } from '@/ui';

/** Переключатель провинции под заголовком раздела: «Noord-Brabant ⌄». Открывает список провинций. */
export function ProvinceSwitch() {
  const { c } = useTheme();
  const { province } = useProvince();
  return (
    <Tap onPress={() => router.push('/province')} accessibilityRole="button"
      accessibilityLabel={`Провинция ${province?.name || 'не выбрана'}. Сменить`}
      style={{ alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 6, height: 34, paddingLeft: 10, paddingRight: 12,
        borderRadius: radius.pill, backgroundColor: c.accentSoft }}>
      <Icon name="location" size={16} color={c.accentText} />
      <Txt v="subhead" tone="accent" style={{ fontFamily: 'Onest_600SemiBold' }}>{province?.name || 'Выбрать провинцию'}</Txt>
      <Icon name="down" size={12} color={c.accentText} />
    </Tap>
  );
}

/** Правая часть шапки: поиск и профиль (аватар, если вошли). */
export function HeaderActions({ onSearch }: { onSearch?: () => void }) {
  const { user } = useAuth();
  return (
    <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
      {onSearch ? <IconButton icon="search" label="Поиск" onPress={onSearch} /> : null}
      {user ? (
        <Tap onPress={() => router.push('/profile')} accessibilityLabel="Профиль" scaleTo={0.92} style={{ borderRadius: 22 }}>
          <Avatar name={user.name || 'Я'} id={user.id} uri={user.avatar} size={44} />
        </Tap>
      ) : <IconButton icon="person" label="Профиль и вход" onPress={() => router.push('/profile')} />}
    </View>
  );
}
