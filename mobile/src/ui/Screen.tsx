import { router } from 'expo-router';
import { ReactNode, useRef, useState } from 'react';
import { NativeScrollEvent, NativeSyntheticEvent, Platform, RefreshControl, ScrollView, StyleProp, View, ViewStyle } from 'react-native';
import Animated, { interpolate, SharedValue, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HAIRLINE, useTheme } from '@/theme';
import { IconButton } from './Button';
import { Glass } from './Glass';
import { Txt } from './Text';

/** Место под нижнюю панель вкладок: в браузере она плавает поверх контента. */
export const TAB_SPACE = Platform.OS === 'web' ? 118 : Platform.OS === 'android' ? 24 : 40;

export function useScrollY() {
  const y = useSharedValue(0);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => { y.set(e.nativeEvent.contentOffset.y); };
  return { y, onScroll };
}

export const BAR_H = 56;

/** Тонкая стеклянная панель сверху, появляется при прокрутке (как в iOS).
 *  hidden (0…1) — панель уезжает вверх, над статус-баром остаётся только стекло. */
export function TopBar({ y, title, left, right, always, hidden }: {
  y: SharedValue<number>; title?: string; left?: ReactNode; right?: ReactNode; always?: boolean; hidden?: SharedValue<number>;
}) {
  const insets = useSafeAreaInsets();
  const bg = useAnimatedStyle(() => ({ opacity: always ? 1 : interpolate(y.value, [10, 60], [0, 1], 'clamp') }));
  const ttl = useAnimatedStyle(() => ({ opacity: always ? 1 : interpolate(y.value, [40, 80], [0, 1], 'clamp') }));
  const slide = useAnimatedStyle(() => {
    const h = hidden ? hidden.value : 0;
    return { transform: [{ translateY: -BAR_H * h }], opacity: 1 - h * 0.999 };
  });
  const slideBg = useAnimatedStyle(() => ({ transform: [{ translateY: -BAR_H * (hidden ? hidden.value : 0) }] }));
  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }}>
      <Animated.View pointerEvents="none" style={[{ position: 'absolute', top: 0, left: 0, right: 0 }, slideBg]}>
        <Animated.View pointerEvents="none" style={[{ height: insets.top + BAR_H }, bg]}>
          <Glass radius={0} strong style={{ flex: 1, borderWidth: 0 }} />
        </Animated.View>
      </Animated.View>
      <Animated.View pointerEvents="box-none" style={[{ paddingTop: insets.top + 6, paddingHorizontal: 12, height: insets.top + BAR_H, flexDirection: 'row', alignItems: 'center', gap: 8 }, slide]}>
        <View style={{ minWidth: 44 }}>{left}</View>
        <Animated.View pointerEvents="none" style={[{ flex: 1, alignItems: 'center' }, ttl]}>
          {title ? <Txt v="headline" numberOfLines={1}>{title}</Txt> : null}
        </Animated.View>
        <View style={{ minWidth: 44, flexDirection: 'row', gap: 8, justifyContent: 'flex-end' }}>{right}</View>
      </Animated.View>
    </View>
  );
}

/** Крупный заголовок раздела (шрифт Unbounded) с действиями справа. */
export function LargeTitle({ title, sub, right, above }: { title: string; sub?: string; right?: ReactNode; above?: ReactNode }) {
  return (
    <View style={{ gap: 6 }}>
      {above}
      <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Txt v="title1" accessibilityRole="header">{title}</Txt>
          {sub ? <Txt v="callout" tone="muted">{sub}</Txt> : null}
        </View>
        {right ? <View style={{ flexDirection: 'row', gap: 8 }}>{right}</View> : null}
      </View>
    </View>
  );
}

/** Корневой экран вкладки: крупный заголовок, стеклянная панель при прокрутке, «потянуть, чтобы обновить».
 *  collapsing — панель уезжает, когда листаете вниз, и возвращается при движении вверх (как в Threads);
 *  pinned/pinAt — полоса (например, вкладки ленты), которая прилипает к верху, когда её место в списке ушло под панель;
 *  pinAt — где эта полоса лежит в прокручиваемом содержимом (y от начала списка). */
export function TabScreen({ title, sub, right, above, children, refreshing, onRefresh, contentStyle, collapsing, pinned, pinAt }: {
  title: string; sub?: string; right?: ReactNode; above?: ReactNode; children: ReactNode;
  refreshing?: boolean; onRefresh?: () => void; contentStyle?: StyleProp<ViewStyle>;
  collapsing?: boolean; pinned?: ReactNode; pinAt?: number;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { y, onScroll } = useScrollY();
  const hidden = useSharedValue(0);
  const last = useRef(0);
  const hiddenNow = useRef(false);
  const [pinnedOn, setPinnedOn] = useState(false);
  const pinnedRef = useRef(false);
  const scroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    onScroll(e);
    const top = e.nativeEvent.contentOffset.y;
    const dy = top - last.current;
    last.current = top;
    if (collapsing) {
      // Вниз по ленте — прячем, назад — сразу показываем; у самого верха панель всегда видна
      const hide = top > 120 && (dy > 6 || (hiddenNow.current && dy >= -6));
      if (hide !== hiddenNow.current) { hiddenNow.current = hide; hidden.set(withTiming(hide ? 1 : 0, { duration: 220 })); }
    }
    if (pinned && pinAt !== undefined) {
      // Прилипаем, когда полоса в списке доходит до низа панели (с учётом того, спрятана ли панель).
      // Отлипаем только ниже — когда оригинал точно виден под раскрытой панелью: смена направления
      // во время анимации панели не прячет вкладки ни на мгновение.
      const unpinAt = pinAt - insets.top - BAR_H;
      const on = pinnedRef.current ? top >= unpinAt : top >= pinAt - insets.top - (hiddenNow.current ? 0 : BAR_H);
      if (on !== pinnedRef.current) { pinnedRef.current = on; setPinnedOn(on); }
    }
  };
  const pinStyle = useAnimatedStyle(() => ({ transform: [{ translateY: -BAR_H * hidden.value }] }));
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView onScroll={scroll} scrollEventThrottle={16} keyboardShouldPersistTaps="handled"
        contentInsetAdjustmentBehavior="never"
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={c.accent} /> : undefined}
        contentContainerStyle={[{ paddingTop: insets.top + 64, paddingHorizontal: 20, paddingBottom: TAB_SPACE + insets.bottom, gap: 22 }, contentStyle]}>
        <LargeTitle title={title} sub={sub} above={above} />
        {children}
      </ScrollView>
      {pinned && pinnedOn ? (
        <Animated.View style={[{ position: 'absolute', top: insets.top + BAR_H, left: 0, right: 0, zIndex: 9, backgroundColor: c.bg,
          paddingHorizontal: 20, paddingTop: 8, paddingBottom: 10, borderBottomWidth: HAIRLINE, borderBottomColor: c.line }, pinStyle]}>
          {pinned}
        </Animated.View>
      ) : null}
      <TopBar y={y} title={title} right={right} hidden={collapsing ? hidden : undefined} />
    </View>
  );
}

/** Вложенный экран (карточка, форма): стеклянная кнопка «назад» и заголовок, появляющийся при прокрутке. */
export function PageScreen({ title, right, children, contentStyle, refreshing, onRefresh, footer, topInset = true, bg }: {
  title?: string; right?: ReactNode; children: ReactNode; contentStyle?: StyleProp<ViewStyle>; refreshing?: boolean; onRefresh?: () => void;
  footer?: ReactNode; topInset?: boolean; bg?: string;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { y, onScroll } = useScrollY();
  return (
    <View style={{ flex: 1, backgroundColor: bg || c.bg }}>
      <ScrollView onScroll={onScroll} scrollEventThrottle={16} keyboardShouldPersistTaps="handled" contentInsetAdjustmentBehavior="never"
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={c.accent} /> : undefined}
        contentContainerStyle={[{ paddingTop: topInset ? insets.top + 64 : 0, paddingHorizontal: 20, paddingBottom: (footer ? 120 : 40) + insets.bottom, gap: 18 }, contentStyle]}>
        {children}
      </ScrollView>
      <TopBar y={y} title={title} left={<BackButton />} right={right} />
      {footer ? (
        <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 14, paddingBottom: insets.bottom + 12, paddingTop: 10 }}>
          {footer}
        </View>
      ) : null}
    </View>
  );
}

export function BackButton() {
  return <IconButton icon="back" label="Назад" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />;
}
