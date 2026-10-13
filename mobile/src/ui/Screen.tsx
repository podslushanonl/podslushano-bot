import { router } from 'expo-router';
import { ReactNode } from 'react';
import { NativeScrollEvent, NativeSyntheticEvent, Platform, RefreshControl, ScrollView, StyleProp, View, ViewStyle } from 'react-native';
import Animated, { interpolate, SharedValue, useAnimatedStyle, useSharedValue } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/theme';
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

/** Тонкая стеклянная панель сверху, появляется при прокрутке (как в iOS). */
export function TopBar({ y, title, left, right, always }: { y: SharedValue<number>; title?: string; left?: ReactNode; right?: ReactNode; always?: boolean }) {
  const insets = useSafeAreaInsets();
  const bg = useAnimatedStyle(() => ({ opacity: always ? 1 : interpolate(y.value, [10, 60], [0, 1], 'clamp') }));
  const ttl = useAnimatedStyle(() => ({ opacity: always ? 1 : interpolate(y.value, [40, 80], [0, 1], 'clamp') }));
  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }}>
      <Animated.View pointerEvents="none" style={[{ position: 'absolute', top: 0, left: 0, right: 0, height: insets.top + 56 }, bg]}>
        <Glass radius={0} strong style={{ flex: 1, borderWidth: 0 }} />
      </Animated.View>
      <View pointerEvents="box-none" style={{ paddingTop: insets.top + 6, paddingHorizontal: 12, height: insets.top + 56, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <View style={{ minWidth: 44 }}>{left}</View>
        <Animated.View pointerEvents="none" style={[{ flex: 1, alignItems: 'center' }, ttl]}>
          {title ? <Txt v="headline" numberOfLines={1}>{title}</Txt> : null}
        </Animated.View>
        <View style={{ minWidth: 44, flexDirection: 'row', gap: 8, justifyContent: 'flex-end' }}>{right}</View>
      </View>
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

/** Корневой экран вкладки: крупный заголовок, стеклянная панель при прокрутке, «потянуть, чтобы обновить». */
export function TabScreen({ title, sub, right, above, children, refreshing, onRefresh, contentStyle }: {
  title: string; sub?: string; right?: ReactNode; above?: ReactNode; children: ReactNode;
  refreshing?: boolean; onRefresh?: () => void; contentStyle?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { y, onScroll } = useScrollY();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView onScroll={onScroll} scrollEventThrottle={16} keyboardShouldPersistTaps="handled"
        contentInsetAdjustmentBehavior="never"
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={c.accent} /> : undefined}
        contentContainerStyle={[{ paddingTop: insets.top + 64, paddingHorizontal: 20, paddingBottom: TAB_SPACE + insets.bottom, gap: 22 }, contentStyle]}>
        <LargeTitle title={title} sub={sub} above={above} />
        {children}
      </ScrollView>
      <TopBar y={y} title={title} right={right} />
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
