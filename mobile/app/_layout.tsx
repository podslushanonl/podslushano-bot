import { DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import 'react-native-reanimated';
import { C } from '@/constants/theme';

export { ErrorBoundary } from 'expo-router';

export const unstable_settings = { initialRouteName: '(tabs)' };

const theme = { ...DefaultTheme, colors: { ...DefaultTheme.colors, background: C.bg, primary: C.accent, text: C.ink, card: C.card, border: C.line } };

export default function RootLayout() {
  return (
    <ThemeProvider value={theme}>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerTintColor: C.ink, headerBackTitle: 'Назад', contentStyle: { backgroundColor: C.bg } }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="event/[key]" options={{ title: 'Событие' }} />
        <Stack.Screen name="login" options={{ title: 'Вход', presentation: 'modal' }} />
        <Stack.Screen name="profile" options={{ title: 'Профиль' }} />
        <Stack.Screen name="chat/[slug]" options={{ title: 'Чат' }} />
        <Stack.Screen name="rules" options={{ title: 'Правила', presentation: 'modal' }} />
        <Stack.Screen name="trains" options={{ title: 'Поезда NS' }} />
        <Stack.Screen name="market/[id]" options={{ title: 'Объявление' }} />
        <Stack.Screen name="market/new" options={{ title: 'Новое объявление', presentation: 'modal' }} />
        <Stack.Screen name="market/my" options={{ title: 'Мои объявления' }} />
        <Stack.Screen name="new-post" options={{ title: 'Новый пост', presentation: 'modal' }} />
      </Stack>
    </ThemeProvider>
  );
}
