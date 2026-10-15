import { router } from 'expo-router';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { ProfileView } from '@/features/profile/ProfileView';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Button, IconButton, TabScreen, Txt } from '@/ui';

/** Вкладка «Профиль»: моя страница как в соцсети; настройки — за шестерёнкой. */
export default function Profile() {
  const { c } = useTheme();
  const { user, ready } = useAuth();
  if (ready && user) return <ProfileView userId={user.id} own />;
  return (
    <TabScreen title="Профиль" right={<IconButton icon="settings" label="Настройки" onPress={() => router.push('/settings')} />}>
      {ready ? (
        <View style={{ backgroundColor: c.hero, borderRadius: radius.xxl, borderWidth: HAIRLINE, borderColor: c.line, padding: 22, gap: 12 }}>
          <Txt v="overline" color={c.accent}>Мой podslushano</Txt>
          <Txt v="title2" color={c.onHero}>Ваша страница, друзья, лента и сообщения</Txt>
          <Txt v="callout" color={c.onHeroMuted}>Пароль не нужен: код по SMS или на почту. Аккаунт создаётся сам.</Txt>
          <Button title="Войти или создать аккаунт" kind="accent" onPress={() => router.push('/login')} />
        </View>
      ) : null}
    </TabScreen>
  );
}
