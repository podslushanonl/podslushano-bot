import { useIsFocused, useNavigation, useScrollToTop } from 'expo-router';
import { RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Platform, RefreshControl, View } from 'react-native';
import Animated, { interpolate, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HAIRLINE, useTheme } from '@/theme';
import { Icon } from './Icon';

const PULL_TRIGGER = 72;   // на сколько потянуть (после «резинки»), чтобы обновить
const PULL_MAX = 120;
const MIN_SPIN_MS = 600;   // спиннер не мелькает, даже если ответ пришёл мгновенно

type Scrollable = {
  scrollTo?: (o: { y: number; animated?: boolean }) => void; scrollToOffset?: (o: { offset: number; animated?: boolean }) => void;
  getScrollableNode?: () => any; getNativeScrollRef?: () => any;
};

// Повторное нажатие на активную вкладку нижнего меню (веб-панель сообщает о нём сама — см. AppTabs.web)
const reselect = new Set<() => void>();
export const emitTabReselect = () => reselect.forEach((f) => f());

/** DOM-элемент прокрутки в браузере: у ScrollView — getScrollableNode, у FlashList — через getNativeScrollRef. */
function domNode(ref: RefObject<Scrollable | null>): HTMLElement | null {
  const r = ref.current;
  if (!r) return null;
  const inner = r.getNativeScrollRef?.() ?? r;
  return inner?.getScrollableNode?.() ?? null;
}

/**
 * Обновление списка как в системных приложениях:
 * — «потянуть вниз»: на телефоне — системный RefreshControl, в браузере (веб-версия приложения) — свой жест со спиннером;
 * — нажатие на текущую вкладку внизу: далеко внизу — плавно наверх (useScrollToTop), уже наверху — обновить.
 * onRefresh должен вернуть промис запроса к серверу: спиннер крутится, пока он не завершится.
 */
export function useRefresh(ref: RefObject<Scrollable | null>, onRefresh: (() => unknown) | undefined, atTop: () => boolean) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const pull = useSharedValue(0);
  const latest = useRef(onRefresh);
  useEffect(() => { latest.current = onRefresh; }, [onRefresh]);

  const run = useCallback(async () => {
    if (busyRef.current || !latest.current) return;
    busyRef.current = true; setBusy(true);
    try {
      await Promise.all([Promise.resolve(latest.current()).catch(() => {}), new Promise((r) => setTimeout(r, MIN_SPIN_MS))]);
    } finally {
      busyRef.current = false; setBusy(false);
    }
  }, []);

  // Нажатие на активную вкладку: далеко внизу — плавно наверх, уже наверху — обновляем.
  // На телефоне прокрутку делает useScrollToTop (событие tabPress системных вкладок), в браузере — наша панель.
  useScrollToTop(ref as any);
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const top = useRef(atTop);
  useEffect(() => { top.current = atTop; }, [atTop]);
  useEffect(() => navigation.addListener?.('tabPress', () => {
    if (navigation.isFocused?.() && top.current()) run();
  }), [navigation, run]);
  useEffect(() => {
    if (!focused) return;
    const onReselect = () => {
      if (top.current()) { run(); return; }
      const r = ref.current;
      if (r?.scrollToOffset) r.scrollToOffset({ offset: 0, animated: true }); else r?.scrollTo?.({ y: 0, animated: true });
    };
    reselect.add(onReselect);
    return () => { reselect.delete(onReselect); };
  }, [focused, ref, run]);

  // Жест «потянуть вниз» в браузере
  const enabled = !!onRefresh;
  useEffect(() => {
    if (Platform.OS !== 'web' || !enabled) return;
    let el: HTMLElement | null = null;
    let startY = 0;
    let pulling = false;
    const start = (e: TouchEvent) => {
      pulling = !busyRef.current && (el?.scrollTop ?? 1) <= 0;
      startY = e.touches[0].clientY;
    };
    const move = (e: TouchEvent) => {
      if (!pulling) return;
      const dy = e.touches[0].clientY - startY;
      if (dy <= 0 || (el?.scrollTop ?? 0) > 0) { pull.set(0); return; }
      pull.set(Math.min(PULL_MAX, dy * 0.5));   // «резинка»: тянется вдвое медленнее пальца
    };
    const end = () => {
      if (!pulling) return;
      pulling = false;
      if (pull.get() >= PULL_TRIGGER) run();
      pull.set(withTiming(0, { duration: 200 }));
    };
    // Список появляется не сразу (FlashList, загрузка) — подключаемся, как только он есть
    let tries = 0;
    const attach = () => {
      el = domNode(ref);
      if (!el) { if (tries++ < 40) timer = setTimeout(attach, 150); return; }
      el.addEventListener('touchstart', start, { passive: true });
      el.addEventListener('touchmove', move, { passive: true });
      el.addEventListener('touchend', end);
      el.addEventListener('touchcancel', end);
    };
    let timer: ReturnType<typeof setTimeout> | undefined = setTimeout(attach, 0);
    return () => {
      if (timer) clearTimeout(timer);
      el?.removeEventListener('touchstart', start);
      el?.removeEventListener('touchmove', move);
      el?.removeEventListener('touchend', end);
      el?.removeEventListener('touchcancel', end);
    };
  }, [ref, run, pull, enabled]);

  const style = useAnimatedStyle(() => {
    const p = busy ? PULL_TRIGGER : pull.value;
    return {
      opacity: busy ? 1 : interpolate(p, [8, PULL_TRIGGER], [0, 1], 'clamp'),
      transform: [{ translateY: interpolate(p, [0, PULL_MAX], [-48, 60], 'clamp') }, { rotate: `${busy ? 0 : p * 3}deg` }],
    };
  });

  const control = onRefresh && Platform.OS !== 'web'
    ? <RefreshControl refreshing={busy} onRefresh={run} tintColor={c.accent} colors={[c.accent]} progressBackgroundColor={c.bgElevated} />
    : undefined;

  const indicator = Platform.OS === 'web' && onRefresh ? (
    <Animated.View pointerEvents="none" style={[{ position: 'absolute', top: insets.top + 56, alignSelf: 'center', zIndex: 20 }, style]}>
      <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line,
        alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 14px rgba(0,0,0,0.45)' } as any}>
        {busy ? <ActivityIndicator size="small" color={c.accent} /> : <Icon name="down" size={18} color={c.accent} />}
      </View>
    </Animated.View>
  ) : null;

  return { busy, run, control, indicator };
}
