import { BottomSheetModalProvider } from '@gorhom/bottom-sheet';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { DarkTheme, DefaultTheme, router, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { bootAuth } from '@/api/auth';
import { persister, queryClient } from '@/api/query';
import { SwipeBack, WEB } from '@/features/nav/SwipeBack';
import { PushSync } from '@/features/push/PushSync';
import { pushSupported, setupNotifications } from '@/lib/push';
import { palette, ThemeRoot } from '@/theme';
import { ToastHost } from '@/ui';

export { ErrorBoundary } from 'expo-router';
export const unstable_settings = { initialRouteName: '(tabs)' };

SplashScreen.preventAutoHideAsync().catch(() => {});
setupNotifications();

/** Нажатие на уведомление открывает экран из data.url (например, /afisha), в том числе при холодном запуске. */
function useNotificationTaps() {
  useEffect(() => {
    if (!pushSupported) return;
    const open = (r: Notifications.NotificationResponse | null) => {
      const url = r?.notification.request.content.data?.url;
      if (typeof url === 'string' && url.startsWith('/')) router.push(url as any);
    };
    Notifications.getLastNotificationResponseAsync().then(open).catch(() => {});
    const sub = Notifications.addNotificationResponseReceivedListener(open);
    return () => sub.remove();
  }, []);
}

export default function RootLayout() {
  const scheme = useColorScheme();
  useEffect(() => { bootAuth(); }, []);
  useNotificationTaps();
  // Шрифты системные — ждать загрузки нечего, заставку убираем сразу
  useEffect(() => { SplashScreen.hideAsync().catch(() => {}); }, []);

  // Тема по системной настройке телефона — как в ThemeRoot
  const p = scheme === 'dark' ? palette.dark : palette.light;
  const nav = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = { ...nav, colors: { ...nav.colors, background: p.bg, card: p.bgElevated, text: p.ink, border: p.line, primary: p.accent } };
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <PersistQueryClientProvider client={queryClient} persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 * 3 }}>
          <PushSync />
          <ThemeRoot>
            <ThemeProvider value={navTheme}>
              <ToastHost>
                <BottomSheetModalProvider>
                <StatusBar style="auto" />
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
                </Stack>
                </BottomSheetModalProvider>
              </ToastHost>
            </ThemeProvider>
          </ThemeRoot>
        </PersistQueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
