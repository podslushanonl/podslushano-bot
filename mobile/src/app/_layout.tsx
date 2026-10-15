import { Onest_400Regular, Onest_500Medium, Onest_600SemiBold, Onest_700Bold } from '@expo-google-fonts/onest';
import { Unbounded_600SemiBold, Unbounded_700Bold } from '@expo-google-fonts/unbounded';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { bootAuth, useAuth } from '@/api/auth';
import { useRealtime } from '@/api/dm';
import { persister, queryClient } from '@/api/query';
import { SwipeBack, WEB } from '@/features/nav/SwipeBack';
import { palette, ThemeRoot } from '@/theme';
import { ToastHost } from '@/ui';

export { ErrorBoundary } from 'expo-router';
export const unstable_settings = { initialRouteName: '(tabs)' };

SplashScreen.preventAutoHideAsync().catch(() => {});

/** Живое соединение для сообщений — пока пользователь вошёл. */
function Realtime() {
  const { user } = useAuth();
  useRealtime(user?.id ?? 0);
  return null;
}

export default function RootLayout() {
  const scheme = useColorScheme();
  const [fontsLoaded, fontError] = useFonts({
    Onest_400Regular, Onest_500Medium, Onest_600SemiBold, Onest_700Bold, Unbounded_600SemiBold, Unbounded_700Bold,
  });
  useEffect(() => { bootAuth(); }, []);
  useEffect(() => { if (fontsLoaded || fontError) SplashScreen.hideAsync().catch(() => {}); }, [fontsLoaded, fontError]);
  if (!fontsLoaded && !fontError) return null;

  // Тема по системной настройке телефона — как в ThemeRoot
  const p = scheme === 'dark' ? palette.dark : palette.light;
  const nav = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = { ...nav, colors: { ...nav.colors, background: p.bg, card: p.bgElevated, text: p.ink, border: p.line, primary: p.accent } };
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <PersistQueryClientProvider client={queryClient} persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 * 3 }}>
          <ThemeRoot>
            <ThemeProvider value={navTheme}>
              <ToastHost>
                <StatusBar style="auto" />
                <Realtime />
                <Stack
                  screenOptions={{
                    headerShown: false,
                    // iOS: свайп от левого края назад — на всей ширине экрана, со стандартным сдвигом справа
                    gestureEnabled: true, fullScreenGestureEnabled: true, animation: 'default',
                    // В браузере предыдущий экран остаётся под текущим — свайп назад его открывает (см. SwipeBack)
                    ...(WEB ? { presentation: 'containedTransparentModal' as const, contentStyle: { backgroundColor: 'transparent' } }
                      : { contentStyle: { backgroundColor: p.bg } }),
                  }}
                  screenLayout={({ children, navigation, options, route }) => (WEB ? (
                    <SwipeBack bg={p.bg} onBack={() => navigation.goBack()}
                      enabled={route.name !== '(tabs)' && navigation.canGoBack() && (!options.presentation || options.presentation === 'containedTransparentModal')}>
                      {children}
                    </SwipeBack>
                  ) : children)}>
                  <Stack.Screen name="(tabs)" options={WEB ? { presentation: 'card' } : undefined} />
                  <Stack.Screen name="login" options={{ presentation: 'modal' }} />
                  <Stack.Screen name="rules" options={{ presentation: 'modal' }} />
                  <Stack.Screen name="new-post" options={{ presentation: 'modal' }} />
                  <Stack.Screen name="stories/[uid]" options={{ presentation: 'fullScreenModal', animation: 'fade' }} />
                  <Stack.Screen name="story-new" options={{ presentation: 'fullScreenModal', animation: 'slide_from_bottom' }} />
                  <Stack.Screen name="clips/[uid]" />
                  <Stack.Screen name="market/new" options={{ presentation: 'modal' }} />
                </Stack>
              </ToastHost>
            </ThemeProvider>
          </ThemeRoot>
        </PersistQueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
